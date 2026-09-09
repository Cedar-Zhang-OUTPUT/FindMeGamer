# First-batch default selections

New Activities initialize `ActivitySelection` once, when the first Query's first batch becomes terminal. All valid discovered candidates in that batch are selected unless that account already has a selection record; existing records, including canceled ones, are untouched.

`ActivityView.initial_selection_initialized` persists this completion marker. An empty or stopped first batch consumes initialization too. Subsequent queries, appended batches, repeated workers, and renderer remounts do not add selections automatically. This is an outreach-list default, not a claim of viewing, preparation, consent or send readiness. Freezing recipients remains an explicit subset operation.

Worker result persistence and initialization share a transaction and discovery change lock. Continuation initializes expired/terminal first batches before appending; queued stop initializes immediately. Thus a late first worker cannot select appended candidates.

Migration `20260909_0021` follows `20260909_0020`. Existing Activities are marked initialized without adding or changing their selections; newly created Activities default to false. Activity brief revision is independent of this marker.

Frontend must only refresh the selections endpoint when the first batch completes or the marker changes false to true. Do not bulk-add on mount. A selections GET that ran before the worker finished needs a read-only refresh.

Verification: initial regression failed with no saved selections; final business gate passed 70 tests across selection, discovery runtime/union, preparation, recipient freeze and Activity API. New selection and migration gate passed 35 tests. Independent review identified the expired-continuation path, which was fixed with regressions; follow-up limited to that finding returned Accept. Existing AnyIO deprecation warning remains unrelated.

Not yet deployed. The frontend-owned fixture at port 56257 remains unchanged.
