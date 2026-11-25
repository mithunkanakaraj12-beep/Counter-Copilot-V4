# Counter Copilot V4

AI-assisted communications intake, material-request preparation, inventory assessment, optional quote pricing, and employee approval for independent lumberyards.

**Status:** Repository foundation and planning documents only. Application code and live integrations have not yet been implemented or verified.

## V4 outcome

Counter Copilot receives contractor communications through connected email, SMS/MMS, and phone/voicemail channels. It preserves the original source, parses or transcribes it, extracts material requests, maps line items to the yard's catalog, assesses inventory when reliable data is available, optionally prepares provisional pricing from approved rules, and sends a draft into an employee review workflow.

Employees can edit, approve the internal draft, decline it, or request clarification. Sending a customer-facing quote, booking an order, exporting to an ERP, or reserving stock is a separate authorized action.

## V4 includes
- Inbound email, SMS/MMS, and call/voicemail intake through replaceable adapters.
- Transcription and supported attachment parsing.
- Structured material extraction with missing-field and ambiguity detection.
- Yard-specific SKU matching.
- ATP and inventory coverage when current, authorized data supports it.
- Optional deterministic provisional pricing; configurable by an authorized yard administrator and OFF until validated.
- Minimal employee dashboard, authenticated quick-approval links, and audit history.
- Quote lifecycle tracking and employee-initiated manual follow-up.
- Shadow mode, fallback, and controlled pilot process.

Automated quote-chasing campaigns and randomized holdout tests are a later module, not an initial V4 launch requirement. Live AI voice answering, ERP replacement, automatic order booking, and building a public telecom network are out of scope.

## Repository
- `docs/` — scope, architecture, data contract, decisions, workflow, handoff.
- `backend/` — API, database, extraction, inventory, pricing, approvals, workers.
- `frontend/` — employee-facing web application.
- `adapters/` — email, SMS, voice, transcription, language-model connectors.
- `infrastructure/` — local development, containers, deployment, operations.
- `tests/` — synthetic fixtures, unit, integration, and security tests.

## Engineering rules
1. Agree on the shared data contract before parallel implementation.
2. One owner per workstream; coordinate before changing another owner's files.
3. Preserve original communications before AI processing.
4. AI extracts and proposes. Deterministic code handles SKU constraints, units, ATP, pricing, permissions, and state transitions.
5. Every business record is scoped to a yard; enforce tenant isolation on every access path.
6. Uncertainty and stale data must be visible, never hidden by confident model output.
7. A failure must not lose a source message or break the yard's ordinary phone route.
8. Code is tested only after it has actually been executed in a development/test environment.

See [V4 scope](docs/V4_SCOPE.md), [architecture](docs/ARCHITECTURE.md), [data contract](docs/DATA_CONTRACT.md), and [handoff](docs/HANDOFF.md).
