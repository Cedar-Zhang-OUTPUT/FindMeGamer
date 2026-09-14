import FindMeGamerCore
import SwiftUI

struct DiscoverResultView: View {
  @Bindable var model: DiscoverModel
  let record: DiscoverRecord
  let onOpenMatch: (UUID) -> Void
  let onAnalysisHistory: () -> Void
  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var batchesExpanded = true
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Text(record.gameName).font(.title2.bold())
        if record.isActive { ProgressView().controlSize(.small) }
        Text(record.stageTitle).foregroundStyle(.secondary)
        if record.status == "partial" || record.status == "failed" {
          Button("Retry incomplete work") { Task { await model.retry() } }
            .disabled(model.isSubmitting || !writesEnabled)
        }
        Spacer()
        Text("\(record.candidates.count) creators").foregroundStyle(.secondary)
      }
      ForEach(Array(record.issues.enumerated()), id: \.offset) { _, issue in
        Label(issue, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(
          .orange)
      }
      // SwiftUI Table's AppKit outline coordinator aborts during animated destination
      // removal on macOS 26.6. Keep native controls in a table-shaped Grid instead.
      ScrollView {
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 8) {
          GridRow {
            Text("Select").frame(width: 44)
            Text("Platform").frame(width: 85, alignment: .leading)
            Text("Creator").frame(width: 200, alignment: .leading)
            Text("URL").frame(maxWidth: .infinity, alignment: .leading)
          }.font(.caption).foregroundStyle(.secondary)
          Divider().gridCellColumns(4)
          ForEach(record.candidates) { candidate in
            GridRow {
              Toggle(
                "Select \(candidate.name)",
                isOn: Binding(
                  get: { model.selectedIDs.contains(candidate.id) },
                  set: { _ in model.toggleCandidate(candidate.id) })
              )
              .labelsHidden().toggleStyle(.checkbox).frame(width: 44)
              Text(CreatorPlatform.title(candidate.platform)).frame(width: 85, alignment: .leading)
              VStack(alignment: .leading, spacing: 2) {
                Text(candidate.name).lineLimit(1)
                if candidate.inLibrary {
                  Text("In Library").font(.caption).foregroundStyle(.secondary)
                }
              }.frame(width: 200, alignment: .leading)
              if let url = URL(string: candidate.url) {
                Link(candidate.url, destination: url).lineLimit(1)
                  .frame(maxWidth: .infinity, alignment: .leading)
              }
            }
            Divider().gridCellColumns(4)
          }
        }.padding(10)
      }.frame(minHeight: 180, maxHeight: .infinity)
        .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 8))
      HStack {
        Text("\(model.selectedIDs.count) selected").foregroundStyle(.secondary)
        Button("Select all") { model.selectAll() }
        Button("Deselect all") { model.deselectAll() }
        Spacer()
        Button("Analysis history", action: onAnalysisHistory)
        if !model.selectedIDs.isEmpty {
          Button("Add Analysis") { model.presentAnalysisConfirmation() }
            .buttonStyle(.borderedProminent)
            .disabled(model.selectedIDs.count > 100 || !writesEnabled)
        }
      }
      if !model.batches.isEmpty {
        DisclosureGroup("Analysis batches", isExpanded: $batchesExpanded) {
          ScrollView {
            VStack(alignment: .leading, spacing: 10) {
              ForEach(model.batches) { batch in
                HStack {
                  Text(batch.status.capitalized).fontWeight(.medium)
                  Text(
                    "\(batch.reusedCount) reused · \(batch.analyzingCount) analyzing · \(batch.succeededCount) succeeded · \(batch.failedCount) failed"
                  )
                  .foregroundStyle(.secondary)
                  Spacer()
                  if let id = batch.matchID { Button("Open Match") { onOpenMatch(id) } }
                }
                if let error = batch.error { Text(error).foregroundStyle(.red) }
                ForEach(batch.items.filter { $0.error != nil }) { item in
                  Text(item.error ?? "").font(.caption).foregroundStyle(.red)
                }
              }
            }.padding(.vertical, 6)
          }.frame(maxHeight: 100)
        }
      }
    }
  }
}
