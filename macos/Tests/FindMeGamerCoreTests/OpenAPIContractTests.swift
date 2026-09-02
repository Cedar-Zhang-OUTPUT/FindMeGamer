import FindMeGamerAPI
import Foundation
import Testing

private let requiredOrdinaryOperations: Set<String> = [
  "validateSession",
  "createAnalysisJob",
  "createMatch",
  "createOutreachSendBatch",
]

@Test func generatedCatalogIncludesOrdinaryClientOperations() {
  #expect(requiredOrdinaryOperations.isSubset(of: Set(GeneratedOperationNames.all)))
}

@Test func generatedCatalogRejectsStaleSendBatchAlias() {
  #expect(!GeneratedOperationNames.all.contains("createSendBatch"))
}

@Test func generatedCatalogExactlyMatchesCopiedSchema() throws {
  let document = try copiedOpenAPIDocument()
  let schemaOperationNames = try operationNames(in: document)

  #expect(Set(GeneratedOperationNames.all) == schemaOperationNames)
  #expect(GeneratedOperationNames.all.count == schemaOperationNames.count)
}

@Test func schemaOperationsAreUniqueCamelCaseNames() throws {
  let document = try copiedOpenAPIDocument()
  let operationNameList = try operationNameList(in: document)
  let camelCase = try Regex(#"^[a-z][A-Za-z0-9]*$"#)

  #expect(operationNameList.count == Set(operationNameList).count)
  #expect(operationNameList.allSatisfy { $0.wholeMatch(of: camelCase) != nil })
}

@Test func responseSchemasExcludeHiddenRankingAndSecrets() throws {
  let document = try copiedOpenAPIDocument()
  let responseSchemas = try responseReachableSchemas(in: document)
  let forbiddenProperties: Set<String> = [
    "rank",
    "backend_order",
    "total_score",
    "dimension_scores",
    "response_token",
    "response_token_digest",
    "token_digest",
    "password",
    "ciphertext",
    "nonce",
    "master_key",
    "master_key_file",
    "workspace_access_key_hash",
    "workspace_key_hash",
    "workspace_key_digest",
  ]

  let exposedProperties = Set(
    responseSchemas.flatMap { schema in
      (schema["properties"] as? [String: Any])?.keys.map { $0.lowercased() } ?? []
    })
  #expect(exposedProperties.isDisjoint(with: forbiddenProperties))
}

@Test func smtpPasswordIsWriteOnlyAndRequestOnly() throws {
  let document = try copiedOpenAPIDocument()
  let schemas = try componentsSchemas(in: document)
  let update = try #require(schemas["SMTPSettingsUpdate"] as? [String: Any])
  let updateProperties = try #require(update["properties"] as? [String: Any])
  let password = try #require(updateProperties["password"] as? [String: Any])
  let response = try #require(schemas["SMTPSettingsResponse"] as? [String: Any])
  let responseProperties = try #require(response["properties"] as? [String: Any])

  #expect(password["writeOnly"] as? Bool == true)
  #expect(responseProperties["password"] == nil)
}

private func copiedOpenAPIDocument() throws -> [String: Any] {
  let testFile = URL(fileURLWithPath: #filePath)
  let packageRoot =
    testFile
    .deletingLastPathComponent()
    .deletingLastPathComponent()
    .deletingLastPathComponent()
  let schemaURL =
    packageRoot
    .appendingPathComponent("Sources/FindMeGamerAPI/openapi.json")
  let data = try Data(contentsOf: schemaURL)
  return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
}

private func operationNames(in document: [String: Any]) throws -> Set<String> {
  Set(try operationNameList(in: document))
}

private func operationNameList(in document: [String: Any]) throws -> [String] {
  let paths = try #require(document["paths"] as? [String: Any])
  return paths.values.flatMap { pathValue -> [String] in
    guard let path = pathValue as? [String: Any] else { return [] }
    return path.values.compactMap { operationValue in
      (operationValue as? [String: Any])?["operationId"] as? String
    }
  }
}

private func componentsSchemas(in document: [String: Any]) throws -> [String: Any] {
  let components = try #require(document["components"] as? [String: Any])
  return try #require(components["schemas"] as? [String: Any])
}

private func responseReachableSchemas(
  in document: [String: Any]
) throws -> [[String: Any]] {
  let paths = try #require(document["paths"] as? [String: Any])
  let schemas = try componentsSchemas(in: document)
  var pending: [Any] = paths.values.compactMap { pathValue in
    guard let path = pathValue as? [String: Any] else { return nil }
    return path.values.compactMap { operationValue -> Any? in
      (operationValue as? [String: Any])?["responses"]
    }
  }
  var visitedNames: Set<String> = []

  while let value = pending.popLast() {
    if let array = value as? [Any] {
      pending.append(contentsOf: array)
      continue
    }
    guard let object = value as? [String: Any] else { continue }
    if let reference = object["$ref"] as? String,
      reference.hasPrefix("#/components/schemas/")
    {
      let name = String(reference.dropFirst("#/components/schemas/".count))
      if visitedNames.insert(name).inserted, let schema = schemas[name] {
        pending.append(schema)
      }
    }
    pending.append(contentsOf: object.values)
  }

  return visitedNames.compactMap { schemas[$0] as? [String: Any] }
}
