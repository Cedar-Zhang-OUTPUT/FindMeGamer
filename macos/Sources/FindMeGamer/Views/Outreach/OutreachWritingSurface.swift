import AppKit
import FindMeGamerCore
import SwiftUI

@MainActor
final class OutreachTextEditing {
  weak var textView: NSTextView?

  @discardableResult
  func insert(_ text: String) -> Bool {
    guard let textView, textView.isEditable else { return false }
    if textView.hasMarkedText() { textView.unmarkText() }
    let range = textView.selectedRange()
    textView.breakUndoCoalescing()
    guard textView.shouldChangeText(in: range, replacementString: text) else { return false }
    textView.textStorage?.replaceCharacters(in: range, with: text)
    textView.didChangeText()
    textView.setSelectedRange(
      NSRange(location: range.location + (text as NSString).length, length: 0))
    textView.breakUndoCoalescing()
    textView.window?.makeFirstResponder(textView)
    textView.scrollRangeToVisible(textView.selectedRange())
    return true
  }

  func synchronize(text: String, isEditable: Bool) {
    guard let editor = textView else { return }
    editor.isEditable = isEditable
    guard !editor.hasMarkedText(), editor.string != text else { return }
    let selection = editor.selectedRange()
    editor.string = text
    editor.setSelectedRange(
      NSRange(location: min(selection.location, (text as NSString).length), length: 0))
    // A different template is a new document, not an undoable keystroke in the previous one.
    editor.undoManager?.removeAllActions()
  }
}

/// A stable native editor keeps variable insertion at the caret and participates in Undo.
struct OutreachMessageEditor: NSViewRepresentable {
  @Binding var text: String
  let editing: OutreachTextEditing
  let accessibilityLabel: String
  @Environment(\.isEnabled) private var isEnabled
  @ScaledMetric(relativeTo: .body) private var editorPointSize: CGFloat = 15

  func makeCoordinator() -> Coordinator { Coordinator(text: $text) }

  func makeNSView(context: Context) -> NSScrollView {
    let scrollView = NSScrollView()
    scrollView.drawsBackground = false
    scrollView.hasVerticalScroller = true
    scrollView.autohidesScrollers = true
    let editor = NSTextView(frame: .zero)
    editor.isRichText = false
    editor.allowsUndo = true
    editor.drawsBackground = false
    editor.font = .systemFont(ofSize: editorPointSize)
    editor.textColor = .labelColor
    editor.insertionPointColor = .labelColor
    editor.textContainerInset = NSSize(width: 2, height: 5)
    editor.isVerticallyResizable = true
    editor.isHorizontallyResizable = false
    editor.autoresizingMask = [.width]
    editor.textContainer?.widthTracksTextView = true
    editor.textContainer?.containerSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
    editor.minSize = NSSize(width: 0, height: 0)
    editor.maxSize = NSSize(
      width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
    editor.setAccessibilityLabel(accessibilityLabel)
    editor.string = text
    editor.delegate = context.coordinator
    scrollView.documentView = editor
    editing.textView = editor
    return scrollView
  }

  func updateNSView(_ scrollView: NSScrollView, context: Context) {
    guard let editor = scrollView.documentView as? NSTextView else { return }
    context.coordinator.text = $text
    editing.textView = editor
    if editor.font?.pointSize != editorPointSize {
      editor.font = .systemFont(ofSize: editorPointSize)
    }
    editing.synchronize(text: text, isEditable: isEnabled)
  }

  final class Coordinator: NSObject, NSTextViewDelegate {
    var text: Binding<String>
    init(text: Binding<String>) { self.text = text }
    func textDidChange(_ notification: Notification) {
      guard let editor = notification.object as? NSTextView else { return }
      text.wrappedValue = editor.string
    }
  }
}

struct OutreachVariableMenu: View {
  let editing: OutreachTextEditing

  var body: some View {
    Menu("Insert variable") {
      ForEach(OutreachVariableOptions.tokens, id: \.self) { token in
        Button(OutreachVariableOptions.label(for: token)) { editing.insert(token) }
      }
    }
    .fixedSize()
  }
}

@MainActor
enum OutreachVariableOptions {
  static var tokens: [String] { OutreachManagementModel.allowedVariables }

  static func label(for token: String) -> String {
    if token == "{{steam_url}}" { return "Steam link" }
    let words = token.replacingOccurrences(of: "{{", with: "")
      .replacingOccurrences(of: "}}", with: "")
      .replacingOccurrences(of: "_", with: " ")
    return words.prefix(1).uppercased() + words.dropFirst()
  }
}

struct OutreachResponseButtons: View {
  let accepted: String
  let declined: String

  var body: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 10) { responses }
      VStack(alignment: .leading, spacing: 10) { responses }
    }
    .accessibilityElement(children: .contain)
    .accessibilityLabel("Response button preview")
  }

  @ViewBuilder private var responses: some View {
    response(accepted, symbol: "checkmark", color: StudioPalette.mint)
    response(declined, symbol: "xmark", color: .secondary)
  }

  private func response(_ label: String, symbol: String, color: Color) -> some View {
    Label(label, systemImage: symbol)
      .font(.callout.weight(.medium))
      .foregroundStyle(color)
      .padding(.horizontal, 12)
      .padding(.vertical, 8)
      .background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 9))
      .accessibilityLabel("\(symbol == "checkmark" ? "Accept" : "Decline"): \(label), preview only")
  }
}

/// A quiet sheet of paper inside the studio, shared by draft and rendered-message views.
struct OutreachWritingSurface: ViewModifier {
  func body(content: Content) -> some View {
    content
      .background(StudioPalette.surface, in: RoundedRectangle(cornerRadius: 18))
      .overlay {
        RoundedRectangle(cornerRadius: 18)
          .strokeBorder(StudioPalette.ink.opacity(0.065), lineWidth: 1)
          .allowsHitTesting(false)
      }
      .shadow(color: .black.opacity(0.035), radius: 14, y: 6)
  }
}

struct OutreachDraftFieldStyle: TextFieldStyle {
  func _body(configuration: TextField<Self._Label>) -> some View {
    configuration
      .textFieldStyle(.plain)
      .padding(.horizontal, 12)
      .padding(.vertical, 10)
      .background(StudioPalette.surface, in: RoundedRectangle(cornerRadius: 10))
      .overlay {
        RoundedRectangle(cornerRadius: 10)
          .strokeBorder(StudioPalette.ink.opacity(0.12), lineWidth: 1)
          .allowsHitTesting(false)
      }
  }
}
