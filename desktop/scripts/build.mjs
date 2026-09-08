import { build as bundle } from 'esbuild';
import { build as renderer } from 'vite';

await renderer();
await bundle({
  entryPoints: ['src/main/index.ts', 'src/preload/index.ts'],
  outbase: 'src', outdir: 'out', outExtension: { '.js': '.cjs' },
  platform: 'node', target: 'node24', format: 'cjs', bundle: true,
  external: ['electron'], sourcemap: true,
});
