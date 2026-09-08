import { expect, it, vi } from 'vitest';
import { readFile } from 'node:fs/promises';
import type { DesktopBridge } from '../src/shared/bridge';
import { WorkspaceGateway } from '../src/main/gateway';
const mocks = vi.hoisted(() => ({ expose: vi.fn(), invoke: vi.fn(async () => ({ ok: true, data: null })) }));
vi.mock('electron', () => ({ contextBridge: { exposeInMainWorld: mocks.expose }, ipcRenderer: { invoke: mocks.invoke } }));
const methods = { templates: 'templates', template: 'template', registerCanonical: 'register-canonical', createTemplate: 'create-template', compositions: 'compositions', composition: 'composition', createComposition: 'create-composition', edit: 'edit', refresh: 'refresh', retry: 'retry', senderFacts: 'sender-facts' } as const;
const request = { method: 'POST' as const, path: '/api/v2/outreach/drafts/11111111-1111-4111-8111-111111111111/retry', body: { expected_revision: 0, context_token: 'a'.repeat(64) } };
function store() { return { status: vi.fn(async () => ({ serviceUrl: 'https://workspace.test', hasKey: true, storageAvailable: true })), getConnection: vi.fn(async () => ({ serviceUrl: 'https://workspace.test', key: 'fixture' })), save: vi.fn(async () => {}), clear: vi.fn(async () => {}) }; }
it('exposes exactly eleven named draft IPC methods and matching application handlers', async () => {
  await import('../src/preload/index');
  const [, api] = mocks.expose.mock.calls[0] as [string, DesktopBridge]; expect(api).toHaveProperty('drafts');
  expect(Object.keys(api.drafts).sort()).toEqual(Object.keys(methods).sort());
  const source = await readFile(new URL('../src/main/application.ts', import.meta.url), 'utf8');
  for (const [method, channel] of Object.entries(methods)) { const input = { fixture: method }; await (api.drafts[method as keyof typeof methods] as (v: unknown) => Promise<unknown>)(input); expect(mocks.invoke).toHaveBeenLastCalledWith(`drafts:${channel}`, input); expect(source).toMatch(new RegExp(`handle\\('drafts:${channel}',\\s*input\\s*=>\\s*drafts\\.${method}\\(input\\)`)); }
  expect(source.match(/handle\('drafts:/g)).toHaveLength(11); expect(api).not.toHaveProperty('request');
});
it('validates draft input before credential access or dispatch', async () => {
  const storage = store(), fetcher = vi.fn(), gateway = new WorkspaceGateway(storage, fetcher); expect(gateway).toHaveProperty('draftsRequest');
  await expect(gateway.draftsRequest({ ...request, body: { expected_revision: false, context_token: 'a'.repeat(64) } })).rejects.toMatchObject({ code: 'request_invalid' });
  expect(storage.getConnection).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
});
it.each([200, 401, 503])('fences old-credential draft outcomes after replacement (%s)', async status => {
  let finish!: (v: Response) => void; const fetcher = vi.fn(() => new Promise<Response>(r => { finish = r; })), gateway = new WorkspaceGateway(store(), fetcher); expect(gateway).toHaveProperty('draftsRequest');
  const pending = gateway.draftsRequest(request); await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce()); await gateway.save({ serviceUrl: 'https://replacement.test', key: 'replacement' });
  finish(new Response('{}', { status })); await expect(pending).rejects.toMatchObject({ code: 'connection_changed', retryable: false }); expect(fetcher).toHaveBeenCalledOnce();
});
