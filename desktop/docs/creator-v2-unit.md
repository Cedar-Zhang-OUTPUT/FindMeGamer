# Creator v2 Library implementation plan

> For agentic workers: use superpowers:subagent-driven-development; independent task reviews and one final unit review. One desktop-only source commit after verification, no per-worker commits.

Goal: editable, task-focused multi-platform Creator records, contacts, known works and explicit identity correction on the existing backend.
Architecture: typed CreatorAPI in shared/creators.ts → narrow preload methods → generation-fenced main client/transport → existing v2 HTTP. Renderer owns an explicit edit/recovery state and retains task context; no business persistence on this Mac.
Tech stack: existing Electron, React, TypeScript, Vitest and Playwright. No new dependencies.
Spec: coordinator's six-part authorized scope plus /Users/cedar/Documents/ChatGPT/FindMeGamer/docs/backend-v2-library-creators.md. Accepted backend source /tmp/fmg-frontend-stable.bpM1DM/repo at0153a38 and its schemas/OpenAPI are authority. Historical dd4 runtime paragraphs are superseded: current18090 already0009 + Settings capture overlay.

## Global Constraints

- Only desktop/ changes. No backend/macOS/contract edits, real providers/mail, production data, push/merge/DMG/deploy, Activity/Discovery/Analyze Request/outreach UI. No container rebuild/reset/seed or environment upgrade.
- Lists use v2 offset/limit/total (default50/max100), query/platform/language/only_collection. Unknown counts/languages/validation stay unknown. Twitch/Instagram manual/unavailable; no fake fetch/analyze action.
- Source identity is separate from editable homepage/handle. History is retained, previous contacts/works read-only. Source/manual values and explicit reset_fields remain accessible without first-screen paragraphs.
- Creator PATCH/contact writes use Creator expected_revision; work create uses expected_identity_revision; work patch uses work expected_revision. All POSTs freeze key/body including omitted fields, at most24h, no automatic retry, never replay after credentials/workspace changes. All success/replay snapshots reconcile current reads before enabling writes.
- Rebind requires explicit old/new comparison, confirmed:true and expected_revision. Old contacts/works do not become current. Analysis/delivery/conflict errors do not auto-retry; unknown outcome requires readback.
- Preserve drafts, filters, scroll and keyboard access; local errors/recovery; no hidden data loss. Existing Game and Settings protections/regressions remain binding. Test writes only18090 isolated clearly named fixtures; no external email.

## Design / states

Path: find or create Creator → shared detail → choose Profile / Emails / Known works → edit one object in place → save → current detail. Identity change is a separate action under Account identity, never an ordinary homepage edit.

| State | Focus / main action | Retained context / disclosure |
|---|---|---|
| List / empty | Search, filters / New creator | platform/language filters compact, paged total |
| Detail | Account identity + current facts / Edit profile | emails/works tabs; source/history disclosure |
| Editing | Current object / Save | cancel, fields grouped, optional data expandable |
| Pending | Local save state | no duplicate submission/navigation/key change |
| Conflict | Changed values / choose latest or mine | latest server revision, explicit resubmission |
| Unknown POST | Frozen attempt / check records or safe same-key retry | draft read-only,24h/key boundaries, no fresh creation |
| Rebind | Old/new identity / explicit confirmation | historical isolation and cleared source facts concise |
| Failed | Relevant error / read-only recovery | drafts and successfully loaded content retained |

Default: identity/name, available follower count, description, recorded audience/notes and selected content; absent optional facts are omitted. On demand: account binding, provenance/source comparison and previous-identity work history. Optional form fields are grouped in named disclosures. Critical identity consequences and unknown-write outcomes appear before decisions. User-driven transitions focus headings/inputs; background readback never steals an active input. Existing reduced-motion/theme/font behavior applies.

## Task 1: Validated Creator adapter and transport

Files: create src/main/creator-client.ts, creator-transport.ts, tests/creator-client.test.ts, creator-transport.test.ts, tests/creator-fixtures.ts. Consume root src/shared/creators.ts. No bridge/gateway/App edits (root).
Interface: export class CreatorClient(request:(input:CreatorRequest)=>Promise<unknown>) with same method inputs as CreatorAPI but unwrapped Promise<DTO>. Export CreatorRequest, validateCreatorRequest, authenticatedCreatorRequest(fetcher,connection,input), creatorOutcomeUnknown. Separate strict routes/methods/queries; no general fetch IPC.

- [x] TDD request/response projections and full literal DTO fixtures against accepted schema; schema fields/constraints/nullability, safe integers/finite metrics, aware times, URLs no credentials, max lengths, partial writes, reset overlap, protected identities, duplicate work/contact handling. Example behavioral assertion: updateContact({creatorId,contactId,data:{expected_revision:3,is_active:false}}) emits PATCH exact contacts/id with that body, response Creator revision4; raw extra response secret never reaches public result. Strict failure rather than leaking unsupported fields acceptable.
- [x] TDD route method whitelist, IDs, query/body top-level whitelist, key syntax8–128, no cookies/redirects,20s timeout/8MiB bound, safe error mapping, sanitized rawerrors, postdispatch mutation/parse/5xx unknown semantics. Error codes include creator_revision_conflict, work_revision_conflict, creator_identity_changed, identity/contact conflicts, analysis/delivery in progress, game_not_found/creator_not_found/contact/worknotfound, idempotency conflict, auth. Preserve safe UUIDcorrelation only.
- [x] Implement minimal adapters then focused tests and self-review. No runtime/probe/container operations. Report exact tests/RED/GREEN and owned files. Root integrates typed gateway.

## Task 2: Forms and draft payloads

Files: create renderer/components/creators/creatorDraft.ts, CreatorForm.tsx, ContactForm.tsx, WorkForm.tsx, LinkedGamePicker.tsx, creatorForms.css; tests/creator-draft.test.ts, creator-forms.test.tsx. Only these files. Consume shared DTOs and tests/creator-fixtures.ts when available; do not edit them.
Interfaces: exported EntityKind='creator'|'contact'|'work'; EditContext={kind:EntityKind;base:CreatorDetail|ContactDetail|WorkDetail|null;creator?:CreatorDetail}; EntityDraft={values:Record<string,JsonValue>;resets:string[]}; functions draftFrom(context), changedKeys(context,draft):string[], makePayload(context,draft):CreatorCreate|CreatorPatch|ContactCreate|ContactPatch|WorkCreate|WorkPatch, validateDraft(context,draft):Record<string,string>, fieldLabel(key):string. Make payload pick only actual supported changed fields; create only meaningful explicit fields, required revisions added from context. Base null creator defaultyoutube/falsefavorite, nullable fields null, arrays empty. Creator creation values include platform/account_id/favorite. Creator public_name change clears public_name_confirmed unless explicitly checked by user again.
Forms export CreatorForm/ContactForm/WorkForm each takes {context,draft,onChange,disabled,errors}; WorkForm additionally api:Pick<DesktopBridge,'games'>. All fields use labeled controls ids creator-field-<key>; one form mounted at once. Pure forms, no submit/navigation/mutations. Fields are editable here even if overall saved record/source; host decides historical read-only.

- [x] TDD partial/null/array/reset/revision output; unknownfollower vs0; confirmationclears; contactemailcannotnull; workmustname/title/url on create; metrics/time finite nonnegative; previousidentity not host-mutated. Tests literal expect expected_revision/context revision and reset_fields notoverlap.
- [x] Creator form grouped identity/display/audience/notes/othercontacts; initial platform+account_idorprofile_url plus optionalname; platform not editable in ordinaryedit. All16businessfields+favorite reachable. Other contacts repeatable labeled rows; arrays not opaque JSON. Noautoinfermetadata. Source/manual comparison disclosure permits per-field Use source; no email reset withoutsourceemail.
- [x] Contact form email/purpose/active plus sourcedURL/verificationnotes; noverifiedtoggle. Work form name/title/type/sourceurl, expandable evidence/time/metrics/Game/provenance-facing fields; all13fields. LinkedGamePicker real bounded api.games.list search/page and api.games.detail for current label, explicit none, retainsselection/error; no rawUUID-only UX.
- [x] Keyboard/narrow-compatible semantic HTML, theme CSS scoped.creators; preserve open details while typing. Validation summary hostopensclosestdetails/focus firstinvalid. Run focused tests and report RED/GREEN.

## Task 3: Shared detail and contact/work reading panels

Files: create renderer/components/creators/CreatorRecord.tsx, CreatorContacts.tsx, CreatorWorks.tsx, creatorRecord.css; tests/creator-record.test.tsx. No forms/library/host/API files.
Interfaces: CreatorRecord({api:DesktopBridge,creator:CreatorDetail,onBack:()=>void,onEdit:(target:{kind:'creator'|'contact'|'work'|'identity';base?:ContactDetail|WorkDetail})=>void,refreshToken?:number}). At root integration DesktopBridge gains creators:CreatorAPI. CreatorRecord is reusable, does not own top-level routes/mutations; it calls onEdit for explicit actions. Export CreatorContacts/CreatorWorks as appropriate, but host uses CreatorRecord.

- [x] TDD current/historical contacts alladdresses, origin/source/validation/purpose shown, no email send; only currentidentity Edit, hidden entriesdisclosed withrestore accessible throughEdit; sources/details explicit. UI never converts unverified toverified.
- [x] Header avatar/name/handle/platform,follower unknownnot0, publicnameconfirmation; display primarysummary andaudience/notes/othercontacts withoutdatawall. Stable tabs Profile/Emails/Knownworks; onefocus. Accountidentity disclosurecurrentplatform/id/homepage+Changeidentity action; noanalyze controls; Twitch/Instagram manual/unavailablelabel.
- [x] Works fetched onlyonactive; strict offset pages currentdefault, includePreviousIdentity toggle explicit; ownloading/error/read-onlyretry, preservepriorpageonfailure, ignorelateid/revisionresponses. Cards withknown metrics/type/evidence excerpt/time/game link label; historicalreadonly. Showorigin/acquisitionidentity vsdisplayvalues inprovenancedisclosure, neverimplyallhistory/played/watched. Work add/edit calls host; refreshToken invalidates localread aftersavedwork, not backgroundpoll.
- [x] SafeHTTPSexternalopening viaapi.openExternal only, no mailto autofire. Keyboardtabnavigation/accessibility; no focussteal onrefresh. Run focused tests, report RED/GREEN. No main/API writes.

## Task 4: Root mutation/navigation integration

Files: new creators/CreatorLibrary.tsx, CreatorEditor.tsx, CreatorIdentityEditor.tsx, creatorMutation.ts, creatorRecovery.tsx and scopedcreators.css asneeded; tests/creator-editor.test.tsx, creator-host.test.tsx; modify LibraryView, App onlywhere needed, sharedbridge/preload/application/gateway narrowwiring andmockconsumers.
- [x] TDD gateway-generation fence/typedchannels; listfilter/offset/returncontext; bothLibrarytabsnavigationguards; preserveGame/Settings. LibraryView hostsCreatorLibrary andGameLibrary independentlymounted and registers onlyactiveguard.
- [x] Explicitstate editing/saving/conflict/uncertain/reconciling/confirmed with oneinflightref; freezesPOSTkey/body/time. Sameoriginrepair lendsSettingsnavigation withoutlosingdraft. Credentialschange irrevocablydisablesoldPOSTretry; workspacechange ignoreslateoutput. 24hexpiry lock, noautomaticresubmit/freshkeyafteruncertain. Checkrecords boundedcurrentGETlist/detail/works, explicitUse thisrecord pluscurrentGET beforefinaldetail. ContactPOST parentdetail andworkPOSTonlywork reconcilecurrentCreator/workspage; no stale snapshot reenablesoldidentityediting.
- [x] Conflictreadlatest/fieldchoices/updatedrevision explicit; no overwrite. Parentcontactrevision synchronized. Workedit ownrevision; detectnewidentity historicalread-only. Failedreconciliation keepsfrozen successknown id not genericnewcreate.
- [x] Identityform currentold/new platform/account/homepage pluscompactconsequenceconfirm; sendsPUTconfirmedtrueonlyafterdialog. Pendinganalysis/delivery/conflicterrors preserveinput; uncertainPUT requirescurrentGET andcompare expectedidentityrevision, no blindretry. Explicitreview latestrebase only when userchooses.
- [x] Draftguard clearstate onlyconfirmeddiscard; close/reload protected; busylocksconnection; UI errorlocal. Tests cover canceledactions, keyboard, delayedresponses,keyrepair, expired/rejectedreplay, allbusinesswrites.

## Task 5: Real packaged acceptance / handoff

Files: e2e/creators.spec.ts and minimal existingfixture/E2E expectationupdates, README andthisverificationrecord. Only18090 isolatedfixtures, no serverrestart or seeds.
- [x] Real Electron UI creates a clearly named manual YouTube record, edits/readbacks, resolves a concurrent revision conflict, adds multiple email addresses and hides one, creates/edits known works, and explicitly rebinds with history read-only. Lost-response POST/PUT cases run through the real unchanged API. Analysis blocking and stale-identity handling have local component tests; no live analysis/delivery was initiated.
- [x] ExistingGame/Settings/alltests regression;720pxdark20px,keyboard,returncontext screenshots; .app sourceonlypackaging/signature/iconchecks. No parallelheavytestload (one longGameflowtesthas10sbudget).
- [x] Independent taskspec+qualityreviews and onefinalunitreview; scopedfixloop. Fresh npmcheck andallpackagedE2Es; desktop-onlyseparatecommit/handoffno publish. Documentexacttestedbehavior andlimitations, preservedtestenvironment.

## Verification record

Baseline a418081, codex/electron-desktop linked worktree. Source implementation, independent scoped review and packaged acceptance complete.

2026-09-08 final source checks: `npm run typecheck` passed; `npm test -- --maxWorkers=4` passed all 458 tests in 25 files (9.43 seconds, final 19:50 run); `npm run build` and `git diff --check` passed. Explicit internal/external navigation intent replaced callback identity comparisons after a review found a delayed-parent-render race. Both new tests were observed RED before the fix; 23 focused editor/Library tests then passed. Creator heading focus, previous-identity work isolation, public-name confirmation coupling and credential-repair/readback guards were independently reviewed. Final test-only locator/disclosure migrations were also independently approved without weakening coverage.

The final bundle includes the navigation-intent fix and passed strict deep ad-hoc signature verification; embedded `electron.icns` exactly matched `build/AppIcon.icns` (SHA-256 `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`). Build completed with 54 modules. The documented `node --use-env-proxy scripts/package.mjs` route was used after the direct GitHub artifact connection stalled. Final renderer assets are `index-DL1Klwah.css` / `index-BhDZm-gW.js`.

Final packaged E2E: **6 passed, 0 skipped, 0 failed in 20.3 seconds**. Command: `FMG_BACKEND_FIXTURE_FILE=<private isolated client file> FMG_SETTINGS_CAPTURE_DIR=<isolated SMTP capture> FMG_VERIFY_SYSTEM_HTTPS=1 FMG_PACKAGED_EXECUTABLE=<local .app executable> npx playwright test`. Credentials were read in memory only; secret-bearing flows disable traces/video.

| Journey | Observed result |
|---|---|
| Existing API → Settings → Creator/Game Library | Auth, current records, bundled images/preload and encrypted persistence passed |
| Creator writes | Create + same-key lost-response replay, explicit conflict merge, repeated public-name confirmation, two contacts/hide, work create/edit/revision, identity-change readback and historical read-only passed |
| Game writes | Save, deduplicated retry, revision conflict, draft/auth repair without old-request replay passed |
| Settings | Appearance/system theme/20px, guarded shared credentials and local provider fixtures, intervals, confirmed capture-only SMTP, update metadata isolation passed |
| HTTPS | Anonymous public health read through macOS system proxy without shell proxy variables, with TLS checks retained, passed |
| Controlled visual/security fixture | Native disclosure keyboard Enter, Creator tab arrows/Home, default/expanded states, failure/retry, 760px layout and 20px dark text, iframe/Node/credential isolation passed |

Screenshots were visually inspected for Creator profile, Emails, Known works, expanded identity, Game detail and connection settings; default and dark/20px narrow layouts preserve usable controls and have no horizontal document overflow. Captures are temporary artifacts, not bundled app resources. Settings additionally exercised a 720px window. Creator unknown, empty, conflict, readback-failed and returned-draft states are covered by the component suite; real lost-response saves are exercised in the packaged flow.

Earlier runs stopped at the OS Keychain gate and then exposed stale test selectors. The user handled Keychain manually. Tests now select the email textbox rather than an identically named hidden Settings tab and actually expand X test scope before checking its limitations. No OS permission bypass, plaintext fallback or weaker timeout/assertion was introduced.

Limits: local Apple Silicon macOS only; not an Intel, Gatekeeper-download, notarization or release-distribution acceptance. Provider fixtures/SMTP capture do not establish real provider access, TLS SMTP handshakes or external delivery. Manual platform variants are component/API tested, not live external discovery. No live analysis/delivery contention or destructive production actions were induced. VoiceOver, mobile/touch and every possible long-content combination were not exhaustively audited. Match/Outreach remain intentionally unimplemented in this Electron unit. No backend source or API contract was changed; the separately authorized one-row seed correction is recorded in `ui-information-pass.md`.

## Task 6: Creator list and Library host integration

This extracts the list/LibraryView portion of Task4 into a disjoint parallel task; root retains editing/mutation/identity/IPC/E2E work.
Own renderer/components/creators/CreatorLibrary.tsx, its scopedcreatorLibrary.css, renderer/components/LibraryView.tsx, tests/creator-library.test.tsx, migration of tests/renderer.test.tsx and tests/games-renderer.test.tsx, tests/settings-fixtures.ts + tests/creator-api-mock.ts only to provide newtypedCreatorAPI mock defaults. Do not edit other files. All GlobalConstraints apply.
Interface CreatorLibrary({api:DesktopBridge,active:boolean,onNavigationGuardChange?:(guard:NavigationGuard|null)=>void,onConnectionRepair?:()=>void}). CreatorEditor root export accepts {api,initial:EditContext,onSaved:(creator:CreatorDetail)=>void,onCancel,onNavigationGuardChange,onConnectionRepair}. CreatorIdentityEditor root export same except initial:CreatorDetail. CreatorRecord Task3 accepts {api,creator,onBack,onEdit:(target:{kind:'creator'|'contact'|'work'|'identity';base?:ContactDetail|WorkDetail})=>void,initialSection?:'profile'|'emails'|'works',refreshToken?:number}. Editingcreator initial={kind:'creator',base:creator}, newbase=null; contact/work initial={kind,base:target.base??null,creator}. Returnfromemail/workedit tocorrespondingdetailtab. NoEditorinternalchanges; rootimplementsmissingfile shortly.
- [x] TDD v2listfilters query/platform/language/favorite, explicitsearch, offset/limit/total pages. No cursor semantics inCreatorUI. Keep validpageonfailedfetch; readretryexact failedinput; no stale overwrites. Zero count not unknown, unknown notzero. Sourceidentity platform truthful manualTwitch/Instagram. NewCreatoractionavailableunfilteredempty.
- [x] LibraryView hostsCreatorLibrary/GameLibrary independentlymounted. Register guards byactivekind only, neverinactiveeffectwipingcurrentguard. Both tabsnavigate throughactiveguard; preserveallfilters/page/selection/tabscroll, keyboardsegmentedarrow/Home/End. Activepropdo notresetfiltersdetail; currentlistreadsonexplicitfilter/refresh/taskupdates, noteveryoutertabtoggle.
- [x] Onsave currentcreator detailshown; list cacheupdated/reconciled withoutlosingfilters, offsetclamped iftotalshrinks; backfocusselectedrowwhenpresent andrestorelistscroll. Detail independentfailingread+retry; nonblockingerrorlocal. Do notauto switchtogamesorSettings.
- [x] Existingrenderer andGame-renderer testsmigrate torealCreatorAPI fixtures/assertions atboundary, preservingoriginalbehaviorcoverage exceptexplicitcursor→offsetcontractchange; no wholesale testdeletionorweakening. Oldv1libraryadapters/tests stay forSettingsactivity; no obsoleteProfileDetail UI inLibrary. Fix centraltypedmock literalok truewidening, keep usefuldefaultPixelHarbor forbaselinehosttests while creatorAPIMock defaultCreatorfixture remains.
- [x] Runfocused tests/TDD and report .superpowers/sdd/creator-v2-unit/task-6-report.md. No commits/agents/liveAPI/backendchanges. Rootfinalreviewsintegration.
