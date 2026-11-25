# Counter Copilot V4 — Architecture

## Design principles
- Own the product logic, data model, normalization, employee workflow, and business rules.
- Keep telecom, mailbox, transcription, and LLM integrations behind replaceable adapters.
- Preserve original source content before AI processing.
- Separate probabilistic AI interpretation from deterministic business rules.
- Make tenant isolation, auditability, freshness, retries, and fail-safe behavior foundational.
- Build the smallest pilot configuration supported by the founding yard; do not require all integrations to be live at once.

## Logical flow
```text
Email / SMS-MMS / Phone-voicemail
              |
         Channel adapters
              |
      Authenticated ingestion API
              |
      Durable event + source storage
              |
       Background processing worker
              |
  Parse / Transcribe / Classify / Extract
              |
      Schema and rule validation
              |
    Yard catalog + inventory + pricing
              |
       Request / quote draft service
              |
      Employee review and approval
              |
   Explicit quote send / export / handoff
```

## Proposed stack
| Area | Initial recommendation | Notes |
|---|---|---|
| Backend | Python + FastAPI | API and service layer |
| Database | PostgreSQL | Tenant-scoped relational records |
| Frontend | Next.js + TypeScript | Minimal employee application |
| Styling | Tailwind CSS | UI styling |
| Background processing | Durable queue/outbox + worker | Choose simplest reliable implementation |
| File storage | Private S3-compatible storage | MinIO for local testing if useful |
| Local infrastructure | Docker Compose | No Kubernetes initially |
| AI | Swappable transcription/extraction adapters | Benchmark local and hosted options |
| Communications | Replaceable email/SMS/voice adapters | Public network access still requires authorized providers/carriers or customer systems |

These are proposed choices, not provisioned services or tested integrations.

## Main layers
### Channel adapters
Normalize external provider/customer-system payloads into the internal event contract. Verify webhook signatures where supported, preserve source identifiers, and implement idempotency/retry behavior. Never put provider-specific payload logic into core request processing.

### Ingestion API
Use FastAPI or equivalent. Authenticate the source, resolve the yard through trusted integration configuration, generate/validate an idempotency key, preserve source metadata/content, enqueue durable work, and return quickly.

### Processing workers
Parse attachments, transcribe audio, classify/extract requests, reconcile mailbox events, retry failures, send notifications, and export approved drafts. Preserve source material if any downstream step fails.

### AI orchestration
Speech-to-text and language-model adapters handle transcription, classification, and structured extraction. Validate all model output against schemas and deterministic checks. Record provider/model, prompt, and schema versions. Use synthetic or redacted examples during benchmarking; review data terms and customer authorization before live processing.

### Business rules
Deterministic code handles SKU constraints, approved unit conversions, ATP/coverage, optional pricing, quote states, permissions, consent, and audit events. An LLM proposal is never a final inventory, pricing, credit, or delivery decision.

### Data storage
PostgreSQL stores yards, users, contacts, messages, requests, drafts, catalogs, inventory snapshots, price rules, quote states, and audit events. Private object storage holds call audio and attachments. Credentials belong in secret management/environment variables, never Git.

### Frontend
A minimal responsive review queue and request card are first-class pilot features. Show the original communication alongside extraction, SKU evidence, inventory freshness/coverage, optional price, and warnings. Secure authenticated notification links open the relevant request. Avoid advanced analytics and full CRM until validated.

## Reliability and deployment
- Durable event/outbox pattern; retries must be idempotent.
- Reconciliation sync for mailbox notifications.
- Webhook signature verification and source idempotency.
- Tenant-scoped authorization on every API and storage path.
- Private file storage with expiring authorized access.
- Monitoring, backups, restore tests, error queue, and incident runbook.
- Production webhooks require an always-on HTTPS endpoint; Codespaces/local development is not production hosting.
- The yard's ordinary phone route must keep working if Counter Copilot fails. Secure PBX/SIP deployment requires a competent operator and fraud controls.

## Suggested processing states
received → source_preserved → queued → processing → draft_ready / needs_review / failed_retry. Preserve the original source and history through all retries; a repeated provider event must not create duplicate quote drafts or sends.

## Explicit action boundaries
Internal draft approval does not equal sending a customer quote, exporting to an ERP, booking an order, or reserving stock. Each later action requires a separate explicit permission, confirmation, and audit record.
