import type { ListProfilesInput, ProfileDetail, ProfileKind, ListPage } from './library';

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
  openExternal(url: string): Promise<Result<void>>;
}

declare global { interface Window { desktop: DesktopBridge } }
