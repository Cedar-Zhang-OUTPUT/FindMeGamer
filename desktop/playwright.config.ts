import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', timeout: 60_000, workers: 1,
  outputDir: 'output/playwright', reporter: 'list',
  use: { trace: 'retain-on-failure' },
});
