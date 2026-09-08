import { describe, expect, it } from 'vitest';
import { normalizeServiceUrl, resourcePath, isTrustedFrame, externalUrl, previewDocument } from '../src/main/policies';

describe('desktop boundaries', () => {
  it('accepts explicit HTTPS services and exact loopback HTTP without credentials', () => {
    expect(normalizeServiceUrl(' https://service.example/ ')).toBe('https://service.example');
    expect(normalizeServiceUrl('http://127.0.0.1:8123')).toBe('http://127.0.0.1:8123');
    for (const value of ['http://example.com', 'https://user:password@example.com', 'file:///tmp/key', 'https://x.test/path', 'https://x.test?key=value', 'https://x.test/#a']) {
      expect(() => normalizeServiceUrl(value)).toThrow();
    }
  });
  it('only serves bundled renderer assets from the fixed app origin', () => {
    expect(resourcePath('fmg://app/', '/app/out/renderer')).toBe('/app/out/renderer/index.html');
    expect(resourcePath('fmg://app/assets/ui.css', '/app/out/renderer')).toBe('/app/out/renderer/assets/ui.css');
    for (const url of ['fmg://evil/index.html', 'fmg://app/%2e%2e%2fmain/index.cjs', 'file:///etc/passwd', 'fmg://app/../../main/index.cjs']) {
      expect(resourcePath(url, '/app/out/renderer')).toBeNull();
    }
  });
  it('only allows business IPC from the exact top-level application page', () => {
    expect(isTrustedFrame('fmg://app/index.html', true)).toBe(true);
    expect(isTrustedFrame('fmg://app/index.html', false)).toBe(false);
    for (const url of ['fmg://app.evil/index.html', 'about:srcdoc', 'https://app/index.html', 'fmg://app/mail.html']) {
      expect(isTrustedFrame(url, true)).toBe(false);
    }
  });
  it('external links cannot invoke system protocols or carry embedded credentials', () => {
    expect(externalUrl('https://youtube.com/@creator')).toBe('https://youtube.com/@creator');
    for (const url of ['javascript:alert(1)', 'file:///tmp/a', 'mailto:test@example.com', 'https://u:p@host.test']) expect(() => externalUrl(url)).toThrow();
  });
  it('email preview starts with a no-script/no-network policy', () => {
    const html = previewDocument('<script>window.desktop.connection.clear()</script><img src="https://remote.test/x">');
    expect(html.indexOf('Content-Security-Policy')).toBeLessThan(html.indexOf('<script>'));
    expect(html).toContain("default-src 'none'");
    expect(html).toContain("script-src 'none'");
    expect(html).toContain("form-action 'none'");
  });
});
