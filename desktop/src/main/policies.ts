import path from 'node:path';
export { previewDocument } from '../shared/mail-preview';

export const APP_URL = 'fmg://app/index.html';
export const CONTENT_POLICY = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; font-src 'self'; connect-src 'none'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'";

export function normalizeServiceUrl(value: string): string {
  if (typeof value !== 'string' || value.length > 2048) throw Error('Enter a valid service address.');
  let url: URL;
  try { url = new URL(value.trim()); } catch { throw Error('Enter a valid service address.'); }
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) ||
      url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) {
    throw Error('Use an HTTPS service address without a path, query, or credentials. HTTP is only supported for local development.');
  }
  return url.origin;
}

export function resourcePath(rawUrl: string, rendererRoot: string): string | null {
  try {
    const decoded = decodeURIComponent(rawUrl);
    if (decoded.includes('\\') || decoded.includes('\0') || decoded.split('/').includes('..')) return null;
    const url = new URL(rawUrl);
    if (url.protocol !== 'fmg:' || url.host !== 'app' || url.username || url.password) return null;
    const name = decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname);
    if (name !== '/index.html' && !/^\/assets\/[a-zA-Z0-9_./@-]+\.(js|css|png|svg|webp|jpg|jpeg|woff2?)$/.test(name)) return null;
    const resolved = path.resolve(rendererRoot, `.${name}`);
    return resolved.startsWith(path.resolve(rendererRoot) + path.sep) ? resolved : null;
  } catch { return null; }
}

export function isTrustedFrame(url: string, isMainFrame: boolean): boolean {
  return isMainFrame && url === APP_URL;
}

export function externalUrl(value: string): string {
  if (typeof value !== 'string' || value.length > 8192) throw Error('This link is not supported.');
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password) throw Error('Only HTTPS links can be opened.');
  return url.href;
}
