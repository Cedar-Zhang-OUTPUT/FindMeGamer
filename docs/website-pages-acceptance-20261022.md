# FindMeGamer website · live acceptance

Verified 2026-10-22, approximately 14:26 Beijing time.

- Production URL: https://cedar-zhang-output.github.io/FindMeGamer/
- Chinese: https://cedar-zhang-output.github.io/FindMeGamer/zh/
- Deployment source: `website` branch, commit `51942ef705d5ea312ac5f779b80d1a81d252287a`.
- Successful build + deployment: https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/actions/runs/39733675983
- Previous run built successfully but deployment was rejected by the newly created Pages environment's default main-only branch policy. Added an exact `website` branch rule, retained the existing main rule and other protections, then deployed normally.

## Evidence

- 333 static checks, Chinese generation reproducibility and application JavaScript syntax checks passed locally and in the workflow.
- All 32 published files returned HTTP 200 and SHA256 matched the local source files, including English/Chinese pages, the installation README, fonts, Three.js and license text.
- Real public HTTPS site tested in Chromium: both languages render the live Three.js hero and copy the exact visible installation Prompt.
- Public installation README returns HTTP 200 with `text/markdown; charset=utf-8`; contains fmg-v0.8.4 instructions. Anonymous release download and isolated CLI/Skills installation were verified before deployment.
- Local responsive, clipboard-denial, no-JavaScript, script-load-failure, no-WebGL, reduced-motion and save-data tests are recorded in `website/DEPLOYMENT.md`.

No authenticated API test, paid research, email, backend deployment or mailbox setting change was performed. CLI release artifacts and the `main` / `cli` branches were not modified. The website's own install guide replaces its link to the old CLI branch guide; it does not rewrite the old guide.

This acceptance note is outside the website artifact and path-trigger filters, so recording it does not redeploy a different site payload.
