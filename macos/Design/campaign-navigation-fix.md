# Campaign detail navigation hardening

## Report and evidence

The user reported that clicking a Campaign list row opened an empty view with a warning symbol. The exact intermittent state was not reproduced during this investigation; both existing Demo campaigns were readable before the change. No campaign data was found missing.

The application's system log did contain `Update NavigationRequestObserver tried to update multiple times per frame.` This suggests a navigation lifecycle problem, but does not prove the complete cause of the reported warning. The CampaignDetailView's own error state contains a title, description, and retry action, unlike a bare SwiftUI unresolved-destination symbol.

## Change

- Replace Outreach's type-erased `NavigationPath` and pending/mount/task path-replacement logic with a single concrete optional `OutreachCampaignDestination` in the existing long-lived `WorkspaceNavigationState`.
- Use macOS 14's `navigationDestination(item:)` on the NavigationStack's direct, non-lazy root content.
- List clicks and Match's View campaign action use the same exact-ID selection method. Re-selecting an already selected ID does not rewrite navigation state.
- Keep native Back and the existing Campaign detail loading/retry behavior. Do not change API data, sending behavior, template drafts, appearance preferences, or other workspaces' navigation paths.
- Follow-up log inspection after the item-binding change still observed one NavigationRequestObserver warning during a cross-workspace jump. The root switch previously applied an animated removal transition to entire NavigationStacks, deliberately keeping outgoing and incoming stacks alive together in one split-view detail column. Change that container transition to identity, and apply the short entrance effect only to the incoming page content inside its stack. Native navigation bars and push/pop animations are not globally disabled.

## Verification

- `swift test --package-path macos -Xswiftc -warnings-as-errors`: **267 tests in 36 suites passed**.
- Three additional Core tests cover exact-ID selection/replacement, clearing and reopening the same selection, and not rewriting other workspace histories. These are state tests, not a substitute for native UI navigation testing.
- Rebuilt and restarted the local Demo.
- Native walkthrough: Campaign list → Neon Harbor detail with 3 deliveries; native Back → same list → same detail; double-click a list row; leave for Library → return to Outreach list → open detail again. All displayed the expected content without a warning placeholder.
- Native cross-workspace walkthrough: leave Neon Harbor; open the Mossbound match; compose and confirm one **local Demo** delivery to Cozy Circuit; View campaign → Mossbound detail with the correct 1-recipient result. No real email was sent.
- Repeated the list/open/leave/return, local Mossbound send/View campaign, native Back, and double-click Neon Harbor paths after the navigation-container transition change. Content remained correct. The final app is open on the Neon Harbor detail.
- Log limitation: the final process (60297) still emitted one `NavigationRequestObserver` multiple-updates warning at 20:02:54 during the cross-workspace jump, even though the destination rendered correctly. The container transition change removes intentional stack overlap but is not evidence that all SwiftUI navigation lifecycle warnings are eliminated.
- Sidebar switching currently returns to the Outreach list rather than restoring the open detail, as observed before this patch as well. Persistent detail restoration across sidebar switches is not claimed.

The original intermittent failure remains unconfirmed as a fully eliminated root cause. This patch removes the indirect path-replacement mechanism and passes the reported entry path and adjacent regression paths; a future occurrence should be captured in its failing state for further diagnosis.
