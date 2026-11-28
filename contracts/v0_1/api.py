"""Proposed v0.1 HTTP operations, used only to generate openapi.yaml.

This is a description of the API, not an implementation. Nothing here serves requests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import models as m

PUBLIC = "public"
EMPLOYEE = "employee"
INTEGRATION = "integration"


def _query(name: str, schema: dict, description: str = "") -> dict:
    parameter = {"name": name, "in": "query", "required": False, "schema": schema}
    if description:
        parameter["description"] = description
    return parameter


def _enum(enum) -> dict:
    return {"type": "string", "enum": [item.value for item in enum]}


UUID_SCHEMA = {"type": "string", "format": "uuid"}
TEXT_SEARCH = {"type": "string", "maxLength": 200}

PAGING = (
    _query("cursor", {"type": "string"}, "Opaque. Bound to the yard and the filters."),
    _query("limit", {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}),
)

INBOX_QUERY = (
    *PAGING,
    _query(
        "view",
        {"type": "string", "enum": ["needs_review", "all"], "default": "needs_review"},
        "needs_review: handling is open, and the item is not an approved or declined "
        "request without attention flags.",
    ),
    _query("q", TEXT_SEARCH, "Case-insensitive substring of sender or subject. Not the body."),
    _query("sender", {"type": "string", "maxLength": 320}, "Exact sender address."),
    _query("received_from", {"type": "string", "format": "date-time"}),
    _query("received_to", {"type": "string", "format": "date-time"}),
    _query("review_state", _enum(m.ReviewState), "Needs request:read."),
    _query("processing_state", _enum(m.ProcessingState)),
    _query("classification", _enum(m.Classification)),
    _query("handling", {"type": "string", "enum": ["open", "handled"]}),
    _query("has_attachments", {"type": "boolean"}),
    _query("has_draft", {"type": "boolean"}, "Needs request:read."),
    _query("attention", {"type": "boolean"}, "Only items with, or without, attention flags."),
)

SKU_QUERY = (
    *PAGING,
    _query("q", TEXT_SEARCH),
    _query("species", TEXT_SEARCH),
    _query("grade", TEXT_SEARCH),
    _query("treatment", TEXT_SEARCH),
    _query(
        "request_id",
        UUID_SCHEMA,
        "With line_id: return a comparison preview. Needs request:read. Selects nothing.",
    ),
    _query("line_id", UUID_SCHEMA, "Send together with request_id."),
)


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    operation_id: str
    summary: str
    auth: str
    responses: dict  # status -> model (None for the binary original)
    errors: tuple[int, ...]
    permission: m.Permission | None = None
    conditional_permissions: dict = field(default_factory=dict)
    request: type | None = None
    idempotency_header: bool = False
    query: tuple = ()
    description: str = ""


YARD = "/api/v1/yards/{yard_id}"
P = m.Permission

READ = (401, 403, 404, 422, 429, 503)
CHANGE = (401, 403, 404, 409, 413, 415, 422, 429, 503)

ATTACHMENT_LIMITATION = (
    "v0.1 has no individual attachment download, extraction or per-part processing. "
    "Attachments are listed as metadata and exist only inside the complete original email."
)

OPERATIONS = [
    Operation(
        "get", "/api/v1/health", "getHealth", "Service health without sensitive details",
        PUBLIC, {200: m.Health}, (503,),
    ),
    Operation(
        "post", "/api/v1/inbound/events", "ingestEmailEvent",
        "Preserve and queue one inbound email", INTEGRATION,
        {200: m.InboundAccepted, 202: m.InboundAccepted},
        (401, 409, 413, 415, 422, 429, 503),
        request=m.InboundEmailEvent,
        description=(
            "202: newly preserved, including mail that cannot be parsed "
            "(processing_state failed_terminal). 200: identical redelivery. 409 "
            "conflicting_redelivery: same external_message_id with different content; the "
            "new bytes are quarantined and the first original is unchanged. 422: forbidden "
            "metadata keys, original_hash_mismatch or no configured mailbox among "
            "envelope_recipients; the submission is quarantined and audited. 413: over any "
            "parser limit; the application stores nothing, and the adapter keeps the source "
            "and alerts an operator. The yard comes from the credential. A success response "
            "is sent only after the original, record and processing job are durable."
        ),
    ),
    Operation(
        "get", "/api/v1/me", "getCurrentUser", "Signed-in employee and yard permissions",
        EMPLOYEE, {200: m.CurrentUser}, (401, 429, 503),
    ),
    Operation(
        "get", YARD + "/inbox", "listInbox", "Communications for one yard, newest first",
        EMPLOYEE, {200: m.InboxPage}, READ,
        permission=P.COMMUNICATION_READ,
        conditional_permissions={
            "request summaries, review_state and has_draft filters": P.REQUEST_READ.value
        },
        query=INBOX_QUERY,
        description=(
            "Ordered by ingested_at, then communication_id, both descending. Request "
            "summaries are null without request:read. A cursor used with another yard or "
            "other filters is 422."
        ),
    ),
    Operation(
        "get", YARD + "/inbox/counts", "getInboxCounts", "Queue sizes for one yard",
        EMPLOYEE, {200: m.InboxCounts}, READ, permission=P.COMMUNICATION_READ,
        conditional_permissions={"request counts": P.REQUEST_READ.value},
    ),
    Operation(
        "get", YARD + "/communications/{communication_id}", "getCommunication",
        "Immutable record, processing status and handling history", EMPLOYEE,
        {200: m.CommunicationDetail}, READ, permission=P.COMMUNICATION_READ,
        description=(
            "body_text, subject, names and filenames are untrusted: render them as plain "
            "text. " + ATTACHMENT_LIMITATION
        ),
    ),
    Operation(
        "get", YARD + "/communications/{communication_id}/original", "downloadOriginal",
        "Download the complete preserved original", EMPLOYEE, {200: None}, READ,
        permission=P.COMMUNICATION_READ_ORIGINAL,
        description=(
            "Streamed through this yard-authorized route only; there is no public or "
            "reusable file link. Always an attachment download. Audited. "
            + ATTACHMENT_LIMITATION
        ),
    ),
    Operation(
        "post", YARD + "/communications/{communication_id}/handling", "changeHandling",
        "Mark a non-request handled, or reopen it", EMPLOYEE,
        {200: m.CommunicationDetail}, CHANGE, permission=P.COMMUNICATION_HANDLE,
        request=m.HandlingRequest, idempotency_header=True,
        description=(
            "mark_handled only for a completed non_request with no material request; "
            "otherwise 409 invalid_state. Failed, unfinished and follow-up items are never "
            "eligible, with or without a note. Deletes nothing and clears no warning."
        ),
    ),
    Operation(
        "post", YARD + "/communications/{communication_id}/requests", "createRequestManually",
        "Start an empty draft when none was produced", EMPLOYEE, {201: m.RequestDetail},
        CHANGE, permission=P.REQUEST_CREATE,
        request=m.ManualRequestCreate, idempotency_header=True,
        description=(
            "Allowed only when processing has completed or failed, no draft exists and the "
            "item is not marked handled."
        ),
    ),
    Operation(
        "get", YARD + "/requests/{request_id}", "getRequest", "Current review draft",
        EMPLOYEE, {200: m.RequestDetail}, READ, permission=P.REQUEST_READ,
        conditional_permissions={"related_messages": P.COMMUNICATION_READ.value},
        description="Warnings, blockers and the live SKU evaluation are computed on read.",
    ),
    Operation(
        "patch", YARD + "/requests/{request_id}", "editRequest",
        "Apply employee edits atomically", EMPLOYEE, {200: m.RequestDetail},
        CHANGE, permission=P.REQUEST_EDIT, request=m.RequestEdit,
        idempotency_header=True,
        description=(
            "All operations apply in order, or none do. One accepted call adds one version. "
            "A change to product, dimensions, species, grade or treatment clears the SKU "
            "selection unless a later select_sku in the same call selects one."
        ),
    ),
    Operation(
        "post", YARD + "/requests/{request_id}/decisions", "decideRequest",
        "Approve internally, decline or reopen", EMPLOYEE, {200: m.RequestDetail},
        CHANGE, request=m.DecisionRequest, idempotency_header=True,
        conditional_permissions={
            "action approve_internal": P.REQUEST_APPROVE_INTERNAL.value,
            "action decline": P.REQUEST_DECLINE.value,
            "action reopen": P.REQUEST_REOPEN.value,
        },
        description=(
            "Approval locks the request and recomputes warnings and blockers; anything new "
            "gives 422 approval_blocked. Nothing is sent, ordered, exported or reserved."
        ),
    ),
    Operation(
        "get", YARD + "/requests/{request_id}/revisions", "listRevisions",
        "Version history, oldest first", EMPLOYEE, {200: m.RevisionPage}, READ,
        permission=P.REQUEST_READ, query=PAGING,
    ),
    Operation(
        "get", YARD + "/requests/{request_id}/revisions/{version}", "getRevision",
        "Content as of one version", EMPLOYEE, {200: m.RevisionDetail}, READ,
        permission=P.REQUEST_READ,
    ),
    Operation(
        "get", YARD + "/skus", "searchSkus", "Search this yard's active catalog", EMPLOYEE,
        {200: m.SkuPage}, READ, permission=P.CATALOG_READ,
        conditional_permissions={"preview with request_id and line_id": P.REQUEST_READ.value},
        query=SKU_QUERY,
    ),
]
