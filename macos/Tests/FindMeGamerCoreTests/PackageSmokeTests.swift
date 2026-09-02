import Testing

@testable import FindMeGamerCore

@Test func coreModuleHasStableProductIdentity() {
  #expect(ProductIdentity.name == "Find Me Gamer")
  #expect(ProductIdentity.bundleIdentifier == "com.findmegamer.desktop")
}
