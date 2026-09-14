import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite(.serialized) struct MatchPresentationTests {
  @Test func firstResultPageDoesNotBuildOffPageCreatorPresentations() {
    let creators = (1...1_200).map { candidate(id: id($0)) }
    let page = MatchResultPresentation(result: result(recommended: creators, other: []))
    #expect(page.recommended.count == 20)
    #expect(page.recommended.map(\.id) == (1...20).map(id))
    #expect(page.other.isEmpty)
  }

  @Test func pagesPreserveOrderAcrossGroupsAndClampAfterResultsShrink() {
    let recommended = (1...23).map { candidate(id: id($0)) }
    let other = (24...45).map { candidate(id: id($0), group: .other) }
    let full = result(recommended: recommended, other: other)
    let middle = MatchResultPresentation(result: full, page: 2)
    #expect(middle.recommended.map(\.id) == [id(21), id(22), id(23)])
    #expect(middle.other.map(\.id) == (24...40).map(id))
    #expect(middle.rangeLabel == "21–40 of 45 creators")
    #expect(middle.totalPages == 3)
    #expect(middle.otherGroup == .disclosure)
    let last = MatchResultPresentation(result: full, page: 3)
    #expect(last.recommended.isEmpty)
    #expect(last.other.map(\.id) == (41...45).map(id))
    #expect(last.otherGroup == .primary)
    #expect(last.rangeLabel == "41–45 of 45 creators")
    let back = MatchResultPresentation(result: full, page: 1)
    #expect(back.visibleCandidates.map(\.id) == (1...20).map(id))
    let shrunk = MatchResultPresentation(result: result(recommended: [recommended[0]], other: []), page: 3)
    #expect(shrunk.page == 1)
    #expect(shrunk.visibleCandidates.map(\.id) == [id(1)])
    let empty = MatchResultPresentation(result: result(recommended: [], other: []), page: 2)
    #expect(empty.page == 1)
    #expect(empty.visibleCandidates.isEmpty)
  }

  @Test func pageSelectionPreservesOtherPagesAndExcludesIneligibleRecipients() {
    let creators = (1...41).map {
      candidate(id: id($0), contactAvailable: $0 != 2, email: $0 == 2 ? nil : "creator\($0)@example.test")
    }
    let full = result(recommended: creators, other: [])
    var selection = MatchRecipientSelection()
    selection.select(MatchResultPresentation(result: full).visibleCandidates)
    #expect(selection.count == 19)
    selection.select(MatchResultPresentation(result: full, page: 3).visibleCandidates)
    selection.reconcile(with: full)
    #expect(selection.count == 20)
    #expect(selection.contains(id(1)))
    #expect(selection.contains(id(41)))
    #expect(!selection.contains(id(2)))
    #expect(!selection.contains(id(21)))
    #expect(selection.orderedRecipients(in: full).count == 20)
    selection.clear()
    #expect(selection.isEmpty)
  }

  @Test func productionCopyAndAccessibilityKeepExactPublicContractWithoutRankingLabels() {
    #expect(MatchCopy.heroPrefix == "Find me a creator for")
    #expect(MatchCopy.sections == ["Recommended Matches", "Other Matches"])
    #expect(MatchAccessibility.gameSelector == "match.game-selector")
    #expect(MatchAccessibility.submit == "match.submit")
    #expect(MatchAccessibility.history == "match.history")
    #expect(MatchAccessibility.result == "match.result")
    #expect(MatchAccessibility.gameProfile == "match.game-profile")
    #expect(MatchAccessibility.task(id(1)) == "match.task.00000000-0000-4000-8000-000000000001")
    #expect(
      MatchAccessibility.creator(id(2)) == "match.creator.00000000-0000-4000-8000-000000000002")
    #expect(
      MatchAccessibility.creatorSelect(id(2))
        == "match.creator-select.00000000-0000-4000-8000-000000000002")
    #expect(
      MatchAccessibility.creatorSend(id(2))
        == "match.creator-send.00000000-0000-4000-8000-000000000002")
    #expect(
      MatchAccessibility.creatorResend(id(2))
        == "match.creator-resend.00000000-0000-4000-8000-000000000002")
    #expect(MatchAccessibility.batchSend == "match.batch-send")
    #expect(MatchCopy.sendOutreach(count: 2) == "Send Outreach (2)")

    for banned in ["Score", "Rank", "#1", "Top 1"] {
      let labels = MatchCopy.productionLabels + [MatchCopy.sendOutreach(count: 2)]
      #expect(!labels.contains { $0.localizedCaseInsensitiveContains(banned) })
    }
  }

  @Test func heroShowsTheNextActionButEnablesItOnlyWhenWritableSelectedAndReady() {
    #expect(
      MatchHeroPolicy(hasSelection: false, writesEnabled: true, canSubmit: false)
        == .init(showsSubmit: true, submitEnabled: false))
    #expect(
      MatchHeroPolicy(hasSelection: true, writesEnabled: false, canSubmit: true)
        == .init(showsSubmit: true, submitEnabled: false))
    #expect(
      MatchHeroPolicy(hasSelection: true, writesEnabled: true, canSubmit: false)
        == .init(showsSubmit: true, submitEnabled: false))
    #expect(
      MatchHeroPolicy(hasSelection: true, writesEnabled: true, canSubmit: true)
        == .init(showsSubmit: true, submitEnabled: true))
  }

  @Test func gameEntryShowsOneTaskStateAndKeepsExistingGamesDuringReloadOrFailure() {
    #expect(
      MatchGameEntryState(hasGames: false, isLoading: false, hasError: false) == .empty)
    #expect(
      MatchGameEntryState(hasGames: false, isLoading: true, hasError: false) == .loading)
    #expect(
      MatchGameEntryState(hasGames: false, isLoading: true, hasError: true) == .loading)
    #expect(
      MatchGameEntryState(hasGames: false, isLoading: false, hasError: true) == .unavailable)
    for isLoading in [false, true] {
      for hasError in [false, true] {
        #expect(
          MatchGameEntryState(hasGames: true, isLoading: isLoading, hasError: hasError) == .choosing)
      }
    }
  }

  @Test func riskDisclosureKeepsTheFirstVisibleAndEveryRemainingRiskInSourceOrder() {
    let noRisks = MatchRiskDisclosurePresentation(risks: [])
    #expect(noRisks.primaryRisk == nil)
    #expect(noRisks.additionalRisks.isEmpty)

    let single = MatchRiskDisclosurePresentation(risks: ["Brand safety review required"])
    #expect(single.primaryRisk == "Brand safety review required")
    #expect(single.additionalRisks.isEmpty)

    let risks = ["Visible risk", "Risk B", "Risk A", "Risk B"]
    let disclosure = MatchRiskDisclosurePresentation(risks: risks)
    #expect(disclosure.primaryRisk == risks[0])
    #expect(disclosure.additionalRisks == Array(risks.dropFirst()))
    #expect(disclosure.disclosureLabel == "3 more risks")
    #expect(
      MatchRiskDisclosurePresentation(risks: ["Visible risk", "Risk B"]).disclosureLabel
        == "1 more risk")
  }

  @Test func evidenceSectionsExposeEveryOriginalDimensionWithoutInventingScores() {
    #expect(MatchEvidenceSection.allCases.count == 6)
    #expect(MatchEvidenceSection.summary.category == nil)
    for category in MatchEvidenceCategory.allCases {
      #expect(MatchEvidenceSection(category: category).category == category)
    }
    #expect(MatchEvidenceDisplayPolicy.additionalReasons([]).isEmpty)
    #expect(MatchEvidenceDisplayPolicy.additionalReasons(["Visible reason"]).isEmpty)
    #expect(
      MatchEvidenceDisplayPolicy.additionalReasons(["Visible reason", "Reason B", "Reason A"])
        == ["Reason B", "Reason A"])
  }

  @Test func historyMapsEveryStatusAndAllowsOnlySuccessfulNavigationAndEligibleRetry() {
    let queued = MatchHistoryPresentation(
      task: task(status: .queued), modelCanRetry: false, writesEnabled: true)
    let running = MatchHistoryPresentation(
      task: task(status: .running, stage: .ranking), modelCanRetry: false, writesEnabled: true)
    let succeeded = MatchHistoryPresentation(
      task: task(status: .succeeded, resultCount: 2), modelCanRetry: false,
      writesEnabled: true)
    let failed = MatchHistoryPresentation(
      task: task(status: .failed, retryable: true), modelCanRetry: true,
      writesEnabled: true)
    let superseded = MatchHistoryPresentation(
      task: task(status: .superseded), modelCanRetry: false, writesEnabled: true)

    #expect(queued.semantic == .progress("Queued"))
    #expect(running.semantic == .progress("Ranking"))
    #expect(succeeded.semantic == .succeeded(resultCount: 2))
    #expect(failed.semantic == .failed("Safe failure"))
    #expect(superseded.semantic == .superseded)
    #expect(!queued.canOpenResult)
    #expect(!running.canOpenResult)
    #expect(succeeded.canOpenResult)
    #expect(!failed.canOpenResult)
    #expect(!superseded.canOpenResult)
    #expect(failed.showsRetry)
    #expect(failed.canRetry)
    let offlineRetry = MatchHistoryPresentation(
      task: task(status: .failed, retryable: true), modelCanRetry: true,
      writesEnabled: false)
    #expect(offlineRetry.showsRetry)
    #expect(!offlineRetry.canRetry)
    let inFlightRetry = MatchHistoryPresentation(
      task: task(status: .failed, retryable: true), modelCanRetry: false,
      writesEnabled: true)
    #expect(inFlightRetry.showsRetry)
    #expect(!inFlightRetry.canRetry)
    #expect(
      !MatchHistoryPresentation(
        task: task(status: .failed, retryable: false), modelCanRetry: true,
        writesEnabled: true
      ).canRetry)
    #expect(
      !MatchHistoryPresentation(
        task: task(status: .failed, retryable: true), modelCanRetry: false,
        writesEnabled: true
      ).canRetry)
  }

  @Test func resultPresentationPreservesGroupsReasonsAndFiveBriefDimensionsInServerOrder() {
    let recommendedOne = candidate(
      id: id(11), name: "Recommended One", group: .recommended, label: .strong,
      reasons: ["Reason B", "Reason A"], evidenceSuffix: "R1")
    let recommendedTwo = candidate(
      id: id(12), name: "Recommended Two", group: .recommended, label: .good,
      evidenceSuffix: "R2")
    let other = candidate(
      id: id(13), name: "Other One", group: .other, label: .limited,
      evidenceSuffix: "O1")
    let presentation = MatchResultPresentation(
      result: result(recommended: [recommendedOne, recommendedTwo], other: [other]))

    #expect(presentation.recommended.map(\.id) == [id(11), id(12)])
    #expect(presentation.other.map(\.id) == [id(13)])
    #expect(presentation.recommended[0].label == "Strong Match")
    #expect(presentation.recommended[1].label == "Good Match")
    #expect(presentation.other[0].label == "Limited Match")
    #expect(presentation.recommended[0].reasons == ["Reason B", "Reason A"])
    #expect(
      presentation.recommended[0].brief.dimensions.map(\.title)
        == ["Content Fit", "Audience Fit", "Performance Fit", "Promotion Fit", "Brand Safety"])
    #expect(
      presentation.recommended[0].brief.dimensions.map(\.analysis)
        == [
          "Content R1", "Audience R1", "Performance R1", "Promotion R1", "Safety R1",
        ])
    #expect(
      presentation.recommended[0].brief.dimensions[0].evidence == ["Content E2", "Content E1"])
    #expect(presentation.recommended[0].brief.strengths == ["Strength 2", "Strength 1"])
    #expect(presentation.recommended[0].brief.risks == ["Risk 2", "Risk 1"])
    #expect(presentation.recommended[0].brief.evidence == ["Evidence 2", "Evidence 1"])
    #expect(presentation.recommended[0].brief.matchReasons == ["Brief reason 2", "Brief reason 1"])
  }

  @Test func otherOnlyResultsAreVisibleWithoutAnEmptyRecommendedGroupOrDisclosurePreference() {
    let recommended = candidate(id: id(11), group: .recommended, label: .strong)
    let other = candidate(id: id(12), group: .other, label: .limited)
    let otherOnly = MatchResultPresentation(result: result(recommended: [], other: [other]))
    #expect(!otherOnly.showsRecommended)
    #expect(otherOnly.otherGroup == .primary)
    #expect(otherOnly.other.map(\.id) == [other.id])
    #expect(otherOnly.other[0].label == "Limited Match")

    let mixed = MatchResultPresentation(
      result: result(recommended: [recommended], other: [other]))
    #expect(mixed.showsRecommended)
    #expect(mixed.otherGroup == .disclosure)

    let recommendedOnly = MatchResultPresentation(
      result: result(recommended: [recommended], other: []))
    #expect(recommendedOnly.showsRecommended)
    #expect(recommendedOnly.otherGroup == .hidden)

    let empty = MatchResultPresentation(result: result(recommended: [], other: []))
    #expect(!empty.showsRecommended)
    #expect(empty.otherGroup == .hidden)
  }

  @Test func outreachPolicySeparatesNewSendFromExplicitResend() {
    let unsent = candidate(id: id(21), contactAvailable: true, email: " creator@example.test ")
    #expect(MatchOutreachActionPolicy.isEligibleForNewSend(unsent))
    #expect(MatchOutreachActionPolicy.canSendNew(unsent, writesEnabled: true))
    #expect(!MatchOutreachActionPolicy.canSendNew(unsent, writesEnabled: false))

    #expect(!MatchOutreachActionPolicy.isEligibleForNewSend(candidate(id: id(22))))
    #expect(
      !MatchOutreachActionPolicy.isEligibleForNewSend(
        candidate(
          id: id(220), contactAvailable: true, email: "legacy@example.test", contacts: [])))
    #expect(
      !MatchOutreachActionPolicy.isEligibleForNewSend(
        candidate(id: id(23), contactAvailable: true, email: "   ")))
    for state in [SendState.queued, .sending, .sent, .failed, .superseded] {
      #expect(
        !MatchOutreachActionPolicy.isEligibleForNewSend(
          candidate(
            id: id(24), contactAvailable: true, email: "creator@example.test",
            sendState: state)))
    }
    for response in [ResponseState.accepted, .declined] {
      #expect(
        !MatchOutreachActionPolicy.isEligibleForNewSend(
          candidate(
            id: id(25), contactAvailable: true, email: "creator@example.test",
            responseState: response)))
    }

    let deliveryID = id(90)
    for state in [SendState.sent, .failed] {
      for response in [ResponseState?.none, .some(.noResponse), .some(.pending)] {
        let resend = candidate(
          id: id(26), contactAvailable: true, email: "creator@example.test",
          deliveryID: deliveryID, sendState: state, responseState: response)
        #expect(MatchOutreachActionPolicy.resendDeliveryID(resend) == deliveryID)
        #expect(MatchOutreachActionPolicy.canResend(resend, writesEnabled: true))
        #expect(!MatchOutreachActionPolicy.canResend(resend, writesEnabled: false))
      }
    }
    for state in [SendState.notSent, .queued, .sending, .superseded] {
      #expect(
        MatchOutreachActionPolicy.resendDeliveryID(
          candidate(id: id(27), deliveryID: deliveryID, sendState: state)) == nil)
    }
    #expect(
      MatchOutreachActionPolicy.resendDeliveryID(
        candidate(id: id(28), deliveryID: nil, sendState: .failed)) == nil)
    #expect(
      MatchOutreachActionPolicy.resendDeliveryID(
        candidate(
          id: id(29), deliveryID: deliveryID, sendState: .sent,
          responseState: .accepted)) == nil)
    #expect(
      MatchOutreachActionPolicy.resendDeliveryID(
        candidate(
          id: id(30), deliveryID: deliveryID, sendState: .failed,
          responseState: .declined)) == nil)
  }

  @Test func localSelectionRejectsIneligiblePrunesChangedResultAndEmitsServerDisplayOrder() {
    let recommended = candidate(
      id: id(31), name: "Recommended", group: .recommended, contactAvailable: true,
      email: "recommended@example.test")
    let unavailable = candidate(
      id: id(32), name: "Unavailable", group: .recommended, contactAvailable: false)
    let other = candidate(
      id: id(33), name: "Other", group: .other, contactAvailable: true,
      email: "other@example.test")
    let initial = result(recommended: [recommended, unavailable], other: [other])
    var selection = MatchRecipientSelection()

    selection.toggle(other)
    selection.toggle(unavailable)
    selection.toggle(recommended)
    #expect(selection.contains(id(31)))
    #expect(!selection.contains(id(32)))
    #expect(selection.contains(id(33)))
    #expect(selection.orderedIDs(in: initial) == [id(31), id(33)])

    let nowContacted = candidate(
      id: id(31), name: "Recommended", group: .recommended, contactAvailable: true,
      email: "recommended@example.test", deliveryID: id(91), sendState: .sent)
    let refreshed = result(recommended: [nowContacted, unavailable], other: [other])
    selection.reconcile(with: refreshed)
    #expect(!selection.contains(id(31)))
    #expect(selection.contains(id(33)))
    #expect(selection.orderedIDs(in: refreshed) == [id(33)])
    selection.clear()
    #expect(selection.isEmpty)
    #expect(selection.storedIDs.isEmpty)
    #expect(selection.orderedRecipients(in: refreshed).isEmpty)
  }

  @Test func selectedOutreachRecipientsPreserveCreatorAndContactOrderWithoutDefaultingAnEmail() {
    let firstContacts = [
      MatchCreatorContact(
        email: "business@example.test", source: "channel_about", sourceURL: nil,
        validationState: "valid", purpose: "Sponsorships"),
      MatchCreatorContact(
        email: "press@example.test", source: "public_web_research",
        sourceURL: "https://creator.example/contact", validationState: "unverified",
        purpose: "Press"),
    ]
    let first = candidate(
      id: id(34), name: "First", contactAvailable: true,
      email: firstContacts[0].email, contacts: firstContacts)
    let second = candidate(
      id: id(35), name: "Second", group: .other, contactAvailable: true,
      email: "second@example.test")
    let current = result(recommended: [first], other: [second])
    var selection = MatchRecipientSelection()

    selection.toggle(second)
    selection.toggle(first)
    let recipients = selection.orderedRecipients(in: current)

    #expect(recipients.map(\.creatorID) == [id(34), id(35)])
    #expect(recipients[0].creatorName == "First")
    #expect(
      recipients[0].contacts.map(\.email) == [
        "business@example.test", "press@example.test",
      ])
    #expect(recipients[0].contacts.map(\.purpose) == ["Sponsorships", "Press"])
    #expect(recipients[0].contacts.map(\.source) == ["channel_about", "public_web_research"])
    #expect(recipients[0].contacts.map(\.sourceURL) == [nil, "https://creator.example/contact"])
    #expect(recipients[0].contacts.map(\.validationState) == ["valid", "unverified"])
  }

  @MainActor
  @Test func realViewsAcceptTaskElevenModelAndExactRoutingClosures() {
    let service = OpenAPIService(
      baseURL: URL(string: "https://example.test")!, keyProvider: { nil })
    let model = MatchModel(api: service)
    let matchID = id(41)
    let view = MatchView(
      model: model,
      onOpenProfile: { (_: ProfileType, _: UUID) in },
      onComposeOutreach: { (_: UUID, _: [OutreachRecipientContext]) in },
      onResendDelivery: { (_: UUID) in })
    let resultView = MatchResultView(
      matchID: matchID, model: model, writesEnabled: true,
      onOpenProfile: { (_: ProfileType, _: UUID) in },
      onComposeOutreach: { (_: UUID, _: [OutreachRecipientContext]) in },
      onResendDelivery: { (_: UUID) in })

    _ = view
    _ = resultView
    #expect(MatchRoute.result(matchID) == .result(matchID))
  }
}

private func id(_ suffix: Int) -> UUID {
  UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", suffix))!
}

private func task(
  status: JobStatus,
  stage: MatchStage = .screening,
  resultCount: Int = 0,
  retryable: Bool = false
) -> MatchTask {
  MatchTask(
    id: id(1), game: gameHeader(), status: status, stage: stage, completedUnits: 1,
    totalUnits: 3, resultCount: resultCount, retryable: retryable,
    failure: status == .failed ? JobFailure(code: "match_failed", message: "Safe failure") : nil,
    correlationID: nil, supersedesID: nil, createdAt: Date(timeIntervalSince1970: 100),
    updatedAt: Date(timeIntervalSince1970: 101), startedAt: nil, completedAt: nil)
}

private func gameHeader() -> MatchGameHeader {
  MatchGameHeader(
    id: id(40), name: "Demo Game", steamAppID: "730",
    canonicalURL: "https://store.steampowered.com/app/730",
    coverURL: "https://cdn.example.test/game.jpg")
}

private func candidate(
  id: UUID,
  name: String = "Creator",
  group: MatchGroup = .recommended,
  label: MatchLabel = .good,
  reasons: [String] = ["Reason"],
  evidenceSuffix: String = "X",
  contactAvailable: Bool = false,
  email: String? = nil,
  contacts: [MatchCreatorContact]? = nil,
  deliveryID: UUID? = nil,
  sendState: SendState? = nil,
  responseState: ResponseState? = nil
) -> MatchCandidate {
  MatchCandidate(
    creator: MatchCreatorCard(
      id: id, name: name, youtubeChannelID: "UC-demo",
      canonicalURL: "https://youtube.com/channel/UC-demo", favorite: false,
      contactAvailable: contactAvailable,
      contact: email.map {
        MatchCreatorContact(
          email: $0, source: "channel_about", sourceURL: "https://example.test/contact",
          validationState: "valid")
      }, avatarURL: "https://cdn.example.test/avatar.jpg",
      performanceSummary: "Steady recent performance", subscriberCount: 12_000,
      recentAverageViews: 3_500, recentMedianViews: 3_000, contacts: contacts),
    group: group, label: label,
    dimensionOutcomes: MatchDimensionOutcomes(
      contentFit: "Aligned", audienceFit: "Aligned", performanceFit: "Promising",
      promotionFit: "Suitable", brandSafety: "Suitable"),
    reasons: reasons,
    brief: MatchBrief(
      contentFit: .init(
        analysis: "Content \(evidenceSuffix)", evidence: ["Content E2", "Content E1"]),
      audienceFit: .init(analysis: "Audience \(evidenceSuffix)", evidence: ["Audience E"]),
      performanceFit: .init(
        analysis: "Performance \(evidenceSuffix)", evidence: ["Performance E"]),
      promotionFit: .init(
        analysis: "Promotion \(evidenceSuffix)", evidence: ["Promotion E"]),
      brandSafety: .init(analysis: "Safety \(evidenceSuffix)", evidence: ["Safety E"]),
      strengths: ["Strength 2", "Strength 1"], risks: ["Risk 2", "Risk 1"],
      evidence: ["Evidence 2", "Evidence 1"],
      matchReasons: ["Brief reason 2", "Brief reason 1"]),
    outreach: MatchOutreach(
      deliveryID: deliveryID, sendState: sendState, responseState: responseState))
}

private func result(
  recommended: [MatchCandidate],
  other: [MatchCandidate]
) -> MatchResult {
  MatchResult(
    id: id(41), game: gameHeader(), status: .succeeded, stage: .ranking,
    completedUnits: 3, totalUnits: 3, resultCount: recommended.count + other.count,
    retryable: false, failure: nil, correlationID: nil, supersedesID: nil,
    createdAt: Date(timeIntervalSince1970: 100), updatedAt: Date(timeIntervalSince1970: 101),
    startedAt: Date(timeIntervalSince1970: 100), completedAt: Date(timeIntervalSince1970: 101),
    state: .available, recommendedMatches: recommended, otherMatches: other)
}
