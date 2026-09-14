import Foundation

/// Mirrors the backend editorial catalog; demo source values are frozen at first read.
enum DemoProfileEditing {
  static func document(_ profile: Profile, type: ProfileType) -> ProfileEditDocument {
    let facts: JSONObject
    let analysis: JSONObject
    let brief: JSONObject
    let name: String
    switch profile {
    case .game(let p):
      (facts, analysis, brief, name) = (p.currentFacts, p.analysis, p.brief, p.name)
    case .creator(let p):
      (facts, analysis, brief, name) = (p.currentFacts, p.analysis, p.brief, p.name)
    }
    let groups: [(String, String, String)] =
      type == .game
      ? [
        ("facts", "text", "name type release_date supported_languages"),
        ("facts", "multiline", "short_description detailed_description about_the_game"),
        ("facts", "list", "developers publishers genres categories platforms"),
        ("analysis", "multiline", "short_summary core_gameplay_loop visual_style"),
        (
          "analysis", "list",
          "themes tone target_audience key_selling_points content_hooks comparable_games suitable_creator_types promotion_risks"
        ),
        ("brief", "multiline", "positioning_premise core_gameplay_loop visual_identity"),
        (
          "brief", "list",
          "genres themes tone target_audience key_selling_points content_hooks comparable_games suitable_creator_types promotion_risks"
        ),
      ]
      : [
        ("facts", "text", "title country"), ("facts", "multiline", "description"),
        (
          "analysis", "multiline",
          "content_summary pacing production_quality livestream_tendency long_form_tendency short_form_tendency recent_performance_summary engagement_summary publishing_frequency_context audience_inference.primary_language"
        ),
        (
          "analysis", "list",
          "primary_games genres formats style representative_video_context sponsorship_patterns brand_safety suitable_game_types collaboration_risks audience_inference.likely_regions audience_inference.interests"
        ),
        (
          "brief", "multiline",
          "positioning style_and_pacing audience performance_context promotion_fit brand_safety"
        ),
        ("brief", "list", "content_focus formats suitable_game_types collaboration_risks"),
      ]
    let fields = groups.flatMap { section, kind, names in
      names.split(separator: " ").map { nameKey -> ProfileEditField in
        let path = nameKey.split(separator: ".").map(String.init)
        let required = section == "facts" && (nameKey == "name" || nameKey == "title")
        var raw: JSONValue? = .object(
          section == "facts" ? facts : section == "analysis" ? analysis : brief)
        for component in path {
          if case .object(let object) = raw { raw = object[component] } else { raw = nil }
        }
        if case .object(let claim) = raw { raw = claim[kind == "list" ? "values" : "value"] }
        let source: ProfileEditValue?
        if required {
          source = .text(name)
        } else if case .string(let text) = raw, kind != "list" {
          source = .text(text)
        } else if case .array(let list) = raw, kind == "list" {
          let items = list.compactMap {
            if case .string(let text) = $0 { return text }
            return nil
          }
          source = items.count == list.count ? .list(items) : nil
        } else {
          source = nil
        }
        return .init(
          key: section + "." + nameKey, section: section,
          label: path.last!.replacingOccurrences(of: "_", with: " ").capitalized,
          kind: kind, required: required, value: source ?? (kind == "list" ? .list([]) : .text("")),
          sourceValue: source, isOverridden: false)
      }
    }
    return .init(profileType: type, profileID: profile.id, revision: 0, fields: fields)
  }

  static func applying(_ document: ProfileEditDocument, to profile: Profile, source: Profile)
    -> Profile
  {
    let sourceFacts: JSONObject
    let sourceAnalysis: JSONObject
    let sourceBrief: JSONObject
    switch source {
    case .game(let p):
      (sourceFacts, sourceAnalysis, sourceBrief) = (p.currentFacts, p.analysis, p.brief)
    case .creator(let p):
      (sourceFacts, sourceAnalysis, sourceBrief) = (p.currentFacts, p.analysis, p.brief)
    }
    func section(_ section: String, _ original: JSONObject) -> JSONObject {
      var result = original
      func assign(_ value: JSONValue, path: ArraySlice<String>, to object: inout JSONObject) {
        guard let key = path.first else { return }
        if path.count == 1 {
          object[key] = value
          return
        }
        var child: JSONObject = [:]
        if case .object(let existing) = object[key] { child = existing }
        assign(value, path: path.dropFirst(), to: &child)
        object[key] = .object(child)
      }
      for field in document.fields where field.section == section && field.isOverridden {
        let raw: JSONValue =
          switch field.value {
          case .text(let text): .string(text)
          case .list(let items): .array(items.map(JSONValue.string))
          }
        let value: JSONValue =
          section == "facts"
          ? raw
          : .object([
            "status": .string("available"), field.kind == "list" ? "values" : "value": raw,
            "provenance": .string(field.isOverridden ? "manual" : "source_fact"),
          ])
        assign(
          value, path: field.key.split(separator: ".").map(String.init).dropFirst(), to: &result)
      }
      return result
    }
    switch profile {
    case .game(var p):
      p.profileRevision = document.revision
      p.manualOverrides = Dictionary(
        uniqueKeysWithValues: document.fields.filter(\.isOverridden).map { ($0.key, $0.value) })
      p.name = document.fields.first!.value.text
      p.currentFacts = section("facts", sourceFacts)
      p.analysis = section("analysis", sourceAnalysis)
      p.brief = section("brief", sourceBrief)
      return .game(p)
    case .creator(var p):
      p.profileRevision = document.revision
      p.manualOverrides = Dictionary(
        uniqueKeysWithValues: document.fields.filter(\.isOverridden).map { ($0.key, $0.value) })
      p.name = document.fields.first!.value.text
      p.currentFacts = section("facts", sourceFacts)
      p.analysis = section("analysis", sourceAnalysis)
      p.brief = section("brief", sourceBrief)
      return .creator(p)
    }
  }
}
