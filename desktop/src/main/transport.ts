import { randomUUID } from 'node:crypto';
import type { PublicError, Result } from '../shared/bridge';
import { normalizeServiceUrl } from './policies';

export class PublicFailure extends Error implements PublicError {
  constructor(public code: string, message: string, public retryable = false, public correlationId?: string) { super(message); }
}
export type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export interface Connection { serviceUrl: string; key: string }
const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const routePattern = new RegExp(`^/api/v1/(session|profiles/(games|creators)(/${UUID})?)$`);
const LIMIT = 8 * 1024 * 1024;

async function boundedJSON(response: Response): Promise<unknown> {
  const oversize = () => new PublicFailure('response_too_large', 'This response is too large to load. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > LIMIT) { await response.body?.cancel(); throw oversize(); }
  const reader = response.body?.getReader();
  if (!reader) throw new PublicFailure('invalid_response', 'The service returned an empty response.', true);
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > LIMIT) { await reader.cancel(); throw oversize(); }
    chunks.push(value);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new PublicFailure('invalid_response', 'The service did not return valid JSON. Check the service address or proxy.', true); }
}

export async function authenticatedGet(fetcher: Fetcher, connection: Connection, route: string, query: Record<string, string> = {}): Promise<unknown> {
  if (!routePattern.test(route)) throw new PublicFailure('request_invalid', 'This read operation is not available.');
  const url = new URL(route, normalizeServiceUrl(connection.serviceUrl));
  for (const [name, value] of Object.entries(query)) {
    if (!['query', 'only_collection', 'cursor', 'limit'].includes(name)) throw new PublicFailure('request_invalid', 'Unsupported filter.');
    url.searchParams.set(name, value);
  }
  try {
    const response = await fetcher(url.href, {
      method: 'GET', headers: { Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID() },
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) {
      // Never echo an upstream response which may contain credentials, headers or proxy pages.
      await response.body?.cancel();
      const correlation = response.headers.get('x-correlation-id');
      const id = correlation && new RegExp(`^${UUID}$`).test(correlation) ? correlation : undefined;
      if (response.status === 401) throw new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
      if (response.status === 403) throw new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
      if (response.status === 404) throw new PublicFailure('not_found', 'This profile or API route is no longer available.', false, id);
      if (response.status === 429) throw new PublicFailure('rate_limited', 'The service is busy. Wait a moment and retry.', true, id);
      throw new PublicFailure('service_error', `The service could not complete this request (HTTP ${response.status}).`, response.status >= 500, id);
    }
    return await boundedJSON(response);
  } catch (error) {
    if (error instanceof PublicFailure) throw error;
    throw new PublicFailure('network_error', 'Could not reach the service. Check your connection, service address, or system proxy and retry.', true);
  }
}

export async function publicResult<T>(action: () => Promise<T>): Promise<Result<T>> {
  try { return { ok: true, data: await action() }; }
  catch (error) {
    if (error instanceof PublicFailure) return { ok: false, error: { code: error.code, message: error.message, retryable: error.retryable, ...(error.correlationId ? { correlationId: error.correlationId } : {}) } };
    // IPC errors are deliberately plain DTOs, never serialized Error objects or raw service exceptions.
    return { ok: false, error: { code: 'operation_failed', message: 'Could not complete this operation. Check Settings and try again.', retryable: true } };
  }
}
