# GitHub Pages deployment

Prepared: 2026-10-22 (Asia/Shanghai).

## Hosting

- Public English: https://cedar-zhang-output.github.io/FindMeGamer/
- Public Chinese: https://cedar-zhang-output.github.io/FindMeGamer/zh/
- Public Agent guide: https://cedar-zhang-output.github.io/FindMeGamer/install/README.md
- Repository source: branch `website`, directory `website/`.
- Workflow: `.github/workflows/website-pages.yml`. Website path changes pushed to this branch validate, stage and deploy to the `github-pages` environment.
- GitHub Pages build type: `workflow`; no custom domain configured.
- Other application branches, backend services, mailbox settings and CLI release artifacts are unchanged.

## Compatibility changes

1. Preserve relative runtime URLs under `/FindMeGamer/`, including Chinese `../` resources and Three.js module imports.
2. Add canonical, hreflang, absolute social metadata, sitemap and a project-path-aware 404.
3. Replace the old installation guide URL with a website-owned README for fmg-v0.8.4. Remove mailbox/game-specific routing from onboarding. Keep the short bilingual Prompt and all guide links consistent.
4. Fix invisible language selectors (`opacity: 0`), Chinese menu accessible labels, and unnecessary English font preloading on the Chinese page.
5. Make content visible if the main script fails; don't enable WebGL in save-data mode. Remove live-scene classes after disposal so bfcache restoration shows fallback artwork instead of blank canvases.
6. Include third-party font/Three.js licenses, pin the Python HTML-tool dependency, and restrict the published artifact to an explicit whitelist.

## Pre-deployment verification

- 333 static checks passed after final changes: prompts, links/resources, metadata, local guide, licensing files and basic accessibility markup.
- English-to-Chinese generation succeeds; both pages use one shared runtime.
- JS syntax checks passed for all three application scripts.
- Anonymous HTTPS download of fmg-v0.8.4 installer and checksum manifest succeeded. SHA256 matches. Installer reviewed, then run in a checkout-local isolated bin/Skills directory; CLI reports 0.8.4 and both Skills installed. No personal CLI/Skills paths changed, no token supplied, no research/send operation run.
- Chromium: English and Chinese clipboard contents exactly match visible Prompt; mobile menu opens/closes with Escape; correct Chinese accessible label.
- Both languages checked at widths 375, 390, 768, 1024 and 1440 without horizontal overflow. Desktop/mobile screenshots inspected; real Three.js hero activates.
- Separate browser contexts passed reduced motion, JavaScript disabled, WebGL unavailable, main-script load failure, clipboard denial/manual selection and save-data fallback scenarios.
- Public artifact staging excludes `source/`, `tools/`, local tests, credentials and the rest of the application repository. About 1.24 MB uncompressed before HTTP compression.

## Limits

No Safari/Firefox or physical low-end-device performance audit, complete accessibility audit, or Lighthouse score certification was performed. No authenticated onboarding or provider business operation was run. Existing public service access still requires an administrator-issued FMG token; website publication does not enable public signup.

The original source delivery checklist and content package contain historical pre-launch notes; this document supersedes their old guide/version blocker. The old `cli` branch AGENT-INSTALL guide is not changed by this independent website deployment.

## Maintenance and rollback

Update the guide when a new CLI release is approved; keep website copy version-agnostic. For a domain/path change, update metadata, sitemap, guide URL in both source prompts and the Chinese generator, then rerun checks.

To roll back the website, revert the bad website commit on `website` and push normally. Do not reset/force-push shared history or deploy the entire repository. A guide-only change also triggers a validated redeploy. Deployment success must be checked in the Actions run and the actual public URLs; this preparation record alone is not evidence of successful hosting.
