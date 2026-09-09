import type * as DTO from '../shared/collaboration';
import { decodeInvitation, decodePage, exact, fail, identifier, integer, keys, object } from './collaboration-validation';
import { collaborationWriteUnknown, isCollaborationWrite, validateCollaborationRequest, type CollaborationRequest } from './collaboration-transport';
export { collaborationWriteUnknown, isCollaborationWrite, validateCollaborationRequest }; export type { CollaborationRequest };
type Input<K extends keyof DTO.CollaborationAPI> = Parameters<DTO.CollaborationAPI[K]>[0];
// AwareDatetime/PostgreSQL retain microseconds; Date.parse alone loses evidence precision.
function sameResponseTime(a: string, b: string): boolean { const micros = (s: string) => `${Math.floor(Date.parse(s) / 1000)}:${(s.match(/\.(\d+)/)?.[1] ?? '').slice(0, 6).padEnd(6, '0')}`; return micros(a) === micros(b); }
export class CollaborationClient {
  constructor(private readonly request: (input: CollaborationRequest) => Promise<unknown>) {}
  private async perform<T>(input: CollaborationRequest, decode: (v: unknown) => T): Promise<T> { const valid = validateCollaborationRequest(input), result = await this.request(valid); try { return decode(result); } catch (error) { throw isCollaborationWrite(valid) ? collaborationWriteUnknown() : error; } }
  async list(value: Input<'list'>): Promise<DTO.ActivityInvitationPage> {
    const r = object(value, 'input'); keys(r, ['activityId', 'sending_state', 'invitation_state', 'follow_up_state', 'limit', 'offset'], 'input'); const activityId = identifier(r.activityId, 'input'), limit = integer(r.limit ?? 50, 'input', 1, 200), offset = integer(r.offset ?? 0, 'input'); const query: Record<string, string> = { limit: String(limit), offset: String(offset) };
    for (const k of ['sending_state', 'invitation_state', 'follow_up_state']) if (Object.hasOwn(r, k)) query[k] = r[k] as string;
    return this.perform({ method: 'GET', path: `/api/v2/activities/${activityId}/invitations`, query }, v => decodePage(v, value, offset, limit));
  }
  async detail(value: Input<'detail'>): Promise<DTO.ActivityInvitation> { const r = exact(value, ['activityId', 'selectionId'], 'input'), activityId = identifier(r.activityId, 'input'), selectionId = identifier(r.selectionId, 'input'); return this.perform({ method: 'GET', path: `/api/v2/activities/${activityId}/invitations/${selectionId}` }, v => decodeInvitation(v, activityId, selectionId)); }
  async creatorHistory(value: Input<'creatorHistory'>): Promise<DTO.ActivityInvitationPage> { const r = object(value, 'input'); keys(r, ['creatorId', 'activityId', 'limit', 'offset'], 'input'); const creatorId = identifier(r.creatorId, 'input'), limit = integer(r.limit ?? 50, 'input', 1, 200), offset = integer(r.offset ?? 0, 'input'), query: Record<string, string> = { limit: String(limit), offset: String(offset) }; if (Object.hasOwn(r, 'activityId')) query.activity_id = identifier(r.activityId, 'input'); return this.perform({ method: 'GET', path: `/api/v2/library/creators/${creatorId}/invitations`, query }, v => decodePage(v, value, offset, limit)); }
  private async write(value: Input<'update'> | Input<'respond'>, response: boolean): Promise<DTO.ActivityInvitation> {
    const r = exact(value, ['activityId', 'selectionId', 'data', 'idempotencyKey'], 'input'), activityId = identifier(r.activityId, 'input'), selectionId = identifier(r.selectionId, 'input'), data = r.data as Record<string, unknown>;
    return this.perform({ method: 'POST', path: `/api/v2/activities/${activityId}/invitations/${selectionId}/${response ? 'responses' : 'update'}`, body: data, idempotencyKey: r.idempotencyKey as string }, v => {
      const row = decodeInvitation(v, activityId, selectionId); if (row.revision !== (data.expected_revision as number) + 1) fail('response');
      if (response) { const latest = row.responses[0]; if (!latest || latest.revision !== row.revision || latest.outcome !== data.outcome || latest.source_note !== (data.source_note as string).trim() || !sameResponseTime(latest.responded_at, data.responded_at as string)) fail('response'); }
      else for (const k of ['notes', 'follow_up_state', 'cooperation_state'] as const) if (Object.hasOwn(data, k) && row[k] !== data[k]) fail('response'); return row;
    });
  }
  update(value: Input<'update'>): Promise<DTO.ActivityInvitation> { return this.write(value, false); }
  respond(value: Input<'respond'>): Promise<DTO.ActivityInvitation> { return this.write(value, true); }
}
