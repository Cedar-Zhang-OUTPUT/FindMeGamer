import type { ListProfilesInput, ProfileDetail, ProfileKind, ListPage } from './library';
import type { CreateGameInput, GameDetail, GameListInput, GamePage, UpdateGameInput } from './games';
import type { SettingsAPI } from './settings';
import type { PreferencesAPI, UpdatesAPI } from './preferences';

export interface ConnectionStatus {
  serviceUrl: string;
  hasKey: boolean;
  storageAvailable: boolean;
}
export interface PublicError { code: string; message: string; retryable: boolean; correlationId?: string }
export type Result<T> = { ok: true; data: T } | { ok: false; error: PublicError };
export interface ConnectionInput { serviceUrl: string; key?: string }
export interface ConnectionCheck { authenticated: true; proxy: 'system'; route: 'direct' | 'proxy' }

/** Business methods only. No generic request, filesystem, shell, or IPC channel access. */
export interface DesktopBridge {
  settings: SettingsAPI;
  preferences: PreferencesAPI;
  updates: UpdatesAPI;
  connection: {
    status(): Promise<Result<ConnectionStatus>>;
    save(input: ConnectionInput): Promise<Result<ConnectionStatus>>;
    test(): Promise<Result<ConnectionCheck>>;
    clear(): Promise<Result<ConnectionStatus>>;
  };
  library: {
    list(input: ListProfilesInput): Promise<Result<ListPage>>;
    detail(input: { kind: ProfileKind; id: string }): Promise<Result<ProfileDetail>>;
  };
  games: {
    list(input: GameListInput): Promise<Result<GamePage>>;
    detail(id: string): Promise<Result<GameDetail>>;
    create(input: CreateGameInput): Promise<Result<GameDetail>>;
    update(input: UpdateGameInput): Promise<Result<GameDetail>>;
  };
  openExternal(url: string): Promise<Result<void>>;
}

declare global { interface Window { desktop: DesktopBridge } }
