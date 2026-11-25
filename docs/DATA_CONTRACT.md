# Counter Copilot V4 — Data Contract v1 (Draft)

This is the shared interface for backend, frontend, and adapter workstreams. Any change must be proposed in DECISIONS.md, approved by the project owner, and reflected across code and tests.

## Conventions
- Every business record has a yard_id; tenant isolation applies to API queries and object storage.
- UUIDs for internal identifiers; UTC timestamps; retain yard timezone for display/business hours.
- Preserve original wording and source references.
- Quantities are decimals paired with explicit units.
- Currency uses ISO currency code and decimal arithmetic, never binary floating point.
- Validate model output against a versioned schema before creating a draft.
- Store model, prompt, and schema versions for reproducibility.

## Main entities
- **Yard:** id, name, timezone, business hours, data freshness policy, pricing_enabled, notification preferences, integration references.
- **User/Employee:** id, yard_id, display name, email, role, status, notification preferences, explicit permissions.
- **Contact/Contractor:** id, yard_id, names, phone/email identifiers, match evidence, known-account evidence, consent and suppression state.
- **SKU:** id, yard_id, SKU code, description, dimensions, species, grade, treatment, sell/base units, approved conversions, synonyms, active state.
- **InventorySnapshot/Line:** id, yard_id, source, received_at, effective_at, freshness state, SKU, on_hand, allocated, held, safety_stock, unavailable, unit, parsing/mapping status.
- **PriceBook/AccountPriceRule:** id, yard_id, source, effective_at, account scope, SKU/category, price, unit, discount/markup, fees/tax, rule precedence, validation/freshness state.
- **Communication/Message:** id, yard_id, channel, direction, provider/source ID, idempotency key, sender/recipient, contact match evidence, timestamps, subject/body/transcript references, attachments, source reference, processing state/error.
- **Request/RequestLine:** id, yard_id, source communication IDs, request type, raw wording, normalized summary, items, quantity/unit/specifications, candidate SKUs/evidence, confidence, missing fields, ambiguity, delivery/job details, status.
- **InventoryAssessment:** id, request_id, inventory snapshot ID, SKU, requested quantity, ATP, coverage percent, component breakdown, source timestamp, freshness, limitations.
- **QuoteDraft:** id, request_id, customer/account, pricing mode, currency, price source/effective time, lines, discounts/fees/tax, provisional total, warnings, state, version.
- **Approval/AuditEvent:** yard, entity, actor, action, previous/new state, timestamp, reason, authentication/authorization evidence, version.
- **FollowUpEvent:** quote, yard, employee, template, channel, time, delivery status, customer response, consent/suppression evaluation.

## Canonical inbound event (illustrative)
```json
{
  "event_id": "provider-event-id",
  "yard_id": "yard-uuid",
  "channel": "email",
  "direction": "inbound",
  "received_at": "2026-11-25T15:00:00Z",
  "sender": {"name": "Synthetic Contractor", "email": "contractor@example.test", "phone": null},
  "recipient": "orders@example-yard.test",
  "subject": "Material request",
  "body_text": "Please quote 40 pieces of 2x6x12 SYP #2.",
  "media": [],
  "source_reference": "private-source-object-reference",
  "provider_metadata": {},
  "idempotency_key": "stable-source-key"
}
```

## Canonical extraction result (illustrative)
```json
{
  "request_type": "material_request",
  "raw_text": "Please quote 40 pieces of 2x6x12 SYP #2.",
  "items": [{
    "raw_wording": "40 pieces of 2x6x12 SYP #2",
    "quantity": "40",
    "unit": "pieces",
    "dimensions": "2x6x12",
    "species": "SYP",
    "grade": "#2",
    "treatment": null,
    "candidate_skus": [],
    "confidence": null,
    "missing_fields": [],
    "ambiguity_reasons": []
  }],
  "warnings": [],
  "model_version": "record-actual-model",
  "schema_version": "1"
}
```

Confidence in examples is not a production threshold. Calibrate thresholds against labeled cases and critical-field errors.

## Inventory rules
Use the yard's documented field semantics. Where components are separately represented:
`ATP = on_hand - allocated - held - safety_stock - unavailable`

Do not subtract a component twice if the ERP's available/on-hand field already accounts for it. For requested quantity Q > 0:
`coverage_percent = min(1, max(0, ATP / Q)) * 100`

Only calculate when SKU, units, and required inputs are understood. Show components and data time. Coverage is not fulfillment probability.

## Pricing rules
- Yard pricing toggle is OFF until validated.
- OFF does not disable request preparation; price is null and display says “Not calculated.”
- ON resolves approved account price rules deterministically.
- Store source price book, effective timestamp, account tier/rule, conversions, discounts, fees/taxes, rounding, and line extensions.
- Missing/stale/conflicting rules require review; model never invents a price.

## State model
Request review: new → processing → draft_ready; draft_ready may become needs_clarification, internally_approved, or declined; retryable failures retain source and history.

Quote lifecycle: draft → internally_approved → sent → revised / customer_accepted / customer_declined / expired_cancelled / converted_to_order (only when yard confirms) / failed_retry.

Internal approval is not a customer-facing send, ERP order, inventory reservation, or delivery commitment.

## Proposed API surface
- POST /api/v1/inbound/events — authenticated adapter event intake.
- GET /api/v1/yard/{yard_id}/inbox — tenant-scoped inbox.
- GET /api/v1/requests/{request_id} — source, extraction, assessments, draft.
- PATCH /api/v1/requests/{request_id} — employee edits with version check.
- POST /api/v1/requests/{request_id}/decision — approve internal draft, decline, clarify, assign.
- POST /api/v1/quotes/{quote_id}/send — separate authorized customer-facing send.
- POST /api/v1/quotes/{quote_id}/manual-follow-up — one employee-initiated approved-template follow-up.
- GET /api/v1/health — service health without sensitive details.

Finalize exact typed request/response models and authentication before implementation.
