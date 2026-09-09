import { expect, it, vi } from 'vitest';
import { authenticatedAnalysisRequest, validateAnalysisRequest, type AnalysisRequest } from '../src/main/analyze-transport';
const connection = { serviceUrl: 'https://service.example', key: 'private-workspace-key' };
const write: AnalysisRequest = { method: 'POST', path: '/api/v1/jobs/analysis', body: { target_type: 'creator', url: 'https://x.com/i/user/123', mode: 'reanalyze' }, idempotencyKey: 'original-key' };
it('keeps authentication in transport and exact keyed body with redirects denied', async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ accepted: true })); await authenticatedAnalysisRequest(fetcher, connection, write);
  expect(fetcher).toHaveBeenCalledWith('https://service.example/api/v1/jobs/analysis', expect.objectContaining({ redirect: 'error', credentials: 'omit', cache: 'no-store', body: JSON.stringify(write.body), headers: expect.objectContaining({ Authorization: 'Bearer private-workspace-key', 'Idempotency-Key': 'original-key' }) }));
});
it.each([new Error('secret'), Response.json({ error: { code: 'analysis_queue_unavailable', message: 'secret' } }, { status: 503 }), new Response('not-json'), new Response('x', { headers: { 'content-length': '9000000' } })])('keeps ambiguous mutation outcomes unknown without leaking upstream data', async failure => {
  const fetcher = failure instanceof Error ? vi.fn().mockRejectedValue(failure) : vi.fn().mockResolvedValue(failure);
  await expect(authenticatedAnalysisRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'analysis_write_unknown', retryable: false });
});
it('rejects excess fields, unsupported targets and paths before network', async () => {
  const fetcher = vi.fn(); for (const bad of [{ ...write, path: '/api/v1/jobs/analysis/../delete' }, { ...write, body: { ...write.body, extra: true } }, { ...write, body: { ...write.body, url: 'https://x.com:443/i/user/123' } }, { method: 'GET', path: '/api/v1/jobs', query: { limit: '201' } }]) await expect(authenticatedAnalysisRequest(fetcher, connection, bad as AnalysisRequest)).rejects.toMatchObject({ code: 'request_invalid' }); expect(fetcher).not.toHaveBeenCalled();
  expect(() => validateAnalysisRequest({ ...write, body: { ...write.body, url: 'https://x.com/i/user/123' } })).not.toThrow();
});
it('returns actionable fixed auth and collection errors without server prose', async () => {
  for (const [status, code] of [[401,'workspace_key_invalid'],[409,'collection_disabled']] as const) { const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code, message: 'secret' } }, { status })); await expect(authenticatedAnalysisRequest(fetcher, connection, write)).rejects.toMatchObject({ code }); }
});
