# Counter Copilot V4 — Data Contract v0.1 (revised proposal)

**Status: revised proposal for independent review. Not approved, not frozen, not implemented.**

This revision applies the owner decisions of November 26, 2026 (DECISIONS.md, D-014). Those decisions are approved. The contract as a whole (D-013) is not.

It narrows the first contract to one slice and makes it exact:

> synthetic email → preserved original → parsing → classification and extracted lines → grounding → catalog comparison → review draft → employee edit, internal approval or decline

Any change must be proposed in DECISIONS.md, approved by the project owner, and reflected across code and tests.

| Artifact (under `contracts/v0_1/` except this document) | Authority |
|---|---|
| This document | Behaviour, and rules that need stored data |
| `models.py` | Request, response, storage and model-output shapes (Pydantic) |
| `openapi.yaml` | HTTP surface, generated from `models.py` and `api.py` |
| `extraction-proposal.schema.json` | Model-adapter output, generated |
| `reference/` | Deterministic parsing, grounding and comparison, executable |
| `examples/`, `fixtures/`, `benchmark/` | Synthetic payloads and cases |
| `qa/matrix.json` | The 57 QA tests and how far the contract covers each |

If they disagree, that is a defect to fix before approval. **U-nn** marks a decision that is still open (section 17).

Two kinds of rule appear here. Rules that one payload can show are enforced by the models, and most also by the generated schema. Rules that need stored data (ownership, transitions, idempotency, locking, auditing) are requirements on a backend that does not exist yet and **have not been tested**.

**Out of scope for v0.1:** SMS, voice, individual attachment download or parsing, contact matching, inventory, pricing, quote entities and sending, follow-up sending, assignment, clarification, notes, notifications, body search, catalog import, ERP export, orders and reservations.

## 0. Conventions
- Every business record has a `yard_id`. References between records stay within one yard, enforced in the database as well as the application.
- Internal identifiers are UUIDs. Timestamps are UTC with offset zero. The yard timezone is for display.
- Original wording is preserved. Strings are not trimmed or Unicode-normalized on the way in.
- Quantities and measurements are decimal strings, never JSON numbers.
- Unknown JSON keys are rejected in requests and model output.
- `schema_version: "0.1"` marks payloads produced by an adapter or model, and the request detail.
- A person is always `PersonRef {user_id, display_name, active}`. A deactivated user keeps the name and has `active: false`.

## 1. Intake, identity and idempotency
The intake endpoint takes a multipart request: `metadata` (`InboundEmailEvent`) and `original` (the raw `message/rfc822` bytes).

**Metadata carries transport facts only:** `channel`, `external_message_id`, `external_event_id`, `provider_thread_id`, `received_at`, `envelope_recipients`, `provider_metadata`, `original_sha256`. Sender, header recipients, subject, body, reply headers and attachments are derived from the bytes. Supplying them, or a `yard_id`, idempotency key or storage reference, is rejected. The yard and integration come from the adapter credential.

**Order of processing:** authenticate → size limit → hash check → bounded parse → mailbox check (`envelope_recipients` must include a configured yard mailbox) → identity → store the original → one transaction for record, job and links → respond.

- Identity is `(yard_id, integration_id, external_message_id)`, unique in the database. `integration_id` stays the same when credentials rotate.
- `external_message_id` is assigned by the mail source and is identical on redelivery. The RFC `Message-ID` is sender-controlled and is only a hint (**U-03**).
- `external_event_id` describes a delivery attempt and never affects identity.

**Content fingerprint** (`reference/email_derivation.content_fingerprint`). SHA-256 of UTF-8 JSON with sorted keys, no insignificant whitespace and unescaped non-ASCII, over: `sender` (address), `recipients` (sorted addresses), `subject`, `body_text`, `attachments` (sorted SHA-256 values). No case folding. Added transport headers, display names, receipt time and provider metadata are excluded. A message that could not be parsed is fingerprinted as the SHA-256 of its raw bytes.

| Delivery | Result |
|---|---|
| New identity | Preserve the original, create record and processing job atomically, `202` |
| New identity, within limits, cannot be parsed | Preserve it, `202`, `failed_terminal` / `parse_failed` |
| Same identity, same fingerprint | No new record or job, `200`, `duplicate: true`. The first original is kept; the attempt and its raw digest are recorded |
| Same identity, different fingerprint | `409 conflicting_redelivery`. The new bytes are quarantined; the first record is untouched and flagged `has_conflicting_redelivery` |
| Forbidden metadata keys, `original_hash_mismatch` or no configured mailbox | `422`, quarantine and a security audit entry |
| Over any limit in section 15 | `413`. The application **stores nothing**: no record, original, quarantine copy, job or attempt row. The adapter keeps the source and alerts an operator |
| Different identity, same RFC Message-ID or fingerprint in the yard | Accept and set `possible_duplicate_of`. Never auto-merge |

Success is returned only after the original and the job are durable. The adapter keeps the source until it receives `200`, `202` or `409`, retries network errors, `429` and `503`, and holds `401`, `413`, `415` and `422` for an operator.

**Delivery attempts** (`DeliveryAttempt`) record every authenticated attempt within the limits. Unauthenticated attempts go to a security log (`SecurityLogEntry`) holding no payload or credential.

**Employee mutations** require an `Idempotency-Key`, scoped to `(yard_id, user_id, method, path)` and kept for 24 hours. After authorization, the key is checked before the version. A repeat of a committed call with the same body returns the stored response; a different body returns `409 idempotency_conflict`; a repeat while the first call is still running returns `409 idempotency_in_progress`. Failed calls are not stored. After `503` or a lost response the client retries with the same key.

**Message identity retention is undecided.** Permanent retention is not approved. How long identities, originals and quarantined bytes are kept must be settled under **U-04** before any live customer data is used. Deduplication only holds while the identity is kept.

## 2. Preserved original and parsed content
- The original bytes and `CommunicationRecord` are written once. No API updates or deletes them.
- The server computes the digest and size and chooses a yard-prefixed private storage key. Storage keys never appear in the API.
- `CommunicationStatus` (processing, classification, flags, handling) is stored separately and may change.
- **The original bytes are the authority.** `body_text` and `subject` are produced from them by a versioned parser and are the text that evidence points into.
- Email content is untrusted. Clients render it as plain text; the extraction step treats it as data, never instructions.
- Retention, legal deletion and storage-level write protection: **U-04**.

### Parser `email-derive-1` (`reference/email_derivation.py`)
- Deterministic and pure. The only change to decoded text is CRLF → LF: no trimming, no Unicode normalization.
- Body: the first inline `text/plain` part; otherwise text derived from the first inline `text/html` part (`body_source: text_html_derived`, informational warning `html_derived_text`); otherwise empty (`none`). HTML conversion does not interpret CSS, so hidden text can appear.
- Every other leaf part is an attachment, including inline images and small files. The HTML twin of the chosen body inside `multipart/alternative` is not. An attached message is one attachment; its inner parts are not read as body or attachments, but count toward MIME limits.
- Quoted and forwarded history is recognised heuristically (`>` lines, reply attributions, original or forwarded blocks, HTML blockquotes) and returned as `quoted_spans`.
- **Unreadable mail** (`parse_failed`, all parsed fields null): undecodable headers, encoded words, charset or transfer encoding; damaged base64; a NUL character; missing multipart boundaries; no usable sender address; any other parser error. There is never a partial result and no draft from a failed parse.
- Limits are enforced while parsing (section 15). The 30-second parse limit is checked between steps; a service must also run the parser where it can be stopped.
- Some oversized header-derived values are cut or skipped rather than rejected; see section 16.

### Attachments
v0.1 has **no individual attachment download, extraction or per-part processing**. Attachments are listed as server-derived metadata (`part_id`, filename, media type, size, digest, disposition, content ID, `not_processed`) and exist only inside the complete original. An authorized employee downloads the complete original through the yard-scoped route; it streams through the API as an attachment with `Content-Disposition`, `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`, and is audited. A request whose message has any attachment carries exactly one grouped `unprocessed_attachment` warning that must be acknowledged.

## 3. Processing, drafts and related messages
**Processing:** `queued → processing → completed | failed_retryable | failed_terminal`; `failed_retryable → queued`. A stored record means the source is preserved. Failures carry a fixed code, a fixed safe message, an attempt count, start time and next retry time. `parse_failed` is terminal. Retry count and reprocessing: **U-20**.

| Outcome | Draft |
|---|---|
| `material_request` | Yes, even with no lines |
| `uncertain` | Yes, with `uncertain_classification` (**U-13**) |
| `follow_up` with lines | Yes, with `possible_follow_up`. Lines are never discarded |
| `follow_up` without lines, not reliably linked | No; stays in the inbox |
| Reliably linked reply without lines, not `non_request` | The system may create an empty linked draft so an employee can recognise and decline it |
| `non_request` | No. A `non_request` with lines is rejected as a structural failure |
| Failed | No; stays in the inbox |

An employee may create an empty draft when processing has completed or failed, none exists and the item is not marked handled. An empty draft can never be approved.

**One communication yields at most one origin request.** Nothing is split or merged automatically.

**Linking.** Messages are linked only by reply headers (`In-Reply-To`, `References`) matching a Message-ID in the same yard, or by the same provider thread ID. A matching sender never creates a link.

When a linked newer message arrives:
- the earlier request keeps its content, version, state and approval;
- it lists the message in `related_messages` and gains a computed `newer_related_message` warning that must be acknowledged before any later approval;
- an approval already given is **not** revoked; the request stays approved and flagged;
- a newer message containing materials creates a separate draft carrying `possible_follow_up`.

**Same sender.** An unlinked message from the same sender within seven days may raise `possible_follow_up_same_sender`. It is informational, lists no related IDs, blocks nothing and needs no acknowledgment.

**Multiple jobs.** The model reports multiple jobs only by quoting evidence (`multiple_jobs_evidence`), which raises `multiple_jobs_detected`. Conflicting job details are `ambiguous` when the model cites the conflict. The employee resolves the message to one job through edits and acknowledgment, or declines it. Detection is not guaranteed.

## 4. Review draft
A `RequestDetail` holds `content` (lines and job details), computed `warnings` and `approval_blockers`, the approval record, the last decision, the extraction run information and related messages. The request is the review draft; there is no quote entity.

Each `MaterialLine` has a stable `line_id`, unique `position`, `origin` (`model` or `employee`), `status` (`active` or `removed`), verbatim `raw_wording`, `source_evidence`, `employee_source_spans`, seven tracked fields (`product`, `quantity`, `unit`, `dimensions`, `species`, `grade`, `treatment`) and a `match`.

- Model lines require source wording and evidence. `raw_wording` equals the quote of the first source evidence item and is never edited.
- Employee-added lines have no source wording or AI proposal. An employee may cite spans of the originating message; the server verifies them and keeps them apart from AI evidence.
- Removed lines are retained, record who removed them and why, and can be restored. Removing a model line raises `model_line_removed`.
- Job details: `fulfillment_method` (`delivery` or `pickup`), `requested_date_text` (as written; "Friday" is not resolved to a date), `delivery_address`, `job_reference`, `notes`.
- All evidence on a request cites its originating message.
- `inventory_status` and `pricing_status` are fixed at `not_assessed` and `not_calculated`.

## 5. Field states
Each state is its own schema, selected by `state`.

| State | Value | Evidence | Extra | Set by |
|---|---|---|---|---|
| `extracted` | required | at least one `supports` | — | model, after grounding |
| `missing` | null | none | — | model, or never supplied |
| `ambiguous` | null | at least one | `ambiguity_reason`; `candidates` may list readings | model or grounding |
| `employee_entered` | required | only when a candidate was chosen | `entered_by`, `entered_at`, `resolution` | employee |
| `employee_cleared` | null | none | `cleared_by`, `cleared_at` | employee |

- Silence is `missing`. It never becomes "untreated", a default grade or a default unit.
- Conflicting statements, including explicit corrections, are `ambiguous` until an employee decides.
- Every model field keeps a read-only `proposal` (state, value, candidates, reason, evidence, run ID, grounding outcome and rules). It cannot be selected or edited. A field still in a model state must equal its proposal.
- `set_*` operations always carry a value. `clear_field` is the only way to empty a field. A cleared quantity or unit blocks approval.
- `choose_candidate` records the chosen index and keeps the evidence; the value must be that proposal's candidate.
- AI-proposed values are never presented as employee-confirmed before approval. There is no per-line "reviewed" flag: approval is sign-off on the whole visible draft.
- There is no confidence score.

## 6. Evidence and grounding
`Evidence` is `(communication_id, source, start, end, quote, role)`. Offsets count **Unicode code points**, zero-based and end-exclusive; `source[start:end] == quote` must hold. JavaScript clients must not use them directly as UTF-16 indexes. `source` is `subject` or `body_text`.

The model proposes quotes with a zero-based `occurrence` (overlapping occurrences each count); the server computes offsets. Raw model output is stored apart from the grounded result (`ExtractionRunRecord`), is never returned by the API and is never copied into a draft. Each run records provider, model, prompt, schema, parser, grounding and lexicon versions.

### Structural failure: the whole run is rejected
`invalid_schema`, `unknown_key` (including any SKU, price, inventory or approval content), `line_without_source_evidence`, `quote_not_found` (missing or wrong occurrence) and `non_request_with_lines`. No draft is created, not even a partial one.

### Unsupported value: the field is downgraded
`reference/grounding.py` (`ground-1`, word lists `en-1`) checks every proposed value. A value the text does not support becomes `ambiguous` with no value, its evidence kept, and the rule recorded. Grounding never creates a value, never upgrades a state and never invents a candidate. A `missing` field stays missing.

| Check | Result |
|---|---|
| Value not found in a supporting quote, or found only outside the line's source spans | `unsupported_by_source` |
| Evidence marked `conflicts` | `conflicting_statements` |
| Support only in quoted or forwarded history | `quoted_history_only` |
| Value negated in the same clause (units, fulfillment, line text, quantity, dimensions) | `negated` |
| Correction wording on the line with competing readings (quantity, unit, dimensions, treatment) | `conflicting_statements` |
| Correction wording anywhere in new text while both fulfillment methods are named | `conflicting_statements` |
| Quantity is a range or one-sided bound ("at least 20", "over 20", "20 or more") | `range_given` |
| Quantity is approximate ("about 20", "20 or so", "20 (approx)") | `approximate` |
| Quantity is relative ("20 more", "add 20") | `relative_quantity` |
| "a", "an", "couple", "few", "some", "dozen", "several" | `number_word` |
| The same quantity restated differently ("twenty (10)"), or two different amounts of the same named thing on one line ("40 studs, 50 studs") | `conflicting_statements`, all readings |
| A value that needs more than six decimal places | `inexact_normalization` |
| Sizes written separately, or more than one written dimension on the line | `separate_measurements` |

Candidates survive only if every one is found in the evidence; otherwise they are all removed. Competing amounts that cannot be read leave the list empty rather than partial.

**Quantities.** Digits, thousands separators, decimals and the fixed English cardinal list are read. A quantity written as a fraction ("1/2 pallet") is not read and stays ambiguous. Number words are accepted only as well-formed cardinals ("one hundred and fifty"). Wording the reader cannot value exactly ("fifteen hundred", "2 thousand", "one and a half", "2 doz") leaves the field ambiguous. Numbers that are measurements or reference numbers are not counts.

**Text fields** must appear verbatim, as whole words, with the same letter case.

### Limits of grounding
Passing these checks proves the wording exists, not that it was understood, and nothing proves every line was found. An employee reviews against the original. Extraction accuracy needs labeled testing with a real model, which has not happened.

## 7. Quantity and unit
- Separate tracked fields. A quantity is a positive decimal string with up to 9 integer and 6 fraction digits.
- `UnitCode`: `piece`, `sheet`, `linear_foot`, `board_foot`, `bundle`, `box`, `bag`, `roll`, `pallet`.
- Only those names, in singular or plural ("linear feet", "board feet"), map to a unit. Everything else, including `pcs`, `LF`, `BF`, `lift`, `bunk`, `sticks` and a bare "feet", stays ambiguous until an authorized yard mapping exists. None exists.
- A bare count ("40 2x6x12") has a `missing` unit. Counts never imply pieces.
- There are **no unit conversions**.

## 8. Dimensions
- One field, `dimensions`: the written text plus components **in written order**. Each component has `raw`, an exact `magnitude` (`7/16` → `0.4375`, `92-5/8` → `92.625`) and a `unit` only when written.
- Feet and inches spellings and symbols are recognised (`ft`, `foot`, `feet`, `'`, `′`, `in`, `inch`, `inches`, `"`, `″`, curly quotes).
- No thickness, width or length axes. No yard conventions. No assumed or converted units.
- The server derives components from text. An employee edits text only (`set_dimensions`); unreadable text is `422`.
- Sizes written separately ("2x4, 10 feet long") are ambiguous.

## 9. Catalog comparison and SKU selection
- Comparison is deterministic (`reference/comparison.py`), uses only the request's yard catalog and returns at most 10 candidates. Catalog and matcher versions are stored. How candidates are found and ranked is not specified by this contract.
- `status` is `not_run`, `no_candidate`, `single_candidate` or `multiple_candidates`. **None implies a selection.** Nothing is preselected, even a sole candidate. Only an employee selects, from the yard's active SKUs.
- Each SKU has its own ordered `dimension_designation`. The whole sequence is compared in order.

| Outcome | When | Acknowledge on the selected SKU |
|---|---|---|
| `exact_match` | Same values; text equal ignoring letter case; dimension units stated and equal | No |
| `synonym_match` | An approved yard synonym rule (none exist) | No |
| `unit_unconfirmed_equal` | Same dimension sequence, a unit unstated | No; shown as unconfirmed |
| `mismatch` | Different values | Yes: `selected_sku_attribute_mismatch` |
| `different_component_count` | Sequences differ in length | Yes: mismatch |
| `different_unit_not_compared` | Stated dimension units differ | Yes: `selected_sku_attribute_unverified` |
| `not_defined_on_sku` | Stated in the request only | Yes: unverified |
| `not_stated_in_request` | On the SKU only | Yes: unverified |

One warning per code per line. The unit check is `same_unit`, `different_unit` or `request_unit_unresolved`.

**Keeping and clearing a selection**
- A quantity change keeps it.
- A unit change keeps it and recomputes compatibility; an incompatible unit blocks approval.
- A change to product, dimensions, species, grade or treatment clears it and records `last_cleared_selection` (SKU, evidence, reason, changed fields, person, time, version), unless a new SKU is selected in the same edit. Operations apply in order, so the `select_sku` must follow the change.
- The evidence at selection time is kept. Every read also returns a live evaluation (`current`) with `sku_active`, `sku_changed` and `catalog_stale`. A changed SKU raises `selected_sku_changed`.
- An inactive SKU cannot be selected or approved. No non-stock approval.
- SKU search can preview the comparison for a given line. It selects nothing.

The catalog is read-only in this API; loading it is out of scope (**U-19**).

## 10. Warnings and approval blockers
Warnings are computed from current facts, carry a typed target and never embed email content. `warning_id` changes if the condition changes.

| Warning | Acknowledge |
|---|---|
| `selected_sku_attribute_mismatch`, `selected_sku_attribute_unverified`, `selected_sku_changed` | Yes |
| `newer_related_message`, `possible_follow_up` | Yes |
| `possible_duplicate`, `conflicting_redelivery` | Yes |
| `uncertain_classification`, `multiple_jobs_detected` | Yes |
| `possible_correction_language`, `uncited_quantity_text`, `evidence_in_quoted_text` (heuristics) | Yes |
| `overlapping_line_evidence`, `model_line_removed` | Yes |
| `unprocessed_attachment` (one, grouped) | Yes |
| `possible_follow_up_same_sender`, `html_derived_text` | No; informational |

The three heuristic warnings are marked `heuristic: true`. They are signals, not guarantees. When deciding, an employee may mark them as false positives; this is recorded so the rules can be evaluated.

**Blockers** (active lines only), one per underlying issue: `no_active_lines`, `ambiguous_field` (line or job detail), `quantity_unresolved`, `unit_unresolved`, `sku_not_selected`, `sku_inactive`, `unit_incompatible`, `warning_not_acknowledged`. An ambiguous quantity or unit yields only its `_unresolved` blocker. Other `missing` attributes do not block once a SKU is selected, but they raise the unverified-attribute warning where the SKU defines them.

`approval_blockers` in a response lists content blockers; acknowledgments are checked when approving.

**Approval requires:** at least one active line; every active line with a resolved quantity and unit and an employee-selected, active SKU with a compatible unit; no ambiguity on any active line or job detail; every required warning acknowledged.

## 11. Review states, edits and history
| From | Action | To | Permission |
|---|---|---|---|
| none | extraction | `draft_ready` | system |
| none | manual creation | `draft_ready` | `request:create` |
| `draft_ready` | edit | `draft_ready` | `request:edit` |
| `draft_ready` | `approve_internal` | `internally_approved` | `request:approve_internal` |
| `draft_ready` | `decline` (reason) | `declined` | `request:decline` |
| `internally_approved`, `declined` | `reopen` (reason) | `draft_ready` | `request:reopen` (**U-15**) |

Anything else is `409 invalid_state` with the current state.

- `version` starts at 1. Every accepted edit call or decision adds exactly one version.
- Each version is an append-only revision: content, resulting state, change type, actor, time, note, operations, per-field before and after, and any decision record.
- Mutations send `expected_version`. A mismatch is `409 version_conflict` naming the current version, who changed it and when. Nothing is merged and no employee edit is overwritten.
- Edits are typed operations applied in order, all or none. Approved and declined requests cannot be edited without reopening.
- An unknown line or SKU ID, including another yard's, returns the same `422` and reveals nothing.
- Revision 1 keeps the model's grounded proposal; later edits never overwrite it.

## 12. Internal approval is not sending
- Approval locks the request, recomputes blockers and warnings against current facts and the current catalog, and fails with `422 approval_blocked` if anything is unmet. A warning that appeared since the employee looked therefore stops a stale approval.
- It records the **reviewed** version: `approved_version` equals `expected_version`, and the request advances to `approved_version + 1`.
- `content_sha256` covers the `content` of the reviewed version, serialized as in section 1 (sorted keys, no insignificant whitespace, unescaped non-ASCII), with every `match.selection.current` removed because that block is computed on read.
- The approval keeps each acknowledged warning as the approver saw it.
- Reopening revokes the approval and keeps the record. A warning that arises after approval is shown but does not revoke it.
- Approval creates no message, quote, export, order or reservation. v0.1 has no send endpoint, send permission or outbound adapter.
- A future send needs its own endpoint, permission, explicit confirmation, idempotency key and audit record, and must reference an active approval.

## 13. Mark handled
`POST Y/communications/{communication_id}/handling` with `mark_handled` or `reopen`.

- Only a **completed `non_request` with no material request** can be marked handled. Failed, queued or processing items and follow-ups are never eligible, with or without a note.
- Reasons: `not_a_request`, `handled_outside_system`, `duplicate`, `spam`, `other` (note required).
- Needs `communication:handle`, CSRF, an idempotency key and `expected_handling_version`. History is append-only and audited.
- It can be reopened, with a reason. It deletes nothing and clears no linked warning.
- A manual draft requires reopening first.

## 14. Authentication, authorization and API
Principals are employees and adapter integrations. Workers use no public API.

**Employees** (mechanism **U-01**; proposed cookie session): `Secure`, `HttpOnly`, `SameSite` session cookie; CSRF token on every mutation (`403 csrf_failed`); TLS only. Sessions expire and can be revoked. Deactivation or permission removal takes effect on the next request. The browser reaches the API through a same-origin proxy; there is no cross-origin access. A `401` means sign in again, keeping no source content on screen. A sign-in stub is for local synthetic development only. Login, recovery and MFA endpoints are not specified until U-01 is decided, which blocks any non-local use.

**Adapters** (**U-02**; proposed bearer token): one credential binds one yard, integration and channel; stored hashed, revocable, rotatable. It can call intake only. Provider signature verification happens in the adapter.

**Rules**
- Deny by default: authentication, yard membership, permission, then resource ownership.
- `401` unauthenticated. `404` for a non-member or another yard's resource. `403` for a member lacking permission.
- `GET` never changes business state. Notification links carry no authority.
- Permissions: `communication:read`, `communication:read_original`, `communication:handle`, `request:read`, `request:create`, `request:edit`, `request:approve_internal`, `request:decline`, `request:reopen`, `catalog:read`. Role bundles and self-approval: **U-05**.
- `communication:read` includes parsed text; `communication:read_original` controls the raw file.
- Errors and logs exclude source content and credentials.
- Audit intake attempts, quarantines, original downloads, handling, every state or content change and denied mutations (`AuditAction`). `AuditEvent` has no v0.1 read endpoint.

Exact parameters, bodies and status codes are in `openapi.yaml`. `Y` is `/api/v1/yards/{yard_id}`.

| Method and path | Purpose |
|---|---|
| `GET /api/v1/health` | Health, unauthenticated |
| `POST /api/v1/inbound/events` | Adapter intake |
| `GET /api/v1/me` | Employee, memberships, CSRF token |
| `GET Y/inbox` | Inbox, cursor paged |
| `GET Y/inbox/counts` | Queue sizes |
| `GET Y/communications/{communication_id}` | Record, status, handling history |
| `GET Y/communications/{communication_id}/original` | Complete original |
| `POST Y/communications/{communication_id}/handling` | Mark handled or reopen |
| `POST Y/communications/{communication_id}/requests` | Manual draft |
| `GET Y/requests/{request_id}` | Review draft |
| `PATCH Y/requests/{request_id}` | Edit |
| `POST Y/requests/{request_id}/decisions` | Approve, decline, reopen |
| `GET Y/requests/{request_id}/revisions` | History |
| `GET Y/requests/{request_id}/revisions/{version}` | One version |
| `GET Y/skus` | Catalog search |

**Inbox.** Newest first by `ingested_at`, then `communication_id`. Cursors are bound to the yard and filters. The default view, `needs_review`, shows items whose handling is open and that are not an approved or declined request without attention flags. `q` searches **sender and subject only**; body search is deferred. Request summaries and the `review_state` and `has_draft` filters need `request:read`.

**Errors** use `ErrorResponse`. Locations are JSON Pointers.

| Status | Codes |
|---|---|
| 401 | `unauthenticated` |
| 403 | `forbidden`, `csrf_failed` |
| 404 | `not_found` |
| 409 | `idempotency_conflict`, `idempotency_in_progress`, `version_conflict`, `invalid_state`, `request_already_exists`, `conflicting_redelivery` |
| 413 | `payload_too_large` |
| 415 | `unsupported_media_type` |
| 422 | `validation_failed`, `approval_blocked`, `original_hash_mismatch` |
| 429 | `rate_limited` |
| 503 | `temporarily_unavailable` |

**Compatibility.** Within v0.1 changes are additive. Requests are strict. Clients tolerate unknown response keys and unknown enum values. A breaking change needs a new `schema_version`.

## 15. Limits (U-16, provisional and testable)
| Limit | Value |
|---|---|
| Raw email | 25,000,000 bytes |
| Body text | 200,000 characters |
| Lines per proposal or request | 500 |
| Attachments | 100 |
| MIME parts | 200 |
| MIME nesting depth (root is 1) | 20 |
| Headers | 256 KB, read as 256,000 bytes |
| Parse time | 30 seconds |
| JSON body | 1 MB, read as 1,000,000 bytes |
| Evidence items per field | 20 |
| Candidates | 10 |
| Edit operations per call | 200 |
| Employee idempotency keys | 24 hours |

The values are published in `openapi.yaml` (`info.x-limits`). The JSON limit applies to HTTP JSON bodies, including intake metadata. No limit on model output size has been approved.

## 16. Interpretations and known limitations

**Interpretations made while implementing. Reviewers should confirm or change them.**
- 1 MB and 256 KB are read as decimal, matching 25 MB = 25,000,000 bytes.
- "500 lines" means material lines in a proposal or request, not lines of email text.
- "Selected in the same edit" (N-4) is implemented as a `select_sku` that follows the change in the operation list; one listed before the change is cleared by it.
- `possible_duplicate` and `conflicting_redelivery` require acknowledgment (from the reviewed plan's table; the owner list does not name them).
- `html_derived_text` is informational.
- "an", "dozens" and "several" are treated like the five approved vague words. Added words for approximation, bounds, dozens, large scales and fractions were not individually approved; they only make a field more cautious.
- "over" directly after "send", "sending", "sent", "bring" or "ship" is read as "send them over", not as a bound.
- A fulfillment correction downgrades the field when correction wording appears anywhere outside quoted history, because job details have no line span.
- Dimension text allows the plural "s" of unit names; treatment words ("treated", "PT", "untreated" and variants) are used only to notice a corrected treatment.
- Grounding matches text case-sensitively; catalog comparison ignores case.
- `SkuSnapshot` includes `product` so that product can be compared.
- Exceeding the parse time returns `413`.
- Mark-handled reasons come from the reviewed plan.
- "Resolve to one job" is implemented as acknowledgment plus ordinary edits; conflicting job details are downgraded only when the model cites the conflict.
- The `content_sha256` input excludes the computed-on-read block (section 12).

**Known limitations**
- Competing amounts on one line are noticed through a conflict the model cites, listed correction wording, a bracketed restatement or the same following noun. Other competing amounts ("40 studs, maybe go 50") can pass if the model picks one.
- The word lists are finite: hedged, bounded or relative wording outside them can pass. "send me over 20" is flagged although it is usually not a bound. "20 by 5" is treated as a size.
- Fulfillment correction is noticed only with listed correction wording; two methods named without it can pass if the model cites one.
- A number inside a date or address can pass if the model cites it as a quantity.
- Correction wording does not by itself downgrade product, species, grade or job text. A correction in quoted history warns only when quoted text is cited.
- The parser cuts display names and filenames to 500 characters, content IDs to 998 and media types to 200; keeps at most 1,000 header recipients (which also affects the fingerprint), the first 100 `In-Reply-To` and the last 100 `References`; and ignores message IDs over 998 and addresses over 320 characters. The original is unaffected.
- A message with no usable sender address is `parse_failed`.
- Quoted-history detection and HTML conversion are heuristics.
- English only.

## 17. Open decisions
"Needed before" names the work that should not start until the decision is made.

| ID | Question | Proposed default | Needed before |
|---|---|---|---|
| U-01 | Employee sign-in, session lifetime, MFA | Managed provider, cookie session | Authentication |
| U-02 | Adapter authentication | Bearer token over TLS | Intake build |
| U-03 | Stable message ID from the pilot mail path | Mailbox-provider ID | Live intake |
| U-04 | Retention (including message identity), deletion, encryption, write lock, quarantine access | Synthetic data only until decided; quarantine operator-only | Live data |
| U-05 | Roles and self-approval | Explicit permissions; self-approval for synthetic data only | Authorization setup |
| U-13 | Drafts for `uncertain` mail | Yes, flagged (the schema supports it) | Processing |
| U-15 | Keep `reopen`, and who holds it | Keep, separate permission | Approval build |
| U-17 | Quote lifecycle | Defer | Quote design |
| U-19 | Pilot catalog source; it must supply ordered dimension designations | Synthetic data | Matching |
| U-20 | Retry count and manual reprocessing | 3 attempts; no manual reprocess | Workers |
| U-22 / N-8 | Benchmark accuracy thresholds | Proposals until a baseline is measured | Accuracy gate |
| U-23 | Pilot email integration and identity | Not yet proposed | Live intake |
| U-24 | Extra approval for corrected fields | Keep history; no extra approval | Authorization setup |
| N-7 | Model provider | Decide separately | Extraction build |

N-6 (required CI checks and branch protection before PR #2 merges) is decided; the repository setting still has to be made by the owner.

Frontend requests not met in v0.1: per-attachment download (N-9), a yard confirmation of unit conventions (U-07), sign-in and sign-out endpoints (U-01), sender authentication results (SPF, DKIM, DMARC), a per-line reviewed marker (N-11) and a non-email inbox shape.

## 18. Changes from the v1 draft
| v1 draft | v0.1 | Why |
|---|---|---|
| `yard_id`, `idempotency_key` in the inbound event | Derived by the server | A payload must not choose its tenant or defeat deduplication |
| Adapter-supplied content and `source_reference` | Adapter uploads raw bytes; the server parses them | The original is the authority |
| All channels | Email only | Approved slice |
| Flat item values, `null` for absent | Tracked fields with five states and evidence | Distinguishes absent, unclear, entered and cleared |
| `confidence` | Removed | Uncalibrated |
| `dimensions` string | Written text plus ordered components | Structured without assigning axes |
| Unit `"pieces"` | `UnitCode`, wording kept in evidence | Controlled vocabulary |
| `candidate_skus` in model output | Deterministic `MatchResult`; employee selects | AI must not choose SKUs |
| Normalized summary | Removed | A summary can introduce unstated specifications |
| Request states `new → processing → draft_ready` | Processing belongs to the communication | A request exists only once there is a draft |
| `QuoteDraft` and send endpoints | Deferred | No pricing or sending |

The first v0.1 proposal (commit `5dd0699`) is superseded by this revision. Main differences: server-side parsing and grounding; five field states with a preserved AI proposal; ordered dimensions instead of thickness, width and length; no unit conversions; mark handled; typed warnings and blockers; fixed limits.

## 19. Carried forward, not part of v0.1
Retained from the v1 draft for later versions. Nothing below is specified exactly or scheduled by this contract.

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
