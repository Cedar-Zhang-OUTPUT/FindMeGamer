import type * as DTO from '../shared/drafts';
import { decodeCatalog, decodeComposition, decodeDraft, decodePage, decodeTemplate, exact, fail, identifier, integer, same } from './drafts-validation';
import { draftWriteUnknown, validateDraftsRequest, type DraftsRequest } from './drafts-transport';
export { validateDraftsRequest, draftWriteUnknown };
export type { DraftsRequest };
type Input<K extends keyof DTO.DraftsAPI> = Parameters<DTO.DraftsAPI[K]>[0];
const templates = '/api/v2/outreach/template-versions';
/** Public Result envelopes are added by the main gateway, as for the other clients. */
export class DraftsClient {
  constructor(private readonly request: (input: DraftsRequest) => Promise<unknown>) {}
  private async send<T>(request: DraftsRequest, decode: (v: unknown) => T): Promise<T> { const valid = validateDraftsRequest(request), result = await this.request(valid); try { return decode(result); } catch (error) { throw valid.method !== 'GET' ? draftWriteUnknown() : error; } }
  async templates(value: Input<'templates'>) { const r = exact(value, ['gameId'], 'input'), id = identifier(r.gameId, 'input'); return this.send({ method: 'GET', path: templates, query: { game_id: id } }, v => decodeCatalog(v, id)); }
  async template(id: string) { identifier(id, 'input'); return this.send({ method: 'GET', path: `${templates}/${id}` }, v => decodeTemplate(v, id)); }
  async registerCanonical(value: Input<'registerCanonical'>) { const r = exact(value, ['gameId', 'idempotencyKey'], 'input'), id = identifier(r.gameId, 'input'); return this.send({ method: 'POST', path: `${templates}/canonical`, body: { game_id: id }, idempotencyKey: r.idempotencyKey as string }, v => { const t = decodeTemplate(v, undefined, id); if (!['canonical','game_bound'].includes(t.source_metadata.kind)) fail('response'); return t; }); }
  async createTemplate(value: Input<'createTemplate'>) { const r = exact(value, ['data', 'idempotencyKey'], 'input'), data = r.data as unknown as DTO.TemplateVersionCreate; return this.send({ method: 'POST', path: templates, body: data as unknown as Record<string, unknown>, idempotencyKey: r.idempotencyKey as string }, v => { const t = decodeTemplate(v, undefined, data.game_id); if (t.source_metadata.kind !== 'user_saved' || t.name !== data.name.trim() || t.subject !== data.subject || JSON.stringify(t.fixed_fragments) !== JSON.stringify(data.fixed_fragments)) fail('response'); return t; }); }
  async compositions(value: Input<'compositions'>) { const { activityId, offset = 0, limit = 50, ...extra } = value; exact(extra, [], 'input'); identifier(activityId, 'input'); integer(offset, 'input'); integer(limit, 'input', 1, 100); return this.send({ method: 'GET', path: `/api/v2/activities/${activityId}/compositions`, query: { offset: String(offset), limit: String(limit) } }, v => decodePage(v, activityId, offset, limit)); }
  async composition(id: string) { identifier(id, 'input'); return this.send({ method: 'GET', path: `/api/v2/outreach/compositions/${id}` }, v => decodeComposition(v, id)); }
  async createComposition(value: Input<'createComposition'>) { const r = exact(value, ['activityId', 'data', 'idempotencyKey'], 'input'), id = identifier(r.activityId, 'input'), data = r.data as unknown as DTO.CompositionCreate; return this.send({ method: 'POST', path: `/api/v2/activities/${id}/compositions`, body: data as unknown as Record<string, unknown>, idempotencyKey: r.idempotencyKey as string }, v => { const c = decodeComposition(v, undefined, id); if (!same(c.recipient_batch_id, data.recipient_batch_id) || !same(c.template_version_id, data.template_version_id)) fail('response'); return c; }); }
  private async revise(value: Input<'refresh'> | Input<'edit'>, kind: 'edit' | 'refresh' | 'retry') {
    const r = exact(value, ['id', 'data'], 'input'), id = identifier(r.id, 'input');
    const data = r.data as unknown as DTO.DraftEdit & { preserve_values?: boolean };
    return this.send({ method: kind === 'edit' ? 'PATCH' : 'POST', path: `/api/v2/outreach/drafts/${id}${kind === 'edit' ? '' : '/' + kind}`, body: data as unknown as Record<string, unknown> }, v => {
      const d = decodeDraft(v, id), preserving = kind === 'refresh' && data.preserve_values === true;
      if (d.revision !== data.expected_revision + 1 || ((kind === 'edit' || preserving)
        && (!d.values || (Object.keys(data.values) as (keyof DTO.SlotValues)[]).some(key => d.values![key] !== data.values[key])))) fail('response');
      if (preserving && (d.source_changed || !['succeeded', 'needs_repair'].includes(d.status)
        || d.sender_facts_valid || Object.keys(d.sender_facts).length || !d.rendered)) fail('response');
      return d;
    });
  }
  edit(value: Input<'edit'>) { return this.revise(value, 'edit'); }
  refresh(value: Input<'refresh'>) { return this.revise(value, 'refresh'); }
  retry(value: Input<'retry'>) { return this.revise(value, 'retry'); }
  async senderFacts(value: Input<'senderFacts'>) { const r = exact(value, ['compositionId', 'data'], 'input'), id = identifier(r.compositionId, 'input'), data = r.data as unknown as DTO.SenderFacts; return this.send({ method: 'POST', path: `/api/v2/outreach/compositions/${id}/sender-facts`, body: data as unknown as Record<string, unknown> }, v => { const c = decodeComposition(v, id); for (const member of data.members) { const d = c.drafts.find(d => same(d.id, member.draft_id)); if (!d || d.revision !== member.expected_revision + 1 || ['following', 'enjoyed', 'liked'].some(k => d.sender_facts[k] !== data[k as keyof DTO.SenderFacts])) fail('response'); } return c; }); }
}
