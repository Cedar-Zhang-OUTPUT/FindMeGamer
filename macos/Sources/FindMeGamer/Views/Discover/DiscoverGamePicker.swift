import FindMeGamerCore
import SwiftUI

struct DiscoverGamePicker: View {
  @Bindable var model: DiscoverModel
  @State private var presented = false
  var body: some View {
    Button {
      presented.toggle()
    } label: {
      Label(model.selectedGame?.name ?? "Choose game", systemImage: "gamecontroller")
        .lineLimit(1).frame(maxWidth: 220)
    }
    .controlSize(.large)
    .popover(isPresented: $presented, arrowEdge: .bottom) {
      VStack(alignment: .leading, spacing: 12) {
        Text("Choose game").font(.headline)
        TextField("Search Library games", text: $model.gameQuery)
          .textFieldStyle(.roundedBorder)
          .onSubmit {
            if let game = model.filteredGames.first {
              model.selectedGame = game
              presented = false
            }
          }
        ScrollView {
          LazyVStack(spacing: 0) {
            ForEach(model.filteredGames, id: \.url) { game in
              Button {
                model.selectedGame = game
                presented = false
              } label: {
                HStack {
                  Text(game.name).lineLimit(1)
                  Spacer()
                  if model.selectedGame?.url == game.url { Image(systemName: "checkmark") }
                }
                .padding(.horizontal, 8).frame(height: 44).contentShape(Rectangle())
              }.buttonStyle(.plain)
              Divider()
            }
          }
        }.frame(height: 135)
        if model.isLoadingGames { ProgressView("Loading games…").controlSize(.small) }
        Divider()
        Text("or paste Steam URL").font(.callout).foregroundStyle(.secondary)
        TextField("Steam store URL", text: $model.steamURL).textFieldStyle(.roundedBorder)
          .onSubmit { Task { await model.resolveGame() } }
        HStack {
          Button("Resolve game") { Task { await model.resolveGame() } }
            .disabled(model.steamURL.isEmpty || model.isResolving)
          if model.isResolving { ProgressView().controlSize(.small) }
          Spacer()
        }
        if let error = model.gameError { Text(error).font(.callout).foregroundStyle(.red) }
        if let game = model.selectedGame {
          Label(game.name, systemImage: "checkmark.circle").foregroundStyle(.secondary)
          Button("Use this game") { presented = false }
        }
      }.padding(16).frame(width: 340)
    }
  }
}
