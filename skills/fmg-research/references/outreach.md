# Contacts and outreach

Use existing explicitly public business contacts when supported by source. When an email is needed but absent, use `fmg email enrich`; save job/key and poll. Complete empty => not_found; failed/quota/timeout => failed/unresolved. Do not infer personal addresses or convert Gemini suggestions into verified delivery. Multiple contacts retain purposes/sources; select the business-appropriate recipient, asking if ambiguous.

Ask only for missing batch decisions: which creators/how many, recipient selection, sender/company signature and intended message. Use Codex's asynchronous question UI if available, otherwise normal conversation. You may continue unrelated authorized preparation while waiting; sending waits for approval.

List/inspect service templates rather than creating arbitrary templates. Fill variables from the selected game and saved creator evidence. A channel name can be the greeting when a public personal name is unavailable. Say what was observed without inventing a viewing experience. Generate an immutable preview for every recipient and show the batch list plus representative/full rendered content as needed for meaningful review. Approval is bound to those exact preview IDs, recipient addresses, template versions and bodies; changed content/recipient needs fresh approval.

Save approval scope in `outreach/<batch>/approval.json` with the relevant user message reference, approved previews and time. Then iterate only that batch, one stable idempotency key per preview, and save each receipt. Do not bulk resend after a timeout: query existing receipts/same-key request; unknown delivery must be investigated. Mark contacted only after SMTP acceptance, keeping uncertain outcomes separate. SMTP acceptance is neither recipient interest nor completed cooperation. This release does not collect replies or implement Yes/No callbacks; do not promise those reports.

If SMTP is not configured, preserve previews/variables and report the missing company setup. Do not ask the user to paste SMTP secrets into research artifacts. Preparing mail can complete without sending it.
