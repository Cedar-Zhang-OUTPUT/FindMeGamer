import { DEFAULT_SERVICE_ORIGIN } from '../shared/connection-default';

export interface CryptoAdapter {
  isEncryptionAvailable(): boolean | Promise<boolean>;
  encryptString(plain: string): Buffer | Promise<Buffer>;
  decryptString(cipher: Buffer): string | Promise<string>;
}

export interface SettingsStatus {
  serviceUrl: string;
  hasKey: boolean;
  storageAvailable: boolean;
}

export interface ConnectionInput { serviceUrl: string; key?: string }
export interface StoredConnection { serviceUrl: string; key: string }
interface EncryptedConnection { serviceUrl: string; encryptedKey: string }

function isMissingFile(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'code' in error && error.code === 'ENOENT';
}

function origin(serviceUrl: string): string {
  try {
    const value = new URL(serviceUrl).origin;
    if (value !== 'null') return value;
  } catch { /* URL normalization belongs to the main-process input policy. */ }
  throw new Error('The service URL is invalid.');
}

function decodeCiphertext(encoded: string): Buffer {
  const ciphertext = Buffer.from(encoded, 'base64');
  if (ciphertext.length === 0 || ciphertext.toString('base64') !== encoded) {
    throw new Error('The stored credentials are invalid.');
  }
  return ciphertext;
}

/** Main-process only: do not export this module through the renderer bridge. */
export class CredentialStore {
  private readonly file: string;
  private pending: Promise<void> = Promise.resolve();

  constructor(private readonly userDataDirectory: string, private readonly crypto: CryptoAdapter) {
    this.file = join(userDataDirectory, 'credentials.json');
  }

  status(): Promise<SettingsStatus> {
    return this.serialized(async () => {
      const stored = await this.read();
      return {
        serviceUrl: stored?.serviceUrl ?? DEFAULT_SERVICE_ORIGIN,
        hasKey: stored !== null,
        storageAvailable: await this.isStorageAvailable(),
      };
    });
  }

  getConnection(): Promise<StoredConnection | null> {
    return this.serialized(async () => {
      const stored = await this.read();
      if (!stored) return null;
      await this.requireStorage();
      try {
        const key = await this.crypto.decryptString(decodeCiphertext(stored.encryptedKey));
        if (typeof key !== 'string' || key.trim().length === 0) throw new Error();
        return { serviceUrl: stored.serviceUrl, key };
      } catch {
        // Never propagate adapter messages: a platform error may contain input data.
        throw new Error('Could not decrypt the stored service key.');
      }
    });
  }

  save(input: ConnectionInput): Promise<void> {
    // Capture primitives before queuing; callers cannot change the origin mid-save.
    const { serviceUrl, key } = input;
    return this.serialized(async () => {
      const newOrigin = origin(serviceUrl);
      await this.requireStorage();
      const previous = await this.read();
      let encryptedKey: string;
      if (key === undefined) {
        if (!previous) throw new Error('A service key is required.');
        if (origin(previous.serviceUrl) !== newOrigin) {
          throw new Error('A new service key is required when changing service origin.');
        }
        encryptedKey = previous.encryptedKey;
      } else {
        if (typeof key !== 'string' || key.trim().length === 0) throw new Error('A service key is required.');
        try {
          const ciphertext = await this.crypto.encryptString(key);
          if (!Buffer.isBuffer(ciphertext) || ciphertext.length === 0) throw new Error();
          encryptedKey = ciphertext.toString('base64');
        } catch {
          throw new Error('Could not securely store the service key.');
        }
      }
      await this.write({ serviceUrl, encryptedKey });
    });
  }

  clear(): Promise<void> {
    return this.serialized(async () => {
      try { await unlink(this.file); }
      catch (error) {
        if (!isMissingFile(error)) throw new Error('Could not clear credentials.');
      }
    });
  }

  private serialized<T>(action: () => Promise<T>): Promise<T> {
    const operation = this.pending.then(action);
    this.pending = operation.then(() => undefined, () => undefined);
    return operation;
  }

  private async isStorageAvailable(): Promise<boolean> {
    try { return await this.crypto.isEncryptionAvailable() === true; }
    catch { return false; }
  }

  private async requireStorage(): Promise<void> {
    if (!await this.isStorageAvailable()) throw new Error('Secure credential storage is unavailable.');
  }

  private async read(): Promise<EncryptedConnection | null> {
    let text: string;
    try { text = await readFile(this.file, 'utf8'); }
    catch (error) {
      if (isMissingFile(error)) return null;
      throw new Error('Could not read credentials.');
    }
    try {
      const value: unknown = JSON.parse(text);
      if (typeof value !== 'object' || value === null
        || !('serviceUrl' in value) || typeof value.serviceUrl !== 'string'
        || !('encryptedKey' in value) || typeof value.encryptedKey !== 'string') throw new Error();
      origin(value.serviceUrl);
      decodeCiphertext(value.encryptedKey);
      return { serviceUrl: value.serviceUrl, encryptedKey: value.encryptedKey };
    } catch {
      throw new Error('The stored credentials are invalid. Clear them to reconnect.');
    }
  }

  private async write(value: EncryptedConnection): Promise<void> {
    const temporaryFile = join(this.userDataDirectory, `credentials.${randomUUID()}.tmp`);
    let handle: FileHandle | undefined;
    try {
      await mkdir(this.userDataDirectory, { recursive: true, mode: 0o700 });
      handle = await open(temporaryFile, 'wx', 0o600);
      await handle.writeFile(JSON.stringify(value), 'utf8');
      await handle.sync();
      await handle.close();
      handle = undefined;
      // Commit only after the complete encrypted file is flushed and closed.
      await rename(temporaryFile, this.file);
    } catch {
      await handle?.close().catch(() => undefined);
      await unlink(temporaryFile).catch(() => undefined);
      throw new Error('Could not save credentials.');
    }
  }
}
import { randomUUID } from 'node:crypto';
import { mkdir, open, readFile, rename, unlink, type FileHandle } from 'node:fs/promises';
import { join } from 'node:path';
