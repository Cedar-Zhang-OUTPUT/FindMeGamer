import type { ConnectionInput, ConnectionStatus } from '../shared/bridge';
import type { Connection, Fetcher, GameRequest } from './transport';
import { authenticatedGameRequest, authenticatedGet, PublicFailure } from './transport';
import { normalizeServiceUrl } from './policies';
import { authenticatedSettingsRequest, validateSettingsRequest, type SettingsRequest } from './settings-transport';
import { authenticatedCreatorRequest, validateCreatorRequest, type CreatorRequest } from './creator-transport';
import { authenticatedMatchRequest, validateMatchRequest, type MatchRequest } from './match-transport';
import { authenticatedSavedSetRequest, validateSavedSetRequest, type SavedSetRequest } from './saved-set-transport';

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
  async gameRequest(input: GameRequest): Promise<unknown> {
    const isWrite = input?.method !== 'GET';
    return this.runCurrent(async () => {
      const generation = this.generation;
      let connection: Connection | null;
      try { connection = await this.store.getConnection(); }
      catch {
        // Credential access failed before dispatch, so this save can be retried after recovery.
        throw new PublicFailure('secure_storage_unavailable', 'Could not read your workspace key. Check Keychain access or reconnect in Settings.');
      }
      if (!connection) throw new PublicFailure('not_connected', 'Connect your workspace in Settings.');
      this.assertGeneration(generation, !isWrite);
      return authenticatedGameRequest(this.fetcher, connection, input);
    }, { isWrite });
  }
  async runCurrent<T>(action: () => Promise<T>, options: { isWrite?: boolean } = {}): Promise<T> {
    const generation = this.generation;
    try {
      const result = await action();
      this.assertGeneration(generation, !options.isWrite);
      return result;
    } catch (error) {
      this.assertGeneration(generation, !options.isWrite);
      throw error;
    }
  }
  async settingsRequest(input:SettingsRequest):Promise<unknown> {
    const request=validateSettingsRequest(input);
    const isWrite=request.method!=='GET';
    return this.runCurrent(async()=>{
      const generation=this.generation;
      let connection:Connection|null;
      try {connection=await this.store.getConnection();}
      catch {throw new PublicFailure('secure_storage_unavailable','Could not read your workspace key. Check Keychain access or reconnect in Settings.');}
      if(!connection)throw new PublicFailure('not_connected','Connect your workspace in Settings.');
      this.assertGeneration(generation,!isWrite);
      return authenticatedSettingsRequest(this.fetcher,connection,request);
    },{isWrite});
  }
  async creatorRequest(input:CreatorRequest):Promise<unknown> {
    const request=validateCreatorRequest(input);
    const isWrite=request.method!=='GET';
    return this.runCurrent(async()=>{
      const generation=this.generation;
      let connection:Connection|null;
      try {connection=await this.store.getConnection();}
      catch {throw new PublicFailure('secure_storage_unavailable','Could not read your workspace key. Check Keychain access or reconnect in Settings.');}
      if(!connection)throw new PublicFailure('not_connected','Connect your workspace in Settings.');
      this.assertGeneration(generation,!isWrite);
      return authenticatedCreatorRequest(this.fetcher,connection,request);
    },{isWrite});
  }
  async matchRequest(input:MatchRequest):Promise<unknown> {
    const request=validateMatchRequest(input),isWrite=request.method!=='GET';
    return this.runCurrent(async()=>{
      const generation=this.generation;let connection:Connection|null;
      try{connection=await this.store.getConnection();}
      catch{throw new PublicFailure('secure_storage_unavailable','Could not read your workspace key. Check Keychain access or reconnect in Settings.');}
      if(!connection)throw new PublicFailure('not_connected','Connect your workspace in Settings.');
      this.assertGeneration(generation,!isWrite);
      return authenticatedMatchRequest(this.fetcher,connection,request);
    },{isWrite});
  }
  async savedSetRequest(input:SavedSetRequest):Promise<unknown> {
    const request=validateSavedSetRequest(input),isWrite=request.method!=='GET';
    return this.runCurrent(async()=>{
      const generation=this.generation;let connection:Connection|null;
      try{connection=await this.store.getConnection();}
      catch{throw new PublicFailure('secure_storage_unavailable','Could not read your workspace key. Check Keychain access or reconnect in Settings.');}
      if(!connection)throw new PublicFailure('not_connected','Connect your workspace in Settings.');
      this.assertGeneration(generation,!isWrite);
      return authenticatedSavedSetRequest(this.fetcher,connection,request);
    },{isWrite});
  }
  private assertGeneration(generation: number, retryable = true) {
    if (generation !== this.generation) throw new PublicFailure('connection_changed', retryable
      ? 'The workspace connection changed. Reload this page.'
      : 'The workspace changed while saving. Check the original workspace before saving again.', retryable);
  }
}
