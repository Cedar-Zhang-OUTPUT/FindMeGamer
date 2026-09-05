import AppKit
import FindMeGamerCore
import Testing

@testable import FindMeGamer

@MainActor
@Suite struct OutreachInteractionPresentationTests {
  @Test func variableMenuPreservesTheCompleteExistingAllowlist() {
    #expect(OutreachVariableOptions.tokens == OutreachManagementModel.allowedVariables)
    #expect(OutreachVariableOptions.tokens.count == 7)
    #expect(OutreachVariableOptions.label(for: "{{channel_name}}") == "Channel name")
    #expect(OutreachVariableOptions.label(for: "{{steam_url}}") == "Steam link")
    #expect(OutreachVariableOptions.label(for: "{{game_summary}}") == "Game summary")
    #expect(OutreachVariableOptions.label(for: "{{match_reason}}") == "Match reason")
  }

  @Test func variableInsertionReplacesOnlyTheSelectionAndSupportsUndo() {
    let editor = OutreachUndoTextView(frame: .zero)
    editor.allowsUndo = true
    editor.string = "Hi Taylor,\n\nA note."
    editor.setSelectedRange((editor.string as NSString).range(of: "Taylor"))
    let editing = OutreachTextEditing()
    editing.textView = editor

    editor.edits.beginUndoGrouping()
    #expect(editing.insert("{{creator_name}}"))
    editor.edits.endUndoGrouping()

    #expect(editor.string == "Hi {{creator_name}},\n\nA note.")
    #expect(editor.selectedRange() == NSRange(location: 19, length: 0))
    #expect(editor.edits.canUndo)
    editor.edits.undo()
    #expect(editor.string == "Hi Taylor,\n\nA note.")
  }

  @Test func unrelatedUpdatesKeepSelectionAndUndoHistory() {
    let editor = OutreachUndoTextView(frame: .zero)
    editor.allowsUndo = true
    editor.string = "Hello "
    editor.setSelectedRange(NSRange(location: 6, length: 0))
    let editing = OutreachTextEditing()
    editing.textView = editor
    editor.edits.beginUndoGrouping()
    #expect(editing.insert("{{game_name}}"))
    editor.edits.endUndoGrouping()
    editor.setSelectedRange(NSRange(location: 0, length: 5))

    editing.synchronize(text: editor.string, isEditable: true)

    #expect(editor.selectedRange() == NSRange(location: 0, length: 5))
    #expect(editor.edits.canUndo)
  }

  @Test func synchronizationDoesNotOverwriteIMEComposition() {
    let editor = OutreachUndoTextView(frame: .zero)
    editor.string = "Hello "
    editor.setSelectedRange(NSRange(location: 6, length: 0))
    editor.setMarkedText(
      "ni", selectedRange: NSRange(location: 2, length: 0),
      replacementRange: NSRange(location: 6, length: 0))
    let editing = OutreachTextEditing()
    editing.textView = editor

    editing.synchronize(text: "Hello ", isEditable: true)

    #expect(editor.hasMarkedText())
    #expect(editor.string == "Hello ni")
    editor.unmarkText()
  }

  @Test func disabledEditorRejectsVariableInsertion() {
    let editor = OutreachUndoTextView(frame: .zero)
    editor.string = "Original"
    editor.isEditable = false
    let editing = OutreachTextEditing()
    editing.textView = editor
    #expect(!editing.insert("{{sender_name}}"))
    #expect(editor.string == "Original")
  }

  @Test func realTestEmailConfirmationNamesTheRecipientAndSharedSaveImpact() {
    let send = SMTPActionConfirmation.sendTest("press@example.com")
    #expect(send.title == "Send one real test email?")
    #expect(send.message.contains("press@example.com"))
    #expect(send.message.contains("real test email"))
    #expect(send.message.contains("saved mailbox"))
    #expect(SMTPActionConfirmation.save.message.contains("all coworkers"))
  }

  @Test func returningToSMTPDraftDoesNotCollapseWhenLastEditIsReverted() {
    var presentation = SMTPConnectionPresentation()
    presentation.restore(configured: true, hasDraft: true)
    #expect(presentation.isEditing)

    presentation.restore(configured: true, hasDraft: false)
    #expect(presentation.isEditing)

    presentation.isEditing = false
    presentation.restore(configured: true, hasDraft: false)
    #expect(!presentation.isEditing)
  }

  @Test func initialCleanConfiguredMailboxKeepsTheSummaryVisible() {
    var presentation = SMTPConnectionPresentation()
    presentation.restore(configured: nil, hasDraft: false)
    #expect(!presentation.isEditing)
    presentation.restore(configured: true, hasDraft: false)
    #expect(!presentation.isEditing)
  }

  @Test func firstMailboxSetupStaysOpenAfterSaving() {
    var presentation = SMTPConnectionPresentation()
    presentation.restore(configured: false, hasDraft: false)
    #expect(presentation.isEditing)
    presentation.restore(configured: true, hasDraft: false)
    #expect(presentation.isEditing)
  }
}

@MainActor
private final class OutreachUndoTextView: NSTextView {
  let edits = UndoManager()
  override var undoManager: UndoManager? { edits }
}
