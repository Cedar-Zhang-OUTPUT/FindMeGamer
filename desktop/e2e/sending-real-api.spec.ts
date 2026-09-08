import { test } from '@playwright/test';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, writeFile, lstat, readdir, rename } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest } from '../src/main/match-transport';
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import { OutreachClient } from '../src/main/outreach-client';
import { authenticatedOutreachRequest } from '../src/main/outreach-transport';
import { DraftsClient } from '../src/main/drafts-client';
import { authenticatedDraftsRequest } from '../src/main/drafts-transport';
import { SendingClient } from '../src/main/sending-client';
import { authenticatedSendingRequest } from '../src/main/sending-transport';
import type { Fetcher } from '../src/main/transport';
import type { Preparation } from '../src/shared/outreach';
import type { DraftView } from '../src/shared/drafts';
import type { Delivery, SendBatch } from '../src/shared/sending';
import { defaultConditions } from '../src/renderer/components/match/discoveryConditionState';

// Authoring this file does not authorize a run. Root must approve this exact test,
// hold the exclusive fixture lease, and explicitly approve global SMTP faults.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
const PRIVATE = '/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-ixcaiiq1/private';
const ORIGIN = 'http://127.0.0.1:62611', PIN = 'ece2e9d9558dfe057dc40ad58bd98a86e3149dd5';
const check = (value: unknown, code: string): void => { if (!value) throw new Error(code); };
const rev = (row: DraftView) => ({ expected_revision: row.revision, context_token: row.context_token });
const pause = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));
// JSON objects are unordered (including PostgreSQL JSONB readback). Keep every
// field and array position, while ignoring only object-property insertion order.
const canonical=(value:unknown):string=>!value||typeof value!=='object'?JSON.stringify(value):Array.isArray(value)?`[${value.map(canonical).join(',')}]`:`{${Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>`${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
const digest = (value: unknown) => createHash('sha256').update(typeof value === 'string' ? value : canonical(value)).digest('hex');
const codeOf = (error: unknown) => {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : error instanceof Error ? error.message : '';
  return /^[a-z][a-z0-9_]{0,99}$/.test(code) ? code : 'suppressed_unexpected_error';
};
async function until<T>(read: () => Promise<T>, done: (value: T) => boolean): Promise<T> {
  const end = Date.now() + 45_000;
  for (;;) { const value = await read(); if (done(value)) return value; check(Date.now() < end, 'bounded_poll_timeout'); await pause(500); }
}
async function mustReject(action: () => Promise<unknown>, code: string) {
  let rejected = false;
  try { await action(); } catch (error) { rejected = true; check(codeOf(error) === code, 'unexpected_rejection_code'); }
  check(rejected, 'expected_rejection_missing');
}

// Python stdlib parses MIME; snapshots travel over stdin, never command arguments
// or output. Only hashes and counts leave the parser, including on failure.
async function verifyMIME(paths: string[], deliveries: Delivery[]): Promise<{ count: number; hashes: string[] }> {
  const script = `import sys,json,hashlib
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
try:
 data=json.load(sys.stdin); rows={x['id']:x for x in data['deliveries']}; hashes=[]
 for path in data['paths']:
  raw=open(path,'rb').read(); message=BytesParser(policy=policy.default).parsebytes(raw)
  identity=str(message['Message-ID']).strip('<>').split('@',1)[0]; row=rows[identity]; snapshot=row['snapshot']; sender=snapshot['sender']
  assert parseaddr(str(message['From']))==((sender['name'] or ''),sender['address'])
  assert parseaddr(str(message['Reply-To'] or ''))[1]==(sender['reply_to'] or '')
  assert parseaddr(str(message['To']))[1]==snapshot['recipient_email']
  assert len(message.get_all('To',[]))==1 and not message.get_all('Cc') and not message.get_all('Bcc')
  assert str(message['Subject'])==snapshot['subject']
  assert message.get_body(preferencelist=('html',)).get_content().rstrip('\\r\\n')==snapshot['html']
  assert message.get_body(preferencelist=('plain',)).get_content().rstrip('\\r\\n')==snapshot['text']
  hashes.append(hashlib.sha256(raw).hexdigest())
 print(json.dumps({'ok':True,'count':len(hashes),'hashes':hashes}))
except Exception:
 print(json.dumps({'ok':False})); sys.exit(1)
`;
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.FMG_P7_PYTHON ?? 'python3', ['-c', script], { stdio: ['pipe', 'pipe', 'ignore'] });
    let output = ''; const timer = setTimeout(() => { child.kill(); reject(new Error('mime_parser_timeout')); }, 15_000);
    child.stdout.on('data', chunk => { output += chunk; if (output.length > 32_000) child.kill(); });
    child.on('error', () => { clearTimeout(timer); reject(new Error('mime_parser_unavailable')); });
    child.on('close', code => { clearTimeout(timer); try { const value = JSON.parse(output); check(code === 0 && value.ok === true, 'mime_verification_failed'); resolve({ count: value.count, hashes: value.hashes }); } catch { reject(new Error('mime_verification_failed')); } });
    child.stdin.on('error', () => {}); child.stdin.end(JSON.stringify({ paths, deliveries }));
  });
}

test('P7 production clients preserve immutable sending through synthetic SMTP recovery', async () => {
  test.skip(process.env.FMG_P7_EXCLUSIVE_FIXTURE !== '62611' || process.env.FMG_P7_SMTP_FAULTS !== 'approved' || process.env.FMG_P7_NOT_SENT_SIMULATION !== 'approved', 'Root review, exclusive lease, SMTP fault approval and labeled override approval required.');
  test.setTimeout(300_000);
  const state = PRIVATE + '/state', sourceControl = state + '/control.json', smtpControl = state + '/smtp-control.json';
  const clientStat = await lstat(PRIVATE + '/client.json'), stateStat = await lstat(state), controlStat = await lstat(smtpControl);
  check(clientStat.isFile() && !clientStat.isSymbolicLink() && (clientStat.mode & 0o777) === 0o600 && stateStat.isDirectory() && !stateStat.isSymbolicLink() && (stateStat.mode & 0o777) === 0o700 && controlStat.isFile() && !controlStat.isSymbolicLink() && (controlStat.mode & 0o777) === 0o600, 'fixture_permissions');
  const config = JSON.parse(await readFile(PRIVATE + '/client.json', 'utf8'));
  check(config.base_url === ORIGIN && config.backend_revision === PIN && config.migration === '20260908_0017', 'fixture_pin');
  const originalControl = await readFile(smtpControl), originalSource = await readFile(sourceControl);
  check(JSON.stringify(JSON.parse(originalControl.toString())) === JSON.stringify({ mode: 'success' }), 'smtp_control_not_idle');
  check(JSON.stringify(JSON.parse(originalSource.toString())) === JSON.stringify({ source_fail: 'none', model_fail: 'none', hold: 'none' }), 'source_control_not_idle');
  const run = randomUUID(), ledger = PRIVATE + `/p7-sending-${run}.json`;
  const report: Record<string, unknown> = { run_id: run, backend_revision: PIN, migration: config.migration, status: 'running', stage: 'preflight', scenarios: {}, checks: [] };
  const counts: Record<string, number> = {};
  const activities = new Set<string>(), plans = new Set<string>(), queries = new Set<string>(), creatorsAllowed = new Set<string>(), compositions = new Set<string>(), draftIds = new Set<string>(), sendBatches = new Set<string>(), deliveryIds = new Set<string>(), templates = new Set<string>();
  const fetcher: Fetcher = async (url, init) => {
    const u = new URL(url), method = init.method ?? 'GET'; check(u.origin === ORIGIN, 'http_origin');
    const route = u.pathname, activity = /^\/api\/v2\/activities\/([^/]+)/.exec(route), plan = /^\/api\/v2\/discovery\/plans\/([^/]+)/.exec(route), query = /^\/api\/v2\/discovery\/queries\/([^/]+)/.exec(route), creator = /^\/api\/v2\/library\/creators\/([^/]+)/.exec(route);
    const composition = /^\/api\/v2\/outreach\/compositions\/([^/]+)/.exec(route), draft = /^\/api\/v2\/outreach\/drafts\/([^/]+)/.exec(route), batch = /^\/api\/v2\/outreach\/send-batches\/([^/]+)/.exec(route), delivery = /^\/api\/v2\/outreach\/deliveries\/([^/]+)/.exec(route);
    check(route === '/api/v2/activities' && method === 'POST' || !!activity || !!plan || !!query || !!creator || !!composition || !!draft || !!batch || !!delivery || route === '/api/v2/outreach/template-versions' && method === 'POST', 'http_route');
    if (activity) check(activities.has(activity[1]), 'activity_scope'); if (plan) check(plans.has(plan[1]), 'plan_scope'); if (query) check(queries.has(query[1]), 'query_scope');
    if (creator) check(creatorsAllowed.has(creator[1]) && method === 'GET', 'creator_read_only');
    if (composition) check(compositions.has(composition[1]), 'composition_scope'); if (draft) check(draftIds.has(draft[1]), 'draft_scope');
    if (batch) check(sendBatches.has(batch[1]) && method === 'GET', 'send_batch_scope'); if (delivery) check(deliveryIds.has(delivery[1]) && method === 'POST', 'delivery_scope');
    const family = `${method} ${route.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi, ':id')}`; counts[family] = (counts[family] ?? 0) + 1;
    return fetch(u, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
  };
  const connection = { serviceUrl: ORIGIN, key: config.workspace_key };
  const match = new MatchClient(r => authenticatedMatchRequest(fetcher, connection, r)), creators = new CreatorClient(r => authenticatedCreatorRequest(fetcher, connection, r));
  const outreach = new OutreachClient(r => authenticatedOutreachRequest(fetcher, connection, r)), drafts = new DraftsClient(r => authenticatedDraftsRequest(fetcher, connection, r));
  const sending = new SendingClient(r => authenticatedSendingRequest(fetcher, connection, r));
  async function checkpoint(stage: string) { report.stage = stage; report.request_counts = counts; await writeFile(ledger, JSON.stringify(report, null, 2), { mode: 0o600 }); }
  async function events(): Promise<string[]> {
    const rows = (await readFile(state + '/smtp-events.jsonl', 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
    check(rows.every(row => Object.keys(row).sort().join(',') === 'endpoint,status' && row.endpoint === 'smtp' && ['captured', 'rejected', 'fail_before', 'unknown_after_capture'].includes(row.status)), 'smtp_event_schema');
    return rows.map(row => row.status);
  }
  async function captures(): Promise<string[]> { return (await readdir(state)).filter(name => /^smtp-[a-f0-9-]{36}\.eml$/.test(name)).sort(); }
  async function mode(value: 'success' | 'reject' | 'unknown_after_capture') {
    const tmp = state + `/smtp-control-${run}.tmp`; await writeFile(tmp, JSON.stringify({ mode: value }), { mode: 0o600 }); await rename(tmp, smtpControl); await pause(400);
    check(JSON.parse(await readFile(smtpControl, 'utf8')).mode === value, 'smtp_control_readback');
  }
  const eventsBefore = await events(), capturesBefore = new Set(await captures());
  async function noSMTP(before: string[]) { await pause(500); check(JSON.stringify(await events()) === JSON.stringify(before), 'unexpected_smtp_effect'); }
  async function terminal(id: string) { return until(() => sending.batch(id), value => value.deliveries.every(row => !['queued', 'sending'].includes(row.state))); }
  async function ownScenario(label: string) {
    await checkpoint(label + '_setup');
    const activity = await match.createActivity({ data: { name: `P7 desktop ${label} ${run.slice(0, 8)}`, game_id: config.game_id, reference_work_ids: config.reference_work_ids }, idempotencyKey: randomUUID() }); activities.add(activity.id);
    const record: Record<string, unknown> = { activity_id: activity.id };
    (report.scenarios as Record<string, unknown>)[label] = record; await checkpoint(label + '_activity_created');
    const activitySource = digest(activity.source_snapshot), accepted = await match.createPlan({ activityId: activity.id, data: { ...defaultConditions(), batch_target: 3, result_limit: 3 }, idempotencyKey: randomUUID() }); plans.add(accepted.plan_id); record.plan_id = accepted.plan_id;
    const plan = await until(() => match.plan(accepted.plan_id), value => ['ready', 'failed'].includes(value.status)); check(plan.status === 'ready' && plan.query_id, 'planning_failed'); queries.add(plan.query_id!);
    await until(() => match.query(plan.query_id!), value => !['queued', 'running'].includes(value.status) && !value.batches.some(item => ['queued', 'running'].includes(item.status)));
    const candidates = (await match.candidates({ queryId: plan.query_id!, offset: 0, limit: 100, sort: 'relevance', evidence: 'all' })).items.sort((a, b) => a.account_id.localeCompare(b.account_id));
    check(candidates.length === 3 && candidates.every(item => ['UCmatchA001', 'UCmatchB002', 'UCmatchC003'].includes(item.account_id)), 'synthetic_candidates_required');
    await match.stop({ queryId: plan.query_id!, idempotencyKey: randomUUID() });
    const prepared: Preparation[] = [], usedEmails = new Set<string>();
    for (const candidate of candidates) {
      const selection = await outreach.add({ activityId: activity.id, data: { candidate_id: candidate.id }, idempotencyKey: randomUUID() }); creatorsAllowed.add(selection.creator_id);
      const creator = await creators.detail(selection.creator_id), works = await creators.works({ creatorId: selection.creator_id, offset: 0, limit: 100 });
      const work = works.items.find(item => item.source_url && item.evidence_excerpt && item.verification_notes && (item.content_title || item.work_name));
      const contact = selection.contact_options.find(item => item.status === 'eligible' && /^[^@\s]+@example\.com$/.test(item.email) && !usedEmails.has(item.email.toLowerCase()));
      check(creator.public_name && (prepared.length === 2 || work && contact), 'existing_synthetic_contacts_and_evidence_required');
      if (contact) usedEmails.add(contact.email.toLowerCase());
      prepared.push(await outreach.update({ activityId: activity.id, id: selection.id, data: { expected_revision: selection.revision, context_token: selection.context_token, contact_id: prepared.length < 2 ? contact!.id : null, work_ids: prepared.length < 2 ? [work!.id] : [], confirm_public_name: true }, idempotencyKey: randomUUID() }));
    }
    const recipientBatch = await outreach.freeze({ activityId: activity.id, data: { request_id: randomUUID(), recipients: prepared.map(item => ({ selection_id: item.id, expected_revision: item.revision, context_token: item.context_token })) }, idempotencyKey: randomUUID() });
    const recipientSource = digest(recipientBatch.recipients.map(item => ({ id: item.id, snapshot: item.snapshot })));
    const template = await drafts.createTemplate({ data: { request_id: randomUUID(), game_id: config.game_id, name: `P7 ${label} ${run.slice(0, 8)}`, subject: 'Synthetic desktop sending verification', fixed_fragments: ['<p>Hi ', ', I follow ', ' and enjoyed ', '. I liked how you ', '</p>'] }, idempotencyKey: randomUUID() }); templates.add(template.id);
    let composition = await drafts.createComposition({ activityId: activity.id, data: { request_id: randomUUID(), recipient_batch_id: recipientBatch.id, template_version_id: template.id }, idempotencyKey: randomUUID() }); compositions.add(composition.id); composition.drafts.forEach(row => draftIds.add(row.id));
    composition = await until(() => drafts.composition(composition.id), value => value.drafts.slice(0, 2).every(row => ['succeeded', 'failed'].includes(row.status)));
    check(composition.drafts.slice(0, 2).every(row => row.status === 'succeeded') && composition.drafts[2].status === 'needs_repair', 'full_n_drafts');
    composition = await drafts.senderFacts({ compositionId: composition.id, data: { members: composition.drafts.slice(0, 2).map(row => ({ draft_id: row.id, ...rev(row) })), following: true, enjoyed: true, liked: true } });
    Object.assign(record, { query_id: plan.query_id, composition_id: composition.id, recipient_batch_id: recipientBatch.id, template_id: template.id });
    return { activity, prepared, composition, recipientBatch, activitySource, recipientSource, record };
  }
  function ownBatch(value: SendBatch) { sendBatches.add(value.id); value.deliveries.forEach(row => deliveryIds.add(row.id)); }
  try {
    check(digest({a:1,b:{x:2,y:3}})===digest({b:{y:3,x:2},a:1})&&digest([1,2])!==digest([2,1]),'canonical_digest_self_check');
    const first = await ownScenario('verified_sent'); const qBefore = await events();
    const mixed = await sending.qualify({ compositionId: first.composition.id, data: { excluded: [{ draft_id: first.composition.drafts[1].id, reason: 'Synthetic mixed-status inspection' }] } });
    check(mixed.total_count === 3 && mixed.eligible_count === 1 && mixed.repair_count === 1 && mixed.excluded_count === 1 && !mixed.send_ready, 'all_n_mixed_qualification'); await noSMTP(qBefore);
    const excluded = [{ draft_id: first.composition.drafts[2].id, reason: 'Synthetic missing-evidence member excluded explicitly' }];
    let qualified = await sending.qualify({ compositionId: first.composition.id, data: { excluded } }); check(qualified.send_ready && qualified.eligible_count === 2, 'qualified_two');
    await checkpoint('stale_token_after_own_source_choice');
    let selection = await outreach.selection({ activityId: first.activity.id, id: first.prepared[0].id });
    await outreach.update({ activityId: first.activity.id, id: selection.id, data: { expected_revision: selection.revision, context_token: selection.context_token, contact_id: null }, idempotencyKey: randomUUID() });
    await mustReject(() => sending.send({ compositionId: first.composition.id, data: { request_id: randomUUID(), qualification_token: qualified.qualification_token, excluded }, idempotencyKey: randomUUID() }), 'qualification_changed'); await noSMTP(qBefore);
    selection = await outreach.selection({ activityId: first.activity.id, id: selection.id });
    await outreach.update({ activityId: first.activity.id, id: selection.id, data: { expected_revision: selection.revision, context_token: selection.context_token, contact_id: first.prepared[0].selected_contact!.id }, idempotencyKey: randomUUID() });
    let current = await drafts.composition(first.composition.id); await drafts.refresh({ id: current.drafts[0].id, data: rev(current.drafts[0]) });
    current = await until(() => drafts.composition(first.composition.id), value => ['succeeded', 'failed'].includes(value.drafts[0].status)); check(current.drafts[0].status === 'succeeded', 'source_restore_generation');
    await drafts.senderFacts({ compositionId: current.id, data: { members: [{ draft_id: current.drafts[0].id, ...rev(current.drafts[0]) }], following: true, enjoyed: true, liked: true } });
    qualified = await sending.qualify({ compositionId: current.id, data: { excluded } }); check(qualified.send_ready, 'restored_qualification');
    const body = { request_id: randomUUID(), qualification_token: qualified.qualification_token, excluded }, key = randomUUID();
    await mode('reject'); await checkpoint('definite_failure_two_owned_deliveries');
    let sent = await sending.send({ compositionId: current.id, data: body, idempotencyKey: key }); ownBatch(sent); sent = await terminal(sent.id);
    check(sent.deliveries.length === 2 && sent.deliveries.every(row => row.state === 'failed' && row.retryable && row.attempt === 1), 'definite_failure_states');
    check(JSON.stringify((await events()).slice(eventsBefore.length)) === JSON.stringify(['rejected', 'rejected']), 'actual_reject_events');
    const replayEvents = await events(); check((await sending.send({ compositionId: current.id, data: body, idempotencyKey: key })).id === sent.id, 'durable_send_replay'); await noSMTP(replayEvents);
    check((await sending.batches({ activityId: first.activity.id, offset: 0, limit: 50 })).total === 1, 'one_final_batch');
    const frozen = digest(sent.deliveries.map(row => row.snapshot));
    current = await drafts.composition(current.id); await drafts.edit({ id: current.drafts[0].id, data: { ...rev(current.drafts[0]), values: { ...current.drafts[0].values!, observation: 'A later synthetic draft edit.' } } });
    await mode('success'); await sending.retry({ id: sent.deliveries[0].id, data: { expected_attempt: 1 } }); sent = await terminal(sent.id);
    check(sent.deliveries[0].state === 'sent' && sent.deliveries[0].attempt === 2 && sent.deliveries[1].state === 'failed', 'targeted_retry_preserves_other');
    await mode('unknown_after_capture'); await sending.retry({ id: sent.deliveries[1].id, data: { expected_attempt: 1 } }); sent = await terminal(sent.id);
    const unknown = sent.deliveries[1]; check(unknown.state === 'unknown' && unknown.attempt === 2 && !unknown.retryable, 'unknown_classification');
    const beforeResolve = await events(); await mustReject(() => sending.retry({ id: unknown.id, data: { expected_attempt: unknown.attempt } }), 'delivery_retry_not_allowed'); await noSMTP(beforeResolve);
    const firstCaptures = (await captures()).filter(name => !capturesBefore.has(name)); check(firstCaptures.length === 2, 'first_capture_count'); await verifyMIME(firstCaptures.map(name => state + '/' + name), sent.deliveries);
    await mode('success'); await checkpoint('evidence_backed_sent_resolution');
    await sending.resolve({ id: unknown.id, data: { expected_attempt: unknown.attempt, outcome: 'sent', source_note: 'Synthetic operator verified this exact Message-ID and frozen MIME in the private local capture. This confirms fixture submission, not mailbox delivery.' } }); await noSMTP(beforeResolve);
    sent = await terminal(sent.id); check(sent.deliveries.every(row => row.state === 'sent') && digest(sent.deliveries.map(row => row.snapshot)) === frozen, 'immutable_frozen_delivery');
    check(digest((await match.activity(first.activity.id)).source_snapshot) === first.activitySource && digest((await outreach.batch({ activityId: first.activity.id, id: first.recipientBatch.id })).recipients.map(item => ({ id: item.id, snapshot: item.snapshot }))) === first.recipientSource, 'original_context_immutable');
    Object.assign(first.record, { send_batch_id: sent.id, delivery_ids: sent.deliveries.map(row => row.id), final_states: sent.deliveries.map(row => row.state), captures: 2, source_snapshot_immutable: true });
    report.renderer_fixture = { activity_id: first.activity.id, composition_id: first.composition.id, recipient_batch_id: first.recipientBatch.id, send_batch_id: sent.id };
    const second = await ownScenario('not_sent_operator_override');
    const exclusions = second.composition.drafts.slice(1).map(row => ({ draft_id: row.id, reason: 'Outside the isolated synthetic operator-override scenario' }));
    const q = await sending.qualify({ compositionId: second.composition.id, data: { excluded: exclusions } }); check(q.send_ready && q.eligible_count === 1 && q.total_count === 3, 'override_qualification');
    await mode('unknown_after_capture'); await checkpoint('labeled_not_sent_transition_simulation');
    let overrideBatch = await sending.send({ compositionId: second.composition.id, data: { request_id: randomUUID(), qualification_token: q.qualification_token, excluded: exclusions }, idempotencyKey: randomUUID() }); ownBatch(overrideBatch); overrideBatch = await terminal(overrideBatch.id);
    const overridden = overrideBatch.deliveries[0]; check(overridden.state === 'unknown', 'override_requires_unknown');
    const overrideBefore = await events(); await mode('success');
    await sending.resolve({ id: overridden.id, data: { expected_attempt: overridden.attempt, outcome: 'not_sent', source_note: 'Synthetic operator override: test not_sent state transition; capture exists, not a factual delivery finding.' } }); await noSMTP(overrideBefore);
    const recorded = (await sending.batch(overrideBatch.id)).deliveries[0]; check(recorded.state === 'failed' && recorded.retryable && recorded.attempt === overridden.attempt && recorded.resolution.outcome === 'not_sent', 'not_sent_records_only');
    await checkpoint('separate_deliberate_retry_after_override'); await sending.retry({ id: recorded.id, data: { expected_attempt: recorded.attempt } }); overrideBatch = await terminal(overrideBatch.id);
    check(overrideBatch.deliveries[0].state === 'sent' && overrideBatch.deliveries[0].attempt === recorded.attempt + 1 && digest(overrideBatch.deliveries[0].snapshot) === digest(overridden.snapshot), 'explicit_retry_after_override');
    const finalCaptures = (await captures()).filter(name => !capturesBefore.has(name)); check(finalCaptures.length === 4, 'four_expected_captures');
    const mime = await verifyMIME(finalCaptures.map(name => state + '/' + name), [...sent.deliveries, ...overrideBatch.deliveries]);
    Object.assign(second.record, { send_batch_id: overrideBatch.id, delivery_id: overridden.id, final_state: 'sent', captures: 2, interpretation: 'synthetic_operator_override_only; intentional_second_capture; not_evidence_of_no_submission' });
    check(JSON.stringify((await events()).slice(eventsBefore.length)) === JSON.stringify(['rejected', 'rejected', 'captured', 'captured', 'unknown_after_capture', 'captured', 'unknown_after_capture', 'captured']), 'actual_smtp_event_sequence');
    report.status = 'passed'; report.smtp_events = (await events()).slice(eventsBefore.length); report.mime = mime;
    report.checks = ['full_n_qualification_no_smtp', 'stale_token_rejected', 'durable_same_request_no_duplicate', 'frozen_mime_and_identity', 'targeted_failed_retry', 'unknown_retry_rejected', 'capture_backed_sent_resolution', 'explicit_labeled_not_sent_transition', 'separate_retry_after_override', 'immutable_activity_and_recipients']; await checkpoint('complete');
  } catch (error) { report.status = 'failed'; report.error = codeOf(error); await checkpoint(String(report.stage)); throw new Error(`P7 fixture verification failed at ${report.stage}: ${report.error}; private ledger retained.`); }
  finally {
    const tmp = state + `/smtp-restore-${run}.tmp`; await writeFile(tmp, originalControl, { mode: 0o600 }); await rename(tmp, smtpControl); await pause(400);
    report.controls_restored = originalControl.equals(await readFile(smtpControl)); report.source_controls_unchanged = originalSource.equals(await readFile(sourceControl));
    if (!report.controls_restored || !report.source_controls_unchanged) { report.status = 'failed'; report.error = 'fixture_restore_check_failed'; }
    await writeFile(ledger, JSON.stringify(report, null, 2), { mode: 0o600 });
    console.log(JSON.stringify({ p7_status: report.status, stage: report.stage, controls_restored: report.controls_restored, ledger }));
    check(report.controls_restored && report.source_controls_unchanged, 'fixture_restore_check_failed');
  }
});
