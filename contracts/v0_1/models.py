"""Counter Copilot V4 data contract v0.1: revised proposal, not yet approved or frozen.

These are interface definitions only. They contain shape rules that can be checked
from one payload. Rules that need stored data (tenant ownership, state transitions,
idempotency, locking) are listed in docs/DATA_CONTRACT.md and belong to the future
backend.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar, Union
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    create_model,
    model_validator,
)
from typing_extensions import TypeAliasType

from reference import values

SCHEMA_VERSION = "0.1"


class Limits:
    """Provisional, testable starting limits (U-16). 1 MB is read as 1,000,000 bytes,
    matching the approved 25,000,000-byte reading of 25 MB."""

    RAW_EMAIL_BYTES = 25_000_000
    BODY_CHARS = 200_000
    # Two separate limits (D-015).
    EMAIL_BODY_LINES = 500  # U-16 parser limit: lines of decoded body text
    MATERIAL_LINES = 500  # contract schema limit: proposal and request material lines
    ATTACHMENTS = 100
    MIME_PARTS = 200
    MIME_DEPTH = 20
    HEADER_BYTES = 256_000
    PARSE_SECONDS = 30
    JSON_BYTES = 1_000_000
    EVIDENCE_ITEMS = 20
    CANDIDATES = 10
    OPERATIONS = 200
    IDEMPOTENCY_HOURS = 24
    PREVIEW_CHARS = 200


class ContractModel(BaseModel):
    """Unknown keys are rejected. Strings are never trimmed: wording is preserved."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


def _require_text_timestamp(value: object) -> object:
    if not isinstance(value, (str, datetime)):
        raise ValueError("timestamp must be an RFC 3339 string")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _require_positive(value: str) -> str:
    if Decimal(value) <= 0:
        raise ValueError("must be greater than zero")
    return value


UtcDatetime = Annotated[
    AwareDatetime, BeforeValidator(_require_text_timestamp), AfterValidator(_require_utc)
]

_NOT_ZERO = {"not": {"pattern": r"^0(\.0+)?$"}}

# Decimals travel as strings so no JSON client can turn them into binary floats.
PositiveDecimal = Annotated[
    str,
    Field(
        pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,6})?$",
        json_schema_extra=_NOT_ZERO,
        examples=["40", "0.4375"],
    ),
    AfterValidator(_require_positive),
]

# Server-derived values: no trailing zeros.
CanonicalDecimal = Annotated[
    str,
    Field(
        pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{0,5}[1-9])?$",
        json_schema_extra=_NOT_ZERO,
        examples=["40", "0.4375"],
    ),
    AfterValidator(_require_positive),
]

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
LongText = Annotated[str, Field(min_length=1, max_length=4000)]
NoteText = Annotated[str, Field(min_length=1, max_length=2000)]
ExternalId = Annotated[str, Field(min_length=1, max_length=512)]
MailAddress = Annotated[str, Field(min_length=1, max_length=320)]
Version = Annotated[int, Field(ge=1, strict=True)]
Count = Annotated[int, Field(ge=0)]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class UnitCode(StrEnum):
    """Approved contract units (U-08). There are no cross-unit conversions."""

    PIECE = "piece"
    SHEET = "sheet"
    LINEAR_FOOT = "linear_foot"
    BOARD_FOOT = "board_foot"
    BUNDLE = "bundle"
    BOX = "box"
    BAG = "bag"
    ROLL = "roll"
    PALLET = "pallet"


class LengthUnit(StrEnum):
    INCH = "in"
    FOOT = "ft"


class FieldState(StrEnum):
    EXTRACTED = "extracted"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    EMPLOYEE_ENTERED = "employee_entered"
    EMPLOYEE_CLEARED = "employee_cleared"


MODEL_STATES = ("extracted", "missing", "ambiguous")
RESOLVED_STATES = ("extracted", "employee_entered")


class AmbiguityReason(StrEnum):
    CONFLICTING_STATEMENTS = "conflicting_statements"
    MULTIPLE_INTERPRETATIONS = "multiple_interpretations"
    RANGE_GIVEN = "range_given"
    UNRECOGNIZED_TERM = "unrecognized_term"
    UNCLEAR_REFERENCE = "unclear_reference"
    UNREADABLE = "unreadable"
    NEGATED = "negated"
    APPROXIMATE = "approximate"
    RELATIVE_QUANTITY = "relative_quantity"
    NUMBER_WORD = "number_word"
    SEPARATE_MEASUREMENTS = "separate_measurements"
    QUOTED_HISTORY_ONLY = "quoted_history_only"
    # Assigned only by the grounding function.
    UNSUPPORTED_BY_SOURCE = "unsupported_by_source"
    INEXACT_NORMALIZATION = "inexact_normalization"


ModelAmbiguityReason = Literal[
    "conflicting_statements",
    "multiple_interpretations",
    "range_given",
    "unrecognized_term",
    "unclear_reference",
    "unreadable",
    "negated",
    "approximate",
    "relative_quantity",
    "number_word",
    "separate_measurements",
    "quoted_history_only",
]


class GroundingRule(StrEnum):
    """Why grounding downgraded a proposed field."""

    NOT_IN_EVIDENCE = "not_in_evidence"
    OUTSIDE_LINE_EVIDENCE = "outside_line_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    QUOTED_ONLY = "quoted_only"
    NEGATED = "negated"
    RELATIVE = "relative"
    APPROXIMATE = "approximate"
    RANGE = "range"
    VAGUE_NUMBER = "vague_number"
    CORRECTION_LANGUAGE = "correction_language"
    RESTATED_DIFFERENTLY = "restated_differently"
    INEXACT = "inexact"
    SEPARATE_MEASUREMENTS = "separate_measurements"
    UNREADABLE_DIMENSION = "unreadable_dimension"
    CANDIDATES_REMOVED = "candidates_removed"


class SourceKind(StrEnum):
    SUBJECT = "subject"
    BODY_TEXT = "body_text"


class EvidenceRole(StrEnum):
    SUPPORTS = "supports"
    CONFLICTS = "conflicts"


class ProcessingState(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class FailureCode(StrEnum):
    PARSE_FAILED = "parse_failed"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    INTERNAL_ERROR = "internal_error"


FAILURE_MESSAGES: dict[str, str] = {
    "parse_failed": "This email could not be read. Open the original message.",
    "model_unavailable": "Automatic reading is temporarily unavailable.",
    "model_timeout": "Automatic reading took too long.",
    "model_output_invalid": "Automatic reading produced an unusable result.",
    "internal_error": "Processing failed. Open the original message.",
}


class Classification(StrEnum):
    MATERIAL_REQUEST = "material_request"
    FOLLOW_UP = "follow_up"
    NON_REQUEST = "non_request"
    UNCERTAIN = "uncertain"


class ReviewState(StrEnum):
    DRAFT_READY = "draft_ready"
    INTERNALLY_APPROVED = "internally_approved"
    DECLINED = "declined"


class Permission(StrEnum):
    COMMUNICATION_READ = "communication:read"
    COMMUNICATION_READ_ORIGINAL = "communication:read_original"
    COMMUNICATION_HANDLE = "communication:handle"
    REQUEST_READ = "request:read"
    REQUEST_CREATE = "request:create"
    REQUEST_EDIT = "request:edit"
    REQUEST_APPROVE_INTERNAL = "request:approve_internal"
    REQUEST_DECLINE = "request:decline"
    REQUEST_REOPEN = "request:reopen"
    CATALOG_READ = "catalog:read"


class WarningCode(StrEnum):
    UNPROCESSED_ATTACHMENT = "unprocessed_attachment"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    CONFLICTING_REDELIVERY = "conflicting_redelivery"
    POSSIBLE_FOLLOW_UP = "possible_follow_up"
    NEWER_RELATED_MESSAGE = "newer_related_message"
    POSSIBLE_FOLLOW_UP_SAME_SENDER = "possible_follow_up_same_sender"
    UNCERTAIN_CLASSIFICATION = "uncertain_classification"
    SELECTED_SKU_ATTRIBUTE_MISMATCH = "selected_sku_attribute_mismatch"
    SELECTED_SKU_ATTRIBUTE_UNVERIFIED = "selected_sku_attribute_unverified"
    SELECTED_SKU_CHANGED = "selected_sku_changed"
    POSSIBLE_CORRECTION_LANGUAGE = "possible_correction_language"
    UNCITED_QUANTITY_TEXT = "uncited_quantity_text"
    EVIDENCE_IN_QUOTED_TEXT = "evidence_in_quoted_text"
    OVERLAPPING_LINE_EVIDENCE = "overlapping_line_evidence"
    MODEL_LINE_REMOVED = "model_line_removed"
    MULTIPLE_JOBS_DETECTED = "multiple_jobs_detected"
    HTML_DERIVED_TEXT = "html_derived_text"


# Warnings that never need acknowledgement. Every other code does.
INFORMATIONAL_WARNINGS = (
    WarningCode.POSSIBLE_FOLLOW_UP_SAME_SENDER,
    WarningCode.HTML_DERIVED_TEXT,
)
# Text heuristics: useful signals, never guarantees. False positives are recorded.
HEURISTIC_WARNINGS = (
    WarningCode.POSSIBLE_CORRECTION_LANGUAGE,
    WarningCode.UNCITED_QUANTITY_TEXT,
    WarningCode.EVIDENCE_IN_QUOTED_TEXT,
)


class BlockerCode(StrEnum):
    NO_ACTIVE_LINES = "no_active_lines"
    AMBIGUOUS_FIELD = "ambiguous_field"
    QUANTITY_UNRESOLVED = "quantity_unresolved"
    UNIT_UNRESOLVED = "unit_unresolved"
    SKU_NOT_SELECTED = "sku_not_selected"
    SKU_INACTIVE = "sku_inactive"
    UNIT_INCOMPATIBLE = "unit_incompatible"
    WARNING_NOT_ACKNOWLEDGED = "warning_not_acknowledged"


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    CSRF_FAILED = "csrf_failed"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"
    VERSION_CONFLICT = "version_conflict"
    INVALID_STATE = "invalid_state"
    REQUEST_ALREADY_EXISTS = "request_already_exists"
    CONFLICTING_REDELIVERY = "conflicting_redelivery"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    VALIDATION_FAILED = "validation_failed"
    APPROVAL_BLOCKED = "approval_blocked"
    ORIGINAL_HASH_MISMATCH = "original_hash_mismatch"
    RATE_LIMITED = "rate_limited"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


ERROR_STATUS: dict[int, tuple[ErrorCode, ...]] = {
    401: (ErrorCode.UNAUTHENTICATED,),
    403: (ErrorCode.FORBIDDEN, ErrorCode.CSRF_FAILED),
    404: (ErrorCode.NOT_FOUND,),
    409: (
        ErrorCode.IDEMPOTENCY_CONFLICT,
        ErrorCode.IDEMPOTENCY_IN_PROGRESS,
        ErrorCode.VERSION_CONFLICT,
        ErrorCode.INVALID_STATE,
        ErrorCode.REQUEST_ALREADY_EXISTS,
        ErrorCode.CONFLICTING_REDELIVERY,
    ),
    413: (ErrorCode.PAYLOAD_TOO_LARGE,),
    415: (ErrorCode.UNSUPPORTED_MEDIA_TYPE,),
    422: (
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.APPROVAL_BLOCKED,
        ErrorCode.ORIGINAL_HASH_MISMATCH,
    ),
    429: (ErrorCode.RATE_LIMITED,),
    503: (ErrorCode.TEMPORARILY_UNAVAILABLE,),
}


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


class PersonRef(ContractModel):
    """A deactivated user keeps their name and is reported with active=false."""

    user_id: UUID
    display_name: ShortText
    active: bool


class Actor(ContractModel):
    type: Literal["system", "employee", "integration"]
    person: PersonRef | None

    @model_validator(mode="after")
    def _employee_is_identified(self) -> Actor:
        if (self.person is not None) != (self.type == "employee"):
            raise ValueError("person is set exactly for employee actors")
        return self


# ---------------------------------------------------------------------------
# Inbound communication
# ---------------------------------------------------------------------------


class EmailParty(ContractModel):
    name: Annotated[str, Field(max_length=500)] | None
    address: MailAddress


MessageRef = Annotated[str, Field(max_length=998)]


class EmailThread(ContractModel):
    """Reply headers as written in the message. Sender-controlled."""

    rfc_message_id: MessageRef | None
    in_reply_to: Annotated[list[MessageRef], Field(max_length=100)]
    references: Annotated[list[MessageRef], Field(max_length=100)]


class AttachmentMetadata(ContractModel):
    """Derived by the server from the preserved bytes. v0.1 does not parse, extract
    or download individual attachments; they exist only inside the complete original."""

    part_id: Annotated[str, Field(pattern=r"^[0-9]+(\.[0-9]+)*$", max_length=100)]
    filename: Annotated[str, Field(max_length=500)] | None
    media_type: Annotated[str, Field(min_length=1, max_length=200)]
    size_bytes: Count
    sha256: Sha256
    disposition: Literal["attachment", "inline"] | None
    content_id: Annotated[str, Field(max_length=998)] | None
    processing: Literal["not_processed"]


class InboundEmailEvent(ContractModel):
    """JSON part of the intake request: transport facts only.

    Sender, header recipients, subject, body, reply headers and attachments are
    derived from the uploaded bytes; supplying them is rejected. The yard comes
    from the credential."""

    schema_version: Literal["0.1"]
    channel: Literal["email"]
    external_message_id: ExternalId = Field(
        description="Stable ID assigned by the mail source; identical on every redelivery."
    )
    external_event_id: ExternalId | None = Field(
        description="ID of this delivery attempt, if the source has one. Not used for deduplication."
    )
    provider_thread_id: ExternalId | None = Field(
        description="Thread ID assigned by the mail source. One of the two reliable link signals."
    )
    received_at: UtcDatetime
    envelope_recipients: Annotated[list[MailAddress], Field(min_length=1, max_length=200)] = Field(
        description="Delivery recipients. A configured yard mailbox must be among them."
    )
    provider_metadata: Annotated[
        dict[str, Annotated[str, Field(max_length=2000)]], Field(max_length=50)
    ]
    original_sha256: Sha256 = Field(description="Digest of the uploaded raw bytes.")


class InboundAccepted(ContractModel):
    communication_id: UUID
    duplicate: bool
    processing_state: ProcessingState
    original_sha256: Sha256 = Field(description="Digest of the first preserved original.")


class OriginalDescriptor(ContractModel):
    media_type: Literal["message/rfc822"]
    size_bytes: Annotated[int, Field(ge=1, le=Limits.RAW_EMAIL_BYTES)]
    sha256: Sha256
    stored_at: UtcDatetime


class TextSpan(ContractModel):
    """Code-point offsets into body_text, zero-based and end-exclusive."""

    start: Count
    end: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _ordered(self) -> TextSpan:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


_PARSED_FIELDS = (
    "sender",
    "recipients",
    "subject",
    "body_text",
    "body_source",
    "thread",
    "attachments",
    "quoted_spans",
)


def _parsed_field_rules() -> dict:
    nulls = {name: {"type": "null"} for name in _PARSED_FIELDS}
    required = {
        name: {"not": {"type": "null"}} for name in _PARSED_FIELDS if name != "subject"
    }
    return {
        "allOf": [
            {
                "if": {
                    "properties": {"parse_status": {"const": "failed"}},
                    "required": ["parse_status"],
                },
                "then": {"properties": nulls},
                "else": {"properties": required},
            }
        ]
    }


class ParsedContent(ContractModel):
    """Output of the versioned parser. All parsed fields are null when it failed."""

    model_config = ConfigDict(json_schema_extra=_parsed_field_rules())

    parser_version: ShortText
    parse_status: Literal["parsed", "failed"]
    sender: EmailParty | None
    recipients: Annotated[list[EmailParty], Field(max_length=1000)] | None = Field(
        description="To and Cc header addresses."
    )
    subject: Annotated[str, Field(max_length=Limits.HEADER_BYTES)] | None
    body_text: (
        Annotated[
            str,
            Field(
                max_length=Limits.BODY_CHARS,
                # More than EMAIL_BODY_LINES lines: that many LFs followed by anything.
                json_schema_extra={
                    "not": {
                        "pattern": rf"^(?:[^\n]*\n){{{Limits.EMAIL_BODY_LINES}}}[\s\S]"
                    }
                },
            ),
        ]
        | None
    ) = Field(
        description="Decoded text with CRLF changed to LF and nothing else. Untrusted."
    )
    body_source: Literal["text_plain", "text_html_derived", "none"] | None
    thread: EmailThread | None
    attachments: (
        Annotated[list[AttachmentMetadata], Field(max_length=Limits.ATTACHMENTS)] | None
    )
    quoted_spans: list[TextSpan] | None = Field(
        description="Ranges of body_text recognised as quoted or forwarded history."
    )

    @model_validator(mode="after")
    def _nulls_follow_status(self) -> ParsedContent:
        if self.parse_status == "failed":
            if any(getattr(self, name) is not None for name in _PARSED_FIELDS):
                raise ValueError("a failed parse carries no parsed fields")
        elif any(getattr(self, name) is None for name in _PARSED_FIELDS if name != "subject"):
            raise ValueError("a parsed message needs every parsed field except subject")
        if (
            self.body_text is not None
            and values.count_lines(self.body_text) > Limits.EMAIL_BODY_LINES
        ):
            raise ValueError("body_text exceeds the email body line limit")
        if self.quoted_spans and self.body_text is not None:
            if any(span.end > len(self.body_text) for span in self.quoted_spans):
                raise ValueError("quoted span lies outside body_text")
        return self


class CommunicationRecord(ParsedContent):
    """Immutable once written. No API updates or deletes it."""

    communication_id: UUID
    yard_id: UUID
    integration_id: UUID
    channel: Literal["email"]
    direction: Literal["inbound"]
    external_message_id: ExternalId
    provider_thread_id: ExternalId | None
    content_fingerprint: Sha256
    received_at: UtcDatetime
    ingested_at: UtcDatetime
    envelope_recipients: Annotated[list[MailAddress], Field(min_length=1, max_length=200)]
    provider_metadata: dict[str, str]
    original: OriginalDescriptor


class LinkedMessage(ContractModel):
    """A message joined by reply headers or a provider thread ID, never by sender."""

    communication_id: UUID
    relation: Literal["earlier", "newer"]
    link_basis: Literal["reply_headers", "provider_thread"]
    received_at: UtcDatetime
    sender: EmailParty | None
    subject: str | None
    processing_state: ProcessingState
    classification: Classification | None
    request_id: UUID | None
    review_state: ReviewState | None


class HandlingReason(StrEnum):
    NOT_A_REQUEST = "not_a_request"
    HANDLED_OUTSIDE_SYSTEM = "handled_outside_system"
    DUPLICATE = "duplicate"
    SPAM = "spam"
    OTHER = "other"


_OTHER_NEEDS_NOTE = {
    "if": {"properties": {"reason": {"const": "other"}}, "required": ["reason"]},
    "then": {"properties": {"note": {"type": "string"}}, "required": ["note"]},
}


class HandlingState(ContractModel):
    model_config = ConfigDict(json_schema_extra={"allOf": [_OTHER_NEEDS_NOTE]})

    status: Literal["open", "handled"]
    version: Count = Field(description="0 until the first handling action.")
    mark_handled_allowed: bool = Field(
        description="True only for an open, completed non_request with no request."
    )
    reason: HandlingReason | None
    note: NoteText | None
    changed_by: PersonRef | None
    changed_at: UtcDatetime | None

    @model_validator(mode="after")
    def _consistent(self) -> HandlingState:
        if self.status == "handled":
            if self.reason is None or self.changed_by is None or self.changed_at is None:
                raise ValueError("handled needs a reason, person and time")
            if self.version < 1 or self.mark_handled_allowed:
                raise ValueError("handled has a version and cannot be marked again")
        elif self.reason is not None or self.note is not None:
            raise ValueError("an open item carries no handling reason or note")
        if self.reason == HandlingReason.OTHER and not self.note:
            raise ValueError("reason 'other' needs a note")
        return self


class HandlingEvent(ContractModel):
    """Append-only."""

    event_id: UUID
    action: Literal["mark_handled", "reopen"]
    reason: ShortText
    note: NoteText | None
    actor: PersonRef
    occurred_at: UtcDatetime
    handling_version: Annotated[int, Field(ge=1)]


class CommunicationStatus(ContractModel):
    """Mutable processing information, stored apart from the immutable record."""

    processing_state: ProcessingState
    classification: Classification | None
    failure_code: FailureCode | None
    employee_message: ShortText | None = Field(
        description="Fixed text for the failure code. Never contains source content."
    )
    attempt_count: Count
    processing_started_at: UtcDatetime | None
    next_retry_at: UtcDatetime | None
    possible_duplicate_of: list[UUID]
    related_messages: list[LinkedMessage]
    has_conflicting_redelivery: bool
    origin_request_id: UUID | None
    handling: HandlingState

    @model_validator(mode="after")
    def _consistent(self) -> CommunicationStatus:
        failed = self.processing_state in (
            ProcessingState.FAILED_RETRYABLE,
            ProcessingState.FAILED_TERMINAL,
        )
        if failed != (self.failure_code is not None):
            raise ValueError("failure_code is set exactly for failed states")
        expected = FAILURE_MESSAGES[self.failure_code] if self.failure_code else None
        if self.employee_message != expected:
            raise ValueError("employee_message must be the fixed text for the failure code")
        if (
            self.failure_code == FailureCode.PARSE_FAILED
            and self.processing_state != ProcessingState.FAILED_TERMINAL
        ):
            raise ValueError("parse_failed is terminal")
        if (
            self.next_retry_at is not None
            and self.processing_state != ProcessingState.FAILED_RETRYABLE
        ):
            raise ValueError("next_retry_at is only set for failed_retryable")
        completed = self.processing_state == ProcessingState.COMPLETED
        if completed != (self.classification is not None):
            raise ValueError("classification is set exactly when processing completed")
        eligible = (
            completed
            and self.classification == Classification.NON_REQUEST
            and self.origin_request_id is None
        )
        if self.handling.status == "handled" and not eligible:
            raise ValueError("only a completed non_request with no request can be handled")
        if self.handling.mark_handled_allowed != (eligible and self.handling.status == "open"):
            raise ValueError("mark_handled_allowed does not match eligibility")
        return self


class CommunicationDetail(ContractModel):
    record: CommunicationRecord
    status: CommunicationStatus
    handling_history: list[HandlingEvent]


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class Evidence(ContractModel):
    """Pointer into immutable source text. Offsets count Unicode code points,
    zero-based, end-exclusive. The server must verify source[start:end] == quote."""

    communication_id: UUID
    source: SourceKind
    start: Count
    end: Annotated[int, Field(ge=1)]
    quote: LongText
    role: EvidenceRole

    @model_validator(mode="after")
    def _span_matches_quote(self) -> Evidence:
        if self.end - self.start != len(self.quote):
            raise ValueError("end - start must equal the length of quote")
        return self


EvidenceList = Annotated[list[Evidence], Field(max_length=Limits.EVIDENCE_ITEMS)]


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


class DimensionComponent(ContractModel):
    raw: ShortText = Field(description="Wording of this component, e.g. '92-5/8'.")
    magnitude: CanonicalDecimal
    unit: LengthUnit | None = Field(description="Set only when written. Never assumed.")


class Dimensions(ContractModel):
    """One contiguous written dimension, components in written order. No axis names,
    no assumed units and no conversion."""

    text: ShortText
    components: Annotated[
        list[DimensionComponent],
        Field(min_length=1, max_length=values.MAX_DIMENSION_COMPONENTS),
    ]

    @model_validator(mode="after")
    def _components_follow_text(self) -> Dimensions:
        derived = [(c.raw, c.magnitude, c.unit) for c in values.parse_dimensions(self.text)]
        if [(c.raw, c.magnitude, c.unit) for c in self.components] != derived:
            raise ValueError("components must be exactly what the written text says")
        return self


def dimensions_from_text(text: str) -> Dimensions:
    return Dimensions(
        text=text,
        components=[
            DimensionComponent(raw=c.raw, magnitude=c.magnitude, unit=c.unit)
            for c in values.parse_dimensions(text)
        ],
    )


Fulfillment = Literal["delivery", "pickup"]
T = TypeVar("T")


# ---------------------------------------------------------------------------
# The AI proposal as stored on a draft (after grounding)
# ---------------------------------------------------------------------------

_NULL = {"type": "null"}
_NOT_NULL = {"not": _NULL}
_EMPTY = {"maxItems": 0}
_CONTAINS_SUPPORT = {
    "minItems": 1,
    "contains": {"properties": {"role": {"const": "supports"}}, "required": ["role"]},
}


def _when(key: str, value: str, then: dict) -> dict:
    return {
        "if": {"properties": {key: {"const": value}}, "required": [key]},
        "then": {"properties": then},
    }


_PROPOSAL_RULES = {
    "allOf": [
        _when(
            "state",
            "extracted",
            {
                "value": _NOT_NULL,
                "candidates": _EMPTY,
                "ambiguity_reason": _NULL,
                "evidence": _CONTAINS_SUPPORT,
            },
        ),
        _when(
            "state",
            "missing",
            {"value": _NULL, "candidates": _EMPTY, "ambiguity_reason": _NULL, "evidence": _EMPTY},
        ),
        _when(
            "state",
            "ambiguous",
            {"value": _NULL, "ambiguity_reason": _NOT_NULL, "evidence": {"minItems": 1}},
        ),
    ]
}


class Grounding(ContractModel):
    outcome: Literal["accepted", "downgraded"]
    rule_codes: list[GroundingRule]

    @model_validator(mode="after")
    def _rules_explain_downgrades(self) -> Grounding:
        if bool(self.rule_codes) != (self.outcome == "downgraded"):
            raise ValueError("rule_codes are set exactly for downgraded fields")
        return self


class _ProposalRecord(ContractModel, Generic[T]):
    model_config = ConfigDict(json_schema_extra=_PROPOSAL_RULES)

    state: Literal["extracted", "missing", "ambiguous"]
    value: T | None
    candidates: Annotated[list[T], Field(max_length=Limits.CANDIDATES)]
    ambiguity_reason: AmbiguityReason | None
    evidence: EvidenceList
    extraction_run_id: UUID
    grounding: Grounding

    @model_validator(mode="after")
    def _state_rules(self) -> _ProposalRecord[T]:
        if (self.value is not None) != (self.state == "extracted"):
            raise ValueError("value is set exactly for extracted")
        if (self.ambiguity_reason is not None) != (self.state == "ambiguous"):
            raise ValueError("ambiguity_reason is set exactly for ambiguous")
        if self.candidates and self.state != "ambiguous":
            raise ValueError("only ambiguous fields list candidates")
        if self.state == "missing" and self.evidence:
            raise ValueError("missing fields carry no evidence")
        if self.state == "ambiguous" and not self.evidence:
            raise ValueError("ambiguous fields need evidence")
        if self.state == "extracted" and not any(e.role == "supports" for e in self.evidence):
            raise ValueError("extracted fields need supporting evidence")
        if self.grounding.outcome == "downgraded" and self.state != "ambiguous":
            raise ValueError("a downgraded field is ambiguous")
        return self


class TextProposalRecord(_ProposalRecord[str]):
    pass


class QuantityProposalRecord(_ProposalRecord[CanonicalDecimal]):
    pass


class UnitProposalRecord(_ProposalRecord[UnitCode]):
    pass


class DimensionsProposalRecord(_ProposalRecord[Dimensions]):
    pass


class FulfillmentProposalRecord(_ProposalRecord[Fulfillment]):
    pass


# ---------------------------------------------------------------------------
# Tracked fields: one schema per state, selected by "state"
# ---------------------------------------------------------------------------


class Resolution(ContractModel):
    method: Literal["typed", "chose_candidate"]
    candidate_index: Annotated[int, Field(ge=0, lt=Limits.CANDIDATES)] | None

    @model_validator(mode="after")
    def _index_belongs_to_choice(self) -> Resolution:
        if (self.candidate_index is not None) != (self.method == "chose_candidate"):
            raise ValueError("candidate_index is set exactly for chose_candidate")
        return self


_NoValues = Annotated[list[T], Field(max_length=0)]


class _Extracted(ContractModel, Generic[T]):
    state: Literal["extracted"]
    value: T
    candidates: _NoValues[T]
    ambiguity_reason: None
    evidence: Annotated[
        list[Evidence],
        Field(max_length=Limits.EVIDENCE_ITEMS, json_schema_extra=_CONTAINS_SUPPORT),
    ]

    @model_validator(mode="after")
    def _supported(self):
        if not any(e.role == "supports" for e in self.evidence):
            raise ValueError("extracted needs supporting evidence")
        return self


class _Missing(ContractModel, Generic[T]):
    state: Literal["missing"]
    value: None
    candidates: _NoValues[T]
    ambiguity_reason: None
    evidence: Annotated[list[Evidence], Field(max_length=0)]


class _Ambiguous(ContractModel, Generic[T]):
    state: Literal["ambiguous"]
    value: None
    candidates: Annotated[list[T], Field(max_length=Limits.CANDIDATES)]
    ambiguity_reason: AmbiguityReason
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=Limits.EVIDENCE_ITEMS)]


class _Entered(ContractModel, Generic[T]):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "resolution": {
                                "properties": {"method": {"const": "typed"}},
                                "required": ["method"],
                            }
                        },
                        "required": ["resolution"],
                    },
                    "then": {"properties": {"evidence": _EMPTY}},
                    "else": {"properties": {"evidence": {"minItems": 1}}},
                }
            ]
        }
    )

    state: Literal["employee_entered"]
    value: T
    candidates: _NoValues[T]
    ambiguity_reason: None
    evidence: EvidenceList
    entered_by: PersonRef
    entered_at: UtcDatetime
    resolution: Resolution

    @model_validator(mode="after")
    def _evidence_follows_method(self):
        if bool(self.evidence) != (self.resolution.method == "chose_candidate"):
            raise ValueError("entered fields keep evidence only when a candidate was chosen")
        return self


class _Cleared(ContractModel, Generic[T]):
    state: Literal["employee_cleared"]
    value: None
    candidates: _NoValues[T]
    ambiguity_reason: None
    evidence: Annotated[list[Evidence], Field(max_length=0)]
    cleared_by: PersonRef
    cleared_at: UtcDatetime


_STATE_BASES = (
    ("Extracted", _Extracted),
    ("Missing", _Missing),
    ("Ambiguous", _Ambiguous),
    ("Entered", _Entered),
    ("Cleared", _Cleared),
)


def _state_models(prefix: str, value_type, proposal_type) -> list[type[ContractModel]]:
    """Concrete classes such as QuantityFieldExtracted. 'proposal' is read-only:
    the AI's grounded proposal for this field, or null for employee-added content."""
    return [
        create_model(
            f"{prefix}{suffix}",
            __base__=base[value_type],
            __module__=__name__,
            proposal=(proposal_type | None, ...),
        )
        for suffix, base in _STATE_BASES
    ]


(
    TextFieldExtracted,
    TextFieldMissing,
    TextFieldAmbiguous,
    TextFieldEntered,
    TextFieldCleared,
) = _state_models("TextField", str, TextProposalRecord)
(
    QuantityFieldExtracted,
    QuantityFieldMissing,
    QuantityFieldAmbiguous,
    QuantityFieldEntered,
    QuantityFieldCleared,
) = _state_models("QuantityField", PositiveDecimal, QuantityProposalRecord)
(
    UnitFieldExtracted,
    UnitFieldMissing,
    UnitFieldAmbiguous,
    UnitFieldEntered,
    UnitFieldCleared,
) = _state_models("UnitField", UnitCode, UnitProposalRecord)
(
    DimensionsFieldExtracted,
    DimensionsFieldMissing,
    DimensionsFieldAmbiguous,
    DimensionsFieldEntered,
    DimensionsFieldCleared,
) = _state_models("DimensionsField", Dimensions, DimensionsProposalRecord)
(
    FulfillmentFieldExtracted,
    FulfillmentFieldMissing,
    FulfillmentFieldAmbiguous,
    FulfillmentFieldEntered,
    FulfillmentFieldCleared,
) = _state_models("FulfillmentField", Fulfillment, FulfillmentProposalRecord)

TextField = TypeAliasType(
    "TextField",
    Annotated[
        Union[
            TextFieldExtracted,
            TextFieldMissing,
            TextFieldAmbiguous,
            TextFieldEntered,
            TextFieldCleared,
        ],
        Field(discriminator="state"),
    ],
)
QuantityField = TypeAliasType(
    "QuantityField",
    Annotated[
        Union[
            QuantityFieldExtracted,
            QuantityFieldMissing,
            QuantityFieldAmbiguous,
            QuantityFieldEntered,
            QuantityFieldCleared,
        ],
        Field(discriminator="state"),
    ],
)
UnitField = TypeAliasType(
    "UnitField",
    Annotated[
        Union[
            UnitFieldExtracted,
            UnitFieldMissing,
            UnitFieldAmbiguous,
            UnitFieldEntered,
            UnitFieldCleared,
        ],
        Field(discriminator="state"),
    ],
)
DimensionsField = TypeAliasType(
    "DimensionsField",
    Annotated[
        Union[
            DimensionsFieldExtracted,
            DimensionsFieldMissing,
            DimensionsFieldAmbiguous,
            DimensionsFieldEntered,
            DimensionsFieldCleared,
        ],
        Field(discriminator="state"),
    ],
)
FulfillmentField = TypeAliasType(
    "FulfillmentField",
    Annotated[
        Union[
            FulfillmentFieldExtracted,
            FulfillmentFieldMissing,
            FulfillmentFieldAmbiguous,
            FulfillmentFieldEntered,
            FulfillmentFieldCleared,
        ],
        Field(discriminator="state"),
    ],
)


def _check_against_proposal(name: str, field) -> None:
    """A field in a model state is the proposal itself; a chosen candidate comes from it."""
    proposal = field.proposal
    if proposal is None:
        return
    if field.state in MODEL_STATES:
        for key in ("state", "value", "candidates", "ambiguity_reason", "evidence"):
            if getattr(field, key) != getattr(proposal, key):
                raise ValueError(f"{name}: the AI proposal cannot be altered without a person")
    elif field.state == "employee_entered" and field.resolution.method == "chose_candidate":
        index = field.resolution.candidate_index
        if (
            proposal.state != "ambiguous"
            or index >= len(proposal.candidates)
            or proposal.candidates[index] != field.value
            or proposal.evidence != field.evidence
        ):
            raise ValueError(f"{name}: chosen candidate must come from the AI proposal")


# ---------------------------------------------------------------------------
# Catalog and matching
# ---------------------------------------------------------------------------


class SkuSnapshot(ContractModel):
    """Catalog values as they were when shown to the employee."""

    sku_id: UUID
    code: ShortText
    description: ShortText
    product: ShortText | None
    dimension_designation: Dimensions | None = Field(
        description="The SKU's own ordered designation. No axis names."
    )
    species: ShortText | None
    grade: ShortText | None
    treatment: ShortText | None
    sell_unit: UnitCode
    active: bool


MATCH_ATTRIBUTES = ("product", "dimensions", "species", "grade", "treatment")
MatchAttribute = Literal["product", "dimensions", "species", "grade", "treatment"]


class MatchOutcome(StrEnum):
    EXACT_MATCH = "exact_match"
    SYNONYM_MATCH = "synonym_match"
    UNIT_UNCONFIRMED_EQUAL = "unit_unconfirmed_equal"
    MISMATCH = "mismatch"
    DIFFERENT_UNIT_NOT_COMPARED = "different_unit_not_compared"
    DIFFERENT_COMPONENT_COUNT = "different_component_count"
    NOT_DEFINED_ON_SKU = "not_defined_on_sku"
    NOT_STATED_IN_REQUEST = "not_stated_in_request"


MISMATCH_OUTCOMES = (MatchOutcome.MISMATCH, MatchOutcome.DIFFERENT_COMPONENT_COUNT)
UNVERIFIED_OUTCOMES = (
    MatchOutcome.DIFFERENT_UNIT_NOT_COMPARED,
    MatchOutcome.NOT_DEFINED_ON_SKU,
    MatchOutcome.NOT_STATED_IN_REQUEST,
)


class AttributeEvidence(ContractModel):
    attribute: MatchAttribute
    request_value: str | None
    sku_value: str | None
    outcome: MatchOutcome
    synonym_rule_id: UUID | None

    @model_validator(mode="after")
    def _synonym_has_rule(self) -> AttributeEvidence:
        if (self.synonym_rule_id is not None) != (self.outcome == "synonym_match"):
            raise ValueError("synonym_rule_id is set exactly for synonym_match")
        return self


class UnitCheck(ContractModel):
    status: Literal["same_unit", "different_unit", "request_unit_unresolved"]


class MatchPreview(ContractModel):
    attribute_evidence: list[AttributeEvidence]
    unit_check: UnitCheck


class CatalogCandidate(ContractModel):
    rank: Annotated[int, Field(ge=1)]
    sku: SkuSnapshot
    attribute_evidence: list[AttributeEvidence]
    unit_check: UnitCheck


class LiveEvaluation(ContractModel):
    """The selection re-checked against the current catalog and line on every read."""

    attribute_evidence: list[AttributeEvidence]
    unit_check: UnitCheck
    sku_active: bool
    sku_changed: bool = Field(description="Catalog values differ from the snapshot.")
    catalog_stale: bool = Field(description="The catalog version moved since selection.")


class SkuSelection(ContractModel):
    """Always made by an employee. Nothing is preselected, even a sole candidate."""

    sku: SkuSnapshot
    attribute_evidence: list[AttributeEvidence]
    unit_check: UnitCheck
    catalog_version: ShortText
    selected_by: PersonRef
    selected_at: UtcDatetime
    current: LiveEvaluation


class ClearedSelection(ContractModel):
    sku: SkuSnapshot
    attribute_evidence: list[AttributeEvidence]
    reason: Literal["matching_attribute_changed", "cleared_by_employee"]
    changed_fields: list[MatchAttribute]
    cleared_by: PersonRef
    cleared_at: UtcDatetime
    version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _fields_explain_reason(self) -> ClearedSelection:
        if bool(self.changed_fields) != (self.reason == "matching_attribute_changed"):
            raise ValueError("changed_fields are listed exactly for an attribute change")
        return self


class MatchResult(ContractModel):
    status: Literal["not_run", "no_candidate", "single_candidate", "multiple_candidates"]
    catalog_version: str | None
    matcher_version: str | None
    candidates: Annotated[list[CatalogCandidate], Field(max_length=Limits.CANDIDATES)]
    selection: SkuSelection | None
    last_cleared_selection: ClearedSelection | None

    @model_validator(mode="after")
    def _status_matches_candidates(self) -> MatchResult:
        count = len(self.candidates)
        expected = (
            "multiple_candidates" if count > 1 else "single_candidate" if count == 1 else None
        )
        if expected:
            if self.status != expected:
                raise ValueError(f"{count} candidates require status {expected}")
        elif self.status not in ("not_run", "no_candidate"):
            raise ValueError("status requires candidates")
        return self


# ---------------------------------------------------------------------------
# Request content
# ---------------------------------------------------------------------------

LINE_FIELDS = ("product", "quantity", "unit", "dimensions", "species", "grade", "treatment")
JOB_FIELDS = (
    "fulfillment_method",
    "requested_date_text",
    "delivery_address",
    "job_reference",
    "notes",
)
LineFieldName = Literal[
    "product", "quantity", "unit", "dimensions", "species", "grade", "treatment"
]
JobFieldName = Literal[
    "fulfillment_method", "requested_date_text", "delivery_address", "job_reference", "notes"
]


class LineRemoval(ContractModel):
    reason: ShortText
    removed_by: PersonRef
    removed_at: UtcDatetime


class MaterialLine(ContractModel):
    line_id: UUID
    position: Annotated[int, Field(ge=1)]
    origin: Literal["model", "employee"]
    status: Literal["active", "removed"]
    removal: LineRemoval | None
    raw_wording: str | None = Field(description="Verbatim source wording. Never edited.")
    source_evidence: EvidenceList
    employee_source_spans: EvidenceList = Field(
        description="Spans an employee cited for a line they added. Not AI evidence."
    )
    product: TextField
    quantity: QuantityField
    unit: UnitField
    dimensions: DimensionsField
    species: TextField
    grade: TextField
    treatment: TextField
    match: MatchResult

    @model_validator(mode="after")
    def _origin_rules(self) -> MaterialLine:
        fields = [(name, getattr(self, name)) for name in LINE_FIELDS]
        if (self.removal is not None) != (self.status == "removed"):
            raise ValueError("removal is recorded exactly for removed lines")
        if self.origin == "model":
            if not self.raw_wording or not self.source_evidence:
                raise ValueError("model lines need raw_wording and source_evidence")
            if self.raw_wording != self.source_evidence[0].quote:
                raise ValueError("raw_wording must equal the first source evidence quote")
            if self.employee_source_spans:
                raise ValueError("employee spans are only for employee lines")
            if any(field.proposal is None for _, field in fields):
                raise ValueError("model lines keep the AI proposal on every field")
        else:
            if self.raw_wording is not None or self.source_evidence:
                raise ValueError("employee lines carry no source wording or AI evidence")
            allowed = ("missing", "employee_entered", "employee_cleared")
            if any(f.state not in allowed or f.proposal is not None for _, f in fields):
                raise ValueError("employee lines cannot hold model field states or proposals")
        for name, field in fields:
            _check_against_proposal(name, field)
        return self


class JobDetails(ContractModel):
    fulfillment_method: FulfillmentField
    requested_date_text: TextField
    delivery_address: TextField
    job_reference: TextField
    notes: TextField

    @model_validator(mode="after")
    def _proposals_respected(self) -> JobDetails:
        for name in JOB_FIELDS:
            _check_against_proposal(name, getattr(self, name))
        return self


class RequestContent(ContractModel):
    lines: Annotated[list[MaterialLine], Field(max_length=Limits.MATERIAL_LINES)]
    job_details: JobDetails

    @model_validator(mode="after")
    def _lines_unique(self) -> RequestContent:
        for key in ("line_id", "position"):
            seen = [getattr(line, key) for line in self.lines]
            if len(seen) != len(set(seen)):
                raise ValueError(f"{key} values must be unique")
        return self


# ---------------------------------------------------------------------------
# Warnings and approval blockers
# ---------------------------------------------------------------------------

_TARGET_RULES = {
    "allOf": [
        _when("scope", "request", {"line_id": _NULL, "field": _NULL}),
        _when(
            "scope",
            "line",
            {
                "line_id": _NOT_NULL,
                "field": {
                    "enum": [
                        "product", "quantity", "unit", "dimensions", "species", "grade",
                        "treatment", "sku", None,
                    ]
                },
            },
        ),
        _when(
            "scope",
            "job_detail",
            {
                "line_id": _NULL,
                "field": {
                    "enum": [
                        "fulfillment_method", "requested_date_text", "delivery_address",
                        "job_reference", "notes",
                    ]
                },
            },
        ),
    ]
}


class Target(ContractModel):
    """What a warning, blocker or change refers to."""

    model_config = ConfigDict(json_schema_extra=_TARGET_RULES)

    scope: Literal["request", "line", "job_detail"]
    line_id: UUID | None
    field: str | None

    @model_validator(mode="after")
    def _scope_rules(self) -> Target:
        if self.scope == "request":
            ok = self.line_id is None and self.field is None
        elif self.scope == "line":
            ok = self.line_id is not None and self.field in (None, "sku", *LINE_FIELDS)
        else:
            ok = self.line_id is None and self.field in JOB_FIELDS
        if not ok:
            raise ValueError("target does not match its scope")
        return self


def _warning_rules() -> dict:
    def group(codes: list[str], then: dict) -> dict:
        return {
            "if": {"properties": {"code": {"enum": codes}}, "required": ["code"]},
            "then": {"properties": then},
        }

    rules = []
    for requires, informational in ((False, True), (True, False)):
        codes = [c.value for c in WarningCode if (c in INFORMATIONAL_WARNINGS) == informational]
        rules.append(group(codes, {"requires_acknowledgement": {"const": requires}}))
    for heuristic in (True, False):
        codes = [c.value for c in WarningCode if (c in HEURISTIC_WARNINGS) == heuristic]
        rules.append(group(codes, {"heuristic": {"const": heuristic}}))
    rules.append(
        group(["possible_follow_up_same_sender"], {"related_communication_ids": _EMPTY})
    )
    rules.append(
        group(
            ["unprocessed_attachment"],
            {"target": {"properties": {"scope": {"const": "request"}}}},
        )
    )
    return {"allOf": rules}


class ReviewWarning(ContractModel):
    """Computed from current facts. warning_id changes if the condition changes."""

    model_config = ConfigDict(json_schema_extra=_warning_rules())

    warning_id: ShortText
    code: WarningCode
    message: ShortText = Field(description="Plain text. Never embeds email content.")
    target: Target
    requires_acknowledgement: bool
    heuristic: bool
    evidence: EvidenceList
    related_communication_ids: list[UUID]

    @model_validator(mode="after")
    def _code_rules(self) -> ReviewWarning:
        if self.requires_acknowledgement == (self.code in INFORMATIONAL_WARNINGS):
            raise ValueError("requires_acknowledgement is fixed by the warning code")
        if self.heuristic != (self.code in HEURISTIC_WARNINGS):
            raise ValueError("heuristic is fixed by the warning code")
        if self.code == WarningCode.POSSIBLE_FOLLOW_UP_SAME_SENDER and (
            self.related_communication_ids
        ):
            raise ValueError("a sender match never links messages")
        if self.code == WarningCode.UNPROCESSED_ATTACHMENT and self.target.scope != "request":
            raise ValueError("attachments share one warning on the request")
        return self


class ApprovalBlocker(ContractModel):
    """One blocker per underlying issue."""

    blocker_id: ShortText
    code: BlockerCode
    message: ShortText
    target: Target
    warning_id: str | None

    @model_validator(mode="after")
    def _code_matches_target(self) -> ApprovalBlocker:
        t = self.target
        if (self.warning_id is not None) != (self.code == "warning_not_acknowledged"):
            raise ValueError("warning_id is set exactly for warning_not_acknowledged")
        expected_field = {
            "quantity_unresolved": "quantity",
            "unit_unresolved": "unit",
            "unit_incompatible": "unit",
            "sku_not_selected": "sku",
            "sku_inactive": "sku",
        }.get(self.code)
        if expected_field and (t.scope != "line" or t.field != expected_field):
            raise ValueError(f"{self.code} targets the line field {expected_field}")
        if self.code == "no_active_lines" and t.scope != "request":
            raise ValueError("no_active_lines targets the request")
        if self.code == "ambiguous_field" and (
            t.field is None or t.field in ("quantity", "unit", "sku")
        ):
            raise ValueError("quantity and unit use their own blocker codes")
        return self


# ---------------------------------------------------------------------------
# Approval, decisions and the request
# ---------------------------------------------------------------------------


class ExtractionRunInfo(ContractModel):
    run_id: UUID
    provider: ShortText
    model_version: ShortText
    prompt_version: ShortText
    schema_version: Literal["0.1"]
    parser_version: ShortText
    grounding_version: ShortText
    lexicon_version: ShortText
    completed_at: UtcDatetime


class AcknowledgedWarning(ContractModel):
    """The warning exactly as the approver saw it."""

    warning_id: ShortText
    code: WarningCode
    message: ShortText
    target: Target
    marked_false_positive: bool

    @model_validator(mode="after")
    def _only_heuristics(self) -> AcknowledgedWarning:
        if self.marked_false_positive and self.code not in HEURISTIC_WARNINGS:
            raise ValueError("only heuristic warnings can be marked as false positives")
        return self


class ApprovedLineCheck(ContractModel):
    """Catalog facts read for one line at the moment of approval."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "properties": {
                        "sku": {"properties": {"active": {"const": True}}},
                        "unit_check": {"properties": {"status": {"const": "same_unit"}}},
                    }
                }
            ]
        }
    )

    line_id: UUID
    sku: SkuSnapshot = Field(description="Catalog values read at approval, not at selection.")
    attribute_evidence: list[AttributeEvidence]
    unit_check: UnitCheck
    sku_changed_since_selection: bool

    @model_validator(mode="after")
    def _approvable(self) -> ApprovedLineCheck:
        if not self.sku.active:
            raise ValueError("an inactive SKU cannot be approved")
        if self.unit_check.status != "same_unit":
            raise ValueError("approval needs a compatible unit")
        return self


class ApprovalCatalogCheck(ContractModel):
    """The immutable record of what approval was checked against. Never recomputed."""

    catalog_version: ShortText = Field(description="Catalog version read at approval.")
    matcher_version: ShortText = Field(description="Version of the comparison rules used.")
    lines: Annotated[
        list[ApprovedLineCheck], Field(min_length=1, max_length=Limits.MATERIAL_LINES)
    ]

    @model_validator(mode="after")
    def _one_per_line(self) -> ApprovalCatalogCheck:
        if len({c.line_id for c in self.lines}) != len(self.lines):
            raise ValueError("each approved line is checked once")
        return self


def canonical_sha256(value: BaseModel) -> str:
    """SHA-256 of UTF-8 JSON: sorted keys, no extra whitespace, unescaped non-ASCII."""
    encoded = json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ApprovalRecord(ContractModel):
    """Internal approval of one reviewed version. It authorizes nothing external."""

    approval_id: UUID
    request_id: UUID
    approved_version: Annotated[int, Field(ge=1)] = Field(
        description="The version that was reviewed. Approval creates approved_version + 1."
    )
    content_sha256: Sha256
    catalog_check: ApprovalCatalogCheck
    catalog_check_sha256: Sha256 = Field(description="Digest of catalog_check.")
    approved_by: PersonRef
    approved_at: UtcDatetime
    acknowledged_warnings: list[AcknowledgedWarning]
    status: Literal["active", "revoked"]
    revoked_by: PersonRef | None
    revoked_at: UtcDatetime | None
    revocation_reason: ShortText | None

    @model_validator(mode="after")
    def _checks_are_intact_and_acknowledged(self) -> ApprovalRecord:
        if self.catalog_check_sha256 != canonical_sha256(self.catalog_check):
            raise ValueError("catalog_check_sha256 does not match catalog_check")
        acknowledged = {(w.code, w.target.line_id) for w in self.acknowledged_warnings}
        for check in self.catalog_check.lines:
            outcomes = {item.outcome for item in check.attribute_evidence}
            needed = []
            if outcomes & set(MISMATCH_OUTCOMES):
                needed.append(WarningCode.SELECTED_SKU_ATTRIBUTE_MISMATCH)
            if outcomes & set(UNVERIFIED_OUTCOMES):
                needed.append(WarningCode.SELECTED_SKU_ATTRIBUTE_UNVERIFIED)
            if check.sku_changed_since_selection:
                needed.append(WarningCode.SELECTED_SKU_CHANGED)
            if any((code, check.line_id) not in acknowledged for code in needed):
                raise ValueError("a checked SKU difference was not acknowledged")
        return self

    @model_validator(mode="after")
    def _revocation_is_complete(self) -> ApprovalRecord:
        revoked = tuple(
            v is not None
            for v in (self.revoked_by, self.revoked_at, self.revocation_reason)
        )
        if revoked != ((True,) * 3 if self.status == "revoked" else (False,) * 3):
            raise ValueError("revocation details are set exactly when revoked")
        return self


class DecisionRecord(ContractModel):
    action: Literal["approve_internal", "decline", "reopen"]
    actor: PersonRef
    occurred_at: UtcDatetime
    resulting_version: Annotated[int, Field(ge=2)]
    reason: ShortText | None
    note: NoteText | None
    false_positive_warning_ids: list[str]


def _check_describes_content(check: ApprovalCatalogCheck, live: list[MaterialLine]) -> None:
    """An active approval's snapshot covers exactly the approved lines and their SKUs."""
    checked = {item.line_id: item for item in check.lines}
    if set(checked) != {line.line_id for line in live}:
        raise ValueError("the catalog check covers exactly the active lines")
    for line in live:
        item, selection = checked[line.line_id], line.match.selection
        if item.sku.sku_id != selection.sku.sku_id:
            raise ValueError("the checked SKU is the selected SKU")
        if item.sku.sell_unit != line.unit.value:
            raise ValueError("the checked sell unit is the approved unit")
        if item.sku_changed_since_selection != (item.sku != selection.sku):
            raise ValueError("sku_changed_since_selection does not match the two snapshots")
        expected = {}
        for name in MATCH_ATTRIBUTES:
            field = getattr(line, name)
            requested = field.value if field.state in RESOLVED_STATES else None
            defined = item.sku.dimension_designation if name == "dimensions" else getattr(
                item.sku, name
            )
            if name == "dimensions":
                requested = requested.text if requested else None
                defined = defined.text if defined else None
            if requested is not None or defined is not None:
                expected[name] = (requested, defined)
        recorded = {e.attribute: (e.request_value, e.sku_value) for e in item.attribute_evidence}
        if len(recorded) != len(item.attribute_evidence) or recorded != expected:
            raise ValueError("checked attributes must state the line and catalog values")


_ONE_ATTACHMENT_WARNING = {
    "contains": {
        "properties": {"code": {"const": "unprocessed_attachment"}},
        "required": ["code"],
    },
    "minContains": 0,
    "maxContains": 1,
}


class RequestDetail(ContractModel):
    schema_version: Literal["0.1"]
    request_id: UUID
    yard_id: UUID
    version: Annotated[int, Field(ge=1)]
    review_state: ReviewState
    origin_communication_id: UUID
    related_messages: list[LinkedMessage] = Field(
        description="Linked messages. They never change this request. Needs communication:read."
    )
    created_at: UtcDatetime
    updated_at: UtcDatetime
    updated_by: Actor
    content: RequestContent
    warnings: Annotated[
        list[ReviewWarning], Field(json_schema_extra=_ONE_ATTACHMENT_WARNING)
    ]
    approval_blockers: list[ApprovalBlocker] = Field(
        description="Content blockers, computed on read. Acknowledgements are checked at approval."
    )
    approval: ApprovalRecord | None
    last_decision: DecisionRecord | None
    extraction: ExtractionRunInfo | None
    inventory_status: Literal["not_assessed"]
    pricing_status: Literal["not_calculated"]

    @model_validator(mode="after")
    def _invariants(self) -> RequestDetail:
        lines = self.content.lines
        job = [getattr(self.content.job_details, name) for name in JOB_FIELDS]
        for line in lines:
            fields = [getattr(line, name) for name in LINE_FIELDS]
            cited = list(line.source_evidence) + list(line.employee_source_spans)
            cited += [e for f in fields for e in f.evidence]
            if any(e.communication_id != self.origin_communication_id for e in cited):
                raise ValueError("line evidence must cite the originating message")
        if any(
            e.communication_id != self.origin_communication_id for f in job for e in f.evidence
        ):
            raise ValueError("job evidence must cite the originating message")

        if [w.code for w in self.warnings].count(WarningCode.UNPROCESSED_ATTACHMENT) > 1:
            raise ValueError("unprocessed attachments share one grouped warning")

        ids = [b.blocker_id for b in self.approval_blockers]
        causes = [
            (b.warning_id,) if b.warning_id else (b.target.scope, b.target.line_id, b.target.field)
            for b in self.approval_blockers
        ]
        if len(ids) != len(set(ids)) or len(causes) != len(set(causes)):
            raise ValueError("one blocker per underlying issue")

        active = self.approval is not None and self.approval.status == "active"
        if active != (self.review_state == ReviewState.INTERNALLY_APPROVED):
            raise ValueError("an active approval exists exactly when internally_approved")
        if self.approval is not None:
            if self.approval.request_id != self.request_id:
                raise ValueError("approval belongs to another request")
            if self.approval.approved_version >= self.version:
                raise ValueError("approved_version must be below the current version")
        if active:
            live = [line for line in lines if line.status == "active"]
            if not live:
                raise ValueError("an approved request has at least one active line")
            for line in live:
                if line.quantity.state not in RESOLVED_STATES:
                    raise ValueError("approved lines have a resolved quantity")
                if line.unit.state not in RESOLVED_STATES:
                    raise ValueError("approved lines have a resolved unit")
                if line.match.selection is None:
                    raise ValueError("approved lines have an employee-selected SKU")
                if line.match.selection.unit_check.status != "same_unit":
                    raise ValueError("approved lines were selected with a compatible unit")
                if any(getattr(line, n).state == "ambiguous" for n in LINE_FIELDS):
                    raise ValueError("approved requests hold no ambiguity")
            if any(f.state == "ambiguous" for f in job):
                raise ValueError("approved requests hold no ambiguity")
            _check_describes_content(self.approval.catalog_check, live)
        return self


# ---------------------------------------------------------------------------
# Employee edits and decisions
# ---------------------------------------------------------------------------

TextLineField = Literal["product", "species", "grade", "treatment"]
JobTextField = Literal["requested_date_text", "delivery_address", "job_reference", "notes"]


# "set" operations always carry a value. clear_field is the only way to empty one.


class SetTextField(ContractModel):
    op: Literal["set_text_field"]
    line_id: UUID
    field: TextLineField
    value: LongText


class SetQuantity(ContractModel):
    op: Literal["set_quantity"]
    line_id: UUID
    value: PositiveDecimal


class SetUnit(ContractModel):
    op: Literal["set_unit"]
    line_id: UUID
    value: UnitCode


class SetDimensions(ContractModel):
    op: Literal["set_dimensions"]
    line_id: UUID
    text: ShortText = Field(
        description="Written dimension. The server derives components; unreadable text is 422."
    )


class SetJobText(ContractModel):
    op: Literal["set_job_text"]
    field: JobTextField
    value: LongText


class SetFulfillment(ContractModel):
    op: Literal["set_fulfillment"]
    value: Fulfillment


class LineFieldTarget(ContractModel):
    scope: Literal["line"]
    line_id: UUID
    field: LineFieldName


class JobFieldTarget(ContractModel):
    scope: Literal["job_detail"]
    field: JobFieldName


FieldTarget = Annotated[Union[LineFieldTarget, JobFieldTarget], Field(discriminator="scope")]


class ClearField(ContractModel):
    op: Literal["clear_field"]
    target: FieldTarget


class ChooseCandidate(ContractModel):
    op: Literal["choose_candidate"]
    target: FieldTarget
    candidate_index: Annotated[int, Field(ge=0, lt=Limits.CANDIDATES, strict=True)]


class SelectSku(ContractModel):
    op: Literal["select_sku"]
    line_id: UUID
    sku_id: UUID


class ClearSkuSelection(ContractModel):
    op: Literal["clear_sku_selection"]
    line_id: UUID


class NewLine(ContractModel):
    """Null means not supplied."""

    product: LongText | None
    quantity: PositiveDecimal | None
    unit: UnitCode | None
    dimensions_text: ShortText | None
    species: LongText | None
    grade: LongText | None
    treatment: LongText | None


class SourceSpan(ContractModel):
    """A span of the originating message chosen by an employee; the server verifies it."""

    source: SourceKind
    start: Annotated[int, Field(ge=0, strict=True)]
    end: Annotated[int, Field(ge=1, strict=True)]
    quote: LongText

    @model_validator(mode="after")
    def _span_matches_quote(self) -> SourceSpan:
        if self.end - self.start != len(self.quote):
            raise ValueError("end - start must equal the length of quote")
        return self


class AddLine(ContractModel):
    op: Literal["add_line"]
    line: NewLine
    source_spans: Annotated[list[SourceSpan], Field(max_length=Limits.EVIDENCE_ITEMS)]


class RemoveLine(ContractModel):
    op: Literal["remove_line"]
    line_id: UUID
    reason: ShortText


class RestoreLine(ContractModel):
    op: Literal["restore_line"]
    line_id: UUID


EditOperation = Annotated[
    Union[
        SetTextField,
        SetQuantity,
        SetUnit,
        SetDimensions,
        SetJobText,
        SetFulfillment,
        ClearField,
        ChooseCandidate,
        SelectSku,
        ClearSkuSelection,
        AddLine,
        RemoveLine,
        RestoreLine,
    ],
    Field(discriminator="op"),
]


class RequestEdit(ContractModel):
    expected_version: Version
    operations: Annotated[
        list[EditOperation], Field(min_length=1, max_length=Limits.OPERATIONS)
    ]
    note: NoteText | None = None


class ManualRequestCreate(ContractModel):
    reason: ShortText


WarningIds = Annotated[list[ShortText], Field(max_length=1000)]


class ApproveInternal(ContractModel):
    action: Literal["approve_internal"]
    expected_version: Version
    acknowledged_warning_ids: WarningIds
    false_positive_warning_ids: WarningIds = Field(
        default_factory=list,
        description="Heuristic warnings the employee judged wrong. Recorded for evaluation.",
    )
    note: NoteText | None = None


class Decline(ContractModel):
    action: Literal["decline"]
    expected_version: Version
    reason: ShortText
    false_positive_warning_ids: WarningIds = Field(default_factory=list)


class Reopen(ContractModel):
    action: Literal["reopen"]
    expected_version: Version
    reason: ShortText


class DecisionRequest(
    RootModel[Annotated[Union[ApproveInternal, Decline, Reopen], Field(discriminator="action")]]
):
    """Flat JSON body, selected by 'action'. There is no 'send' action."""


class MarkHandled(ContractModel):
    model_config = ConfigDict(json_schema_extra={"allOf": [_OTHER_NEEDS_NOTE]})

    action: Literal["mark_handled"]
    expected_handling_version: Annotated[int, Field(ge=0, strict=True)]
    reason: HandlingReason
    note: NoteText | None = None

    @model_validator(mode="after")
    def _other_needs_note(self) -> MarkHandled:
        if self.reason == HandlingReason.OTHER and not self.note:
            raise ValueError("reason 'other' needs a note")
        return self


class ReopenHandling(ContractModel):
    action: Literal["reopen"]
    expected_handling_version: Annotated[int, Field(ge=1, strict=True)]
    reason: ShortText


class HandlingRequest(
    RootModel[Annotated[Union[MarkHandled, ReopenHandling], Field(discriminator="action")]]
):
    """Closes or reopens a non-request. It deletes nothing and clears no warning."""


# ---------------------------------------------------------------------------
# History, audit and other storage shapes
# ---------------------------------------------------------------------------


class ChangeValue(ContractModel):
    state: str | None
    text: str | None
    sku_id: UUID | None


class FieldChange(ContractModel):
    target: Target
    before: ChangeValue | None
    after: ChangeValue | None


class RevisionSummary(ContractModel):
    version: Annotated[int, Field(ge=1)]
    change_type: Literal[
        "model_proposal",
        "manual_creation",
        "employee_edit",
        "internal_approval",
        "decline",
        "reopen",
    ]
    review_state: ReviewState
    actor: Actor
    created_at: UtcDatetime
    note: str | None
    operations: list[EditOperation]
    changes: list[FieldChange]
    decision: DecisionRecord | None


class RevisionDetail(ContractModel):
    summary: RevisionSummary
    content: RequestContent


class AuditAction(StrEnum):
    INTAKE_ACCEPTED = "intake_accepted"
    INTAKE_DUPLICATE = "intake_duplicate"
    INTAKE_CONFLICT_QUARANTINED = "intake_conflict_quarantined"
    INTAKE_REJECTED_QUARANTINED = "intake_rejected_quarantined"
    ORIGINAL_DOWNLOADED = "original_downloaded"
    ACCESS_DENIED = "access_denied"
    REQUEST_CREATED = "request_created"
    REQUEST_EDITED = "request_edited"
    REQUEST_APPROVED = "request_approved"
    REQUEST_DECLINED = "request_declined"
    REQUEST_REOPENED = "request_reopened"
    HANDLING_MARKED = "handling_marked"
    HANDLING_REOPENED = "handling_reopened"
    PROCESSING_CHANGED = "processing_changed"


class AuditEvent(ContractModel):
    """Storage shape only. Append-only. No v0.1 endpoint exposes it."""

    audit_id: UUID
    yard_id: UUID
    actor_type: Literal["system", "employee", "integration"]
    actor_id: UUID | None
    action: AuditAction
    entity_type: ShortText
    entity_id: UUID | None
    previous_state: str | None
    new_state: str | None
    entity_version: int | None
    reason: str | None
    auth_method: str | None
    permission_used: Permission | None
    trace_id: UUID
    occurred_at: UtcDatetime


class DeliveryAttempt(ContractModel):
    """Storage shape: one row per authenticated intake attempt within the limits.
    Over-limit submissions store nothing."""

    attempt_id: UUID
    yard_id: UUID
    integration_id: UUID
    external_message_id: ExternalId | None
    external_event_id: ExternalId | None
    raw_sha256: Sha256 | None
    outcome: Literal["accepted", "duplicate", "conflict_quarantined", "rejected_quarantined"]
    error_code: ErrorCode | None
    occurred_at: UtcDatetime


class SecurityLogEntry(ContractModel):
    """Storage shape for unauthenticated attempts. Holds no payload or credential."""

    entry_id: UUID
    source: ShortText
    error_code: ErrorCode
    trace_id: UUID
    occurred_at: UtcDatetime


# ---------------------------------------------------------------------------
# Model-adapter output (checked, then grounded, before any draft is created)
# ---------------------------------------------------------------------------


class ProposedEvidence(ContractModel):
    """The model quotes; the server locates the quote and computes offsets."""

    source: SourceKind
    quote: LongText
    occurrence: Annotated[int, Field(ge=0, strict=True)]
    role: EvidenceRole


ProposedEvidenceList = Annotated[
    list[ProposedEvidence], Field(max_length=Limits.EVIDENCE_ITEMS)
]


class _PExtracted(ContractModel, Generic[T]):
    state: Literal["extracted"]
    value: T
    candidates: _NoValues[T]
    ambiguity_reason: None
    evidence: Annotated[
        list[ProposedEvidence],
        Field(max_length=Limits.EVIDENCE_ITEMS, json_schema_extra=_CONTAINS_SUPPORT),
    ]

    @model_validator(mode="after")
    def _supported(self):
        if not any(e.role == "supports" for e in self.evidence):
            raise ValueError("extracted fields need supporting evidence")
        return self


class _PMissing(ContractModel, Generic[T]):
    state: Literal["missing"]
    value: None
    candidates: _NoValues[T]
    ambiguity_reason: None
    evidence: Annotated[list[ProposedEvidence], Field(max_length=0)]


class _PAmbiguous(ContractModel, Generic[T]):
    state: Literal["ambiguous"]
    value: None
    candidates: Annotated[list[T], Field(max_length=Limits.CANDIDATES)]
    ambiguity_reason: ModelAmbiguityReason
    evidence: Annotated[
        list[ProposedEvidence], Field(min_length=1, max_length=Limits.EVIDENCE_ITEMS)
    ]


def _proposed_models(prefix: str, value_type) -> list[type[ContractModel]]:
    return [
        create_model(f"{prefix}{suffix}", __base__=base[value_type], __module__=__name__)
        for suffix, base in (
            ("Extracted", _PExtracted),
            ("Missing", _PMissing),
            ("Ambiguous", _PAmbiguous),
        )
    ]


ProposedTextExtracted, ProposedTextMissing, ProposedTextAmbiguous = _proposed_models(
    "ProposedText", LongText
)
(
    ProposedQuantityExtracted,
    ProposedQuantityMissing,
    ProposedQuantityAmbiguous,
) = _proposed_models("ProposedQuantity", PositiveDecimal)
ProposedUnitExtracted, ProposedUnitMissing, ProposedUnitAmbiguous = _proposed_models(
    "ProposedUnit", UnitCode
)
(
    ProposedDimensionsExtracted,
    ProposedDimensionsMissing,
    ProposedDimensionsAmbiguous,
) = _proposed_models("ProposedDimensions", ShortText)
(
    ProposedFulfillmentExtracted,
    ProposedFulfillmentMissing,
    ProposedFulfillmentAmbiguous,
) = _proposed_models("ProposedFulfillment", Fulfillment)

ProposedText = TypeAliasType(
    "ProposedText",
    Annotated[
        Union[ProposedTextExtracted, ProposedTextMissing, ProposedTextAmbiguous],
        Field(discriminator="state"),
    ],
)
ProposedQuantity = TypeAliasType(
    "ProposedQuantity",
    Annotated[
        Union[ProposedQuantityExtracted, ProposedQuantityMissing, ProposedQuantityAmbiguous],
        Field(discriminator="state"),
    ],
)
ProposedUnit = TypeAliasType(
    "ProposedUnit",
    Annotated[
        Union[ProposedUnitExtracted, ProposedUnitMissing, ProposedUnitAmbiguous],
        Field(discriminator="state"),
    ],
)
ProposedDimensions = TypeAliasType(
    "ProposedDimensions",
    Annotated[
        Union[
            ProposedDimensionsExtracted,
            ProposedDimensionsMissing,
            ProposedDimensionsAmbiguous,
        ],
        Field(discriminator="state"),
    ],
)
ProposedFulfillment = TypeAliasType(
    "ProposedFulfillment",
    Annotated[
        Union[
            ProposedFulfillmentExtracted,
            ProposedFulfillmentMissing,
            ProposedFulfillmentAmbiguous,
        ],
        Field(discriminator="state"),
    ],
)


class ProposedLine(ContractModel):
    source_evidence: Annotated[
        list[ProposedEvidence], Field(min_length=1, max_length=Limits.EVIDENCE_ITEMS)
    ]
    product: ProposedText
    quantity: ProposedQuantity
    unit: ProposedUnit
    dimensions: ProposedDimensions
    species: ProposedText
    grade: ProposedText
    treatment: ProposedText


class ProposedJobDetails(ContractModel):
    fulfillment_method: ProposedFulfillment
    requested_date_text: ProposedText
    delivery_address: ProposedText
    job_reference: ProposedText
    notes: ProposedText


class ExtractionProposal(ContractModel):
    """Model output. No SKU, price, inventory or approval keys exist; extras are rejected."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [_when("classification", "non_request", {"lines": _EMPTY})]
        }
    )

    schema_version: Literal["0.1"]
    classification: Classification
    lines: Annotated[list[ProposedLine], Field(max_length=Limits.MATERIAL_LINES)]
    job_details: ProposedJobDetails
    multiple_jobs_evidence: ProposedEvidenceList = Field(
        description="Quotes showing that the message covers more than one job. Empty if not."
    )

    @model_validator(mode="after")
    def _non_requests_have_no_lines(self) -> ExtractionProposal:
        if self.classification == Classification.NON_REQUEST and self.lines:
            raise ValueError("non_request_with_lines")
        return self


# Grounded result -------------------------------------------------------------


class GroundedLine(ContractModel):
    source_evidence: Annotated[
        list[Evidence], Field(min_length=1, max_length=Limits.EVIDENCE_ITEMS)
    ]
    product: TextProposalRecord
    quantity: QuantityProposalRecord
    unit: UnitProposalRecord
    dimensions: DimensionsProposalRecord
    species: TextProposalRecord
    grade: TextProposalRecord
    treatment: TextProposalRecord


class GroundedJobDetails(ContractModel):
    fulfillment_method: FulfillmentProposalRecord
    requested_date_text: TextProposalRecord
    delivery_address: TextProposalRecord
    job_reference: TextProposalRecord
    notes: TextProposalRecord


class GroundingWarning(ContractModel):
    code: WarningCode
    line_index: Annotated[int, Field(ge=0)] | None
    evidence: list[Evidence]


class GroundedProposal(ContractModel):
    schema_version: Literal["0.1"]
    extraction_run_id: UUID
    grounding_version: ShortText
    lexicon_version: ShortText
    classification: Classification
    lines: Annotated[list[GroundedLine], Field(max_length=Limits.MATERIAL_LINES)]
    job_details: GroundedJobDetails
    warnings: list[GroundingWarning]


class StructuralFailureCode(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    UNKNOWN_KEY = "unknown_key"
    LINE_WITHOUT_SOURCE_EVIDENCE = "line_without_source_evidence"
    QUOTE_NOT_FOUND = "quote_not_found"
    NON_REQUEST_WITH_LINES = "non_request_with_lines"


class StructuralFailure(ContractModel):
    code: StructuralFailureCode
    location: str = Field(description="JSON Pointer into the model output.")


class ExtractionRunRecord(ContractModel):
    """Storage shape only. Raw model output is kept apart from the grounded result
    and is never returned by the API or copied into a draft."""

    run: ExtractionRunInfo
    communication_id: UUID
    raw_output: str
    raw_output_sha256: Sha256
    outcome: Literal["grounded", "rejected"]
    failures: list[StructuralFailure]
    grounded: GroundedProposal | None

    @model_validator(mode="after")
    def _outcome_matches(self) -> ExtractionRunRecord:
        if self.outcome == "grounded":
            ok = self.grounded is not None and not self.failures
        else:
            ok = self.grounded is None and bool(self.failures)
        if not ok:
            raise ValueError("a run is either grounded or rejected with reasons")
        return self


# ---------------------------------------------------------------------------
# Lists, identity and errors
# ---------------------------------------------------------------------------


class AttentionFlag(StrEnum):
    PROCESSING_FAILED = "processing_failed"
    CONFLICTING_REDELIVERY = "conflicting_redelivery"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    NEWER_RELATED_MESSAGE = "newer_related_message"
    POSSIBLE_FOLLOW_UP = "possible_follow_up"
    UNCERTAIN_CLASSIFICATION = "uncertain_classification"
    UNPROCESSED_ATTACHMENT = "unprocessed_attachment"


class InboxRequestSummary(ContractModel):
    request_id: UUID
    review_state: ReviewState
    version: Annotated[int, Field(ge=1)]
    active_line_count: Count
    blocker_count: Count
    ambiguous_field_count: Count
    missing_field_count: Count
    unselected_line_count: Count


class InboxItem(ContractModel):
    communication_id: UUID
    channel: Literal["email"]
    received_at: UtcDatetime
    ingested_at: UtcDatetime
    updated_at: UtcDatetime
    sender: EmailParty | None
    subject: str | None
    preview: Annotated[str, Field(max_length=Limits.PREVIEW_CHARS)] | None = Field(
        description="First 200 code points of body_text, verbatim. Untrusted."
    )
    processing_state: ProcessingState
    classification: Classification | None
    failure_code: FailureCode | None
    attachment_count: Count | None
    warning_codes: list[WarningCode]
    attention: list[AttentionFlag]
    handling: HandlingState
    related_messages: list[LinkedMessage]
    request: InboxRequestSummary | None = Field(description="Null without request:read.")


class InboxPage(ContractModel):
    items: list[InboxItem]
    next_cursor: str | None


class InboxCounts(ContractModel):
    needs_review: Count
    open_non_requests: Count
    processing: Count
    failed: Count
    handled: Count
    drafts: Count | None = Field(description="Null without request:read.")
    internally_approved: Count | None = Field(description="Null without request:read.")
    declined: Count | None = Field(description="Null without request:read.")


class RevisionPage(ContractModel):
    items: list[RevisionSummary]
    next_cursor: str | None


class SkuSearchResult(ContractModel):
    sku: SkuSnapshot
    preview: MatchPreview | None = Field(
        description="Comparison with the line given by request_id and line_id, else null."
    )


class SkuPage(ContractModel):
    catalog_version: str
    items: list[SkuSearchResult]
    next_cursor: str | None


class YardMembership(ContractModel):
    yard_id: UUID
    yard_name: str
    timezone: str
    permissions: list[Permission]


class CurrentUser(ContractModel):
    user_id: UUID
    display_name: str
    memberships: list[YardMembership]
    csrf_token: str


class Health(ContractModel):
    status: Literal["ok", "degraded"]


class ErrorDetail(ContractModel):
    location: str = Field(description="JSON Pointer to the offending part of the body.")
    message: str


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str = Field(description="Never echoes source content or secrets.")
    details: list[ErrorDetail]
    blockers: list[ApprovalBlocker]
    current_version: int | None
    current_state: str | None
    changed_by: PersonRef | None
    changed_at: UtcDatetime | None
    retry_after_seconds: Count | None
    trace_id: UUID


class ErrorResponse(ContractModel):
    error: ErrorBody
