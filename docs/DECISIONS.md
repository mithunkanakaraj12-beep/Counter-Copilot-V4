# Counter Copilot V4 — Decision Log

Append consequential decisions. Do not silently change scope or architecture.

- **D-001 Product boundary:** V4 is inbound communications, transcription/parsing, material extraction, SKU matching, inventory coverage when supported, optional provisional pricing, employee approval, quote lifecycle, and manual follow-up. Automated Quote Chaser is later scope.
- **D-002 Pricing:** Material preparation is always ON. Automatic provisional pricing is yard-configurable ON/OFF and defaults OFF until data/rules are validated.
- **D-003 Inventory:** V4 shows ATP/line coverage and source freshness. No predictive fulfillment probability until verified outcomes, calibration, and held-out testing.
- **D-004 Approval:** Internal draft approval is separate from sending a quote, ERP export, booking, or stock reservation.
- **D-005 Quick approval:** Initial quick approval uses authenticated links/actions. Notifications alone are not approval. Reply-to-approve requires separate security design and is not enabled by default.
- **D-006 Infrastructure:** Own Counter Copilot's application, data model, normalization, business rules, and employee workflow. Use authorized customer systems and replaceable telecom/mail/SMS connectivity. Do not build a public carrier network.
- **D-007 Pilot channels:** V4 supports calls, email, and texts, but the founding pilot may enable channels sequentially according to systems, access, registration, and readiness.
- **D-008 AI:** AI transcribes/classifies/extracts. Deterministic code handles units, SKU constraints, ATP, prices, permissions, and state transitions.
- **D-009 Quote Chaser:** Automated 24-hour campaigns and randomized holdouts are later scope. V4 records quote status and manual employee follow-up.
- **D-010 Pilot operator:** Before live pilot, identify a competent operator responsible for deployment, integration testing, monitoring, backups/recovery, and incident response.
- **D-011 Data and authorization:** Synthetic data for development. Live processing requires customer authorization, proper permissions, retention/security controls, and applicable messaging/call-recording compliance.
- **D-012 Collaboration:** Separate branches/workstreams, one owner per folder, contract changes approved by project owner, reviewed pull requests, and HANDOFF.md updates.
- **D-013 Data contract v0.1 (PROPOSED, not approved or frozen):** Adopt `docs/DATA_CONTRACT.md` v0.1 and `contracts/v0_1/` for the synthetic email-to-reviewed-draft slice. The first proposal (commit `5dd0699`) was revised after five reviews to apply D-014. Affects backend, frontend, adapters, fixtures and tests. Open questions are listed in section 17 of the contract. Requires independent review and project-owner approval.
- **D-014 Contract revision decisions (APPROVED by the project owner, 2026-11-26):** These take precedence over the recommendations in the five-review revision plan. A contract-only patch on `work/backend-foundation` is authorized; `main`, frontend files, application code, live integrations and merging PR #2 are not.
  - Units and dimensions: only contract unit names and approved spellings; bare counts never imply pieces; unknown abbreviations stay ambiguous until a yard mapping exists; no unit conversions; written dimension order is preserved with no axes or yard conventions; whole sequences are compared.
  - Messages: link only by reply headers or provider thread ID; a newer message flags but never changes or revokes; materials create a separate draft; a seven-day same-sender hint is informational; a linked reply without material lines may get an empty, never approvable draft; multiple jobs are flagged from quoted evidence, never split or merged.
  - Attachments: no individual download or processing; the complete original only; one grouped acknowledgment including inline and small images.
  - Quantities: fixed English cardinal list; vague, approximate, range, relative and conflicting readings stay ambiguous; no invented candidates.
  - Mark handled: completed non-requests with no request only; reason required, note for `other`; reopenable and audited. Clarification, assignment and notes are deferred.
  - Approval: active line, resolved quantity and unit, employee-selected SKU, no ambiguity, required acknowledgments; no non-stock approval; no per-line reviewed box; one blocker per issue.
  - Limits: 25,000,000-byte raw email, 200,000 body characters, 500 lines, 100 attachments, 200 MIME parts, depth 20, 256 KB headers, 30-second parse, 1 MB JSON, 20 evidence items, 10 candidates, 200 operations, 24-hour idempotency keys. Permanent message identity retention is **not** approved (U-04).
  - Parsing and grounding: deterministic versioned parser; preserved bytes; CRLF to LF only; code-point offsets; unreadable mail is `failed_terminal` / `parse_failed`; over-limit mail is `413` with nothing stored; pure reference functions; only structural failures reject a run; unsupported values become ambiguous with no candidates; heuristic warnings with false-positive tracking.
  - SKU: never auto-select; quantity keeps a selection, unit recomputes, matching-attribute changes clear it unless a new SKU is selected in the same edit.
  - Other: inbox search covers sender and subject only; required CI checks and branch protection before merging PR #2; raw and grounded output scored separately with zero unsupported values in drafts; accuracy targets remain proposals; Gemini owns benchmark labels.
- **D-015 Two line limits (APPROVED by the project owner, 2026-11-28):** Resolves the question, raised in review of `924f469`, of what D-014's "500 lines" measures.
  - The approved U-16 limit of 500 lines applies to decoded email body lines, including blank and quoted lines, after CRLF-to-LF normalization (`EMAIL_BODY_LINES = 500`). Over-limit emails return `413` and are not stored by the application.
  - `MATERIAL_LINES = 500` is kept as a separate contract-level maximum for proposal and request material lines. It is a separate schema/resource limit, not an interpretation of the U-16 email parser limit.
  - The separate names, validation rules, documentation and tests are preserved.
