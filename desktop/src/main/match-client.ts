import type * as DTO from '../shared/match';
import { decodeActivity, decodeActivityDetail, decodeCandidate, decodeDiscoveryAccepted, decodeEvaluation, decodeEvaluationAccepted, decodeEvaluationResult, decodePage, decodePlan, decodePlanAccepted, decodeQuery, decodeStopped, identifier, integer, keys, object, sameID } from './match-validation';
import { matchOutcomeUnknown, validateMatchRequest, type MatchRequest } from './match-transport';
export type { MatchRequest } from './match-transport';
export { matchOutcomeUnknown, validateMatchRequest } from './match-transport';
type Input<K extends keyof DTO.MatchAPI> = Parameters<DTO.MatchAPI[K]>[0];
const activities = '/api/v2/activities', discovery = '/api/v2/discovery';
function input(value: unknown, allowed: string[]) { const raw = object(value, 'input'); keys(raw, allowed, 'input'); return raw; }
function pagination(raw: Record<string, unknown>, max: number) {
  return { offset: String(integer(raw.offset === undefined ? 0 : raw.offset, 'input')), limit: String(integer(raw.limit === undefined ? 50 : raw.limit, 'input', 1, max)) };
}
/** Main-only narrow client. IPC's existing publicResult supplies the Result envelope. */
export class MatchClient {
  constructor(private readonly request: (input: MatchRequest) => Promise<unknown>) {}
  private async send<T>(request: MatchRequest, decode: (value: unknown) => T): Promise<T> {
    const valid = validateMatchRequest(request);
    const value = await this.request(valid);
    try { return decode(value); } catch (error) { throw valid.method === 'POST' ? matchOutcomeUnknown() : error; }
  }
  async activities(value: Input<'activities'>): Promise<DTO.ActivityPage> {
    const raw = input(value, ['offset', 'limit']);
    return this.send({ method: 'GET', path: activities, query: pagination(raw, 100) }, result => decodePage(result, decodeActivity, 100, item => item.id));
  }
  async createActivity(value: Input<'createActivity'>): Promise<DTO.ActivityView> {
    const raw = input(value, ['data', 'idempotencyKey']);
    const gameId = identifier(object(raw.data, 'input').game_id, 'input');
    return this.send({ method: 'POST', path: activities, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, result => {
      const activity = decodeActivity(result); sameID(activity.game_id, gameId); return activity;
    });
  }
  async activity(id: string): Promise<DTO.ActivityDetail> {
    identifier(id, 'input'); return this.send({ method: 'GET', path: `${activities}/${id}` }, value => decodeActivityDetail(value, id));
  }
  async plans(value: Input<'plans'>): Promise<DTO.PlanPage> {
    const raw = input(value, ['activityId', 'offset', 'limit']), id = identifier(raw.activityId, 'input');
    return this.send({ method: 'GET', path: `${activities}/${id}/discovery-plans`, query: pagination(raw, 200) }, result => decodePage(result, item => decodePlan(item, undefined, id), 200, item => item.id));
  }
  async createPlan(value: Input<'createPlan'>): Promise<DTO.PlanAccepted> {
    const raw = input(value, ['activityId', 'data', 'idempotencyKey']), id = identifier(raw.activityId, 'input');
    return this.send({ method: 'POST', path: `${activities}/${id}/discovery-plans`, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, decodePlanAccepted);
  }
  async plan(id: string): Promise<DTO.PlanView> {
    identifier(id, 'input'); return this.send({ method: 'GET', path: `${discovery}/plans/${id}` }, value => decodePlan(value, id));
  }
  async retryPlan(value: Input<'retryPlan'>): Promise<DTO.PlanAccepted> {
    const raw = input(value, ['id', 'idempotencyKey']), id = identifier(raw.id, 'input');
    return this.send({ method: 'POST', path: `${discovery}/plans/${id}/retry`, idempotencyKey: raw.idempotencyKey as string }, result => decodePlanAccepted(result, id));
  }
  async query(id: string): Promise<DTO.QueryView> {
    identifier(id, 'input'); return this.send({ method: 'GET', path: `${discovery}/queries/${id}` }, value => decodeQuery(value, id));
  }
  async candidates(value: Input<'candidates'>): Promise<DTO.CandidatePage> {
    const raw = input(value, ['queryId', 'offset', 'limit']), id = identifier(raw.queryId, 'input');
    return this.send({ method: 'GET', path: `${discovery}/queries/${id}/results`, query: pagination(raw, 100) }, result => decodePage(result, decodeCandidate, 100, item => item.id));
  }
  async stop(value: Input<'stop'>): Promise<DTO.DiscoveryStopped> {
    const raw = input(value, ['queryId', 'idempotencyKey']), id = identifier(raw.queryId, 'input');
    return this.send({ method: 'POST', path: `${discovery}/queries/${id}/stop`, idempotencyKey: raw.idempotencyKey as string }, result => decodeStopped(result, id));
  }
  async continueDiscovery(value: Input<'continueDiscovery'>): Promise<DTO.DiscoveryAccepted> {
    const raw = input(value, ['queryId', 'data', 'idempotencyKey']), id = identifier(raw.queryId, 'input');
    return this.send({ method: 'POST', path: `${discovery}/queries/${id}/continue`, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, result => decodeDiscoveryAccepted(result, id));
  }
  async evaluations(value: Input<'evaluations'>): Promise<DTO.EvaluationPage> {
    const raw = input(value, ['queryId', 'offset', 'limit']), id = identifier(raw.queryId, 'input');
    return this.send({ method: 'GET', path: `${discovery}/queries/${id}/evaluations`, query: pagination(raw, 200) }, result => decodePage(result, item => decodeEvaluation(item, undefined, id), 200, item => item.id));
  }
  async evaluate(value: Input<'evaluate'>): Promise<DTO.EvaluationAccepted> {
    const raw = input(value, ['queryId', 'data', 'idempotencyKey']), id = identifier(raw.queryId, 'input');
    return this.send({ method: 'POST', path: `${discovery}/queries/${id}/evaluations`, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, decodeEvaluationAccepted);
  }
  async evaluation(id: string): Promise<DTO.EvaluationView> {
    identifier(id, 'input'); return this.send({ method: 'GET', path: `${discovery}/evaluations/${id}` }, value => decodeEvaluation(value, id));
  }
  async evaluationResults(value: Input<'evaluationResults'>): Promise<DTO.EvaluationResultPage> {
    const raw = input(value, ['id', 'offset', 'limit']), id = identifier(raw.id, 'input');
    return this.send({ method: 'GET', path: `${discovery}/evaluations/${id}/results`, query: pagination(raw, 200) }, result => decodePage(result, decodeEvaluationResult, 200, item => item.candidate_id));
  }
  async retryEvaluation(value: Input<'retryEvaluation'>): Promise<DTO.EvaluationAccepted> {
    const raw = input(value, ['id', 'data', 'idempotencyKey']), id = identifier(raw.id, 'input');
    return this.send({ method: 'POST', path: `${discovery}/evaluations/${id}/retry`, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, result => decodeEvaluationAccepted(result, id));
  }
}
