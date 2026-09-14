import FindMeGamerCore
import Foundation
import Observation

enum GameProfileSection: CaseIterable, Hashable, Sendable {
  case overview
  case gameplay
  case visualStyle
  case audience
  case contentHooks
  case risks
  case gameBrief

  var title: String {
    switch self {
    case .overview: "Overview"
    case .gameplay: "Gameplay"
    case .visualStyle: "Visual Style"
    case .audience: "Audience"
    case .contentHooks: "Content Hooks"
    case .risks: "Risks"
    case .gameBrief: "Game Brief"
    }
  }
}

enum CreatorProfileSection: CaseIterable, Hashable, Sendable {
  case overview
  case performance
  case content
  case audienceInference
  case promotionFit
  case contact
  case creatorBrief

  var title: String {
    switch self {
    case .overview: "Overview"
    case .performance: "Performance"
    case .content: "Content"
    case .audienceInference: "Audience Inference"
    case .promotionFit: "Promotion Fit"
    case .contact: "Contact"
    case .creatorBrief: "Creator Brief"
    }
  }
}

struct ProfileDisplayField: Equatable, Sendable {
  let label: String
  let values: [String]
  let annotation: String?

  var visibleStrings: [String] {
    [label] + values + [annotation].compactMap { $0 }
  }
}

enum ProfileLinkPolicy {
  static func validated(_ rawValue: String?) -> URL? {
    guard let rawValue,
      let url = URL(string: rawValue),
      let scheme = url.scheme?.lowercased(),
      scheme == "http" || scheme == "https",
      url.host != nil
    else {
      return nil
    }
    return url
  }
}

struct GameProfilePresentation: Equatable {
  let name: String
  let sourceURL: URL?
  let artworkURL: URL?
  let sourceFacts: [ProfileDisplayField]
  let sections: [GameProfileSection: [ProfileDisplayField]]
  let briefFields: [ProfileDisplayField]

  init(profile original: FindMeGamerCore.GameProfile) {
    var profile = original
    profile.currentFacts = ProfileManualPresentation.annotatedFacts(
      profile.currentFacts, overrides: profile.manualOverrides)
    name = profile.name
    sourceURL = ProfileLinkPolicy.validated(profile.canonicalURL)
    artworkURL =
      ProfileJSON.webURL(profile.currentFacts["cover_image_url"])
      ?? ProfileJSON.webURL(profile.currentFacts["header_image_url"])

    sourceFacts =
      [ProfileDisplayField(label: "Steam App ID", values: [profile.steamAppID], annotation: nil)]
      + ProfileFieldBuilder.fields(
        from: profile.currentFacts,
        specs: [
          ("Short Description", "short_description"),
          ("Developers", "developers"),
          ("Publishers", "publishers"),
          ("Release Date", "release_date"),
          ("Coming Soon", "coming_soon"),
          ("Free to Play", "is_free"),
          ("Required Age", "required_age"),
          ("Genres", "genres"),
          ("Categories", "categories"),
          ("Platforms", "platforms"),
          ("Supported Languages", "supported_languages"),
          ("Review Summary", "review_summary"),
          ("Recommendations", "recommendation_count"),
        ])

    sections = [
      .overview: ProfileFieldBuilder.fields(
        from: profile.analysis,
        specs: [
          ("Summary", "short_summary"), ("Themes", "themes"), ("Tone", "tone"),
          ("Key Selling Points", "key_selling_points"),
        ]),
      .gameplay: ProfileFieldBuilder.fields(
        from: profile.analysis,
        specs: [
          ("Core Gameplay Loop", "core_gameplay_loop"),
          ("Comparable Games", "comparable_games"),
        ]),
      .visualStyle: ProfileFieldBuilder.fields(
        from: profile.analysis, specs: [("Visual Style", "visual_style")]),
      .audience: ProfileFieldBuilder.fields(
        from: profile.analysis,
        specs: [
          ("Target Audience", "target_audience"),
          ("Suitable Creator Types", "suitable_creator_types"),
        ]),
      .contentHooks: ProfileFieldBuilder.fields(
        from: profile.analysis, specs: [("Content Hooks", "content_hooks")]),
      .risks: ProfileFieldBuilder.fields(
        from: profile.analysis, specs: [("Promotion Risks", "promotion_risks")]),
      .gameBrief: [],
    ]
    briefFields = ProfileFieldBuilder.fields(
      from: profile.brief,
      specs: [
        ("Positioning", "positioning_premise"),
        ("Core Gameplay Loop", "core_gameplay_loop"),
        ("Genres", "genres"),
        ("Themes", "themes"),
        ("Tone", "tone"),
        ("Visual Identity", "visual_identity"),
        ("Target Audience", "target_audience"),
        ("Key Selling Points", "key_selling_points"),
        ("Content Hooks", "content_hooks"),
        ("Comparable Games", "comparable_games"),
        ("Suitable Creator Types", "suitable_creator_types"),
        ("Promotion Risks", "promotion_risks"),
      ])
  }
}

struct CreatorContactPresentation: Equatable, Sendable {
  let email: String
  let purpose: String?
  let availability: ContactAvailability
  let validationState: String
  let source: String
  let sourceURL: URL?
}

struct CreatorProfilePresentation: Equatable {
  static let staleCopy = "YouTube data is stale. Re-analysis is required."
  let platformTitle: String

  let name: String
  let sourceURL: URL?
  let artworkURL: URL?
  let sourceFacts: [ProfileDisplayField]
  let sections: [CreatorProfileSection: [ProfileDisplayField]]
  let briefFields: [ProfileDisplayField]
  let contact: CreatorContactPresentation?
  let contacts: [CreatorContactPresentation]
  let staleWarning: String?

  init(profile original: FindMeGamerCore.CreatorProfile) {
    var profile = original
    platformTitle = CreatorPlatform.isX(url: profile.canonicalURL) ? "X" : "YouTube"
    profile.currentFacts = ProfileManualPresentation.annotatedFacts(
      profile.currentFacts, overrides: profile.manualOverrides)
    name = profile.name
    sourceURL = ProfileLinkPolicy.validated(profile.canonicalURL)
    let isStale = CreatorStalePolicy.isStale(profile.sourceStatus)
    staleWarning =
      isStale
      ? (platformTitle == "X" ? "X data is stale. Re-analysis is required." : Self.staleCopy) : nil

    if isStale {
      artworkURL = nil
      profile.currentFacts = ProfileManualPresentation.onlyManual(profile.currentFacts)
      profile.analysis = ProfileManualPresentation.onlyManual(profile.analysis)
      profile.brief = ProfileManualPresentation.onlyManual(profile.brief)
      sourceFacts = Self.makeSourceFacts(profile: profile).filter { $0.annotation == "Manual" }
      sections = Self.makeSections(profile: profile)
      briefFields = Self.makeBriefFields(profile.brief)
    } else {
      artworkURL = ProfileJSON.webURL(profile.currentFacts["avatar_url"])
      sourceFacts = Self.makeSourceFacts(profile: profile)
      sections = Self.makeSections(profile: profile)
      briefFields = Self.makeBriefFields(profile.brief)
    }

    let visibleContacts =
      isStale
      ? profile.contacts.filter { $0.availability == .manual }
      : profile.contacts
    contacts = visibleContacts.map {
      CreatorContactPresentation(
        email: $0.email,
        purpose: $0.purpose,
        availability: $0.availability,
        validationState: $0.validationState,
        source: $0.source,
        sourceURL: ProfileLinkPolicy.validated($0.sourceURL))
    }
    contact = contacts.first
  }

  private static func makeSourceFacts(profile: FindMeGamerCore.CreatorProfile)
    -> [ProfileDisplayField]
  {
    if CreatorPlatform.isX(url: profile.canonicalURL) {
      return [
        ProfileDisplayField(
          label: "Platform Account ID", values: [profile.platformAccountID], annotation: nil)
      ]
        + ProfileFieldBuilder.fields(
          from: profile.currentFacts,
          specs: [
            ("Description", "description"), ("Username", "username"),
            ("Followers", "follower_count"), ("Posts", "post_count"),
          ])
    }
    var fields = [
      ProfileDisplayField(
        label: profile.youtubeChannelID == nil ? "Platform Account ID" : "YouTube Channel ID",
        values: [profile.platformAccountID], annotation: nil)
    ]
    fields += ProfileFieldBuilder.fields(
      from: profile.currentFacts,
      specs: [
        ("Description", "description"),
        ("Country", "country"),
        ("Published Date", "published_at"),
        ("Subscribers", "subscriber_count"),
        ("Total Views", "total_view_count"),
        ("Public Videos", "public_video_count"),
      ])

    if case .object(let metrics) = profile.currentFacts["recent_metrics"] {
      fields += ProfileFieldBuilder.fields(
        from: metrics,
        specs: [
          ("Recent Public Videos", "recent_public_video_count"),
          ("Videos With View Counts", "numeric_view_sample_count"),
          ("Average Views", "average_views"),
          ("Median Views", "median_views"),
          ("Newest Video", "newest_published_at"),
          ("Oldest Video", "oldest_published_at"),
        ])
      if case .object(let frequency) = metrics["publishing_frequency"] {
        fields += ProfileFieldBuilder.fields(
          from: frequency,
          specs: [
            ("Uploads per 30 Days", "uploads_per_30_days"),
            ("Publishing Sample", "sample_count"),
            ("Publishing Span (Days)", "span_days"),
          ])
      }
    }

    if let videos = representativeVideos(profile.currentFacts["representative_videos"]),
      !videos.isEmpty
    {
      fields.append(
        ProfileDisplayField(label: "Representative Video", values: videos, annotation: nil))
    }
    return fields
  }

  private static func makeSections(profile: FindMeGamerCore.CreatorProfile)
    -> [CreatorProfileSection: [ProfileDisplayField]]
  {
    var sections: [CreatorProfileSection: [ProfileDisplayField]] = [
      .overview: ProfileFieldBuilder.fields(
        from: profile.analysis, specs: [("Summary", "content_summary")]),
      .performance: ProfileFieldBuilder.fields(
        from: profile.analysis,
        specs: [
          ("Recent Performance", "recent_performance_summary"),
          ("Engagement", "engagement_summary"),
          ("Publishing Frequency", "publishing_frequency_context"),
        ]),
      .content: ProfileFieldBuilder.fields(
        from: profile.analysis,
        specs: [
          ("Primary Games", "primary_games"),
          ("Genres", "genres"),
          ("Formats", "formats"),
          ("Style", "style"),
          ("Pacing", "pacing"),
          ("Production Quality", "production_quality"),
          ("Livestream Tendency", "livestream_tendency"),
          ("Long-form Tendency", "long_form_tendency"),
          ("Short-form Tendency", "short_form_tendency"),
          ("Representative Context", "representative_video_context"),
          ("Sponsorship Patterns", "sponsorship_patterns"),
          ("Brand Safety", "brand_safety"),
          ("Suitable Game Types", "suitable_game_types"),
          ("Collaboration Risks", "collaboration_risks"),
        ]),
      .audienceInference: [],
      .promotionFit: ProfileFieldBuilder.fields(
        from: profile.brief,
        specs: [
          ("Promotion Fit", "promotion_fit"),
          ("Suitable Game Types", "suitable_game_types"),
          ("Brand Safety", "brand_safety"),
          ("Collaboration Risks", "collaboration_risks"),
        ]),
      .contact: [],
      .creatorBrief: [],
    ]
    if case .object(let inference) = profile.analysis["audience_inference"] {
      sections[.audienceInference] = ProfileFieldBuilder.fields(
        from: inference,
        specs: [
          ("Primary Language", "primary_language"),
          ("Likely Regions", "likely_regions"),
          ("Interests", "interests"),
        ], inference: true)
    }
    return sections
  }

  private static func makeBriefFields(_ brief: JSONObject) -> [ProfileDisplayField] {
    ProfileFieldBuilder.fields(
      from: brief,
      specs: [
        ("Positioning", "positioning"),
        ("Content Focus", "content_focus"),
        ("Formats", "formats"),
        ("Style and Pacing", "style_and_pacing"),
        ("Audience", "audience"),
        ("Performance Context", "performance_context"),
        ("Promotion Fit", "promotion_fit"),
        ("Brand Safety", "brand_safety"),
        ("Suitable Game Types", "suitable_game_types"),
        ("Collaboration Risks", "collaboration_risks"),
      ])
  }

  private static func representativeVideos(_ value: JSONValue?) -> [String]? {
    guard case .array(let values) = value else { return nil }
    return values.compactMap { value in
      guard case .object(let video) = value,
        let title = ProfileJSON.text(video["title"])
      else {
        return nil
      }
      var parts = [title]
      if let published = ProfileJSON.text(video["published_at"]) { parts.append(published) }
      if let views = ProfileJSON.scalar(video["view_count"]) { parts.append("\(views) views") }
      if let duration = ProfileJSON.nonnegativeInteger(video["duration_seconds"]) {
        parts.append(ProfileJSON.duration(duration))
      }
      return parts.joined(separator: " — ")
    }
  }
}

enum CreatorStalePolicy {
  static func isStale(_ sourceStatus: JSONObject) -> Bool {
    for key in [
      "status", "state", "freshness", "youtube_status", "youtube_state", "youtube_freshness",
    ] {
      if statusIsStale(sourceStatus[key]) { return true }
    }
    if statusIsStale(sourceStatus["youtube"]) { return true }
    if case .object(let sources) = sourceStatus["sources"], statusIsStale(sources["youtube"]) {
      return true
    }
    return false
  }

  private static func statusIsStale(_ value: JSONValue?) -> Bool {
    switch value {
    case .string(let status):
      return status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "stale"
    case .object(let object):
      return ["status", "state", "freshness"].contains { statusIsStale(object[$0]) }
    default:
      return false
    }
  }
}

struct CreatorManualDraft: Equatable, Sendable {
  var email: String
  var notes: String

  init(profile: FindMeGamerCore.CreatorProfile) {
    email = profile.contact?.availability == .manual ? profile.contact?.email ?? "" : ""
    notes = profile.manualNotes ?? ""
  }

  var normalizedEmail: String? {
    let value = email.trimmingCharacters(in: .whitespacesAndNewlines)
    return value.isEmpty ? nil : value
  }

  var validationMessage: String? {
    if let normalizedEmail, !Self.isPracticalEmail(normalizedEmail) {
      return "Enter a valid email address."
    }
    if notes.count > 20_000 {
      return "Notes must be 20,000 characters or fewer."
    }
    return nil
  }

  private static func isPracticalEmail(_ email: String) -> Bool {
    guard !email.contains(where: \Character.isWhitespace) else { return false }
    let parts = email.split(separator: "@", omittingEmptySubsequences: false)
    guard parts.count == 2, !parts[0].isEmpty, !parts[1].isEmpty else { return false }
    let domainParts = parts[1].split(separator: ".", omittingEmptySubsequences: false)
    return domainParts.count >= 2 && domainParts.allSatisfy { !$0.isEmpty }
  }
}

enum ProfileActionPolicy {
  static func readsEnabled(writesEnabled _: Bool) -> Bool { true }

  static func canFavorite(writesEnabled: Bool, isInFlight: Bool) -> Bool {
    writesEnabled && !isInFlight
  }

  static func canReanalyze(writesEnabled: Bool, isInFlight: Bool) -> Bool {
    writesEnabled && !isInFlight
  }

  static func canSaveManual(writesEnabled: Bool, isInFlight: Bool, isValid: Bool) -> Bool {
    writesEnabled && !isInFlight && isValid
  }
}

typealias ProfileFavoriteAction =
  @MainActor (ProfileType, UUID, Bool) async throws -> ProfileCard
typealias ProfileReanalyzeAction =
  @MainActor (ProfileType, UUID, String) async throws -> Void
typealias ProfileSaveManualAction =
  @MainActor (UUID, String?, String) async throws -> FindMeGamerCore.CreatorProfile

enum ProfileManualEditorMode: Equatable {
  case summary, editing
}

@MainActor
@Observable
final class ProfileSheetState {
  private(set) var profile: Profile
  private(set) var favorite: Bool
  private(set) var creatorOverride: FindMeGamerCore.CreatorProfile?
  var manualDraft: CreatorManualDraft
  private(set) var manualEditorMode: ProfileManualEditorMode = .summary
  private(set) var isFavoriteInFlight = false
  private(set) var isReanalyzeInFlight = false
  private(set) var isManualSaveInFlight = false
  private(set) var actionMessage: String?
  private(set) var actionSuccessMessage: String?
  @ObservationIgnored private var editedProfileRefreshGeneration: UInt64 = 0

  init(profile: Profile) {
    self.profile = profile
    switch profile {
    case .game(let game):
      favorite = game.favorite
      manualDraft = CreatorManualDraft.empty
    case .creator(let creator):
      favorite = creator.favorite
      manualDraft = CreatorManualDraft(profile: creator)
    }
  }

  var currentProfile: Profile {
    if let creatorOverride { return .creator(creatorOverride) }
    return profile
  }

  func beginEditedProfileRefresh() -> UInt64 {
    editedProfileRefreshGeneration &+= 1
    return editedProfileRefreshGeneration
  }

  func isCurrentEditedProfileRefresh(_ generation: UInt64) -> Bool {
    generation == editedProfileRefreshGeneration
  }

  func replaceEditedProfile(_ value: Profile, generation: UInt64) {
    guard isCurrentEditedProfileRefresh(generation), !isManualSaveInFlight,
      value.id == profile.id
    else { return }
    let preserveDraft = hasUnsavedManualChanges
    profile = value
    creatorOverride = nil
    if !preserveDraft, case .creator(let creator) = value {
      manualDraft = CreatorManualDraft(profile: creator)
    }
  }

  var hasUnsavedManualChanges: Bool {
    guard let creator = currentCreator else { return false }
    return manualDraft != CreatorManualDraft(profile: creator)
  }

  func beginManualEditing() {
    guard currentCreator != nil else { return }
    actionMessage = nil
    actionSuccessMessage = nil
    manualEditorMode = .editing
  }

  /// Called only by the explicit Cancel/Discard action, never by tab or data updates.
  func discardManualEditing() {
    guard !isManualSaveInFlight, let creator = currentCreator else { return }
    manualDraft = CreatorManualDraft(profile: creator)
    actionMessage = nil
    actionSuccessMessage = nil
    manualEditorMode = .summary
  }

  func toggleFavorite(using action: ProfileFavoriteAction) async {
    guard !isFavoriteInFlight else { return }
    isFavoriteInFlight = true
    actionMessage = nil
    actionSuccessMessage = nil
    let identity = profileIdentity
    let desired = !favorite
    defer { isFavoriteInFlight = false }
    do {
      let canonical = try await action(identity.type, identity.id, desired)
      guard Self.matches(canonical, identity: identity) else {
        actionMessage = "The server returned a different profile."
        return
      }
      favorite = canonical.isFavorite
    } catch {
      actionMessage = Self.safeMessage(error)
    }
  }

  func reanalyze(idempotencyKey: String, using action: ProfileReanalyzeAction) async {
    guard !isReanalyzeInFlight else { return }
    isReanalyzeInFlight = true
    actionMessage = nil
    actionSuccessMessage = nil
    let identity = profileIdentity
    defer { isReanalyzeInFlight = false }
    do {
      try await action(identity.type, identity.id, idempotencyKey)
      actionSuccessMessage = "Re-analysis requested. Track progress in Library."
    } catch {
      actionMessage = Self.safeMessage(error)
    }
  }

  func saveManual(using action: ProfileSaveManualAction) async {
    guard !isManualSaveInFlight else { return }
    guard let creator = currentCreator else { return }
    manualEditorMode = .editing
    actionSuccessMessage = nil
    let submittedDraft = manualDraft
    guard let validationMessage = submittedDraft.validationMessage else {
      // A pending profile read predates this contact write and must not replace it.
      editedProfileRefreshGeneration &+= 1
      isManualSaveInFlight = true
      actionMessage = nil
      actionSuccessMessage = nil
      defer { isManualSaveInFlight = false }
      do {
        let canonical = try await action(
          creator.id, submittedDraft.normalizedEmail, submittedDraft.notes)
        guard canonical.id == creator.id else {
          actionMessage = "The server returned a different profile."
          return
        }
        editedProfileRefreshGeneration &+= 1
        creatorOverride = canonical
        favorite = canonical.favorite
        if manualDraft == submittedDraft {
          manualDraft = CreatorManualDraft(profile: canonical)
          manualEditorMode = .summary
        }
        actionSuccessMessage = "Contact and notes saved."
      } catch {
        actionMessage = Self.safeMessage(error)
      }
      return
    }
    actionMessage = validationMessage
  }

  private var currentCreator: FindMeGamerCore.CreatorProfile? {
    guard case .creator(let creator) = currentProfile else { return nil }
    return creator
  }

  private var profileIdentity: (type: ProfileType, id: UUID) {
    switch profile {
    case .game(let game): (.game, game.id)
    case .creator(let creator): (.creator, creator.id)
    }
  }

  private static func matches(
    _ card: ProfileCard, identity: (type: ProfileType, id: UUID)
  ) -> Bool {
    switch (identity.type, card) {
    case (.game, .game(let game)): game.id == identity.id
    case (.creator, .creator(let creator)): creator.id == identity.id
    default: false
    }
  }

  private static func safeMessage(_ error: any Error) -> String {
    (error as? APIError)?.description ?? "The action could not be completed."
  }
}

extension ProfileCard {
  fileprivate var isFavorite: Bool {
    switch self {
    case .game(let game): game.favorite
    case .creator(let creator): creator.favorite
    }
  }
}

extension CreatorManualDraft {
  fileprivate static let empty = CreatorManualDraft(email: "", notes: "")

  private init(email: String, notes: String) {
    self.email = email
    self.notes = notes
  }
}

private enum ProfileFieldBuilder {
  static func fields(
    from object: JSONObject,
    specs: [(label: String, key: String)],
    inference: Bool = false
  ) -> [ProfileDisplayField] {
    specs.compactMap { spec in
      guard let claim = ProfileJSON.claim(object[spec.key], inference: inference) else {
        return nil
      }
      return ProfileDisplayField(
        label: spec.label, values: claim.values, annotation: claim.annotation)
    }
  }
}

private enum ProfileJSON {
  struct Claim {
    let values: [String]
    let annotation: String?
  }

  static func claim(_ value: JSONValue?, inference: Bool) -> Claim? {
    guard let value else { return nil }
    if case .object(let object) = value {
      let status = text(object["status"])?.lowercased()
      if status == "unavailable" {
        let reason = text(object["reason"])
        return Claim(
          values: ["Not available"], annotation: reason.map { "Reason: \($0)" })
      }
      if status != nil, status != "available" { return nil }
      let values: [String]
      if let scalar = scalar(object["value"]) {
        values = [scalar]
      } else if let array = scalarArray(object["values"]), !array.isEmpty {
        values = array
      } else {
        return nil
      }
      return Claim(values: values, annotation: claimAnnotation(object, inference: inference))
    }
    if let scalar = scalar(value) { return Claim(values: [scalar], annotation: nil) }
    if let values = scalarArray(value), !values.isEmpty {
      return Claim(values: values, annotation: nil)
    }
    return nil
  }

  static func text(_ value: JSONValue?) -> String? {
    guard case .string(let rawValue) = value else { return nil }
    let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
    return value.isEmpty ? nil : value
  }

  static func scalar(_ value: JSONValue?) -> String? {
    switch value {
    case .string:
      return text(value)
    case .integer(let value):
      return String(value)
    case .number(let value) where value.isFinite:
      if value.rounded(.towardZero) == value, value >= Double(Int.min), value <= Double(Int.max) {
        return String(Int(value))
      }
      return String(value)
    case .boolean(let value):
      return value ? "Yes" : "No"
    default:
      return nil
    }
  }

  static func nonnegativeInteger(_ value: JSONValue?) -> Int? {
    switch value {
    case .integer(let value) where value >= 0:
      return value
    case .number(let value)
    where value.isFinite && value >= 0 && value.rounded(.towardZero) == value
      && value <= Double(Int.max):
      return Int(value)
    default:
      return nil
    }
  }

  static func webURL(_ value: JSONValue?) -> URL? {
    ProfileLinkPolicy.validated(text(value))
  }

  static func duration(_ seconds: Int) -> String {
    let hours = seconds / 3_600
    let minutes = (seconds % 3_600) / 60
    let remainingSeconds = seconds % 60
    if hours > 0 { return "\(hours)h \(minutes)m \(remainingSeconds)s" }
    if minutes > 0 { return "\(minutes)m \(remainingSeconds)s" }
    return "\(remainingSeconds)s"
  }

  private static func scalarArray(_ value: JSONValue?) -> [String]? {
    guard case .array(let array) = value else { return nil }
    let values = array.compactMap(text)
    return values.count == array.count ? values : nil
  }

  private static func claimAnnotation(_ object: JSONObject, inference: Bool) -> String? {
    if text(object["provenance"]) == "manual" { return "Manual" }
    var parts: [String] = []
    if inference {
      parts.append("AI Inference")
    } else if let provenance = qualitativeProvenance(text(object["provenance"])) {
      parts.append(provenance)
    }
    if let confidence = qualitativeConfidence(text(object["confidence"])) {
      parts.append("Confidence: \(confidence)")
    }
    return parts.isEmpty ? nil : parts.joined(separator: " · ")
  }

  private static func qualitativeConfidence(_ value: String?) -> String? {
    guard let value else { return nil }
    return switch value.lowercased() {
    case "low": "Low"
    case "medium": "Medium"
    case "high": "High"
    default: nil
    }
  }

  private static func qualitativeProvenance(_ value: String?) -> String? {
    guard let value else { return nil }
    return switch value.lowercased() {
    case "ai_inference": "AI Inference"
    case "source_fact": "Source Fact"
    case "visual_observation": "Visual Observation"
    default: nil
    }
  }
}
