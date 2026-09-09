import { mkdtemp, readFile, readdir, rename, rm, stat, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CredentialStore, type CryptoAdapter } from '../src/main/credential-store';

vi.mock('node:fs/promises', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs/promises')>();
  return { ...actual, rename: vi.fn(actual.rename), unlink: vi.fn(actual.unlink) };
});

const SERVICE = 'https://service.example/api';
const OTHER_SERVICE = 'https://other.example/api';
const KEY = 'fixture-secret-never-show-in-status';
const temporaryDirectories: string[] = [];

// Deliberately fake reversible encryption: tests never access a real keychain.
function fakeCrypto(): CryptoAdapter {
  const transform = (bytes: Buffer) => Buffer.from(bytes.map((value) => value ^ 0xa5));
  return {
    isEncryptionAvailable: vi.fn(() => true),
    encryptString: vi.fn((plain: string) => transform(Buffer.from(plain, 'utf8'))),
    decryptString: vi.fn((cipher: Buffer) => transform(cipher).toString('utf8')),
  };
}

async function fixture(crypto: CryptoAdapter = fakeCrypto()) {
  const directory = await mkdtemp(join(tmpdir(), 'fmg-credential-test-'));
  temporaryDirectories.push(directory);
  return { directory, crypto, store: new CredentialStore(directory, crypto) };
}

async function storedFile(directory: string) {
  const names = await readdir(directory);
  expect(names).toHaveLength(1);
  return join(directory, names[0]!);
}

afterEach(async () => {
  vi.mocked(rename).mockReset();
  vi.mocked(unlink).mockReset();
  await Promise.all(temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })));
});

describe('CredentialStore', () => {
  it('starts disconnected and exposes only the settings whitelist', async () => {
    const { store, directory, crypto } = await fixture();
    expect(await store.status()).toEqual({ serviceUrl: 'https://44.233.174.193', hasKey: false, storageAvailable: true });
    expect(await store.getConnection()).toBeNull();
    expect(await readdir(directory)).toEqual([]);
    expect(crypto.encryptString).not.toHaveBeenCalled();
    expect(crypto.decryptString).not.toHaveBeenCalled();
  });

  it('persists only encrypted key bytes in a private file and reloads the connection', async () => {
    const { directory, crypto, store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    const file = await storedFile(directory);
    const text = await readFile(file, 'utf8');
    const disk: unknown = JSON.parse(text);
    expect(text).not.toContain(KEY);
    expect(disk).toEqual({ serviceUrl: SERVICE, encryptedKey: expect.any(String) });
    expect((await stat(file)).mode & 0o777).toBe(0o600);
    expect(crypto.encryptString).toHaveBeenCalledWith(KEY);
    expect(await new CredentialStore(directory, crypto).getConnection()).toEqual({ serviceUrl: SERVICE, key: KEY });
    expect(await store.status()).toEqual({ serviceUrl: SERVICE, hasKey: true, storageAvailable: true });
    expect(JSON.stringify(await store.status())).not.toContain(KEY);
  });

  it('supports asynchronous encryption availability, encryption, and decryption', async () => {
    const synchronous = fakeCrypto();
    const crypto: CryptoAdapter = {
      isEncryptionAvailable: async () => synchronous.isEncryptionAvailable(),
      encryptString: async (plain) => synchronous.encryptString(plain),
      decryptString: async (cipher) => synchronous.decryptString(cipher),
    };
    const { store } = await fixture(crypto);
    await store.save({ serviceUrl: SERVICE, key: KEY });
    expect(await store.getConnection()).toEqual({ serviceUrl: SERVICE, key: KEY });
    expect((await store.status()).storageAvailable).toBe(true);
  });

  it('never falls back to plaintext when encryption is unavailable', async () => {
    const crypto = fakeCrypto();
    vi.mocked(crypto.isEncryptionAvailable).mockReturnValue(false);
    const { directory, store } = await fixture(crypto);
    expect(await store.status()).toEqual({ serviceUrl: 'https://44.233.174.193', hasKey: false, storageAvailable: false });
    await expect(store.save({ serviceUrl: SERVICE, key: KEY })).rejects.toThrow('Secure credential storage is unavailable.');
    expect(await readdir(directory)).toEqual([]);
    expect(crypto.encryptString).not.toHaveBeenCalled();
  });

  it('preserves stored credentials but refuses to read or replace them while encryption is unavailable', async () => {
    const { directory, crypto, store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    const file = await storedFile(directory);
    const before = await readFile(file, 'utf8');
    vi.mocked(crypto.isEncryptionAvailable).mockReturnValue(false);
    expect(await store.status()).toEqual({ serviceUrl: SERVICE, hasKey: true, storageAvailable: false });
    await expect(store.getConnection()).rejects.toThrow('Secure credential storage is unavailable.');
    await expect(store.save({ serviceUrl: SERVICE, key: 'replacement' })).rejects.toThrow('Secure credential storage is unavailable.');
    expect(await readFile(file, 'utf8')).toBe(before);
  });

  it('requires a nonempty key for an initial connection or explicit replacement', async () => {
    const { store } = await fixture();
    for (const key of [undefined, '', '   ']) {
      await expect(store.save({ serviceUrl: SERVICE, key })).rejects.toThrow('A service key is required.');
    }
    await store.save({ serviceUrl: SERVICE, key: KEY });
    await expect(store.save({ serviceUrl: SERVICE, key: '' })).rejects.toThrow('A service key is required.');
    expect(await store.getConnection()).toEqual({ serviceUrl: SERVICE, key: KEY });
  });

  it('retains a key only for the same service origin and requires a new key across origins', async () => {
    const { store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    const sameOrigin = 'https://service.example/another-api';
    await store.save({ serviceUrl: sameOrigin });
    expect(await store.getConnection()).toEqual({ serviceUrl: sameOrigin, key: KEY });
    for (const serviceUrl of [OTHER_SERVICE, 'http://service.example/api', 'https://service.example:444/api']) {
      await expect(store.save({ serviceUrl })).rejects.toThrow('A new service key is required when changing service origin.');
      expect(await store.getConnection()).toEqual({ serviceUrl: sameOrigin, key: KEY });
    }
    await store.save({ serviceUrl: OTHER_SERVICE, key: 'new-origin-key' });
    expect(await store.getConnection()).toEqual({ serviceUrl: OTHER_SERVICE, key: 'new-origin-key' });
  });

  it('keeps the previous file and connection when encryption fails without exposing its error', async () => {
    const { directory, crypto, store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    const file = await storedFile(directory);
    const before = await readFile(file, 'utf8');
    vi.mocked(crypto.encryptString).mockImplementationOnce(() => { throw new Error(`raw key: ${KEY}`); });
    await expect(store.save({ serviceUrl: OTHER_SERVICE, key: 'replacement' })).rejects.toMatchObject({
      message: 'Could not securely store the service key.',
    });
    expect(await readFile(file, 'utf8')).toBe(before);
    expect(await store.getConnection()).toEqual({ serviceUrl: SERVICE, key: KEY });
  });

  it('atomically preserves the previous file on rename failure and removes the temporary file', async () => {
    const { directory, store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    const file = await storedFile(directory);
    const before = await readFile(file, 'utf8');
    vi.mocked(rename).mockRejectedValueOnce(new Error(`filesystem error with ${KEY}`));
    await expect(store.save({ serviceUrl: OTHER_SERVICE, key: 'replacement' })).rejects.toMatchObject({
      message: 'Could not save credentials.',
    });
    expect(await readFile(file, 'utf8')).toBe(before);
    expect(await storedFile(directory)).toBe(file);
    expect(await store.getConnection()).toEqual({ serviceUrl: SERVICE, key: KEY });
  });

  it('does not leak raw decryption errors or ciphertext through status', async () => {
    const { crypto, store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    vi.mocked(crypto.decryptString).mockImplementationOnce(() => { throw new Error(`raw key: ${KEY}`); });
    await expect(store.getConnection()).rejects.toMatchObject({ message: 'Could not decrypt the stored service key.' });
    expect(await store.status()).toEqual({ serviceUrl: SERVICE, hasKey: true, storageAvailable: true });
  });

  it('clears this app credential file and can reconnect, including when encryption is unavailable', async () => {
    const { directory, crypto, store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    vi.mocked(crypto.isEncryptionAvailable).mockReturnValue(false);
    await store.clear();
    await store.clear();
    expect(await readdir(directory)).toEqual([]);
    expect(await store.status()).toEqual({ serviceUrl: 'https://44.233.174.193', hasKey: false, storageAvailable: false });
    expect(await store.getConnection()).toBeNull();
    vi.mocked(crypto.isEncryptionAvailable).mockReturnValue(true);
    await store.save({ serviceUrl: OTHER_SERVICE, key: 'new-key' });
    expect(await store.getConnection()).toEqual({ serviceUrl: OTHER_SERVICE, key: 'new-key' });
  });

  it('serializes asynchronous save and clear in invocation order', async () => {
    const synchronous = fakeCrypto();
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const crypto: CryptoAdapter = {
      ...synchronous,
      encryptString: async (plain) => { await gate; return synchronous.encryptString(plain); },
    };
    const { store } = await fixture(crypto);
    const saving = store.save({ serviceUrl: SERVICE, key: KEY });
    const clearing = store.clear();
    release!();
    await Promise.all([saving, clearing]);
    expect(await store.getConnection()).toBeNull();
  });

  it('does not expose corrupt stored data and requires explicit clear before reconnecting', async () => {
    const { directory, store } = await fixture();
    const file = join(directory, 'credentials.json');
    const invalid = JSON.stringify({ serviceUrl: SERVICE, key: KEY });
    await writeFile(file, invalid, { mode: 0o600 });
    const error = { message: 'The stored credentials are invalid. Clear them to reconnect.' };
    await expect(store.status()).rejects.toMatchObject(error);
    await expect(store.getConnection()).rejects.toMatchObject(error);
    await expect(store.save({ serviceUrl: OTHER_SERVICE, key: 'replacement' })).rejects.toMatchObject(error);
    expect(await readFile(file, 'utf8')).toBe(invalid);
    await store.clear();
    expect(await store.status()).toEqual({ serviceUrl: 'https://44.233.174.193', hasKey: false, storageAvailable: true });
  });

  it('clear removes only the credential file, not other application data', async () => {
    const { directory, store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    const preferences = join(directory, 'preferences.json');
    await writeFile(preferences, '{"theme":"dark"}');
    await store.clear();
    expect(await readdir(directory)).toEqual(['preferences.json']);
    expect(await readFile(preferences, 'utf8')).toBe('{"theme":"dark"}');
    expect(await store.getConnection()).toBeNull();
  });

  it('a failed clear leaves the original configuration available without exposing filesystem errors', async () => {
    const { store } = await fixture();
    await store.save({ serviceUrl: SERVICE, key: KEY });
    vi.mocked(unlink).mockRejectedValueOnce(new Error(`filesystem error with ${KEY}`));
    await expect(store.clear()).rejects.toMatchObject({ message: 'Could not clear credentials.' });
    expect(await store.getConnection()).toEqual({ serviceUrl: SERVICE, key: KEY });
  });
});
