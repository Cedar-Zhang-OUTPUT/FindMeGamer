import Foundation
import FindMeGamerAPI
import Testing

@Suite struct ProfileEditingWireTests {
  @Test func decodesNullAndListSourceValuesFromEditorWireDocument() throws {
    let data = Data(#"""
      {"profile_type":"game","profile_id":"10000000-0000-4000-8000-000000000001","revision":1,"fields":[
        {"key":"facts.name","section":"facts","label":"Name","kind":"text","required":true,"value":"Human title","source_value":null,"is_overridden":true},
        {"key":"analysis.themes","section":"analysis","label":"Themes","kind":"list","required":false,"value":[],"source_value":["Source theme"],"is_overridden":true}
      ]}
      """#.utf8)
    let document = try JSONDecoder().decode(Components.Schemas.ProfileEditDocument.self, from: data)
    #expect(document.fields.count == 2)
    #expect(document.fields[0].source_value == nil)
    #expect(document.fields[1].source_value != nil)
    let roundTrip = try JSONSerialization.jsonObject(with: JSONEncoder().encode(document)) as! [String: Any]
    let fields = roundTrip["fields"] as! [[String: Any]]
    #expect(fields[0]["value"] as? String == "Human title")
    #expect(fields[1]["source_value"] as? [String] == ["Source theme"])
    #expect(fields[1]["value"] as? [String] == [])
  }
}
