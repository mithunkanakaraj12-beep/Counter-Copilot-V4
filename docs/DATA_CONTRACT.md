# Counter Copilot V4 — Data Contract v0.1 (PROPOSED)

**Status: proposal awaiting project-owner approval (D-013). Nothing here is implemented.**

This replaces the earlier "v1 (Draft)". It narrows the first contract to one slice and makes it exact:

> synthetic email → preserved original → classification → extracted lines → catalog match → review draft → employee edit, internal approval or decline

Any change must be proposed in DECISIONS.md, approved by the project owner, and reflected across code and tests.

| Artifact | Authority |
|---|---|
| This document | Behaviour and rules that need stored data |
| `contracts/v0_1/models.py` | Exact request, response and model-output shapes (Pydantic) |
| `contracts/v0_1/openapi.yaml` | HTTP surface, generated from the models and `api.py` |
| `contracts/v0_1/examples/` | Synthetic payloads checked against the schemas |

If they disagree, that is a defect to fix before approval. Items marked **U-nn** are open (section 16); the text shows a proposed default, not a decision.

**Out of scope for v0.1:** SMS, voice, attachment parsing, contact matching, inventory, pricing, quote entities and sending, follow-up, assignment, clarification, notifications, catalog import, ERP export, orders and reservations.

## 0. Conventions
- Every business record has a `yard_id`. References between records must stay within one yard, enforced in the database as well as the application.
- Internal identifiers are UUIDs. Timestamps are UTC (offset zero). The yard timezone is for display.
- Original wording is preserved. Strings are not trimmed or normalized on the way in.
- Quantities and measurements are decimal strings, never JSON numbers.
- Unknown JSON keys are rejected.
- Request bodies use `schema_version: "0.1"` where the payload is stored or produced by an adapter or model.

## 1. Communication identity and idempotency
The intake endpoint takes a multipart request: `metadata` (`InboundEmailEvent`) and `original` (the raw `message/rfc822` bytes).

- The yard and integration come from the adapter credential. The payload has **no** `yard_id`, idempotency key or storage reference.
- Identity is `(yard_id, integration_id, external_message_id)`, unique in the database. `integration_id` stays the same when credentials rotate.
- `external_message_id` must be assigned by the mail source and be identical on redelivery. The RFC `Message-ID` is sender-controlled and is only a duplicate hint (**U-03**).
- `external_event_id` describes a delivery attempt and never affects identity.

**Content fingerprint.** SHA-256 of UTF-8 JSON with sorted keys, no insignificant whitespace and unescaped non-ASCII, over: `sender` (address), `recipients` (sorted addresses), `subject`, `body_text`, `attachments` (sorted SHA-256 values). No case folding. Transport headers, names, receipt time and provider metadata are excluded.

| Delivery | Result |
|---|---|
| New identity | Preserve original, create record and processing job atomically, `202` |
| Same identity, same fingerprint | No new record or job, `200`, `duplicate: true`. First original is kept; the attempt and its raw digest are audited |
| Same identity, different fingerprint | Quarantine the new bytes durably, set `has_conflicting_delivery`, `409`. The first record is untouched |
| Different identity, same RFC Message-ID or fingerprint in the yard | Accept, set `possible_duplicate_of`. Never auto-merge |

Success is returned only after the original and the job are durable. The adapter keeps the source until it receives `200`, `202` or `409`, retries network errors and `503`, and holds `401`, `413` and `422` for an operator.

**Replies.** A new communication never changes an existing request. If thread headers match an earlier communication in the yard, `related_request_ids` is set, the earlier request lists the message in `related_communication_ids`, and any new draft carries `possible_follow_up` (**U-12**).

**Employee mutations** require an `Idempotency-Key`, scoped to `(yard_id, user_id, method, path)`. After authorization, the key is checked before the version. A repeat of a committed call with the same body returns the stored response; a different body returns `409 idempotency_conflict`. Failed calls are not stored. Retention: **U-16**.

## 2. Immutable original and source text
- `CommunicationRecord` and the original bytes are written once. No API updates or deletes them.
- The server computes the digest and size, and chooses a yard-prefixed private storage key. Storage keys never appear in the API.
- `CommunicationStatus` (processing, classification, flags) is stored separately and may change.
- `body_text` and `subject` are the immutable text that evidence points into. `body_text` is the adapter's plain-text reading of the email; the raw bytes remain the authority.
- The server does not check that `metadata` agrees with the raw bytes. v0.1 trusts the adapter for this.
- Attachment metadata is adapter-reported. Bytes stay inside the raw message. Any attachment raises `unprocessed_attachment`.
- Download streams through the API as an attachment with `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`, and is audited.
- Email content is untrusted. Clients render it as plain text; the extraction step treats it as data, never instructions.
- Retention, legal deletion and storage-level write protection: **U-04**.

## 3. Structured material request
A `RequestDetail` holds `content` (lines and job details), computed `warnings` and `approval_blockers`, the approval record and extraction run information. The request is the review draft; there is no separate quote entity in v0.1.

Each `MaterialLine` has a stable `line_id`, `position`, `origin` (`model` or `employee`), `status` (`active` or `removed`), verbatim `raw_wording`, `source_evidence`, ten tracked fields (`product`, `quantity`, `unit`, `dimension_text`, `thickness`, `width`, `length`, `species`, `grade`, `treatment`) and a `match`.

- Model lines require source wording and evidence. `raw_wording` equals the quote of the first source evidence item and is never edited.
- Employee-added lines have no source wording and only `missing` or `employee_entered` fields.
- Removed lines are retained.
- Job details: `fulfillment_method`, `requested_date_text` (as written; "Friday" is not resolved to a date), `delivery_address`, `job_reference`, `notes`.
- One communication yields at most one origin request (**U-18**).
- `inventory_status` and `pricing_status` are fixed at `not_assessed` and `not_calculated`.

## 4. Field states

| State | Value | Evidence | Other | Set by |
|---|---|---|---|---|
| `extracted` | required | at least one `supports` | — | model |
| `missing` | null | none | — | model or employee |
| `ambiguous` | null | at least one | `ambiguity_reason`; `candidates` may list readings | model |
| `employee_entered` | required | none | `entered_by`, `entered_at` | employee |

- Silence is `missing`. It never becomes "untreated", a default grade or a default unit (**U-06**).
- Conflicting statements, including an explicit mid-message correction, are `ambiguous` until an employee decides (**U-09**).
- An employee resolves a field by entering a value, or marks it `missing` with a `null` value. Earlier model values and evidence remain in version history.
- There is no confidence score in the API. An uncalibrated number invites automatic trust.

## 5. Provenance and evidence
`Evidence` is `(communication_id, source, start, end, quote, role)`. Offsets count **Unicode code points**, zero-based and end-exclusive. JavaScript clients must not use them directly as UTF-16 indexes.

Model output is validated in this order, and any failure rejects the whole run, creating no partial draft:
1. The output matches `ExtractionProposal`. SKU, price, inventory, approval and `employee_entered` content is rejected.
2. Each proposed quote is found in the stated source at the stated `occurrence` (zero-based). The server computes offsets.
3. Extracted text values and ambiguous text candidates appear verbatim in a quote.
4. The server verifies `source[start:end] == quote` before storing.
5. Deterministic code applies approved conventions and runs the matcher.

**Limits.** A real quote does not prove a quantity, unit or measurement was read correctly, and nothing proves every line was found. Employees review against the original, and extraction accuracy needs labeled synthetic tests.

Each run stores provider, model, prompt and schema versions. v0.1 does not re-extract a communication that already has a request.

## 6. Quantity and unit
- Quantity and unit are separate tracked fields. A quantity is a positive decimal string with up to 9 integer and 6 fraction digits.
- Ranges ("10–12") are `ambiguous` with `range_given`. Other reasons: `conflicting_statements`, `multiple_interpretations`, `unrecognized_term`, `unclear_reference`, `unreadable`.
- `UnitCode` is a provisional closed list (**U-08**): `piece`, `sheet`, `linear_foot`, `board_foot`, `bundle`, `box`, `bag`, `roll`, `pallet`. An unrecognized unit is `ambiguous` with `unrecognized_term`.
- A bare count ("40 2x6x12") has a `missing` unit (**U-06**).
- The requested quantity and unit are never overwritten by a conversion. `UnitCheck` records any conversion with its approved rule, factor and result. Rounding is undecided, so a result needing rounding is left null (**U-08**).

## 7. Dimensions
- `dimension_text` keeps the wording ("2x6x12").
- `thickness`, `width` and `length` are separate fields, so "2x6" leaves length `missing`.
- A `Measure` has `raw`, `magnitude` (decimal string; "7/16" is "0.4375"), `unit` and `unit_basis`: `stated`, `yard_convention` (with `convention_rule_id`) or `unspecified` (unit null).
- The model may only report a stated unit. Only deterministic code applies a yard convention.
- Fractions that cannot be written exactly in six decimals are `ambiguous` with `unrecognized_term`.
- Position-to-axis reading of "AxBxC", unit conventions and nominal versus actual size are unapproved (**U-07**). Until then units stay `unspecified`, and the matcher reports those dimensions `not_resolved_in_request`. This limits matching quality for ordinary lumber shorthand.

## 8. Catalog candidates and match evidence
- Matching is deterministic, uses only the request's yard catalog and returns at most 10 ranked candidates. Catalog and matcher versions are stored.
- Each candidate has a `SkuSnapshot`, per-attribute evidence (`exact_match`, `synonym_match` with rule ID, `mismatch`, `not_resolved_in_request`, `not_defined_on_sku`) and a unit check.
- `status` is `not_run`, `no_candidate`, `single_candidate` or `multiple_candidates`. None implies a selection.
- Only an employee selects a SKU, including when there is one candidate (**U-11**). Any active SKU of the yard may be selected.
- Selecting against a stated attribute adds `selected_sku_attribute_mismatch`, which must be acknowledged.
- Changing any line field recomputes candidates and clears the selection, unless the same edit selects a SKU after the change.
- The catalog is read-only in this API. Loading it is out of scope (**U-19**).

## 9. Review and processing states
**Communication processing:** `queued → processing → completed | failed_retryable | failed_terminal`; `failed_retryable → queued`. A stored record implies the source is preserved.

| Outcome | Draft |
|---|---|
| `material_request` | Yes, even with no lines |
| `uncertain` | Yes, with `uncertain_classification` |
| Any class with extracted lines | Yes; lines are never discarded. Unless `material_request`, add `uncertain_classification` or `possible_follow_up` |
| `follow_up` or `non_request` without lines | No; stays in the inbox |
| Failed | No; stays in the inbox |

An employee may create an empty draft when processing has completed or failed and none exists. This corrects classification and extraction misses (**U-13**).

**Request review:**

| From | Action | To | Permission |
|---|---|---|---|
| none | extraction | `draft_ready` | system |
| none | manual creation | `draft_ready` | `request:create` |
| `draft_ready` | edit | `draft_ready` | `request:edit` |
| `draft_ready` | `approve_internal` | `internally_approved` | `request:approve_internal` |
| `draft_ready` | `decline` (reason) | `declined` | `request:decline` |
| `internally_approved`, `declined` | `reopen` (reason) | `draft_ready` | `request:reopen` |

Anything else is `409 invalid_state`. `needs_clarification` is reserved for a later version (**U-14**).

**Approval blockers** (active lines only): no active lines; any `ambiguous` field on a line or in job details; unresolved quantity or unit; no selected SKU; selected SKU inactive; unit incompatible with the SKU (`no_approved_conversion`, or a conversion with no exact result); a required warning not acknowledged. Other `missing` attributes do not block once an employee selects a SKU (**U-10**).

Blocker codes, in the same order: `no_active_lines`, `ambiguous_field`, `quantity_unresolved`, `unit_unresolved`, `sku_not_selected`, `sku_inactive`, `unit_incompatible`, `warning_not_acknowledged`.

`approval_blockers` in a response lists content blockers; acknowledgements are checked when approving. A blocked approval returns `422 approval_blocked` with the blockers.

**Warnings** are computed from current facts. All v0.1 codes require acknowledgement. A `warning_id` changes if its condition changes. A warning arising after approval is shown but does not revoke the approval.

## 10. Edits and version history
- `version` starts at 1. Every accepted edit call or decision adds exactly one version.
- Each version is an append-only revision: full content, resulting state, change type, actor, time, note and operations.
- Mutations send `expected_version`. A mismatch returns `409 version_conflict` with `current_version`; nothing is merged.
- Edits are typed operations applied in order, all or none. Approved and declined requests cannot be edited without reopening.
- An unknown line or SKU ID, including another yard's, returns `422` and reveals nothing.
- Model proposals are never overwritten: revision 1 keeps them.

## 11. Internal approval is not sending
- Approval records the **reviewed** version (`approved_version` equals `expected_version`; the request then advances one version) and the SHA-256 of its content, canonicalized as in section 1.
- At approval the server re-checks blockers against the current catalog and warnings.
- Reopening revokes the approval and keeps the record.
- Approval creates no message, quote, export, order or reservation. v0.1 has no send endpoint, send permission or outbound adapter.
- A future send needs its own endpoint, permission, explicit confirmation, idempotency key and audit record, and must reference an active approval.

## 12. Authentication and authorization
Principals are employees and adapter integrations. Workers use no public API.

**Employees** (mechanism **U-01**; proposed cookie session):
- `Secure`, `HttpOnly`, `SameSite` session cookie; CSRF token on every mutation; TLS only.
- Sessions expire and can be revoked. Deactivation or permission removal takes effect on the next request.
- Login, recovery and MFA endpoints are not specified until U-01 is decided. This blocks any non-local use.

**Adapters** (**U-02**; proposed bearer token):
- One credential binds one yard, integration and channel; stored hashed, revocable, rotatable.
- It can call intake only. Provider signature verification happens in the adapter.

**Rules:**
- Deny by default. Check authentication, yard membership, permission, then resource ownership.
- `401` unauthenticated. `404` for a non-member or another yard's resource. `403` for a member lacking permission.
- `GET` never changes business state. Notification links carry no authority.
- Permissions: `communication:read`, `communication:read_original`, `request:read`, `request:create`, `request:edit`, `request:approve_internal`, `request:decline`, `request:reopen`, `catalog:read`. Role bundles and self-approval: **U-05**.
- `communication:read` includes the parsed text; `communication:read_original` controls the raw file.
- Errors and logs exclude source content and credentials.
- Audit intake attempts, original downloads, every state or content change and denied mutations. `AuditEvent` has no v0.1 read endpoint.

## 13. API surface
Exact parameters, bodies and status codes are in `openapi.yaml`. `Y` is `/api/v1/yards/{yard_id}`.

| Method and path | Purpose |
|---|---|
| `GET /api/v1/health` | Health, unauthenticated |
| `POST /api/v1/inbound/events` | Adapter intake |
| `GET /api/v1/me` | Employee, memberships, CSRF token |
| `GET Y/inbox` | Inbox, newest first, cursor paged |
| `GET Y/communications/{communication_id}` | Record and status |
| `GET Y/communications/{communication_id}/original` | Original bytes |
| `POST Y/communications/{communication_id}/requests` | Manual draft |
| `GET Y/requests/{request_id}` | Review draft |
| `PATCH Y/requests/{request_id}` | Edit |
| `POST Y/requests/{request_id}/decisions` | Approve, decline, reopen |
| `GET Y/requests/{request_id}/revisions` | History |
| `GET Y/requests/{request_id}/revisions/{version}` | One version |
| `GET Y/skus` | Catalog search |

**Errors** use `ErrorResponse`:

| Status | Codes |
|---|---|
| 401 | `unauthenticated` |
| 403 | `forbidden` |
| 404 | `not_found` |
| 409 | `idempotency_conflict`, `version_conflict`, `invalid_state`, `request_already_exists` |
| 413 | `payload_too_large` |
| 422 | `validation_failed`, `approval_blocked` |
| 503 | `temporarily_unavailable` |

## 14. Changes from the v1 draft

| v1 draft | v0.1 proposal | Why |
|---|---|---|
| `yard_id`, `idempotency_key` in the inbound event | Derived by the server | A payload must not choose its tenant or defeat deduplication |
| Adapter-supplied `source_reference` | Adapter uploads raw bytes | Prevents pointing at unverified or foreign objects |
| One `event_id` | Message identity plus optional delivery ID | Redeliveries may have new event IDs |
| All channels, `media`, `transcript` | Email only, attachment metadata | Approved slice; other channels need their own event types |
| `recipient` | `recipients` list | Email has several |
| Contact match evidence on messages | Deferred | Contact matching is outside the slice |
| `request_type`, `warnings`, model versions in extraction output | `classification`, computed warnings, server-recorded run information | The model should not describe itself or set review warnings |
| Several source communication IDs per request | One origin plus related IDs | Later messages never change a request |
| `body_text` and `subject` on a general message | Immutable record separated from mutable status | Enforces preservation |
| Flat item values, `null` for absent | Tracked fields with four states | Distinguishes absent, unclear and entered |
| `missing_fields`, `ambiguity_reasons` | Per-field state and reason | One source of truth |
| `confidence` | Removed | Uncalibrated |
| `dimensions` string | Raw text plus three measures | Structured without losing wording |
| Unit `"pieces"` | `UnitCode` `piece`, wording kept in evidence | Controlled vocabulary |
| `candidate_skus` in extraction output | Removed from model output; deterministic `MatchResult` | AI must not choose SKUs |
| `normalized summary` | Removed | A free summary can introduce unstated specifications |
| Request states `new → processing → draft_ready` | Processing moved to communication | A request exists only once there is a draft |
| `needs_clarification` | Reserved | Deferred |
| — | `reopen`, manual draft, revisions, SKU search, `/me` | Needed to correct mistakes and review |
| Yard-less request and quote paths | Yard-scoped paths | Uniform tenant checks |
| `POST .../decision` including assign and clarify | `POST .../decisions`: approve, decline, reopen | Approved slice |
| `QuoteDraft` with every request | Deferred; request is the draft | No pricing or sending yet |
| Quote send and follow-up endpoints | Not in v0.1 | Separate authorized actions, designed later |

**Follow-on updates if approved** (not made in this change): ARCHITECTURE.md processing states; `tests/fixtures/synthetic_yard.json` (UUIDs, structured measures, unit codes, catalog fields); backend and frontend work.

## 15. Carried forward, not part of v0.1
Retained from the v1 draft for later versions. Nothing below is specified exactly or scheduled by this proposal.

**Entities:** Yard (name, timezone, business hours, data freshness policy, pricing_enabled, notification preferences, integration references); User/Employee (display name, email, role, status, notification preferences, explicit permissions); Contact/Contractor (names, phone/email identifiers, match evidence, known-account evidence, consent and suppression state); InventorySnapshot/Line (source, received_at, effective_at, freshness state, SKU, on_hand, allocated, held, safety_stock, unavailable, unit, parsing/mapping status); PriceBook/AccountPriceRule (source, effective_at, account scope, SKU/category, price, unit, discount/markup, fees/tax, rule precedence, validation/freshness state); InventoryAssessment (request, snapshot, SKU, requested quantity, ATP, coverage percent, component breakdown, source timestamp, freshness, limitations); QuoteDraft (request, customer/account, pricing mode, currency, price source/effective time, lines, discounts/fees/tax, provisional total, warnings, state, version); FollowUpEvent (quote, employee, template, channel, time, delivery status, customer response, consent/suppression evaluation). Currency uses ISO codes and decimal arithmetic.

**Inventory rules.** Use the yard's documented field semantics. Where components are separately represented:
`ATP = on_hand - allocated - held - safety_stock - unavailable`

Do not subtract a component twice if the ERP's available/on-hand field already accounts for it. For requested quantity Q > 0:
`coverage_percent = min(1, max(0, ATP / Q)) * 100`

Only calculate when SKU, units, and required inputs are understood. Show components and data time. Coverage is not fulfillment probability.

**Pricing rules**
- Yard pricing toggle is OFF until validated.
- OFF does not disable request preparation; price is null and display says “Not calculated.”
- ON resolves approved account price rules deterministically.
- Store source price book, effective timestamp, account tier/rule, conversions, discounts, fees/taxes, rounding, and line extensions.
- Missing/stale/conflicting rules require review; model never invents a price.

**Quote lifecycle:** draft → internally_approved → sent → revised / customer_accepted / customer_declined / expired_cancelled / converted_to_order (only when yard confirms) / failed_retry.

**Later endpoints:** `POST .../quotes/{quote_id}/send` and `.../manual-follow-up`.

Internal approval is not a customer-facing send, ERP order, inventory reservation, or delivery commitment.

## 16. Unresolved decisions
"Blocks" means implementation of that area should not start until decided.

| ID | Question | Proposed default | Blocks |
|---|---|---|---|
| U-01 | Employee login: managed identity provider or first-party; session lifetime; MFA | Managed provider, cookie session | Authentication |
| U-02 | Adapter auth: bearer token or signed requests with replay window | Bearer token over TLS | Intake |
| U-03 | Which stable message ID will the pilot's mail path provide? Forwarding may provide none | Mailbox-provider ID | Live intake (synthetic work can proceed) |
| U-04 | Retention, deletion requests versus immutability, encryption, storage write lock, quarantine access | Keep all synthetic data; decide before live data. Quarantined deliveries are operator-only, although employees must acknowledge the warning | Live data |
| U-05 | Roles; may an editor approve their own edits? | Explicit permissions; self-approval allowed | Authorization setup |
| U-06 | Is a bare count of dimensional lumber "pieces"? | No: unit missing, employee enters it | Extraction, review effort |
| U-07 | Dimension conventions: axis order, units, nominal or actual | Axis by position; units unspecified until the yard approves rules | Matching quality |
| U-08 | Unit list, conversions, rounding; ratios such as 1/12 are not expressible as exact decimal factors | Listed codes; exact conversions only | Matching |
| U-09 | May an explicit correction resolve automatically? | No: ambiguous | Extraction |
| U-10 | May non-stock lines be approved? Which missing attributes should block (e.g. treatment when an untreated SKU is selected)? | No non-stock approval; missing attributes do not block | Approval |
| U-11 | Preselect a sole candidate? | No | Matching, UI |
| U-12 | Replies with materials: new draft or amendment? | New flagged draft | Request creation |
| U-13 | Should `uncertain` create drafts? | Yes, flagged | Processing |
| U-14 | When to add clarification, assignment and notes | After the core path passes tests | — |
| U-15 | Keep `reopen`? Who holds it? | Keep, separate permission | Approval |
| U-16 | Limits (proposed 25 MB original, 200,000 body characters, 500 lines) and idempotency retention | 24 hours for employee keys; message identity permanent | Intake |
| U-17 | v1 quote lifecycle repeats `internally_approved` | Resolve when quotes are designed | — |
| U-18 | Can one email need several requests (multiple jobs)? | One per communication | Data model |
| U-19 | Source and loading of the pilot catalog and synonym rules | Seeded synthetic data | Matching |
| U-20 | Automatic retry count, and employee-triggered reprocessing | 3 attempts; no manual reprocess | Workers |
