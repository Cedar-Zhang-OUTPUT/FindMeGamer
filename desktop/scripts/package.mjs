import { packager } from '@electron/packager';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { mkdir, mkdtemp, readFile } from 'node:fs/promises';

const execute = promisify(execFile);

const metadata = JSON.parse(await readFile('package.json', 'utf8'));
// Unique release directory: never replace an existing package or daily installation.
await mkdir('artifacts', { recursive: true });
const output = await mkdtemp(path.resolve('artifacts', `FindMeGamer-Electron-${metadata.version}-${process.arch}-`));
// Local .app only; DMG generation and publication are explicit separate steps.
const paths = await packager({
  dir: '.', out: output, name: 'FindMeGamer', appBundleId: 'com.findmegamer.desktop',
  platform: 'darwin', arch: process.arch, electronVersion: '44.2.0',
  appVersion: '0.2.0', buildVersion: '20001',
  icon: 'build/AppIcon.icns',
  asar: true, overwrite: false, appCategoryType: 'public.app-category.productivity',
  extendInfo: { LSMinimumSystemVersion: '14.0', FMGReleaseVersion: metadata.version, FMGClientTechnology: 'Electron' },
  // Bundle only runtime output and its entry-point metadata, never local test/config files.
  ignore: [/^\/(?!(?:package\.json$|out(?:\/|$)))/, /\.map$/],
});
for (const directory of paths) {
  const bundle = path.join(directory, 'FindMeGamer.app');
  // Re-seal the modified Electron bundle for local use only. This does not use a
  // Developer ID identity, access signing credentials, or notarize a distribution.
  await execute('/usr/bin/codesign', ['--sign', '-', '--force', '--deep', '--preserve-metadata=entitlements,requirements,flags,runtime', bundle]);
  await execute('/usr/bin/codesign', ['--verify', '--deep', '--strict', bundle]);
}
console.log(paths.join('\n'));
