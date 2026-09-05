# Local Demo acceptance scenarios

These are explicit, in-memory UI simulations. They never contact providers, send real email, or affect the live API service. Normal Demo behavior is unchanged unless the process environment opts in. Closing the process resets the scenario and its local changes.

`AppSession.demo()` reads `FMG_DEMO_SCENARIO`. The live session does not read it. `DemoAPIService()` itself always defaults to the normal scenario, including in ordinary tests.

| Value | Behavior | Walkthrough |
| --- | --- | --- |
| Unset, `normal`, or unrecognized | Existing immediate-success fixtures | Browse profiles, matches, templates, and campaigns. |
| `qa-journey` | New matches progress through queued, screening, comparing, and completed on the existing job polls. The first valid email preview fails once. | Start a new match; leave and return while it runs; choose Review creators when ready; compose outreach; choose the explicit retry after the preview failure; return to Message, edit, and review again. |
| `empty-library` | No initial profiles, analysis history, matches, or campaigns; templates and Demo settings remain available | Check Library/Match/Campaign empty states; create a Game or Creator using Analyze Request; verify the imported local profile appears. |

Launch an already-built **Demo** bundle directly from the repository root after closing its previous instance:

```sh
FMG_DEMO_SCENARIO=qa-journey ./dist/FindMeGamer.app/Contents/MacOS/FindMeGamer
```

Use `FMG_DEMO_SCENARIO=empty-library` for the empty-state walkthrough. Launch without the variable to restore the normal Demo. No launcher or release configuration needs to change.

The processing scenario is poll-driven, not a claim about real matching duration: it deliberately exposes state transitions for inspection. Pending units remain unknown (`0/0`); no fabricated percentage or promised completion time is presented. The preview failure is consumed only by a valid request, so invalid recipient choices continue to receive their normal validation errors. Retry preserves the same draft and recipient choices.

Automated coverage in `DemoScenarioTests` verifies scenario parsing, unchanged normal behavior, ordered Match lifecycle snapshots and terminal stability, valid-preview failure/recovery, and populating the empty library through the existing analysis flow. GUI acceptance should be recorded separately; passing these tests does not establish keyboard, layout, or focus behavior.
