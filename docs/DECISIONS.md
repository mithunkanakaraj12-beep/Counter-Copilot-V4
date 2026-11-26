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
- **D-013 Data contract v0.1 (PROPOSED, not approved):** Adopt `docs/DATA_CONTRACT.md` v0.1 and `contracts/v0_1/` for the synthetic email-to-reviewed-draft slice. Narrows the v1 draft to email; derives tenant and idempotency on the server; introduces tracked field states with source evidence, employee-only SKU selection and versioned review; excludes quote sending. Changes are listed in section 14 and open questions (U-01 to U-20) in section 16. Affects backend, frontend, adapters, fixtures and tests. Requires project-owner approval.
