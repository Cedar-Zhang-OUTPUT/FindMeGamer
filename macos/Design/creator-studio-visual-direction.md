# Creator Studio — expressive native UI

## Intent

Move the experience from a neutral administration tool toward an editorial creator-discovery product. Preserve the task-centered workflow, exact data, explicit email decisions, and editable drafts; change how that information feels and reads.

- **Identity first:** real avatar or honest monogram, name, one positioning statement, source-backed metrics.
- **Information as composition:** explicit topic values become chips; audience, opportunity, and caution receive recognizable icon/color treatments; long evidence stays available in named disclosures.
- **One dramatic area per state:** the Match start/current-task panel is deep ink; the surrounding workspace stays warm and quiet. Profile cover material is decorative, not a second dashboard.
- **Tactile response:** brief card lift, selected-tab movement, pressed feedback. No perpetual motion or invented progress; reduced motion removes movement.
- **Writing as writing:** template/message text uses paper surfaces and readable rhythm, while the existing recipient → message → exact preview → confirm sequence remains intact.

## Color semantics

Warm pearl canvas and deep ink typography are paired with adaptive electric blue, mint, coral, and amber. Each has a separate dark-appearance value. Creator identity colors come from a stable hash of the supplied identity string and are decorative only. They do not represent inferred genre, quality, ranking, or fit.

Meaningful state or evidence labels remain textual. A risk is never communicated by tint alone. There are no invented radar plots, percentages, demographic charts, stock portraits posing as real creators, or synthetic performance claims.

## State continuity

| State | Visual emphasis | Kept available |
| --- | --- | --- |
| Library | Cover-like creator/game collection | Search/type/favorites, stable responsive input, Analyze |
| Match start | Ink task panel and game selector | Recent matches remain secondary |
| Matching | Current game and honest processing status | Leave/back, other work, no forced navigation |
| Results | Creator identity, real metrics, categorical fit | First caution, full evidence, selection and stale-state gates |
| Profile overview | Identity cover, positioning, themed insights | Risks visible; evidence and contacts named tabs |
| Profile evidence | Grouped source/analysis/inference sections | Every previously exposed field remains reachable |
| Profile contacts | Contact cards and notes editor | Source, purpose, validation, explicit save/discard |
| Compose / templates | Letter-like text area and current step | Back/cancel, exact preview, consequences and retry |

The original presentation/state ownership is retained. This pass does not change backend APIs, provider configuration, model rankings, sending authorization, or server preview authority.

## Original material

Asset: `../Sources/FindMeGamer/Resources/studio-orbit-cover.png`.

Generated with the built-in imagegen tool. Used in the actual native profile/header background, not presented as profile data. The PNG is included in SwiftPM resources for development/tests and copied into the app's `Contents/Resources` by development/release packaging. Application resource lookup takes precedence, so packaged use does not depend on the generation directory or a network request. Signing and service settings are unchanged.

Final generation prompt:

> Use case: stylized-concept. Asset type: original wide decorative header material for a premium native macOS creator-discovery application. Create one beautifully art-directed abstract 3D still life, no interface, no text. A single large translucent glass orbit ring tilted in three-quarter perspective, accompanied by two small translucent rounded beads, suggesting connection and creative discovery. Luminous electric cobalt blue refractions, soft mint-green accents and a tiny peach/coral reflection; satin pearl-white studio background. The ring occupies the RIGHT HALF of the wide canvas, partly cropped at the right edge, the LEFT HALF has clean softly-lit negative space suitable for dark interface typography. Sophisticated photorealistic physical materials, subtle caustics, soft contact shadow, tactile frosted-glass-to-clear-glass variations, pristine editorial product lighting. Warm, playful, luminous, calm; not science fiction, not a crypto advertisement. Wide landscape composition around 2.5:1. No people, no faces, no logos, no watermark, no letters, no numbers, no UI controls, no dark background, no busy sparkles, no excess floating objects. This is an ornamental brand asset, not an infographic or simulated data.

## Verification

- Final strict Swift package run: **264 tests / 35 suites passed**, including the post-QA fixes and three production-color contrast checks.
- Added tests for source metric allowlisting, topic chips vs prose, risk classification, stable identity palette, honest monograms, and local asset decoding.
- Packaging checks now compare the archived image bytes to the project asset. These are fixture-based packaging tests, not a new notarized release.
- Native visual QA and any remaining limitations are recorded below after the walkthrough.

### Native walkthrough — September 5, 2026

Tested the actual macOS Demo app, not a web recreation. All test writes used the in-memory Demo service; no real email was sent.

- Opened a creator from Library and inspected the positioning, actual source metrics, topic chips, audience, promotion, and risk sections.
- Opened Contacts & Notes, entered a manual email and notes, switched to Overview and back, and verified both draft values were preserved. Saved locally and observed the success message and updated contact list.
- Opened a recent Match, composed an individual email, inspected the recipient-specific rendered preview, explicitly confirmed the local send, and followed **View campaign** to the matching campaign detail. The submitted creator changed to Sent and was no longer selectable as a new delivery.
- Inspected the 560pt composer: current step, readable writing/preview area, and fixed Back/Cancel/primary footer remain accessible.
- Edited a template subject, resized the main window from approximately 1150pt to 730pt and back with the sidebar visible, then typed more without refocusing. The same field retained its text and caret; the compact template selector and Save/Discard footer remained inside the content area. Discarded this temporary test draft through its confirmation dialog.
- Inspected Settings and Creator Profile in the app's Dark appearance, then restored the original System appearance. This changed only the app preference, not the Mac's global appearance or accessibility settings.

Issues caught by actual rendering and corrected in this pass:

- Oversized decorative orbits were participating in the creator cover's size calculation and clipping the avatar. Decorations now live in a background overlay; the same isolation was applied to game covers.
- Native menu styling made the game selector too dark on the ink hero and ignored the composed SwiftUI label. It now uses a simple native text menu with the explicit pearl surface applied outside the menu, rather than inside its label. Ink-panel primary actions use a fixed deep blue, rather than the lighter dark-mode text accent. Production-color contrast tests cover the main label, secondary label, and white action text (respectively 13.716:1, 5.450:1, and 6.645:1 for the defined opaque color pairs; this is not a claim of a complete application-wide accessibility audit).
- Profile sections inherited unrelated scroll offsets. Only an explicit section change now scrolls to the stable top anchor; profile refreshes and draft edits do not trigger scrolling or programmatic keyboard focus changes.
- The small page-header material showed a rectangular edge in Dark appearance. Its mask now fades on all four edges.

After rebuilding, the creator avatars/monograms were verified fully visible, and returning from the bottom of Contacts & Notes to Overview returned the viewport to its top. The final game menu was opened, Iron Chorus was selected, and Find creators produced the local ready-state task card. At approximately 730pt window width with the sidebar present, the ornament disappeared and the game selector/start action stacked without clipping. Game cover titles and rounded edges were also visually inspected. The exact bundled artwork was byte-compared with the project source. The final Demo was left open at the Creator Profile overview in the original System appearance.

### Verification limits

- Existing automated tests cover state policies, stale/offline write gates, draft preservation, and Demo loading/failure fixtures. Empty-library creation and a retryable preview failure were walked in the preceding task-centered pass; those scenarios were not re-walked visually for every new color treatment.
- Reduced-motion behavior is implemented through the existing system preference policy and guarded transforms/matched geometry. This pass did not change the Mac's accessibility setting or perform a complete VoiceOver/keyboard-only audit.
- Testing used the current host's macOS version. There has not been a separate macOS 14 device walkthrough, release performance benchmark, or real notarized-release validation in this visual pass.
