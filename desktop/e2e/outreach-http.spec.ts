import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest } from '../src/main/match-transport';
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import { OutreachClient } from '../src/main/outreach-client';
import { authenticatedOutreachRequest } from '../src/main/outreach-transport';
import type { Connection, Fetcher } from '../src/main/transport';
import type { CreatorDetail } from '../src/shared/creators';
import type { CandidateView, QueryView } from '../src/shared/match';
import type { Preparation, RecipientBatchCreate } from '../src/shared/outreach';
import { defaultConditions } from '../src/renderer/components/match/discoveryConditionState';

// Opt-in production-adapter acceptance against the coordinator-owned synthetic
// fixture. It launches no browser and makes no provider, model, SMTP, native,
// Keychain, package, or control mutation; Creator writes require explicit gates.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
test.describe.configure({ mode: 'serial' });

const ORIGIN = 'http://127.0.0.1:65164';
const PIN = 'a852307d6908e671ae1998c9741f19ffe65f5048';
const MIGRATION = '20260908_0015';
const UUID_ROUTE = '[0-9a-fA-F-]{36}';
const EXPECTED_FIXTURE = '/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-mjpzjv70/private/client.json';
const REPORT_ACTIVITY = process.env.FMG_OUTREACH_REPORT_ACTIVITY_ID;
const CONTACT_ACTIVITY = process.env.FMG_OUTREACH_CONTACT_ACTIVITY_ID;
const NAME_ACTIVITY = process.env.FMG_OUTREACH_NAME_ACTIVITY_ID;
const ACCEPTED_ACTIVITY = '40425b20-7241-4e44-965b-0ac3a5fb0165';
const ACCEPTED_CREATOR = '14b26ddb-02e5-460f-a67f-77a1f1b7dd12';
const ACCEPTED_ACTIVE_SELECTION = '98772f17-93b7-4191-b5b5-a6404d8946af';
const ACCEPTED_CANCELLED_SELECTION = '3bc9cc29-2d0d-46ba-a667-a04dcc1dc24e';

interface Fixture {
  base_url: string;
  backend_revision: string;
  migration: string;
  workspace_key: string;
  game_id: string;
  reference_work_ids: string[];
}
interface RequestRecord { method: string; family: 'activity' | 'plan' | 'query' | 'selection' | 'batch' }

const identity = (value: { platform: string; account_id: string }) => `${value.platform}\u0000${value.account_id}`;
const assertSafe = (condition: boolean, message: string): void => { if (!condition) throw new Error(message); };
function stableCreatorProfile(creator: CreatorDetail): Omit<CreatorDetail, 'revision' | 'contacts' | 'updated_at' | 'active_email_count' | 'contact_status'> {
  const { revision: _revision, contacts: _contacts, updated_at: _updatedAt, active_email_count: _activeEmailCount,
    contact_status: _contactStatus, ...stable } = creator;
  return stable;
}

test('all nine outreach methods preserve explicit people and immutable preparation through real HTTP', async () => {
  test.skip(Boolean(REPORT_ACTIVITY || CONTACT_ACTIVITY || NAME_ACTIVITY), 'An existing-Activity mode does not create another Activity.');
  test.setTimeout(180_000);
  const fixtureFile = process.env.FMG_QUERY_FIXTURE_FILE;
  test.skip(!fixtureFile, 'Requires exclusive coordinator handoff of the pinned query fixture.');
  if (!fixtureFile) return;

  const resolvedFile = path.resolve(fixtureFile);
  assertSafe(resolvedFile === EXPECTED_FIXTURE, 'The outreach acceptance fixture path is not the exclusive coordinator handoff.');
  const privateDirectory = path.dirname(resolvedFile);
  expect((await stat(resolvedFile)).mode & 0o777).toBe(0o600);
  expect((await stat(privateDirectory)).mode & 0o777).toBe(0o700);
  let fixture: Fixture;
  try { fixture = JSON.parse(await readFile(resolvedFile, 'utf8')) as Fixture; }
  catch { throw new Error('Private outreach fixture unavailable; sensitive details suppressed.'); }
  assertSafe(fixture.base_url === ORIGIN && fixture.backend_revision === PIN && fixture.migration === MIGRATION,
    'The outreach fixture does not match the accepted backend pin.');
  assertSafe(typeof fixture.workspace_key === 'string' && fixture.workspace_key.length > 0,
    'The outreach fixture workspace credential is unavailable.');

  const controlFile = path.join(privateDirectory, 'state', 'control.json');
  const controlBefore = await readFile(controlFile);
  const records: RequestRecord[] = [];
  const selectionCollection = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/selections$`);
  const selectionBulk = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/selections/bulk$`);
  const selectionMutation = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/selections/${UUID_ROUTE}/(update|cancel)$`);
  const batchCollection = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/recipient-batches$`);
  const planCollection = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/discovery-plans$`);
  const queryMutation = new RegExp(`^/api/v2/discovery/queries/${UUID_ROUTE}/(continue|stop)$`);
  const fetcher: Fetcher = async (url, init) => {
    const target = new URL(url), method = String(init.method ?? 'GET').toUpperCase();
    let family: RequestRecord['family'] | undefined;
    if (target.pathname === '/api/v2/activities') family = 'activity';
    else if (planCollection.test(target.pathname)) family = 'plan';
    else if (target.pathname.startsWith('/api/v2/discovery/')) family = 'query';
    else if (target.pathname.includes('/recipient-batches')) family = 'batch';
    else if (target.pathname.includes('/selections')) family = 'selection';
    else if (target.pathname.startsWith('/api/v2/activities/')) family = 'activity';
    const allowedRead = method === 'GET' && (/^\/api\/v2\/activities(\/|$)/.test(target.pathname) || /^\/api\/v2\/discovery\//.test(target.pathname));
    const allowedWrite = method === 'POST' && (target.pathname === '/api/v2/activities' || planCollection.test(target.pathname)
      || queryMutation.test(target.pathname) || selectionCollection.test(target.pathname) || selectionBulk.test(target.pathname)
      || selectionMutation.test(target.pathname) || batchCollection.test(target.pathname));
    if (target.origin !== ORIGIN || !family || (!allowedRead && !allowedWrite)) {
      throw new Error('Outreach acceptance request escaped the strict fixture allowlist.');
    }
    records.push({ method, family });
    return fetch(target, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
  };

  const connection: Connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
  const match = new MatchClient(input => authenticatedMatchRequest(fetcher, connection, input));
  const outreach = new OutreachClient(input => authenticatedOutreachRequest(fetcher, connection, input));
  const activity = await match.createActivity({ data: { name: `F7 HTTP acceptance ${randomUUID().slice(0, 8)}`,
    game_id: fixture.game_id, reference_work_ids: fixture.reference_work_ids }, idempotencyKey: randomUUID() });
  console.log(`F7_HTTP_ACTIVITY ${activity.id}`);

  async function createSettledQuery(batchTarget: number): Promise<{ query: QueryView; candidates: CandidateView[] }> {
    const accepted = await match.createPlan({ activityId: activity.id, data: { ...defaultConditions(), batch_target: batchTarget, result_limit: 6 },
      idempotencyKey: randomUUID() });
    let queryId = '';
    await expect.poll(async () => {
      const plan = await match.plan(accepted.plan_id); queryId = plan.query_id ?? ''; return plan.status;
    }, { timeout: 60_000 }).toBe('ready');
    let query: QueryView | undefined;
    await expect.poll(async () => {
      query = await match.query(queryId);
      return !['queued', 'running'].includes(query.status) && !query.batches.some(batch => ['queued', 'running'].includes(batch.status));
    }, { timeout: 60_000 }).toBe(true);
    const candidates = await match.candidates({ queryId, evidence: 'all', sort: 'relevance', offset: 0, limit: 100 });
    return { query: query!, candidates: candidates.items };
  }

  const firstQuery = await createSettledQuery(2);
  if (firstQuery.query.result_count < 6) {
    await match.continueDiscovery({ queryId: firstQuery.query.id, data: { acknowledge_unknown: false }, idempotencyKey: randomUUID() });
    await expect.poll(async () => {
      firstQuery.query = await match.query(firstQuery.query.id);
      return !['queued', 'running'].includes(firstQuery.query.status)
        && !firstQuery.query.batches.some(batch => ['queued', 'running'].includes(batch.status));
    }, { timeout: 60_000 }).toBe(true);
    firstQuery.candidates = (await match.candidates({ queryId: firstQuery.query.id, evidence: 'all', sort: 'relevance', offset: 0, limit: 100 })).items;
  }
  assertSafe(firstQuery.candidates.length >= 2, 'The accepted synthetic query did not provide two explicit people.');
  const primaryCandidate = firstQuery.candidates.find(candidate => candidate.creator && !candidate.identity_changed);
  assertSafe(Boolean(primaryCandidate), 'The accepted fixture has no current candidate identity for explicit selection.');
  const incompleteCandidate = firstQuery.candidates.find(candidate => identity(candidate) !== identity(primaryCandidate!));
  assertSafe(Boolean(incompleteCandidate), 'The accepted fixture has no distinct incomplete recipient candidate.');

  const primaryAdded = await outreach.add({ activityId: activity.id, data: { candidate_id: primaryCandidate!.id }, idempotencyKey: randomUUID() });
  assertSafe(primaryAdded.selected_contact === null, 'Selection implicitly chose a default contact.');
  assertSafe(primaryAdded.contact_status === 'not_selected', 'A current eligible option was treated as an implicit selection.');
  const bulk = await outreach.bulk({ activityId: activity.id, data: { add_candidate_ids: [incompleteCandidate!.id] }, idempotencyKey: randomUUID() });
  assertSafe(bulk.added_selection_ids.length === 1, 'The explicit one-person bulk selection did not add exactly one selection.');
  let selected = await outreach.selections({ activityId: activity.id, offset: 0, limit: 200 });
  assertSafe(selected.total === 2, 'The Activity selection list does not contain exactly the two explicit people.');
  const incompleteAdded = selected.items.find(item => identity(item.identity) === identity(incompleteCandidate!));
  assertSafe(Boolean(incompleteAdded) && incompleteAdded!.selected_contact === null, 'The incomplete selected person was dropped or implicitly assigned an email.');
  const detailBeforeUpdate = await outreach.selection({ activityId: activity.id, id: primaryAdded.id });
  const preparedPrimary = await outreach.update({ activityId: activity.id, id: primaryAdded.id,
    data: { expected_revision: detailBeforeUpdate.revision, context_token: detailBeforeUpdate.context_token, contact_id: null },
    idempotencyKey: randomUUID() });
  assertSafe(preparedPrimary.selected_contact === null && preparedPrimary.contact_status === 'not_selected',
    'The explicit no-contact update did not preserve the single-address boundary.');
  let staleCode = '';
  try {
    await outreach.update({ activityId: activity.id, id: primaryAdded.id,
      data: { expected_revision: detailBeforeUpdate.revision, context_token: detailBeforeUpdate.context_token, contact_id: null },
      idempotencyKey: randomUUID() });
  } catch (error) { staleCode = typeof error === 'object' && error && 'code' in error ? String(error.code) : ''; }
  assertSafe(staleCode === 'selection_revision_conflict', 'A stale preparation edit did not retain the deterministic revision conflict.');

  const secondQuery = await createSettledQuery(2);
  const duplicate = secondQuery.candidates.find(candidate => identity(candidate) === identity(primaryCandidate!));
  assertSafe(Boolean(duplicate) && duplicate!.id !== primaryCandidate!.id, 'The second query did not expose a distinct candidate row for account deduplication.');
  const deduplicated = await outreach.add({ activityId: activity.id, data: { candidate_id: duplicate!.id }, idempotencyKey: randomUUID() });
  assertSafe(deduplicated.id === primaryAdded.id && deduplicated.candidate_id === primaryAdded.candidate_id,
    'Cross-query account deduplication did not preserve the original selection candidate.');

  const frozenChoices = [incompleteAdded!, preparedPrimary].map(item => ({ selection_id: item.id,
    expected_revision: item.revision, context_token: item.context_token }));
  if (secondQuery.query.result_count < 6) {
    await match.continueDiscovery({ queryId: secondQuery.query.id, data: { acknowledge_unknown: false }, idempotencyKey: randomUUID() });
    await expect.poll(async () => {
      secondQuery.query = await match.query(secondQuery.query.id);
      return !['queued', 'running'].includes(secondQuery.query.status)
        && !secondQuery.query.batches.some(batch => ['queued', 'running'].includes(batch.status));
    }, { timeout: 60_000 }).toBe(true);
  }
  const laterPage = await match.candidates({ queryId: secondQuery.query.id, evidence: 'all', sort: 'relevance', offset: 0, limit: 100 });
  const chosenIdentities = new Set([identity(primaryCandidate!), identity(incompleteCandidate!)]);
  const lateCandidate = laterPage.items.find(candidate => !chosenIdentities.has(identity(candidate)));
  assertSafe(Boolean(lateCandidate), 'The synthetic continuation did not provide a late unselected person.');
  selected = await outreach.selections({ activityId: activity.id, offset: 0, limit: 200 });
  assertSafe(!selected.items.some(item => identity(item.identity) === identity(lateCandidate!)), 'A late candidate was selected without an explicit mutation.');

  for (const queryId of [firstQuery.query.id, secondQuery.query.id]) {
    const stopped = await match.stop({ queryId, idempotencyKey: randomUUID() });
    assertSafe(stopped.query_id === queryId && stopped.stop_requested, 'Discovery stop did not succeed before recipient freeze.');
  }
  const freezeData: RecipientBatchCreate = { request_id: randomUUID(), recipients: frozenChoices };
  const freezeKey = randomUUID();
  const batch = await outreach.freeze({ activityId: activity.id, data: freezeData, idempotencyKey: freezeKey });
  assertSafe(batch.recipient_count === 2 && batch.send_ready_count === 0 && batch.needs_repair_count === 2,
    'The frozen batch did not retain both complete and incomplete people as repairable.');
  assertSafe(batch.recipients.map(item => item.selection_id).join('|') === frozenChoices.map(item => item.selection_id).join('|'),
    'The frozen recipient order differs from the explicit order.');
  assertSafe(batch.recipients.every(item => item.snapshot.selected_contact === null),
    'The incomplete frozen snapshots unexpectedly acquired a contact.');
  assertSafe(!batch.recipients.some(item => identity(item.snapshot.identity) === identity(lateCandidate!)),
    'A late unselected person entered the frozen recipient list.');
  const sameKey = await outreach.freeze({ activityId: activity.id, data: freezeData, idempotencyKey: freezeKey });
  const persistent = await outreach.freeze({ activityId: activity.id, data: freezeData, idempotencyKey: randomUUID() });
  assertSafe(sameKey.id === batch.id && persistent.id === batch.id, 'Same-intent retry or persistent request-ID recovery created another batch.');

  const batchPage = await outreach.batches({ activityId: activity.id, offset: 0, limit: 200 });
  assertSafe(batchPage.items.some(item => item.id === batch.id), 'The frozen batch is missing from Activity history.');
  const reopened = await outreach.batch({ activityId: activity.id, id: batch.id });
  const primaryCurrent = reopened.recipients.find(item => item.selection_id === preparedPrimary.id)!.preparation;
  const edited = await outreach.update({ activityId: activity.id, id: primaryCurrent.id,
    data: { expected_revision: primaryCurrent.revision, context_token: primaryCurrent.context_token, work_ids: [] }, idempotencyKey: randomUUID() });
  assertSafe(edited.revision === primaryCurrent.revision + 1 && edited.selected_contact === null,
    'The explicit current preparation edit was not applied.');
  const incompleteCurrent = reopened.recipients.find(item => item.selection_id === incompleteAdded!.id)!.preparation;
  const cancelled = await outreach.cancel({ activityId: activity.id, id: incompleteCurrent.id,
    data: { expected_revision: incompleteCurrent.revision }, idempotencyKey: randomUUID() });
  assertSafe(!cancelled.active, 'The test-owned selection cancellation was not applied.');

  const history = await outreach.batch({ activityId: activity.id, id: batch.id });
  const historicalPrimary = history.recipients.find(item => item.selection_id === preparedPrimary.id)!;
  const historicalIncomplete = history.recipients.find(item => item.selection_id === incompleteAdded!.id)!;
  assertSafe(historicalPrimary.snapshot.revision === preparedPrimary.revision
    && historicalPrimary.preparation.revision === edited.revision && historicalPrimary.source_changed,
  'A current preparation edit rewrote or obscured the immutable initial snapshot.');
  assertSafe(historicalIncomplete.snapshot.active && !historicalIncomplete.preparation.active && historicalIncomplete.source_changed,
    'Current cancellation rewrote or obscured the immutable initial selection snapshot.');
  const activeOnly = await outreach.selections({ activityId: activity.id, offset: 0, limit: 200 });
  const withCancelled = await outreach.selections({ activityId: activity.id, includeCancelled: true, offset: 0, limit: 200 });
  assertSafe(activeOnly.total === 1 && withCancelled.total === 2, 'Cancelled history was lost or remained in the active selection list.');

  const writesBeforeHistoryReads = records.filter(record => record.method === 'POST').length;
  await outreach.selection({ activityId: activity.id, id: preparedPrimary.id });
  await outreach.selections({ activityId: activity.id, includeCancelled: true, offset: 0, limit: 200 });
  await outreach.batches({ activityId: activity.id, offset: 0, limit: 200 });
  await outreach.batch({ activityId: activity.id, id: batch.id });
  assertSafe(records.filter(record => record.method === 'POST').length === writesBeforeHistoryReads,
    'Opening current preparation or immutable history caused an unexpected write.');
  assertSafe(controlBefore.equals(await readFile(controlFile)), 'The synthetic fixture queue controls changed during outreach acceptance.');

  const writes = records.filter(record => record.method === 'POST');
  console.log(`F7_HTTP_COUNTS ${JSON.stringify({ activityId: activity.id, activities: 1, queries: 2, selections: 2, batches: 1,
    postAttempts: writes.length, activityPosts: writes.filter(item => item.family === 'activity').length,
    planPosts: writes.filter(item => item.family === 'plan').length, queryPosts: writes.filter(item => item.family === 'query').length,
    selectionPosts: writes.filter(item => item.family === 'selection').length, batchPosts: writes.filter(item => item.family === 'batch').length })}`);
});

test('explicit second contact requires source-version reconfirmation through real HTTP', async () => {
  test.skip(!CONTACT_ACTIVITY, 'Requires the accepted F7 Activity for the bounded contact supplement.');
  test.setTimeout(60_000);
  const fixtureFile = process.env.FMG_QUERY_FIXTURE_FILE;
  if (!fixtureFile || !CONTACT_ACTIVITY) return;
  assertSafe(CONTACT_ACTIVITY === ACCEPTED_ACTIVITY, 'The contact supplement is restricted to the accepted F7 Activity.');

  const resolvedFile = path.resolve(fixtureFile), privateDirectory = path.dirname(resolvedFile);
  assertSafe(resolvedFile === EXPECTED_FIXTURE, 'The contact supplement fixture path is not the exclusive coordinator handoff.');
  expect((await stat(resolvedFile)).mode & 0o777).toBe(0o600);
  expect((await stat(privateDirectory)).mode & 0o777).toBe(0o700);
  let fixture: Fixture;
  try { fixture = JSON.parse(await readFile(resolvedFile, 'utf8')) as Fixture; }
  catch { throw new Error('Private outreach fixture unavailable; sensitive details suppressed.'); }
  assertSafe(fixture.base_url === ORIGIN && fixture.backend_revision === PIN && fixture.migration === MIGRATION,
    'The contact supplement fixture does not match the accepted backend pin.');
  assertSafe(typeof fixture.workspace_key === 'string' && fixture.workspace_key.length > 0,
    'The contact supplement workspace credential is unavailable.');

  const controlFile = path.join(privateDirectory, 'state', 'control.json'), controlBefore = await readFile(controlFile);
  const writes: Array<{ method: string; family: 'creator' | 'selection' | 'batch' }> = [];
  const creatorDetailRoute = new RegExp(`^/api/v2/library/creators/${UUID_ROUTE}$`);
  const creatorContactCollection = new RegExp(`^/api/v2/library/creators/${UUID_ROUTE}/contacts$`);
  const creatorContactDetail = new RegExp(`^/api/v2/library/creators/${UUID_ROUTE}/contacts/${UUID_ROUTE}$`);
  const selectionCollection = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/selections$`);
  const selectionDetail = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/selections/${UUID_ROUTE}$`);
  const selectionMutation = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/selections/${UUID_ROUTE}/(update|cancel)$`);
  const batchCollection = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/recipient-batches$`);
  const batchDetail = new RegExp(`^/api/v2/activities/${UUID_ROUTE}/recipient-batches/${UUID_ROUTE}$`);
  const fetcher: Fetcher = async (url, init) => {
    const target = new URL(url), method = String(init.method ?? 'GET').toUpperCase();
    let family: 'creator' | 'selection' | 'batch' | undefined;
    if (creatorDetailRoute.test(target.pathname) || creatorContactCollection.test(target.pathname) || creatorContactDetail.test(target.pathname)) family = 'creator';
    else if (selectionCollection.test(target.pathname) || selectionDetail.test(target.pathname) || selectionMutation.test(target.pathname)) family = 'selection';
    else if (batchCollection.test(target.pathname) || batchDetail.test(target.pathname)) family = 'batch';
    const allowed = target.origin === ORIGIN && family && (
      (method === 'GET' && (creatorDetailRoute.test(target.pathname) || selectionDetail.test(target.pathname) || batchDetail.test(target.pathname)))
      || (method === 'POST' && (creatorContactCollection.test(target.pathname) || selectionCollection.test(target.pathname)
        || selectionMutation.test(target.pathname) || batchCollection.test(target.pathname)))
      || (method === 'PATCH' && creatorContactDetail.test(target.pathname))
    );
    if (!allowed || !family) throw new Error('Contact supplement request escaped the strict fixture allowlist.');
    if (method !== 'GET') writes.push({ method, family });
    return fetch(target, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
  };

  const connection: Connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
  const creators = new CreatorClient(input => authenticatedCreatorRequest(fetcher, connection, input));
  const outreach = new OutreachClient(input => authenticatedOutreachRequest(fetcher, connection, input));
  const initial = await outreach.selection({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION });
  assertSafe(initial.active && initial.selected_contact === null && initial.contact_status === 'not_selected',
    'The accepted primary selection no longer has its explicit no-contact starting state.');
  const creatorBefore = await creators.detail(initial.creator_id);
  const oldContacts = new Map(creatorBefore.contacts.map(contact => [contact.id, contact]));
  const suffix = ACCEPTED_ACTIVITY.slice(0, 8);
  const firstEmail = `f7-http-${suffix}-first@example.com`, secondEmail = `f7-http-${suffix}-second@example.com`;
  const firstCreated = await creators.createContact({ creatorId: creatorBefore.id,
    data: { expected_revision: creatorBefore.revision, email: firstEmail, purpose: 'F7 explicit first fixture contact',
      source_url: `https://example.com/f7/${suffix}/first` }, idempotencyKey: `f7-contact-${suffix}-first` });
  const firstContact = firstCreated.contacts.find(contact => contact.email === firstEmail);
  assertSafe(Boolean(firstContact), 'The first fixture-purpose contact was not returned after creation.');
  const secondCreated = await creators.createContact({ creatorId: creatorBefore.id,
    data: { expected_revision: firstCreated.revision, email: secondEmail, purpose: 'F7 explicit second fixture contact',
      source_url: `https://example.com/f7/${suffix}/second` }, idempotencyKey: `f7-contact-${suffix}-second` });
  const secondContact = secondCreated.contacts.find(contact => contact.email === secondEmail);
  assertSafe(Boolean(secondContact) && secondContact!.id !== firstContact!.id, 'The second fixture-purpose contact was not created distinctly.');
  assertSafe(JSON.stringify(stableCreatorProfile(secondCreated)) === JSON.stringify(stableCreatorProfile(creatorBefore)),
    'Adding fixture contacts changed an unrelated Creator field.');
  for (const [contactId, contact] of oldContacts) {
    assertSafe(JSON.stringify(secondCreated.contacts.find(item => item.id === contactId)) === JSON.stringify(contact),
      'Adding fixture contacts changed a pre-existing Creator contact.');
  }

  const withOptions = await outreach.selection({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION });
  const ownedOptions = withOptions.contact_options.filter(contact => contact.id === firstContact!.id || contact.id === secondContact!.id);
  assertSafe(withOptions.selected_contact === null && withOptions.contact_status === 'not_selected'
    && ownedOptions.length === 2 && ownedOptions.every(contact => contact.status === 'eligible'),
  'Two current fixture contacts were not exposed without an implicit default.');
  const selectedSecond = await outreach.update({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION,
    data: { expected_revision: withOptions.revision, context_token: withOptions.context_token, contact_id: secondContact!.id },
    idempotencyKey: `f7-select-${suffix}-second` });
  assertSafe(selectedSecond.contact_status === 'eligible' && selectedSecond.selected_contact?.id === secondContact!.id,
    'The explicit second contact selection was not saved.');
  const selectedSnapshot = selectedSecond.selected_contact!;

  const changedCreator = await creators.updateContact({ creatorId: creatorBefore.id, contactId: secondContact!.id,
    data: { expected_revision: secondCreated.revision, purpose: 'F7 explicit second fixture contact revised',
      source_url: `https://example.com/f7/${suffix}/second-revised` } });
  const changed = await outreach.selection({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION });
  const changedOption = changed.contact_options.find(contact => contact.id === secondContact!.id);
  assertSafe(Boolean(changedOption), 'The changed current second contact disappeared from the preparation options.');
  assertSafe(changed.contact_status === 'changed' && JSON.stringify(changed.selected_contact) === JSON.stringify(selectedSnapshot)
    && changedOption!.purpose === 'F7 explicit second fixture contact revised'
    && changedOption!.source_url === `https://example.com/f7/${suffix}/second-revised`,
  'A current contact source change did not retain the selected snapshot and require confirmation.');
  const reconfirmed = await outreach.update({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION,
    data: { expected_revision: changed.revision, context_token: changed.context_token, contact_id: secondContact!.id },
    idempotencyKey: `f7-reselect-${suffix}-second` });
  assertSafe(reconfirmed.contact_status === 'eligible' && reconfirmed.selected_contact?.purpose === changedOption!.purpose
    && reconfirmed.selected_contact.source_url === changedOption!.source_url,
  'Explicitly reselecting the changed current contact did not refresh the saved contact version.');

  const cancelledBefore = await outreach.selection({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_CANCELLED_SELECTION });
  assertSafe(!cancelledBefore.active, 'The accepted historical selection was unexpectedly active before the supplement.');
  const reactivated = await outreach.add({ activityId: ACCEPTED_ACTIVITY, data: { candidate_id: cancelledBefore.candidate_id },
    idempotencyKey: `f7-reactivate-${suffix}-second-person` });
  assertSafe(reactivated.id === ACCEPTED_CANCELLED_SELECTION && reactivated.active,
    'The explicitly chosen historical person was not reactivated for the full-N freeze.');
  const freezeData: RecipientBatchCreate = { request_id: randomUUID(), recipients: [reconfirmed, reactivated].map(item => ({
    selection_id: item.id, expected_revision: item.revision, context_token: item.context_token })) };
  const batch = await outreach.freeze({ activityId: ACCEPTED_ACTIVITY, data: freezeData,
    idempotencyKey: `f7-contact-freeze-${suffix}` });
  assertSafe(batch.recipient_count === 2 && batch.recipients.map(item => item.selection_id).join('|')
    === [ACCEPTED_ACTIVE_SELECTION, ACCEPTED_CANCELLED_SELECTION].join('|'),
  'The contact supplement freeze did not preserve the explicit two-person order and count.');

  const finalCreator = await creators.updateContact({ creatorId: creatorBefore.id, contactId: secondContact!.id,
    data: { expected_revision: changedCreator.revision, purpose: 'F7 explicit second fixture contact renderer change',
      source_url: `https://example.com/f7/${suffix}/second-renderer-change` } });
  const finalPrimary = await outreach.selection({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION });
  assertSafe(finalPrimary.active && finalPrimary.contact_status === 'changed'
    && finalPrimary.selected_contact?.purpose === 'F7 explicit second fixture contact revised'
    && finalPrimary.contact_options.find(contact => contact.id === secondContact!.id)?.purpose
      === 'F7 explicit second fixture contact renderer change',
  'The renderer handback did not retain one active selection with a changed selected-contact version.');
  const finalOther = await outreach.cancel({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_CANCELLED_SELECTION,
    data: { expected_revision: reactivated.revision }, idempotencyKey: `f7-recancel-${suffix}-second-person` });
  assertSafe(!finalOther.active, 'The temporary full-N selection was not returned to its historical cancelled state.');
  const frozenHistory = await outreach.batch({ activityId: ACCEPTED_ACTIVITY, id: batch.id });
  assertSafe(frozenHistory.recipients[0]?.snapshot.selected_contact?.purpose === 'F7 explicit second fixture contact revised'
    && frozenHistory.recipients[0]?.source_changed,
  'Later contact source changes rewrote or obscured the frozen selected-contact snapshot.');
  assertSafe(finalCreator.contacts.filter(contact => contact.id === firstContact!.id || contact.id === secondContact!.id).length === 2,
    'A fixture-purpose contact was removed during the supplement.');
  assertSafe(controlBefore.equals(await readFile(controlFile)), 'The synthetic fixture queue controls changed during the contact supplement.');

  console.log(`F7_HTTP_CONTACT_SUPPLEMENT ${JSON.stringify({ activityId: ACCEPTED_ACTIVITY, creatorId: creatorBefore.id,
    contactIds: [firstContact!.id, secondContact!.id], selectionIds: [ACCEPTED_ACTIVE_SELECTION, ACCEPTED_CANCELLED_SELECTION],
    batchId: batch.id, finalPrimaryStatus: finalPrimary.contact_status, finalOtherActive: finalOther.active,
    postAttempts: writes.filter(item => item.method === 'POST').length, patchAttempts: writes.filter(item => item.method === 'PATCH').length,
    creatorWrites: writes.filter(item => item.family === 'creator').length,
    selectionWrites: writes.filter(item => item.family === 'selection').length,
    batchWrites: writes.filter(item => item.family === 'batch').length })}`);
});

test('name-only Creator patch preserves contacts and immutable outreach history through real HTTP', async () => {
  test.skip(!NAME_ACTIVITY, 'Requires the accepted F7 Activity for the bounded public-name supplement.');
  test.setTimeout(60_000);
  const fixtureFile = process.env.FMG_QUERY_FIXTURE_FILE;
  if (!fixtureFile || !NAME_ACTIVITY) return;
  assertSafe(NAME_ACTIVITY === ACCEPTED_ACTIVITY, 'The public-name supplement is restricted to the accepted F7 Activity.');

  const resolvedFile = path.resolve(fixtureFile), privateDirectory = path.dirname(resolvedFile);
  assertSafe(resolvedFile === EXPECTED_FIXTURE, 'The public-name supplement fixture path is not the exclusive coordinator handoff.');
  expect((await stat(resolvedFile)).mode & 0o777).toBe(0o600);
  expect((await stat(privateDirectory)).mode & 0o777).toBe(0o700);
  let fixture: Fixture;
  try { fixture = JSON.parse(await readFile(resolvedFile, 'utf8')) as Fixture; }
  catch { throw new Error('Private outreach fixture unavailable; sensitive details suppressed.'); }
  assertSafe(fixture.base_url === ORIGIN && fixture.backend_revision === PIN && fixture.migration === MIGRATION,
    'The public-name supplement fixture does not match the accepted backend pin.');
  assertSafe(typeof fixture.workspace_key === 'string' && fixture.workspace_key.length > 0,
    'The public-name supplement workspace credential is unavailable.');

  const controlFile = path.join(privateDirectory, 'state', 'control.json'), controlBefore = await readFile(controlFile);
  const creatorRoute = `/api/v2/library/creators/${ACCEPTED_CREATOR}`;
  const selectionRoute = `/api/v2/activities/${ACCEPTED_ACTIVITY}/selections/${ACCEPTED_ACTIVE_SELECTION}`;
  const batchCollection = `/api/v2/activities/${ACCEPTED_ACTIVITY}/recipient-batches`;
  const batchDetail = new RegExp(`^${batchCollection}/${UUID_ROUTE}$`);
  const records: Array<{ method: string; path: string }> = [];
  let exactPatchBody = false;
  const fetcher: Fetcher = async (url, init) => {
    const target = new URL(url), method = String(init.method ?? 'GET').toUpperCase();
    const allowedGet = method === 'GET' && (target.pathname === creatorRoute || target.pathname === selectionRoute
      || target.pathname === batchCollection || batchDetail.test(target.pathname));
    const allowedPatch = method === 'PATCH' && target.pathname === creatorRoute;
    if (target.origin !== ORIGIN || (!allowedGet && !allowedPatch)) {
      throw new Error('Public-name supplement request escaped the strict fixture allowlist.');
    }
    if (allowedPatch) {
      let body: unknown;
      try { body = JSON.parse(String(init.body)); } catch { throw new Error('Public-name supplement PATCH body was not JSON.'); }
      const raw = body as Record<string, unknown>;
      exactPatchBody = Object.keys(raw).sort().join('|') === 'expected_revision|public_name'
        && raw.public_name === 'Fixture F7 Creator' && Number.isInteger(raw.expected_revision);
      if (!exactPatchBody) throw new Error('Public-name supplement PATCH contained a field outside the authorized shape.');
    }
    records.push({ method, path: target.pathname });
    return fetch(target, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
  };

  const connection: Connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
  const creators = new CreatorClient(input => authenticatedCreatorRequest(fetcher, connection, input));
  const outreach = new OutreachClient(input => authenticatedOutreachRequest(fetcher, connection, input));
  const beforePreparation = await outreach.selection({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION });
  const beforeCreator = await creators.detail(ACCEPTED_CREATOR);
  assertSafe(beforePreparation.creator_id === ACCEPTED_CREATOR && beforePreparation.public_name === null,
    'The accepted primary preparation no longer has the authorized empty public-name state.');
  assertSafe(beforeCreator.id === ACCEPTED_CREATOR && beforeCreator.public_name === null
    && (!Object.hasOwn(beforeCreator.manual_overrides, 'public_name') || beforeCreator.manual_overrides.public_name === null),
  'The accepted Creator no longer has an empty effective and manual public name; no PATCH is allowed.');
  const beforeBatchPage = await outreach.batches({ activityId: ACCEPTED_ACTIVITY, offset: 0, limit: 200 });
  const beforeHistory = await Promise.all(beforeBatchPage.items.map(item => outreach.batch({ activityId: ACCEPTED_ACTIVITY, id: item.id })));

  await creators.update({ id: ACCEPTED_CREATOR,
    data: { expected_revision: beforeCreator.revision, public_name: 'Fixture F7 Creator' } });
  const afterCreator = await creators.detail(ACCEPTED_CREATOR);
  const afterPreparation = await outreach.selection({ activityId: ACCEPTED_ACTIVITY, id: ACCEPTED_ACTIVE_SELECTION });
  const afterBatchPage = await outreach.batches({ activityId: ACCEPTED_ACTIVITY, offset: 0, limit: 200 });
  const afterHistory = await Promise.all(afterBatchPage.items.map(item => outreach.batch({ activityId: ACCEPTED_ACTIVITY, id: item.id })));

  const withoutAuthorizedCreatorChange = (creator: CreatorDetail) => {
    const { revision: _revision, updated_at: _updatedAt, public_name: _publicName,
      public_name_confirmed: _publicNameConfirmed, manual_overrides: _manualOverrides,
      overridden_fields: _overriddenFields, ...unchanged } = creator;
    return unchanged;
  };
  const expectedOverrides = { ...beforeCreator.manual_overrides,
    public_name: 'Fixture F7 Creator', public_name_confirmed: false };
  assertSafe(afterCreator.revision === beforeCreator.revision + 1 && afterCreator.public_name === 'Fixture F7 Creator'
    && !afterCreator.public_name_confirmed, 'The name-only PATCH did not apply exactly one unconfirmed Creator revision.');
  assertSafe(JSON.stringify(withoutAuthorizedCreatorChange(afterCreator)) === JSON.stringify(withoutAuthorizedCreatorChange(beforeCreator)),
    'The name-only PATCH changed an unauthorized Creator field or contact.');
  assertSafe(JSON.stringify(afterCreator.manual_overrides) === JSON.stringify(expectedOverrides)
    && JSON.stringify(afterCreator.overridden_fields) === JSON.stringify(Object.keys(expectedOverrides).sort()),
  'The name-only PATCH changed manual overrides beyond the name and implicit false confirmation.');

  const withoutDerivedPreparationName = (preparation: Preparation) => {
    const { public_name: _publicName, public_name_confirmed: _publicNameConfirmed,
      name_confirmed_at: _nameConfirmedAt, context_token: _contextToken, ...unchanged } = preparation;
    return unchanged;
  };
  assertSafe(afterPreparation.public_name === 'Fixture F7 Creator' && !afterPreparation.public_name_confirmed
    && afterPreparation.name_confirmed_at === null && afterPreparation.context_token !== beforePreparation.context_token,
  'Preparation did not expose the new unconfirmed public name and current context.');
  assertSafe(JSON.stringify(withoutDerivedPreparationName(afterPreparation)) === JSON.stringify(withoutDerivedPreparationName(beforePreparation)),
    'The name-only PATCH changed selection state, contacts, work, evaluation, or sender facts.');
  assertSafe(JSON.stringify(afterBatchPage) === JSON.stringify(beforeBatchPage),
    'The name-only PATCH changed the frozen batch list.');
  const immutableHistory = (items: typeof beforeHistory) => items.map(batch => ({ ...batch,
    recipients: batch.recipients.map(({ preparation: _preparation, source_changed: _sourceChanged,
      current_missing_fields: _currentMissingFields, ...immutable }) => immutable) }));
  assertSafe(JSON.stringify(immutableHistory(afterHistory)) === JSON.stringify(immutableHistory(beforeHistory)),
    'The name-only PATCH changed an immutable recipient or snapshot.');
  assertSafe(exactPatchBody && records.filter(item => item.method === 'PATCH').length === 1
    && records.every(item => item.method === 'GET' || item.method === 'PATCH'),
  'The public-name supplement did not retain its single-PATCH method boundary.');
  assertSafe(controlBefore.equals(await readFile(controlFile)), 'Fixture controls changed during the public-name supplement.');

  console.log(`F7_HTTP_NAME_SUPPLEMENT ${JSON.stringify({ activityId: ACCEPTED_ACTIVITY, creatorId: ACCEPTED_CREATOR,
    selectionId: ACCEPTED_ACTIVE_SELECTION, publicNameSet: true, publicNameConfirmed: afterPreparation.public_name_confirmed,
    selectionRevision: afterPreparation.revision, contactStatus: afterPreparation.contact_status,
    batchIds: afterBatchPage.items.map(item => item.id), getAttempts: records.filter(item => item.method === 'GET').length,
    patchAttempts: records.filter(item => item.method === 'PATCH').length, postAttempts: records.filter(item => item.method === 'POST').length })}`);
});

test('read-only handback reports public IDs and final human-selection states', async () => {
  test.skip(!REPORT_ACTIVITY, 'Requires an accepted F7 Activity ID for read-only handback.');
  const fixtureFile = process.env.FMG_QUERY_FIXTURE_FILE;
  if (!fixtureFile || !REPORT_ACTIVITY) return;
  const resolvedFile = path.resolve(fixtureFile), privateDirectory = path.dirname(resolvedFile);
  assertSafe(resolvedFile === EXPECTED_FIXTURE, 'The report fixture path is not the exclusive coordinator handoff.');
  expect((await stat(resolvedFile)).mode & 0o777).toBe(0o600);
  expect((await stat(privateDirectory)).mode & 0o777).toBe(0o700);
  let fixture: Fixture;
  try { fixture = JSON.parse(await readFile(resolvedFile, 'utf8')) as Fixture; }
  catch { throw new Error('Private outreach fixture unavailable; sensitive details suppressed.'); }
  assertSafe(fixture.base_url === ORIGIN && fixture.backend_revision === PIN && fixture.migration === MIGRATION,
    'The report fixture does not match the accepted backend pin.');
  const controlFile = path.join(privateDirectory, 'state', 'control.json'), controlBefore = await readFile(controlFile);
  let getCount = 0;
  const fetcher: Fetcher = async (url, init) => {
    const target = new URL(url), method = String(init.method ?? 'GET').toUpperCase();
    if (target.origin !== ORIGIN || method !== 'GET'
      || !(/^\/api\/v2\/activities(\/|$)/.test(target.pathname) || /^\/api\/v2\/discovery\//.test(target.pathname))) {
      throw new Error('Read-only F7 handback escaped its strict allowlist.');
    }
    getCount++;
    return fetch(target, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
  };
  const connection: Connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
  const match = new MatchClient(input => authenticatedMatchRequest(fetcher, connection, input));
  const outreach = new OutreachClient(input => authenticatedOutreachRequest(fetcher, connection, input));
  const activity = await match.activity(REPORT_ACTIVITY);
  const selections = await outreach.selections({ activityId: REPORT_ACTIVITY, includeCancelled: true, offset: 0, limit: 200 });
  const batches = await outreach.batches({ activityId: REPORT_ACTIVITY, offset: 0, limit: 200 });
  const selectedIdentities = new Set(selections.items.map(item => identity(item.identity)));
  const queryIds: string[] = [], candidateIds: string[] = [], unselectedCandidateIds: string[] = [];
  for (const query of activity.queries) {
    queryIds.push(query.id);
    const page = await match.candidates({ queryId: query.id, evidence: 'all', sort: 'relevance', offset: 0, limit: 100 });
    for (const candidate of page.items) {
      candidateIds.push(candidate.id);
      if (!selectedIdentities.has(identity(candidate))) unselectedCandidateIds.push(candidate.id);
    }
  }
  assertSafe(selections.total === 2 && selections.items.filter(item => item.active).length === 1,
    'The accepted Activity no longer has its final one-active/one-cancelled selection state.');
  assertSafe(batches.total === 1 && unselectedCandidateIds.length > 0,
    'The accepted Activity no longer has one batch plus naturally unselected candidates.');
  assertSafe(controlBefore.equals(await readFile(controlFile)), 'Fixture controls changed during the read-only handback.');
  console.log(`F7_HTTP_HANDBACK ${JSON.stringify({ activityId: activity.id, queryIds,
    candidateIds: [...new Set(candidateIds)], unselectedCandidateIds: [...new Set(unselectedCandidateIds)],
    selections: selections.items.map(item => ({ selectionId: item.id, candidateId: item.candidate_id, active: item.active,
      selectedContact: item.selected_contact !== null, missingFields: item.missing_fields })),
    batchIds: batches.items.map(item => item.id), readRequests: getCount, writeRequests: 0 })}`);
});
