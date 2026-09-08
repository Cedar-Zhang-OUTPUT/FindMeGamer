import type { ConnectionInput, ConnectionStatus } from '../shared/bridge';
import type { Connection, Fetcher } from './transport';
import { authenticatedGet, PublicFailure } from './transport';
import { normalizeServiceUrl } from './policies';

interface Store {
  status(): Promise<ConnectionStatus>;
  getConnection(): Promise<Connection | null>;
  save(input: ConnectionInput): Promise<void>;
  clear(): Promise<void>;
}

export class WorkspaceGateway {
  private generation = 0;
  constructor(private readonly store: Store, private readonly fetcher: Fetcher) {}
  status() { return this.store.status(); }
  async save(input: ConnectionInput) {
    let serviceUrl: string;
    try { serviceUrl = normalizeServiceUrl(input?.serviceUrl); }
    catch { throw new PublicFailure('request_invalid', 'Use an HTTPS service address, or a loopback HTTP address for local development.'); }
    if (input.key !== undefined && typeof input.key !== 'string') throw new PublicFailure('request_invalid', 'Enter a valid workspace key.');
    const key = input.key?.trim();
    if (input.key !== undefined && (!key || key.length > 4096 || /[^\x21-\x7e]/.test(key))) {
      throw new PublicFailure('request_invalid', 'Enter a valid workspace key without spaces or line breaks.');
    }
    const previous = await this.store.status();
    if (!previous.storageAvailable) throw new PublicFailure('storage_unavailable', 'Secure storage is unavailable. Allow Keychain access and try again.');
    if (!key && (!previous.hasKey || previous.serviceUrl !== serviceUrl)) throw new PublicFailure('key_required', 'Enter a workspace key for this service address.');
    await this.store.save({ serviceUrl, ...(key ? { key } : {}) });
    this.generation++;
    return this.status();
  }
  async clear() {
    await this.store.clear();
    this.generation++;
    return this.status();
  }
  async request(route: string, query?: Record<string, string>) {
    return this.runCurrent(async () => {
      const generation = this.generation;
      const connection = await this.store.getConnection();
      if (!connection) throw new PublicFailure('not_connected', 'Connect your workspace in Settings.');
      this.assertGeneration(generation);
      return authenticatedGet(this.fetcher, connection, route, query);
    });
  }
  async runCurrent<T>(action: () => Promise<T>): Promise<T> {
    const generation = this.generation;
    try {
      const result = await action();
      this.assertGeneration(generation);
      return result;
    } catch (error) {
      this.assertGeneration(generation);
      throw error;
    }
  }
  private assertGeneration(generation: number) {
    if (generation !== this.generation) throw new PublicFailure('connection_changed', 'The workspace connection changed. Reload this page.', true);
  }
}
