import Foundation
import Testing

@testable import FindMeGamerCore

@Suite struct CreatorPlatformTests {
  @MainActor @Test func publicXAccountIsAnAnalysisSource() async {
    let model = AnalyzeRequestModel(api: DemoAPIService())
    model.targetType = .creator
    model.urlText = "https://x.com/indiecreator"
    await model.submit()
    #expect(model.validationMessage == nil)
  }
}
