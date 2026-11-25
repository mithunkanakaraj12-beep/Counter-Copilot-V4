# Counter Copilot V4 — Product Scope

## Product definition
A lumberyard-focused communications intake and quote-preparation application. It captures contractor requests, understands material needs, checks yard catalog/inventory data when available, optionally calculates provisional prices from authorized pricing rules, and prepares an employee-reviewed draft. It supplements existing ERP/POS/accounting/dispatch systems; it does not replace them.

## Core workflow
1. Receive inbound email, SMS/MMS, phone event, or authorized voicemail/recording.
2. Authenticate source, resolve the yard, assign an idempotency key, and preserve the original.
3. Parse text/attachments or transcribe supported audio.
4. Classify the communication and extract material/job/delivery fields.
5. Match each requested line against the yard's SKU catalog with evidence and uncertainty.
6. Assess inventory from an authorized, timestamped inventory snapshot/feed.
7. If enabled, calculate provisional quote pricing from validated price books and account rules.
8. Create a draft with source, transcript, line items, SKU candidates, inventory evidence, optional price, and warnings.
9. Notify an authorized employee through an authenticated link.
10. Employee edits, approves the internal draft, declines, or requests clarification.
11. Sending a quote, exporting data, booking an order, or reserving stock remains a separate explicit action.
12. Track quote lifecycle and allow authorized employee-initiated manual follow-up.

## Functional requirements

### Communications
- Email: forwarding/dedicated mailbox first; add Gmail/Google Workspace or Microsoft 365 OAuth connectors only as needed.
- SMS/MMS: inbound messages, media references, threading, status metadata, consent and opt-out controls.
- Voice: call metadata and authorized post-call recording/voicemail transcription; no live AI voice agent in V4.
- All channel adapters are replaceable. V4 supports all three channels, but the first pilot may activate them sequentially based on the yard's systems and approvals.

### Extraction
Extract quantity, unit, dimensions, species, grade, treatment, product wording, and delivery/job details when supplied. Preserve original contractor wording. Missing or conflicting specifications must be flagged, not guessed. Support PDF, spreadsheets, and images only to the level that can be tested reliably; unclear handwriting goes to employee review.

### SKU and inventory
- Map requests to yard-specific SKUs using exact attributes, approved synonyms, and employee-reviewed candidates.
- Normalize units only with yard-approved conversion rules.
- Calculate available-to-promise (ATP) and line coverage only when inventory inputs and semantics are understood.
- Show source time, freshness, assumptions, and missing components.
- V4 displays inventory coverage, not a made-up probability of fulfillment. A predictive fulfillment probability requires verified outcomes, calibration, and held-out testing.

### Optional price calculation
- Request/material preparation is always ON.
- Automatic provisional quote pricing is an authorized yard-level ON/OFF setting and defaults OFF until source data and rules are validated.
- OFF means “Not calculated”; extraction, SKU matching, inventory assessment, and draft creation continue.
- ON uses deterministic code and approved price books, account tiers, units, discounts, fees/taxes, and rounding.
- Store price source, effective time, account rule, calculation details, and warnings.
- Missing or stale pricing rules require employee review. The model never invents a price.

### Employee experience
- Minimal responsive interface: unified review queue, one request detail/review card, essential quote history/status, and minimal settings.
- Edit, approve internal draft, decline, request clarification, assign, and add notes.
- Quick approval is a secure authenticated link/action. A notification itself is never approval.
- A future reply-to-approve flow requires separate design for registered identity, request-specific verification, replay protection, role permissions, and audit logging. It must not send a quote or book an order merely because an SMS says “approve.”

### Quote lifecycle and follow-up
Track draft, internally approved, sent, revised, customer accepted/declined, expired/cancelled, converted to order (only when confirmed by yard), and failed/retry states as applicable. V4 includes one-off employee-initiated manual follow-up using approved templates and communication permissions. Automated 24-hour quote chaser campaigns and randomized holdout experiments are future scope.

## First-pilot configuration
The complete V4 vision supports calls, email, and text. The first pilot should be the smallest complete workflow the founding yard can authorize and operate:
1. Controlled email forwarding or dedicated mailbox.
2. SMS intake using approved connectivity after registration and consent are ready.
3. Call/voicemail connection only after phone-system discovery, a controlled test path, and fallback are verified.
4. Use inventory and pricing only when actual sample files/data prove parseable, current, and semantically understood.
5. Start with a minimal approval interface and secure link; defer advanced analytics, full CRM, and broad admin screens.
6. Run in shadow mode before controlled live use.

Do not promise a fixed go-live date before mailbox access, telecom setup/registration, data access, and technical operator availability are confirmed.

## Explicitly outside initial V4 launch
- Automated quote-chasing campaigns and randomized holdout experiments.
- Live AI phone answering or outbound AI calling.
- Replacing ERP/POS/accounting/purchasing/dispatch/warehouse systems.
- Automatic order booking, supplier purchase orders, stock reservation, credit approval, or confirmed delivery scheduling.
- Operating a public telephone/mobile network or carrier business.
- Training a foundation language or speech model from scratch.
- Advanced owner analytics, full CRM automation, multi-branch optimization, and expansion to other trades.

## Pilot success metrics
Measure communication capture rate, source preservation, time-to-draft, critical-field extraction accuracy, SKU match/correction rate, inventory freshness and ATP agreement, price calculation agreement (if enabled), employee adoption/review time, duplicate/lost/failed events, and onboarding/support hours per yard. Do not claim recovered revenue without a defensible attribution method.
