"""Proposed v0.1 HTTP operations, used only to generate openapi.yaml.

This is a description of the API, not an implementation. Nothing here serves requests.
"""

from __future__ import annotations

from dataclasses import dataclass

import models as m

PUBLIC = "public"
EMPLOYEE = "employee"
INTEGRATION = "integration"


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
    request: type | None = None
    idempotency_header: bool = False
    paged: bool = False
    search: bool = False
    inbox_filters: bool = False
    description: str = ""


YARD = "/api/v1/yards/{yard_id}"
P = m.Permission

OPERATIONS = [
    Operation(
        "get", "/api/v1/health", "getHealth", "Service health without sensitive details",
        PUBLIC, {200: m.Health}, (503,),
    ),
    Operation(
        "post", "/api/v1/inbound/events", "ingestEmailEvent",
        "Preserve and queue one inbound email", INTEGRATION,
        {200: m.InboundAccepted, 202: m.InboundAccepted}, (401, 409, 413, 422, 503),
        request=m.InboundEmailEvent,
        description=(
            "202: newly preserved. 200: identical redelivery. 409: same external_message_id "
            "with different content; the new bytes are quarantined. The yard comes from the "
            "credential. A success response is sent only after the original and the "
            "processing job are durable."
        ),
    ),
    Operation(
        "get", "/api/v1/me", "getCurrentUser", "Signed-in employee and yard permissions",
        EMPLOYEE, {200: m.CurrentUser}, (401,),
    ),
    Operation(
        "get", YARD + "/inbox", "listInbox", "Communications for one yard, newest first",
        EMPLOYEE, {200: m.InboxPage}, (401, 403, 404, 422),
        permission=P.COMMUNICATION_READ, paged=True, inbox_filters=True,
        description="request summaries are included only with request:read, otherwise null.",
    ),
    Operation(
        "get", YARD + "/communications/{communication_id}", "getCommunication",
        "Immutable record and processing status", EMPLOYEE,
        {200: m.CommunicationDetail}, (401, 403, 404, 422), permission=P.COMMUNICATION_READ,
        description="body_text is untrusted: render it as plain text.",
    ),
    Operation(
        "get", YARD + "/communications/{communication_id}/original", "downloadOriginal",
        "Download the preserved original", EMPLOYEE, {200: None},
        (401, 403, 404, 422, 503), permission=P.COMMUNICATION_READ_ORIGINAL,
        description="Always an attachment download with nosniff and no-store. Audited.",
    ),
    Operation(
        "post", YARD + "/communications/{communication_id}/requests", "createRequestManually",
        "Start an empty draft when none was produced", EMPLOYEE, {201: m.RequestDetail},
        (401, 403, 404, 409, 422), permission=P.REQUEST_CREATE,
        request=m.ManualRequestCreate, idempotency_header=True,
        description="Allowed only when processing has completed or failed and no draft exists.",
    ),
    Operation(
        "get", YARD + "/requests/{request_id}", "getRequest", "Current review draft",
        EMPLOYEE, {200: m.RequestDetail}, (401, 403, 404, 422), permission=P.REQUEST_READ,
    ),
    Operation(
        "patch", YARD + "/requests/{request_id}", "editRequest",
        "Apply employee edits atomically", EMPLOYEE, {200: m.RequestDetail},
        (401, 403, 404, 409, 422), permission=P.REQUEST_EDIT, request=m.RequestEdit,
        idempotency_header=True,
        description="All operations apply or none do. One accepted call adds one version.",
    ),
    Operation(
        "post", YARD + "/requests/{request_id}/decisions", "decideRequest",
        "Approve internally, decline or reopen", EMPLOYEE, {200: m.RequestDetail},
        (401, 403, 404, 409, 422), request=m.DecisionRequest, idempotency_header=True,
        description=(
            "Permission depends on action: request:approve_internal, request:decline or "
            "request:reopen. Nothing is sent, ordered, exported or reserved."
        ),
    ),
    Operation(
        "get", YARD + "/requests/{request_id}/revisions", "listRevisions",
        "Version history, oldest first", EMPLOYEE, {200: m.RevisionPage},
        (401, 403, 404, 422), permission=P.REQUEST_READ, paged=True,
    ),
    Operation(
        "get", YARD + "/requests/{request_id}/revisions/{version}", "getRevision",
        "Content as of one version", EMPLOYEE, {200: m.RevisionDetail},
        (401, 403, 404, 422), permission=P.REQUEST_READ,
    ),
    Operation(
        "get", YARD + "/skus", "searchSkus", "Search this yard's active catalog", EMPLOYEE,
        {200: m.SkuPage}, (401, 403, 404, 422), permission=P.CATALOG_READ, paged=True,
        search=True,
    ),
]
