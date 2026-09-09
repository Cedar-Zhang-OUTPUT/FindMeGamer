import { test } from '@playwright/test';
import { createHash, randomUUID } from 'node:crypto';
import { lstat, readFile, readdir, writeFile } from 'node:fs/promises';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest } from '../src/main/match-transport';
import { OutreachClient } from '../src/main/outreach-client';
import { authenticatedOutreachRequest } from '../src/main/outreach-transport';
import { CollaborationClient } from '../src/main/collaboration-client';
import { authenticatedCollaborationRequest } from '../src/main/collaboration-transport';
import type { Fetcher } from '../src/main/transport';
import type { ActivityInvitation } from '../src/shared/collaboration';
import { defaultConditions } from '../src/renderer/components/match/discoveryConditionState';

// Author-only until the coordinator grants the exclusive 64692 lease and all
// three flags. Never reuse 62611. No SMTP, Analyze, Library or control writes.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
const PRIVATE = '/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-xmmhoufp/private';
const ORIGIN = 'http://127.0.0.1:64692';
const PIN = '5706ad76f924991b80ee2a7fb6806528366be5ce';
const C = '9259d448819e076557e5bb5228104b63fcae543b';
const check = (value: unknown, code: string) => { if (!value) throw new Error(code); };
const canonical=(value:unknown):string=>value===null||typeof value!=='object'?JSON.stringify(value):Array.isArray(value)?`[${value.map(canonical).join(',')}]`:`{${Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>`${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
const hash = (value: unknown) => createHash('sha256').update(canonical(value)).digest('hex');
const delay = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));
const safeCode = (error: unknown) => {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : error instanceof Error ? error.message : '';
  return /^[a-z][a-z0-9_]{0,99}$/.test(code) ? code : 'suppressed_unexpected_error';
};
async function poll<T>(read: () => Promise<T>, done: (value: T) => boolean): Promise<T> {
  const end = Date.now() + 60_000;
  for (;;) { const value = await read(); if (done(value)) return value; check(Date.now() < end, 'bounded_poll_timeout'); await delay(500); }
}
const noMail = (row: ActivityInvitation) => row.sending_state === 'not_sent' && row.invited_at === null && row.send_history.length === 0;

test('C production clients retain independent sourced collaboration relationships', async () => {
  test.skip(process.env.FMG_C_EXCLUSIVE_FIXTURE !== '64692' || process.env.FMG_C_OWN_SEED !== 'approved' || process.env.FMG_C_MANUAL_RECORDS !== 'approved', 'Coordinator lease, owned Match seed and synthetic manual-record authorization required.');
  test.setTimeout(240_000);
  const run = randomUUID(), ledger = `${PRIVATE}/c-collaboration-${run}.json`;
  const report: Record<string, unknown> = { run_id: run, status: 'running', stage: 'preflight', backend_revision: PIN, collaboration_revision: C, owned: [], checks: [] };
  const counts: Record<string, number> = {};
  let postCount = 0, conflict409 = 0;
  async function checkpoint(stage: string) { report.stage = stage; report.request_counts = counts; await writeFile(ledger, JSON.stringify(report, null, 2), { mode: 0o600 }); }
  // These are read-only baseline hashes. No fixture content or private key is
  // printed; missing files are represented as absent, not created.
  async function sideEffects() {
    const names = (await readdir(PRIVATE + '/state')).filter(name => /^(?:.*control\.json|smtp-events\.jsonl|analyze-events\.jsonl|smtp-[a-f0-9-]{36}\.eml)$/.test(name)).sort();
    const values: Record<string, string> = {};
    for (const name of names) {
      const path = PRIVATE + '/state/' + name, stat = await lstat(path);
      check(stat.isFile() && !stat.isSymbolicLink(), 'fixture_state_file');
      values[name] = createHash('sha256').update(await readFile(path)).digest('hex');
    }
    return values;
  }
  let baseline: Record<string, string> | null = null;
  try {
    const stat = await lstat(PRIVATE), clientStat = await lstat(PRIVATE + '/client.json');
    check(stat.isDirectory() && !stat.isSymbolicLink() && (stat.mode & 0o777) === 0o700 && clientStat.isFile() && !clientStat.isSymbolicLink() && (clientStat.mode & 0o777) === 0o600, 'private_permissions');
    await checkpoint('preflight');
    const config = JSON.parse(await readFile(PRIVATE + '/client.json', 'utf8'));
    check(config.base_url === ORIGIN && config.backend_revision === PIN && config.migration === '20260908_0019', 'fixture_pin');
    baseline = await sideEffects();
    const activities = new Set<string>(), plans = new Set<string>(), queries = new Set<string>(), creators = new Set<string>();
    const fetcher: Fetcher = async (url, init) => {
      const parsed = new URL(url), method = init.method ?? 'GET', path = parsed.pathname;
      check(parsed.origin === ORIGIN, 'origin_scope');
      const activity = /^\/api\/v2\/activities\/([^/]+)(.*)$/.exec(path);
      const plan = /^\/api\/v2\/discovery\/plans\/([^/]+)$/.exec(path);
      const query = /^\/api\/v2\/discovery\/queries\/([^/]+)(.*)$/.exec(path);
      const creator = /^\/api\/v2\/library\/creators\/([^/]+)\/invitations$/.exec(path);
      const allowed = path === '/api/v2/activities' && method === 'POST'
        || activity && activities.has(activity[1]) && (method === 'GET' && /^\/(?:invitations(?:\/[^/]+)?|selections)$/.test(activity[2]) || method === 'POST' && /^\/(?:discovery-plans|selections|invitations\/[^/]+\/(?:update|responses))$/.test(activity[2]))
        || plan && plans.has(plan[1]) && method === 'GET'
        || query && queries.has(query[1]) && (method === 'GET' && ['', '/results'].includes(query[2]) || method === 'POST' && query[2] === '/stop')
        || creator && creators.has(creator[1]) && method === 'GET';
      check(allowed, 'route_or_owned_id_scope');
      const family = `${method} ${path.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi, ':id')}`; counts[family] = (counts[family] ?? 0) + 1;
      if (method === 'POST') postCount++;
      const response = await fetch(parsed, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
      if (response.status === 409 && path.includes('/invitations/')) conflict409++;
      return response;
    };
    const connection = { serviceUrl: ORIGIN, key: config.workspace_key };
    const match = new MatchClient(value => authenticatedMatchRequest(fetcher, connection, value));
    const outreach = new OutreachClient(value => authenticatedOutreachRequest(fetcher, connection, value));
    const collaboration = new CollaborationClient(value => authenticatedCollaborationRequest(fetcher, connection, value));
    async function seed(label: string) {
      await checkpoint(label + '_create');
      const activity = await match.createActivity({ data: { name: `C desktop ${label} ${run.slice(0, 8)}`, game_id: config.game_id, reference_work_ids: config.reference_work_ids }, idempotencyKey: randomUUID() }); activities.add(activity.id);
      const owned: Record<string, unknown> = { activity_id: activity.id }; (report.owned as unknown[]).push(owned); await checkpoint(label + '_activity_created');
      const readsBefore = postCount, empty = await collaboration.list({ activityId: activity.id });
      check(empty.total === 0 && (await collaboration.list({ activityId: activity.id })).total === 0 && postCount === readsBefore, 'empty_get_no_write');
      const accepted = await match.createPlan({ activityId: activity.id, data: { ...defaultConditions(), batch_target: 3, result_limit: 3 }, idempotencyKey: randomUUID() }); plans.add(accepted.plan_id); owned.plan_id = accepted.plan_id; await checkpoint(label + '_plan_created');
      const plan = await poll(() => match.plan(accepted.plan_id), value => ['ready', 'failed'].includes(value.status)); check(plan.status === 'ready' && plan.query_id, 'seed_plan_failed'); queries.add(plan.query_id!); owned.query_id = plan.query_id;
      await poll(() => match.query(plan.query_id!), value => !['queued', 'running'].includes(value.status) && !value.batches.some(batch => ['queued', 'running'].includes(batch.status)));
      const candidates = (await match.candidates({ queryId: plan.query_id!, offset: 0, limit: 100, sort: 'relevance', evidence: 'all' })).items;
      const candidate = candidates.find(value => value.account_id === 'UCmatchA001'); check(candidate, 'synthetic_candidate_required');
      await match.stop({ queryId: plan.query_id!, idempotencyKey: randomUUID() });
      const selection = await outreach.add({ activityId: activity.id, data: { candidate_id: candidate!.id }, idempotencyKey: randomUUID() }); creators.add(selection.creator_id); owned.selection_id = selection.id; owned.creator_id = selection.creator_id; await checkpoint(label + '_selection_created');
      const repeated = await outreach.add({ activityId: activity.id, data: { candidate_id: candidate!.id }, idempotencyKey: randomUUID() });
      check(repeated.id === selection.id && (await outreach.selections({ activityId: activity.id })).total === 1, 'same_activity_selection_dedup');
      const scope = { activityId: activity.id, selectionId: selection.id }, before = postCount;
      const initial = await collaboration.detail(scope), list = await collaboration.list({ activityId: activity.id });
      check(initial.revision === 0 && noMail(initial) && initial.responses.length === 0 && initial.invitation_state === 'not_invited' && list.total === 1 && list.items[0].selection_id === selection.id, 'initial_relationship');
      check(hash(await collaboration.detail(scope)) === hash(initial) && postCount === before, 'relationship_get_stable');
      return { scope, selection, initial, owned };
    }
    const a = await seed('primary'), b = await seed('independent');
    check(a.selection.creator_id === b.selection.creator_id && a.selection.id !== b.selection.id, 'cross_activity_same_creator');
    await checkpoint('progress_only');
    const progressed = await collaboration.update({ ...a.scope, data: { expected_revision: 0, follow_up_state: 'follow_up_needed', notes: 'Synthetic collaboration fixture note; no actual outreach.' }, idempotencyKey: randomUUID() });
    check(progressed.revision === 1 && progressed.follow_up_state === 'follow_up_needed' && progressed.cooperation_state === 'not_started' && noMail(progressed) && progressed.responses.length === 0 && progressed.invitation_state === 'not_invited', 'progress_does_not_invent_response_or_send');
    await checkpoint('record_synthetic_response');
    const body = { expected_revision: 1, outcome: 'accepted' as const, source_note: 'Synthetic fixture response: operator-authored acceptance for state verification, not a real creator reply.', responded_at: '2026-09-08T12:34:56+08:00' }, key = randomUUID();
    const accepted = await collaboration.respond({ ...a.scope, data: body, idempotencyKey: key });
    check(accepted.revision === 2 && accepted.invitation_state === 'accepted' && accepted.responses.length === 1 && accepted.responses[0].source_note === body.source_note && Date.parse(accepted.responses[0].responded_at) === Date.parse(body.responded_at) && Date.parse(accepted.responses[0].recorded_at) !== Date.parse(body.responded_at) && accepted.cooperation_state === 'not_started' && noMail(accepted), 'explicit_response_only');
    const replay = await collaboration.respond({ ...a.scope, data: body, idempotencyKey: key });
    report.replay_comparison={serialized_equal:JSON.stringify(replay)===JSON.stringify(accepted),canonical_equal:hash(replay)===hash(accepted),response_count:replay.responses.length,revision:replay.revision};
    check(hash(replay) === hash(accepted) && (await collaboration.detail(a.scope)).responses.length === 1, 'response_idempotent_replay');
    let staleRejected = false;
    try { await collaboration.update({ ...a.scope, data: { expected_revision: 1, notes: 'Must not be applied' }, idempotencyKey: randomUUID() }); }
    catch (error) { check(safeCode(error) === 'collaboration_revision_conflict', 'unexpected_conflict'); staleRejected = true; }
    check(staleRejected && conflict409 === 1 && hash(await collaboration.detail(a.scope)) === hash(accepted), 'stale_revision_409_unchanged');
    check(hash(await collaboration.detail(b.scope)) === hash(b.initial), 'other_activity_independent');
    await checkpoint('creator_relationship_history');
    const beforeHistory = postCount;
    const aHistory = await collaboration.creatorHistory({ creatorId: a.selection.creator_id, activityId: a.scope.activityId });
    const bHistory = await collaboration.creatorHistory({ creatorId: b.selection.creator_id, activityId: b.scope.activityId });
    check(aHistory.total === 1 && hash(aHistory.items[0]) === hash(accepted) && bHistory.total === 1 && hash(bHistory.items[0]) === hash(b.initial) && postCount === beforeHistory, 'creator_actual_scoped_relationships');
    const all: ActivityInvitation[] = [];
    for (let offset = 0; ; offset += 200) { const page = await collaboration.creatorHistory({ creatorId: a.selection.creator_id, offset, limit: 200 }); all.push(...page.items); if (offset + page.items.length >= page.total) break; check(page.items.length > 0 && offset < 2000, 'history_bounded'); }
    check(all.some(item => item.activity_id === a.scope.activityId && item.selection_id === a.selection.id) && all.some(item => item.activity_id === b.scope.activityId && item.selection_id === b.selection.id), 'creator_history_includes_both');
    check(hash(await sideEffects()) === hash(baseline), 'smtp_analyze_controls_unchanged');
    report.status = 'passed'; report.renderer_fixture = { activity_id: a.scope.activityId, selection_id: a.selection.id, creator_id: a.selection.creator_id, independent_activity_id: b.scope.activityId, independent_selection_id: b.selection.id };
    report.checks = ['empty_get_no_posts_or_rows', 'get_projection_revision_stable', 'same_activity_dedup', 'cross_activity_independent', 'progress_no_fabricated_send_or_reply', 'explicit_synthetic_response_time', 'acceptance_no_cooperation_advance', 'same_key_no_extra_response', 'stale_409_unchanged', 'creator_actual_relationships', 'no_smtp_analyze_or_controls_change'];
    // API projection and request counts establish observable GET purity; this
    // does not claim a direct database audit of absent tracking rows.
    await checkpoint('complete');
  } catch (error) {
    report.status = 'failed'; report.error = safeCode(error); await checkpoint(String(report.stage));
    throw new Error(`C verification failed at ${report.stage}: ${report.error}; private ledger retained.`);
  } finally {
    if (baseline) { report.side_effects_unchanged = hash(await sideEffects()) === hash(baseline); if (!report.side_effects_unchanged) { report.status = 'failed'; report.error = 'smtp_analyze_controls_changed'; } }
    await checkpoint(String(report.stage));
    console.log(JSON.stringify({ c_status: report.status, stage: report.stage, ledger }));
    check(report.side_effects_unchanged !== false, 'smtp_analyze_controls_changed');
  }
});
