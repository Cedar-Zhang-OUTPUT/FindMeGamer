import SwiftUI

struct FactSection: View {
  let title: String
  let fields: [ProfileDisplayField]

  var body: some View {
    GroupBox(title) {
      VStack(alignment: .leading, spacing: 10) {
        if fields.isEmpty {
          Text("Not available")
            .foregroundStyle(.secondary)
        } else {
          ForEach(Array(fields.enumerated()), id: \.offset) { _, field in
            VStack(alignment: .leading, spacing: 3) {
              Text(field.label)
                .font(.caption)
                .foregroundStyle(.secondary)
              if field.values.count == 1 {
                Text(field.values[0])
              } else {
                ForEach(Array(field.values.enumerated()), id: \.offset) { _, value in
                  Label(value, systemImage: "circle.fill")
                    .labelStyle(ProfileBulletLabelStyle())
                }
              }
              if let annotation = field.annotation {
                Text(annotation)
                  .font(.caption)
                  .foregroundStyle(.secondary)
              }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
          }
        }
      }
      .padding(.top, 4)
      .frame(maxWidth: .infinity, alignment: .leading)
      .textSelection(.enabled)
    }
  }
}

private struct ProfileBulletLabelStyle: LabelStyle {
  func makeBody(configuration: Configuration) -> some View {
    HStack(alignment: .firstTextBaseline, spacing: 7) {
      configuration.icon
        .font(.system(size: 4))
        .foregroundStyle(.secondary)
      configuration.title
    }
  }
}
