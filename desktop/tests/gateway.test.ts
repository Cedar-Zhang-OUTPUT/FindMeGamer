import { describe, expect, it } from 'vitest';
import { WorkspaceGateway } from '../src/main/gateway';

function fixture() {
  let connection: {serviceUrl: string; key: string} | null = {serviceUrl: 'https://workspace.test', key: 'test-key'};
  return {
    status: async () => ({serviceUrl: connection?.serviceUrl ?? '', hasKey: !!connection, storageAvailable: true}),
    getConnection: async () => connection,
    save: async (input: {serviceUrl: string; key?: string}) => { connection = { serviceUrl: input.serviceUrl, key: input.key ?? connection!.key }; },
    clear: async () => { connection = null; },
  };
}

describe('connection changes', () => {
  it('does not allow a previous workspace response to appear after disconnect', async () => {
    let complete!: (r: Response) => void;
    const gateway = new WorkspaceGateway(fixture(), () => new Promise(r => { complete = r; }));
    const pending = gateway.request('/api/v1/session');
    await new Promise(r => setTimeout(r, 0));
    await gateway.clear();
    complete(new Response('{}'));
    await expect(pending).rejects.toMatchObject({ code: 'connection_changed' });
  });
  it('validates settings at the main boundary before storage', async () => {
    const gateway = new WorkspaceGateway(fixture(), async () => new Response('{}'));
    await expect(gateway.save({ serviceUrl: 'https://host.test', key: 'bad\r\nHeader: injected' })).rejects.toMatchObject({code:'request_invalid'});
    await expect(gateway.save({ serviceUrl: 'http://metadata.internal', key: 'test-key' })).rejects.toMatchObject({code:'request_invalid'});
    expect((await gateway.status()).serviceUrl).toBe('https://workspace.test');
  });
  it('disconnected Library requests do not reach the network', async () => {
    let count = 0;
    const gateway = new WorkspaceGateway(fixture(), async () => { count++; return new Response('{}'); });
    await gateway.clear();
    await expect(gateway.request('/api/v1/session')).rejects.toMatchObject({code:'not_connected'});
    expect(count).toBe(0);
  });
  it('does not report an old workspace authentication failure against a new connection', async () => {
    let complete!: (r: Response) => void;
    const gateway = new WorkspaceGateway(fixture(), () => new Promise(r => { complete = r; }));
    const pending = gateway.request('/api/v1/session');
    await new Promise(r => setTimeout(r, 0));
    await gateway.save({serviceUrl:'https://new-workspace.test',key:'new-test-key'});
    complete(new Response('{}', {status:401}));
    await expect(pending).rejects.toMatchObject({code:'connection_changed'});
  });
  it('discards late network failures after disconnect', async () => {
    let fail!: (error: Error) => void;
    const gateway = new WorkspaceGateway(fixture(), () => new Promise((_r, reject) => { fail = reject; }));
    const pending = gateway.request('/api/v1/session');
    await new Promise(r => setTimeout(r, 0));
    await gateway.clear();
    fail(Error('late network error'));
    await expect(pending).rejects.toMatchObject({code:'connection_changed'});
  });
  it('binds the complete connection test including proxy resolution to one generation', async () => {
    let complete!: () => void;
    const gateway = new WorkspaceGateway(fixture(), async () => new Response('{}'));
    const pending = gateway.runCurrent(async () => {
      await new Promise<void>(resolve => { complete = resolve; });
      return {authenticated:true};
    });
    await gateway.clear();
    complete();
    await expect(pending).rejects.toMatchObject({code:'connection_changed'});
  });
});
