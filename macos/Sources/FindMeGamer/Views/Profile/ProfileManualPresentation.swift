import FindMeGamerCore

enum ProfileManualPresentation {
  static func annotatedFacts(_ facts: JSONObject, overrides: [String: ProfileEditValue])
    -> JSONObject
  {
    var result = facts
    for (key, value) in overrides where key.hasPrefix("facts.") {
      let field = String(key.dropFirst(6))
      switch value {
      case .text(let text):
        result[field] = .object([
          "status": .string("available"), "value": .string(text), "provenance": .string("manual"),
        ])
      case .list(let list):
        result[field] = .object([
          "status": .string("available"), "values": .array(list.map(JSONValue.string)),
          "provenance": .string("manual"),
        ])
      }
    }
    return result
  }
  static func onlyManual(_ object: JSONObject) -> JSONObject {
    object.reduce(into: [:]) { result, entry in
      guard case .object(let child) = entry.value else { return }
      if child["provenance"] == .string("manual") {
        result[entry.key] = entry.value
      } else {
        let nested = onlyManual(child)
        if !nested.isEmpty { result[entry.key] = .object(nested) }
      }
    }
  }
}
