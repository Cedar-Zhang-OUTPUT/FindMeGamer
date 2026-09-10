// Read-only verification of actual API exports against frozen internal.4 decoders.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pin = '26e382f';
const [legacyGame, legacyDraft, currentDraft] = process.argv.slice(2);
if (!legacyGame || !legacyDraft || !currentDraft) throw Error('Expected actual legacy Game, legacy draft, opt-in draft JSON paths');
const entry = 'export { decodeDetail } from "./game-client"; export { decodeDraft } from "./drafts-validation";';
async function decoders(frozen) {
  const result = await build({ stdin: { contents: entry, resolveDir: path.join(desktop, 'src/main'), loader: 'ts' }, bundle: true, platform: 'node', format: 'cjs', write: false,
    plugins: frozen ? [{ name: 'frozen-internal4-decoders', setup(builder) {
      builder.onLoad({ filter: /\/(game-client|drafts-validation)\.ts$/ }, args => ({ contents: execFileSync('git', ['show', `${pin}:desktop/src/main/${path.basename(args.path)}`], { cwd: desktop, encoding: 'utf8' }), loader: 'ts', resolveDir: path.dirname(args.path) }));
    } }] : [] });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', result.outputFiles[0].text)(createRequire(import.meta.url), module, module.exports);
  return module.exports;
}
const old = await decoders(true), current = await decoders(false);
const game = JSON.parse(readFileSync(legacyGame, 'utf8')), draft = JSON.parse(readFileSync(legacyDraft, 'utf8')), optedIn = JSON.parse(readFileSync(currentDraft, 'utf8'));
assert.deepEqual(old.decodeDetail(game), game);
assert.deepEqual(old.decodeDraft(draft), draft);
assert.deepEqual(current.decodeDraft(optedIn), optedIn);
for (const snapshot of [game, draft.input.game]) {
  assert.equal(Object.hasOwn(snapshot, 'steam_recommendations'), false);
  for (const reference of snapshot.reference_works) { assert.equal(Object.hasOwn(reference, 'source'), false); assert.equal(Object.hasOwn(reference, 'source_url'), false); }
}
assert.ok(Object.hasOwn(optedIn.input.game, 'steam_recommendations'));
console.log(JSON.stringify({ status: 'passed', legacyDecoderPin: pin, legacyGame: true, legacyNestedDraft: true, currentNestedDraft: true }));
