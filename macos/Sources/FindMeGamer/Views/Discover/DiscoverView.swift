import FindMeGamerCore
import SwiftUI

struct DiscoverView: View {
  @Bindable var model: DiscoverModel
  let onOpenMatch: (UUID) -> Void
  let onAnalysisHistory: () -> Void
  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var historyExpanded = true

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text("Discover new creators").font(.system(size: 32, weight: .bold, design: .rounded))
        .foregroundStyle(StudioPalette.ink)
      HStack(spacing: 10) {
        Text("Use").font(.title3)
        DiscoverGamePicker(model: model)
        Text("to continue finding").font(.title3)
        if model.selectedGame != nil {
          Button("Start") { model.presentConditions() }
            .buttonStyle(.borderedProminent)
            .disabled(!model.canStart || !writesEnabled)
        }
        Spacer()
      }
      if let error = model.error {
        Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.red)
          .font(.callout).textSelection(.enabled)
      }
      if !model.history.isEmpty {
        DisclosureGroup("Discover history · \(model.history.count)", isExpanded: $historyExpanded) {
          ScrollView {
            LazyVStack(spacing: 8) {
              ForEach(model.history) { item in
                Button {
                  Task { await model.open(id: item.id) }
                } label: {
                  HStack {
                    Text(item.gameName).fontWeight(.medium)
                    Spacer()
                    Text("\(item.candidateCount) creators").foregroundStyle(.secondary)
                    Text(item.status.capitalized).foregroundStyle(.secondary)
                    Text(item.createdAt, style: .date).foregroundStyle(.secondary)
                  }
                  .padding(8).frame(maxWidth: .infinity, alignment: .leading).contentShape(
                    Rectangle())
                }.buttonStyle(.plain)
              }
            }
          }
          .frame(height: 120)
        }
      }
      if let record = model.record {
        DiscoverResultView(
          model: model, record: record, onOpenMatch: onOpenMatch,
          onAnalysisHistory: onAnalysisHistory)
      } else {
        ContentUnavailableView(
          "Find your next creator", systemImage: "sparkle.magnifyingglass",
          description: Text(
            "Choose a game from your Library or resolve a Steam URL, then set your discovery conditions."
          )
        )
        .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
    .padding(24)
    .navigationTitle("Discover")
    .toolbar {
      Button {
        Task { await model.load() }
      } label: {
        Label("Refresh", systemImage: "arrow.clockwise")
      }
    }
    .sheet(isPresented: $model.conditionsPresented) { DiscoverConditionsSheet(model: model) }
    .sheet(isPresented: $model.analysisConfirmationPresented) {
      VStack(alignment: .leading, spacing: 18) {
        Text("Do you want to start matching immediately after analysis?").font(.title2.bold())
        Text("\(model.selectedIDs.count) creators selected").foregroundStyle(.secondary)
        Text("Matching uses all eligible creators in your Library after this analysis finishes.")
          .foregroundStyle(.secondary)
        if let error = model.error { Text(error).foregroundStyle(.red) }
        HStack {
          Button("Cancel") { model.cancelAnalysisConfirmation() }.keyboardShortcut(.cancelAction)
          Spacer()
          Button("Just analyze") { Task { await model.submitAnalysis(mode: .analyze) } }
            .disabled(!model.canAddAnalysis || !writesEnabled)
          Button("Do matching immediately") {
            Task { await model.submitAnalysis(mode: .analyzeAndMatch) }
          }
          .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(!model.canAddAnalysis || !writesEnabled)
        }
        if model.isSubmittingBatch { ProgressView("Submitting analysis…") }
      }.padding(24).frame(width: 590)
    }
  }
}
