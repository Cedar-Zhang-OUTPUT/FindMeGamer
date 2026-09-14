import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite(.serialized) struct ProfileFieldCoverageTests {
  @Test func gameAndCreatorSectionsRemainCompleteAndDistinct() {
    #expect(
      GameProfileSection.allCases == [
        .overview, .gameplay, .visualStyle, .audience, .contentHooks, .risks, .gameBrief,
      ])
    #expect(
      CreatorProfileSection.allCases == [
        .overview, .performance, .content, .audienceInference, .promotionFit, .contact,
        .creatorBrief,
      ])
  }

  @Test func gamePresentationMapsAllowlistedFactsAnalysisAndBriefInServerOrder() {
    let presentation = GameProfilePresentation(profile: gameProfile())

    #expect(field("Steam App ID", in: presentation.sourceFacts)?.values == ["730"])
    #expect(field("Developers", in: presentation.sourceFacts)?.values == ["Valve", "Hidden Path"])
    #expect(field("Coming Soon", in: presentation.sourceFacts)?.values == ["No"])
    #expect(field("Recommendations", in: presentation.sourceFacts)?.values == ["42"])
    #expect(
      field("Themes", in: presentation.sections[.overview] ?? [])?.values
        == ["Competition", "Teamwork"])
    #expect(
      field("Core Gameplay Loop", in: presentation.sections[.gameplay] ?? [])?.values
        == ["Buy, coordinate, and execute."])
    #expect(
      field("Target Audience", in: presentation.sections[.audience] ?? [])?.annotation
        == "Confidence: Medium")
    #expect(
      field("Promotion Risks", in: presentation.sections[.risks] ?? [])?.values
        == ["Not available"])
    #expect(
      field("Promotion Risks", in: presentation.sections[.risks] ?? [])?.annotation
        == "Reason: No supported risk claim.")
    #expect(field("Positioning", in: presentation.briefFields)?.values == ["A tactical classic."])
    #expect(presentation.artworkURL?.absoluteString == "https://cdn.example.test/cover.jpg")
    #expect(presentation.sourceURL?.host == "store.steampowered.com")

    let visible = gameVisibleStrings(presentation)
    for poison in [
      "RANK-POISON", "SCORE-POISON", "MODEL-POISON", "PROMPT-POISON", "EVIDENCE-POISON",
      "MATCH-BRIEF-POISON", "UNKNOWN-POISON",
    ] {
      #expect(!visible.contains(where: { $0.contains(poison) }))
    }
  }

  @Test func creatorPresentationSeparatesFactsAnalysisInferenceAndBrief() {
    let presentation = CreatorProfilePresentation(profile: creatorProfile())

    #expect(field("YouTube Channel ID", in: presentation.sourceFacts)?.values == ["UC-demo"])
    #expect(field("Subscribers", in: presentation.sourceFacts)?.values == ["120000"])
    #expect(field("Average Views", in: presentation.sourceFacts)?.values == ["15000"])
    #expect(
      field("Representative Video", in: presentation.sourceFacts)?.values
        == ["Launch Review — 2026-08-01 — 25000 views — 12m 5s"])
    #expect(
      field("Recent Performance", in: presentation.sections[.performance] ?? [])?.values
        == ["Recent uploads are steady."])
    #expect(
      field("Primary Games", in: presentation.sections[.content] ?? [])?.values
        == ["Strategy", "Simulation"])
    #expect(
      field("Likely Regions", in: presentation.sections[.audienceInference] ?? [])?.values
        == ["North America", "Europe"])
    #expect(
      field("Likely Regions", in: presentation.sections[.audienceInference] ?? [])?.annotation
        == "AI Inference · Confidence: Low")
    #expect(
      field("Promotion Fit", in: presentation.sections[.promotionFit] ?? [])?.values
        == ["Strong fit for thoughtful launches."])
    #expect(field("Positioning", in: presentation.briefFields)?.values == ["Analytical creator."])
    #expect(presentation.contact?.availability == .discovered)
    #expect(presentation.contacts.map(\.email) == ["hello@creator.example"])
    #expect(presentation.staleWarning == nil)

    let visible = creatorVisibleStrings(presentation)
    for poison in [
      "RANK-POISON", "SCORE-POISON", "MODEL-POISON", "PROMPT-POISON", "EVIDENCE-POISON",
      "MATCH-BRIEF-POISON", "UNKNOWN-POISON",
    ] {
      #expect(!visible.contains(where: { $0.contains(poison) }))
    }
  }

  @Test func creatorPresentationPreservesAllContactMetadataInServerOrder() {
    let preferred = CreatorContact(
      email: "business@creator.example", availability: .manual, source: "manual",
      sourceURL: nil, validationState: "valid", purpose: "Partnerships")
    let press = CreatorContact(
      email: "press@creator.example", availability: .discovered,
      source: "public_web_research", sourceURL: "https://creator.example/contact",
      validationState: "unverified", purpose: "Press")
    let presentation = CreatorProfilePresentation(
      profile: replacingCreator(
        creatorProfile(), contact: preferred, contacts: [preferred, press]))

    #expect(presentation.contact?.email == preferred.email)
    #expect(presentation.contacts.map(\.email) == [preferred.email, press.email])
    #expect(presentation.contacts.map(\.purpose) == ["Partnerships", "Press"])
    #expect(presentation.contacts.map(\.source) == ["manual", "public_web_research"])
    #expect(presentation.contacts.map(\.validationState) == ["valid", "unverified"])
  }

  @Test func presentationLinksRequireAbsoluteHostBearingHTTPURLs() {
    #expect(ProfileLinkPolicy.validated("https://youtube.com/channel/UC-demo") != nil)
    #expect(ProfileLinkPolicy.validated("http://images.example.test/avatar.png") != nil)
    #expect(ProfileLinkPolicy.validated("file:///tmp/profile") == nil)
    #expect(ProfileLinkPolicy.validated("javascript:alert(1)") == nil)
    #expect(ProfileLinkPolicy.validated("https:///missing-host") == nil)
    #expect(ProfileLinkPolicy.validated("/relative") == nil)

    var invalidArtwork = creatorProfile()
    invalidArtwork = replacingCreator(
      invalidArtwork,
      currentFacts: invalidArtwork.currentFacts.merging(["avatar_url": .string("file:///avatar")]) {
        _, replacement in replacement
      })
    #expect(CreatorProfilePresentation(profile: invalidArtwork).artworkURL == nil)
  }

  @Test func malformedClaimStatusIsOmittedInsteadOfPresentedAsAnalysis() {
    let original = gameProfile()
    let malformed = FindMeGamerCore.GameProfile(
      id: original.id, name: original.name, steamAppID: original.steamAppID,
      canonicalURL: original.canonicalURL, favorite: original.favorite,
      currentFacts: original.currentFacts, brief: original.brief,
      sourceStatus: original.sourceStatus, lastAnalyzedAt: original.lastAnalyzedAt,
      nextAnalysisAt: original.nextAnalysisAt,
      analysis: [
        "short_summary": .object([
          "status": .string("unexpected"), "value": .string("MALFORMED-POISON"),
        ]),
        "themes": .array([.integer(99)]),
      ], modelMetadata: original.modelMetadata, promptMetadata: original.promptMetadata)

    let presentation = GameProfilePresentation(profile: malformed)
    #expect(field("Summary", in: presentation.sections[.overview] ?? []) == nil)
    #expect(field("Themes", in: presentation.sections[.overview] ?? []) == nil)
    #expect(!gameVisibleStrings(presentation).contains("MALFORMED-POISON"))
  }

  @Test func everySupportedStaleShapeSuppressesYoutubeDataAndDiscoveredContact() {
    let staleStatuses: [JSONObject] = [
      ["status": .string("STALE")],
      ["state": .string(" stale ")],
      ["freshness": .string("StAlE")],
      ["youtube": .string("stale")],
      ["youtube": .object(["status": .string("stale")])],
      ["youtube_status": .string("stale")],
      ["youtube_state": .string("stale")],
      ["youtube_freshness": .string("stale")],
      ["sources": .object(["youtube": .object(["freshness": .string("stale")])])],
    ]

    for status in staleStatuses {
      let stale = CreatorProfilePresentation(
        profile: replacingCreator(creatorProfile(), sourceStatus: status))
      #expect(stale.staleWarning == "YouTube data is stale. Re-analysis is required.")
      #expect(stale.sourceFacts.isEmpty)
      let allAnalysisIsSuppressed = stale.sections.values.reduce(true) {
        $0 && $1.isEmpty
      }
      #expect(allAnalysisIsSuppressed)
      #expect(stale.briefFields.isEmpty)
      #expect(stale.contact == nil)
      #expect(stale.contacts.isEmpty)
    }

    let manualContact = CreatorContact(
      email: "owner@company.example", availability: .manual, source: "manual",
      sourceURL: "https://company.example/contact", validationState: "valid")
    let staleManual = CreatorProfilePresentation(
      profile: replacingCreator(
        creatorProfile(), sourceStatus: ["youtube": .string("stale")], contact: manualContact))
    #expect(staleManual.contact?.email == "owner@company.example")
    #expect(staleManual.contact?.availability == .manual)
  }

  @Test func staleCreatorRetainsManualFactsAndClaimsWithoutRevivingSource() {
    var profile = replacingCreator(creatorProfile(), sourceStatus: ["youtube": .string("stale")])
    profile.manualOverrides = ["facts.description": .text("Human description")]
    profile.currentFacts["description"] = .string("Human description")
    profile.analysis["content_summary"] = .object(["status": .string("available"), "value": .string("Human analysis"), "provenance": .string("manual")])
    profile.brief["audience"] = .object(["status": .string("available"), "value": .string("Human audience"), "provenance": .string("manual")])
    let presentation = CreatorProfilePresentation(profile: profile)
    #expect(presentation.sourceFacts.flatMap(\.values) == ["Human description"])
    #expect(presentation.sourceFacts.first?.annotation == "Manual")
    let analysis = presentation.sections.values.flatMap { $0 }.flatMap(\.values)
    #expect(analysis.contains("Human analysis"))
    #expect(!analysis.contains("Measured"))
    #expect(presentation.briefFields.flatMap(\.values) == ["Human audience"])
    #expect(presentation.briefFields.first?.annotation == "Manual")
  }

  @Test func manualDraftNeverPromotesDiscoveredContactAndValidatesExactBoundaries() {
    var discovered = CreatorManualDraft(profile: creatorProfile())
    #expect(discovered.email == "")
    #expect(discovered.notes == "Existing private note")
    discovered.email = "   "
    #expect(discovered.normalizedEmail == nil)
    #expect(discovered.validationMessage == nil)

    discovered.email = " person+launch@studio.example "
    discovered.notes = "Keep exact notes"
    #expect(discovered.normalizedEmail == "person+launch@studio.example")
    #expect(discovered.validationMessage == nil)

    discovered.email = "not-an-email"
    #expect(discovered.validationMessage == "Enter a valid email address.")
    discovered.email = "person@studio.example"
    discovered.notes = String(repeating: "n", count: 20_001)
    #expect(discovered.validationMessage == "Notes must be 20,000 characters or fewer.")

    let manualContact = CreatorContact(
      email: "manual@studio.example", availability: .manual, source: "manual", sourceURL: nil,
      validationState: "valid")
    let manual = CreatorManualDraft(
      profile: replacingCreator(creatorProfile(), contact: manualContact))
    #expect(manual.email == "manual@studio.example")
    #expect(manual.notes == "Existing private note")
  }

  @MainActor
  @Test func actionStateKeepsReadsOfflineSingleFlightsAndRejectsWrongCanonicalIdentity() async {
    #expect(ProfileActionPolicy.readsEnabled(writesEnabled: false))
    #expect(!ProfileActionPolicy.canFavorite(writesEnabled: false, isInFlight: false))
    #expect(!ProfileActionPolicy.canFavorite(writesEnabled: true, isInFlight: true))
    #expect(ProfileActionPolicy.canFavorite(writesEnabled: true, isInFlight: false))
    #expect(!ProfileActionPolicy.canReanalyze(writesEnabled: false, isInFlight: false))
    #expect(
      !ProfileActionPolicy.canSaveManual(writesEnabled: true, isInFlight: true, isValid: true))

    let profile = gameProfile()
    let recorder = ProfileFavoriteRecorder()
    let gate = ProfileActionGate()
    let state = ProfileSheetState(profile: .game(profile))
    let first = Task { @MainActor in
      await state.toggleFavorite { type, id, desired in
        await recorder.record(type: type, id: id, desired: desired)
        await gate.wait()
        return .game(gameCard(id: id, favorite: desired))
      }
    }
    await gate.waitUntilEntered()
    await state.toggleFavorite { _, _, _ in
      Issue.record("A second Favorite callback must not start")
      return .game(gameCard(id: profile.id, favorite: false))
    }
    await gate.resume()
    await first.value

    #expect(await recorder.calls == [.init(type: .game, id: profile.id, desired: false)])
    #expect(state.favorite == false)
    #expect(!state.isFavoriteInFlight)

    let reanalyzeRecorder = ProfileReanalyzeRecorder()
    await state.reanalyze(idempotencyKey: "reanalyze-key-one") { type, id, key in
      await reanalyzeRecorder.record(type: type, id: id, key: key)
    }
    await state.reanalyze(idempotencyKey: "reanalyze-key-two") { type, id, key in
      await reanalyzeRecorder.record(type: type, id: id, key: key)
    }
    #expect(
      await reanalyzeRecorder.calls == [
        .init(type: .game, id: profile.id, key: "reanalyze-key-one"),
        .init(type: .game, id: profile.id, key: "reanalyze-key-two"),
      ])

    let creator = creatorProfile()
    let creatorState = ProfileSheetState(profile: .creator(creator))
    creatorState.manualDraft.email = "replacement@studio.example"
    await creatorState.saveManual { _, _, _ in
      replacingCreator(creator, id: UUID(uuidString: "FFFFFFFF-FFFF-4FFF-8FFF-FFFFFFFFFFFF")!)
    }
    #expect(creatorState.creatorOverride == nil)
    #expect(creatorState.actionMessage == "The server returned a different profile.")
  }

  @MainActor
  @Test func heldManualSavePreservesPostSubmitEditorChangesWhileApplyingCanonicalCreator() async {
    let creator = creatorProfile()
    let canonicalContact = CreatorContact(
      email: "canonical@studio.example", availability: .manual, source: "manual",
      sourceURL: nil, validationState: "valid")
    let canonical = replacingCreator(
      creator, contact: canonicalContact, manualNotes: "Canonical server note")
    let recorder = ProfileManualSaveRecorder()
    let gate = ProfileActionGate()
    let state = ProfileSheetState(profile: .creator(creator))
    state.beginManualEditing()
    state.manualDraft.email = " submitted@studio.example "
    state.manualDraft.notes = "Submitted note"

    let save = Task { @MainActor in
      await state.saveManual { id, email, notes in
        await recorder.record(id: id, email: email, notes: notes)
        await gate.wait()
        return canonical
      }
    }
    await gate.waitUntilEntered()
    state.manualDraft.email = "newer@studio.example"
    state.manualDraft.notes = "Newer unsaved note"
    await gate.resume()
    await save.value

    #expect(
      await recorder.calls == [
        .init(id: creator.id, email: "submitted@studio.example", notes: "Submitted note")
      ])
    #expect(state.creatorOverride?.contact?.email == "canonical@studio.example")
    #expect(state.creatorOverride?.manualNotes == "Canonical server note")
    #expect(state.manualDraft.email == "newer@studio.example")
    #expect(state.manualDraft.notes == "Newer unsaved note")
    #expect(state.hasUnsavedManualChanges)
    #expect(state.manualEditorMode == .editing)
    #expect(state.actionSuccessMessage == "Contact and notes saved.")
  }

  @MainActor
  @Test func unchangedManualDraftAdoptsCanonicalServerNormalization() async {
    let creator = creatorProfile()
    let canonicalContact = CreatorContact(
      email: "canonical@studio.example", availability: .manual, source: "manual",
      sourceURL: nil, validationState: "valid")
    let canonical = replacingCreator(
      creator, contact: canonicalContact, manualNotes: "Canonical server note")
    let state = ProfileSheetState(profile: .creator(creator))
    #expect(!state.hasUnsavedManualChanges)
    #expect(state.manualEditorMode == .summary)
    state.beginManualEditing()
    #expect(state.manualEditorMode == .editing)
    state.manualDraft.email = " submitted@studio.example "
    state.manualDraft.notes = "Submitted note"

    await state.saveManual { _, _, _ in canonical }

    #expect(state.creatorOverride?.contact?.email == "canonical@studio.example")
    #expect(state.creatorOverride?.manualNotes == "Canonical server note")
    #expect(state.manualDraft.email == "canonical@studio.example")
    #expect(state.manualDraft.notes == "Canonical server note")
    #expect(!state.hasUnsavedManualChanges)
    #expect(state.manualEditorMode == .summary)
    #expect(state.actionSuccessMessage == "Contact and notes saved.")
  }

  @MainActor
  @Test func failedManualSaveRetainsDraftAndDoesNotReportSuccess() async {
    let state = ProfileSheetState(profile: .creator(creatorProfile()))
    state.beginManualEditing()
    state.manualDraft.email = "draft@studio.example"
    state.manualDraft.notes = "Keep this draft while I resolve the connection."
    let draft = state.manualDraft

    await state.saveManual { _, _, _ in throw CancellationError() }

    #expect(state.manualDraft == draft)
    #expect(state.hasUnsavedManualChanges)
    #expect(state.actionMessage != nil)
    #expect(state.actionSuccessMessage == nil)
    #expect(state.manualEditorMode == .editing)
  }

  @MainActor
  @Test func discardingAFailedManualSaveClearsObsoleteErrorWithoutSaving() async {
    let state = ProfileSheetState(profile: .creator(creatorProfile()))
    let original = state.manualDraft
    state.beginManualEditing()
    state.manualDraft.notes = "A discarded draft"
    await state.saveManual { _, _, _ in throw CancellationError() }
    #expect(state.actionMessage != nil)
    state.discardManualEditing()
    #expect(state.manualEditorMode == .summary)
    #expect(state.manualDraft == original)
    #expect(state.actionMessage == nil)
    #expect(state.actionSuccessMessage == nil)
    #expect(state.creatorOverride == nil)
  }

  @MainActor
  @Test func contactSummaryOnlyReturnsAfterExplicitDiscardOrSuccessfulSave() {
    let state = ProfileSheetState(profile: .creator(creatorProfile()))
    let savedDraft = state.manualDraft
    #expect(state.manualEditorMode == .summary)
    state.beginManualEditing()
    state.manualDraft.email = "draft@studio.example"
    state.manualDraft.notes = "Unsaved notes survive section navigation."
    #expect(state.hasUnsavedManualChanges)
    // Re-entering editing (including after navigating back) must not reinitialize the draft.
    state.beginManualEditing()
    #expect(state.manualDraft.email == "draft@studio.example")
    #expect(state.manualDraft.notes == "Unsaved notes survive section navigation.")
    state.discardManualEditing()
    #expect(state.manualDraft == savedDraft)
    #expect(state.manualEditorMode == .summary)
    #expect(!state.hasUnsavedManualChanges)
  }
}

private func field(_ label: String, in fields: [ProfileDisplayField]) -> ProfileDisplayField? {
  fields.first { $0.label == label }
}

private func gameVisibleStrings(_ presentation: GameProfilePresentation) -> [String] {
  presentation.sourceFacts.flatMap(\.visibleStrings)
    + presentation.sections.values.flatMap { $0.flatMap(\.visibleStrings) }
    + presentation.briefFields.flatMap(\.visibleStrings)
}

private func creatorVisibleStrings(_ presentation: CreatorProfilePresentation) -> [String] {
  presentation.sourceFacts.flatMap(\.visibleStrings)
    + presentation.sections.values.flatMap { $0.flatMap(\.visibleStrings) }
    + presentation.briefFields.flatMap(\.visibleStrings)
}

private func available(
  value: String, confidence: String = "high", provenance: String? = nil
) -> JSONValue {
  var object: JSONObject = [
    "status": .string("available"), "value": .string(value),
    "confidence": .string(confidence), "evidence": .array([.string("EVIDENCE-POISON")]),
  ]
  if let provenance { object["provenance"] = .string(provenance) }
  return .object(object)
}

private func available(
  values: [String], confidence: String = "high", provenance: String? = nil
) -> JSONValue {
  var object: JSONObject = [
    "status": .string("available"), "values": .array(values.map(JSONValue.string)),
    "confidence": .string(confidence), "evidence": .array([.string("EVIDENCE-POISON")]),
  ]
  if let provenance { object["provenance"] = .string(provenance) }
  return .object(object)
}

private func gameProfile() -> FindMeGamerCore.GameProfile {
  FindMeGamerCore.GameProfile(
    id: UUID(uuidString: "10000000-0000-4000-8000-000000000001")!, name: "Counter-Strike",
    steamAppID: "730", canonicalURL: "https://store.steampowered.com/app/730", favorite: true,
    currentFacts: [
      "short_description": .string("Team tactical action."),
      "developers": .array([.string("Valve"), .string("Hidden Path")]),
      "publishers": .array([.string("Valve")]), "release_date": .string("2012-08-21"),
      "coming_soon": .boolean(false), "is_free": .boolean(true), "required_age": .integer(16),
      "genres": .array([.string("Action"), .string("Strategy")]),
      "categories": .array([.string("Multiplayer")]),
      "platforms": .array([.string("Windows"), .string("macOS")]),
      "supported_languages": .string("English, French"),
      "review_summary": .string("Very Positive"), "recommendation_count": .integer(42),
      "cover_image_url": .string("https://cdn.example.test/cover.jpg"),
      "header_image_url": .string("https://cdn.example.test/header.jpg"),
      "rank": .string("RANK-POISON"), "score": .string("SCORE-POISON"),
      "unknown": .string("UNKNOWN-POISON"),
    ],
    brief: [
      "positioning_premise": available(value: "A tactical classic."),
      "core_gameplay_loop": available(value: "Plan then execute."),
      "genres": available(values: ["Tactical", "Shooter"]),
      "themes": available(values: ["Competition"]), "tone": available(values: ["Tense"]),
      "visual_identity": available(value: "Readable arenas."),
      "target_audience": available(values: ["Competitive players"]),
      "key_selling_points": available(values: ["Team depth"]),
      "content_hooks": available(values: ["Clutch plays"]),
      "comparable_games": available(values: ["Valorant"]),
      "suitable_creator_types": available(values: ["FPS analysts"]),
      "promotion_risks": available(values: ["Violence"]),
      "match_brief": .string("MATCH-BRIEF-POISON"),
    ], sourceStatus: ["steam": .string("available")],
    lastAnalyzedAt: Date(timeIntervalSince1970: 1_700_000_000),
    nextAnalysisAt: Date(timeIntervalSince1970: 1_800_000_000),
    analysis: [
      "short_summary": available(value: "A precise team shooter."),
      "core_gameplay_loop": available(value: "Buy, coordinate, and execute."),
      "themes": available(values: ["Competition", "Teamwork"]),
      "tone": available(values: ["Tense"]),
      "key_selling_points": available(values: ["High skill ceiling"]),
      "visual_style": available(value: "Readable military realism."),
      "target_audience": available(values: ["Competitive players"], confidence: "medium"),
      "suitable_creator_types": available(values: ["FPS educators"]),
      "content_hooks": available(values: ["Clutch breakdowns"]),
      "comparable_games": available(values: ["Valorant"]),
      "promotion_risks": .object([
        "status": .string("unavailable"), "reason": .string("No supported risk claim."),
      ]),
      "evidence": .string("EVIDENCE-POISON"), "score": .string("SCORE-POISON"),
    ], modelMetadata: ["name": .string("MODEL-POISON")],
    promptMetadata: ["version": .string("PROMPT-POISON")])
}

private func creatorProfile() -> FindMeGamerCore.CreatorProfile {
  return FindMeGamerCore.CreatorProfile(
    id: UUID(uuidString: "20000000-0000-4000-8000-000000000002")!, name: "Demo Creator",
    youtubeChannelID: "UC-demo", canonicalURL: "https://youtube.com/channel/UC-demo",
    favorite: false,
    currentFacts: [
      "description": .string("Thoughtful reviews."), "country": .string("US"),
      "published_at": .string("2020-01-02"), "subscriber_count": .integer(120_000),
      "total_view_count": .integer(9_000_000), "public_video_count": .integer(420),
      "avatar_url": .string("https://cdn.example.test/avatar.jpg"),
      "recent_metrics": .object([
        "recent_public_video_count": .integer(12), "numeric_view_sample_count": .integer(10),
        "average_views": .integer(15_000), "median_views": .number(12_500),
        "publishing_frequency": .object([
          "uploads_per_30_days": .number(6), "sample_count": .integer(10),
          "span_days": .number(48),
        ]),
      ]),
      "representative_videos": .array([
        .object([
          "title": .string("Launch Review"), "published_at": .string("2026-08-01"),
          "view_count": .integer(25_000), "duration_seconds": .integer(725),
          "rank": .string("RANK-POISON"),
        ])
      ]),
      "unknown": .string("UNKNOWN-POISON"),
    ],
    brief: [
      "positioning": available(value: "Analytical creator."),
      "content_focus": available(values: ["Strategy", "Simulation"]),
      "formats": available(values: ["Reviews"]),
      "style_and_pacing": available(value: "Measured and detailed."),
      "audience": available(
        value: "Players seeking depth.", confidence: "medium", provenance: "ai_inference"),
      "performance_context": available(value: "Consistent reach."),
      "promotion_fit": available(value: "Strong fit for thoughtful launches."),
      "brand_safety": available(value: "Generally suitable."),
      "suitable_game_types": available(values: ["Strategy games"]),
      "collaboration_risks": available(values: ["Long lead time"]),
      "match_brief": .string("MATCH-BRIEF-POISON"),
    ], sourceStatus: ["youtube": .string("available")],
    lastAnalyzedAt: Date(timeIntervalSince1970: 1_700_000_000),
    nextAnalysisAt: Date(timeIntervalSince1970: 1_800_000_000),
    contact: CreatorContact(
      email: "hello@creator.example", availability: .discovered, source: "channel_about",
      sourceURL: "https://creator.example/contact", validationState: "valid"),
    manualNotes: "Existing private note",
    analysis: [
      "content_summary": available(value: "Detailed game analysis."),
      "primary_games": available(values: ["Strategy", "Simulation"]),
      "genres": available(values: ["Reviews"]), "formats": available(values: ["Long form"]),
      "style": available(values: ["Analytical"]), "pacing": available(value: "Measured"),
      "production_quality": available(value: "Polished"),
      "livestream_tendency": available(value: "Occasional"),
      "long_form_tendency": available(value: "Frequent"),
      "short_form_tendency": available(value: "Rare"),
      "recent_performance_summary": available(value: "Recent uploads are steady."),
      "engagement_summary": available(value: "Comments are substantive."),
      "publishing_frequency_context": available(value: "About weekly."),
      "representative_video_context": available(values: ["Reviews emphasize systems"]),
      "sponsorship_patterns": available(values: ["Clearly disclosed integrations"]),
      "brand_safety": available(values: ["Low controversy"]),
      "suitable_game_types": available(values: ["Complex strategy"]),
      "collaboration_risks": available(values: ["Needs early access"]),
      "audience_inference": .object([
        "primary_language": available(
          value: "English", confidence: "high", provenance: "ai_inference"),
        "likely_regions": available(
          values: ["North America", "Europe"], confidence: "low",
          provenance: "ai_inference"),
        "interests": available(
          values: ["Game systems", "PC hardware"], confidence: "medium",
          provenance: "ai_inference"),
      ]),
      "evidence": .string("EVIDENCE-POISON"), "rank": .string("RANK-POISON"),
    ], modelMetadata: ["name": .string("MODEL-POISON")],
    promptMetadata: ["version": .string("PROMPT-POISON")])
}

private func replacingCreator(
  _ profile: FindMeGamerCore.CreatorProfile,
  id: UUID? = nil,
  currentFacts: JSONObject? = nil,
  sourceStatus: JSONObject? = nil,
  contact: CreatorContact?? = nil,
  contacts: [CreatorContact]? = nil,
  manualNotes: String?? = nil
) -> FindMeGamerCore.CreatorProfile {
  let resolvedContact = contact ?? profile.contact
  let resolvedContacts: [CreatorContact]
  if let contacts {
    resolvedContacts = contacts
  } else if contact != nil {
    resolvedContacts = resolvedContact.map { [$0] } ?? []
  } else {
    resolvedContacts = profile.contacts
  }
  return FindMeGamerCore.CreatorProfile(
    id: id ?? profile.id, name: profile.name, youtubeChannelID: profile.youtubeChannelID,
    canonicalURL: profile.canonicalURL, favorite: profile.favorite,
    currentFacts: currentFacts ?? profile.currentFacts, brief: profile.brief,
    sourceStatus: sourceStatus ?? profile.sourceStatus, lastAnalyzedAt: profile.lastAnalyzedAt,
    nextAnalysisAt: profile.nextAnalysisAt, contact: resolvedContact,
    manualNotes: manualNotes ?? profile.manualNotes, analysis: profile.analysis,
    modelMetadata: profile.modelMetadata, promptMetadata: profile.promptMetadata,
    contacts: resolvedContacts)
}

private func gameCard(id: UUID, favorite: Bool) -> FindMeGamerCore.GameProfileCard {
  FindMeGamerCore.GameProfileCard(
    id: id, name: "Counter-Strike", steamAppID: "730",
    canonicalURL: "https://store.steampowered.com/app/730", favorite: favorite,
    currentFacts: [:], brief: [:], sourceStatus: [:], lastAnalyzedAt: nil,
    nextAnalysisAt: nil)
}

private actor ProfileFavoriteRecorder {
  struct Call: Equatable, Sendable {
    let type: ProfileType
    let id: UUID
    let desired: Bool
  }

  private(set) var calls: [Call] = []

  func record(type: ProfileType, id: UUID, desired: Bool) {
    calls.append(.init(type: type, id: id, desired: desired))
  }
}

private actor ProfileReanalyzeRecorder {
  struct Call: Equatable, Sendable {
    let type: ProfileType
    let id: UUID
    let key: String
  }

  private(set) var calls: [Call] = []

  func record(type: ProfileType, id: UUID, key: String) {
    calls.append(.init(type: type, id: id, key: key))
  }
}

private actor ProfileManualSaveRecorder {
  struct Call: Equatable, Sendable {
    let id: UUID
    let email: String?
    let notes: String
  }

  private(set) var calls: [Call] = []

  func record(id: UUID, email: String?, notes: String) {
    calls.append(.init(id: id, email: email, notes: notes))
  }
}

private actor ProfileActionGate {
  private var entered = false
  private var continuation: CheckedContinuation<Void, Never>?

  func wait() async {
    entered = true
    await withCheckedContinuation { continuation = $0 }
  }

  func waitUntilEntered() async {
    while !entered { await Task.yield() }
  }

  func resume() {
    continuation?.resume()
    continuation = nil
  }
}
