"""Counter Copilot V4 data contract v0.1: PROPOSED, not approved.

These are interface definitions only. They contain shape rules that can be checked
from one payload. Rules that need stored data (tenant ownership, evidence offsets
against source text, state transitions, idempotency) are listed in
docs/DATA_CONTRACT.md and belong to the future backend.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar, Union
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    model_validator,
)

SCHEMA_VERSION = "0.1"


class ContractModel(BaseModel):
    """Unknown keys are rejected. Strings are never trimmed: wording is preserved."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _require_positive(value: str) -> str:
    if Decimal(value) <= 0:
        raise ValueError("must be greater than zero")
    return value


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]

# Decimals travel as strings so no JSON client can turn them into binary floats.
PositiveDecimal = Annotated[
    str,
    Field(
        pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,6})?$",
        json_schema_extra={"not": {"pattern": r"^0(\.0+)?$"}},
        examples=["40", "0.4375"],
    ),
    AfterValidator(_require_positive),
]

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
ExternalId = Annotated[str, Field(min_length=1, max_length=512)]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class UnitCode(StrEnum):
    """Provisional vocabulary (unresolved decision U-08)."""

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
    MILLIMETER = "mm"


class FieldState(StrEnum):
    EXTRACTED = "extracted"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    EMPLOYEE_ENTERED = "employee_entered"


class AmbiguityReason(StrEnum):
    CONFLICTING_STATEMENTS = "conflicting_statements"
    MULTIPLE_INTERPRETATIONS = "multiple_interpretations"
    RANGE_GIVEN = "range_given"
    UNRECOGNIZED_TERM = "unrecognized_term"
    UNCLEAR_REFERENCE = "unclear_reference"
    UNREADABLE = "unreadable"


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
    POSSIBLE_FOLLOW_UP = "possible_follow_up"
    CONFLICTING_DELIVERY = "conflicting_delivery"
    UNCERTAIN_CLASSIFICATION = "uncertain_classification"
    SELECTED_SKU_ATTRIBUTE_MISMATCH = "selected_sku_attribute_mismatch"


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
    NOT_FOUND = "not_found"
    VALIDATION_FAILED = "validation_failed"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    VERSION_CONFLICT = "version_conflict"
    INVALID_STATE = "invalid_state"
    REQUEST_ALREADY_EXISTS = "request_already_exists"
    APPROVAL_BLOCKED = "approval_blocked"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


# ---------------------------------------------------------------------------
# Inbound communication
# ---------------------------------------------------------------------------


class EmailParty(ContractModel):
    name: Annotated[str, Field(max_length=500)] | None
    address: Annotated[str, Field(min_length=1, max_length=320)]


class EmailThread(ContractModel):
    rfc_message_id: Annotated[str, Field(max_length=998)] | None
    in_reply_to: Annotated[str, Field(max_length=998)] | None
    references: Annotated[list[Annotated[str, Field(max_length=998)]], Field(max_length=100)]


class AttachmentMetadata(ContractModel):
    """Adapter-reported. The bytes remain inside the preserved original message."""

    filename: Annotated[str, Field(max_length=500)] | None
    media_type: Annotated[str, Field(min_length=1, max_length=200)]
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Sha256


class InboundEmailEvent(ContractModel):
    """JSON part of the intake request. It deliberately carries no yard_id,
    storage reference or idempotency key: the server derives all three."""

    schema_version: Literal["0.1"]
    channel: Literal["email"]
    external_message_id: ExternalId = Field(
        description="Stable ID assigned by the mail source; identical on every redelivery."
    )
    external_event_id: ExternalId | None = Field(
        description="ID of this delivery attempt, if the source has one. Not used for deduplication."
    )
    received_at: UtcDatetime
    sender: EmailParty
    recipients: Annotated[list[EmailParty], Field(min_length=1, max_length=200)]
    subject: Annotated[str, Field(max_length=2000)] | None
    body_text: Annotated[str, Field(max_length=200_000)]
    thread: EmailThread
    attachments: Annotated[list[AttachmentMetadata], Field(max_length=100)]
    provider_metadata: Annotated[
        dict[str, Annotated[str, Field(max_length=2000)]], Field(max_length=50)
    ]


class InboundAccepted(ContractModel):
    communication_id: UUID
    duplicate: bool
    processing_state: ProcessingState
    original_sha256: Sha256 = Field(description="Digest of the first preserved original.")


class OriginalDescriptor(ContractModel):
    media_type: Literal["message/rfc822"]
    size_bytes: Annotated[int, Field(ge=1)]
    sha256: Sha256
    stored_at: UtcDatetime


class CommunicationRecord(ContractModel):
    """Immutable once written. No API updates or deletes it."""

    communication_id: UUID
    yard_id: UUID
    integration_id: UUID
    channel: Literal["email"]
    direction: Literal["inbound"]
    external_message_id: ExternalId
    content_fingerprint: Sha256
    received_at: UtcDatetime
    ingested_at: UtcDatetime
    sender: EmailParty
    recipients: list[EmailParty]
    subject: str | None
    body_text: str
    thread: EmailThread
    attachments: list[AttachmentMetadata]
    original: OriginalDescriptor


class CommunicationStatus(ContractModel):
    """Mutable processing information, stored apart from the immutable record."""

    processing_state: ProcessingState
    classification: Classification | None
    failure_code: str | None
    possible_duplicate_of: list[UUID]
    related_request_ids: list[UUID]
    has_conflicting_delivery: bool
    origin_request_id: UUID | None


class CommunicationDetail(ContractModel):
    record: CommunicationRecord
    status: CommunicationStatus


# ---------------------------------------------------------------------------
# Evidence and tracked fields
# ---------------------------------------------------------------------------


class Evidence(ContractModel):
    """Pointer into immutable source text. Offsets count Unicode code points,
    zero-based, end-exclusive. The server must verify source[start:end] == quote."""

    communication_id: UUID
    source: SourceKind
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=1)]
    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    role: EvidenceRole

    @model_validator(mode="after")
    def _span_matches_quote(self) -> Evidence:
        if self.end - self.start != len(self.quote):
            raise ValueError("end - start must equal the length of quote")
        return self


class Measure(ContractModel):
    raw: ShortText = Field(description="Wording for this measurement, e.g. '7/16'.")
    magnitude: PositiveDecimal
    unit: LengthUnit | None
    unit_basis: Literal["stated", "yard_convention", "unspecified"]
    convention_rule_id: UUID | None

    @model_validator(mode="after")
    def _basis_is_consistent(self) -> Measure:
        if (self.unit is None) != (self.unit_basis == "unspecified"):
            raise ValueError("unit is null exactly when unit_basis is 'unspecified'")
        if (self.convention_rule_id is not None) != (self.unit_basis == "yard_convention"):
            raise ValueError("convention_rule_id is set exactly when a yard convention applied")
        return self


T = TypeVar("T")

_NULL = {"type": "null"}
_NOT_NULL = {"not": _NULL}
_EMPTY = {"maxItems": 0}
_NOT_ENTERED = {"entered_by": _NULL, "entered_at": _NULL}


def _when(state: str, then: dict) -> dict:
    return {
        "if": {"properties": {"state": {"const": state}}, "required": ["state"]},
        "then": {"properties": then},
    }


_FIELD_STATE_RULES = {
    "allOf": [
        _when(
            "extracted",
            {
                "value": _NOT_NULL,
                "candidates": _EMPTY,
                "ambiguity_reason": _NULL,
                "evidence": {
                    "minItems": 1,
                    "contains": {"properties": {"role": {"const": "supports"}}},
                },
                **_NOT_ENTERED,
            },
        ),
        _when(
            "missing",
            {
                "value": _NULL,
                "candidates": _EMPTY,
                "ambiguity_reason": _NULL,
                "evidence": _EMPTY,
                **_NOT_ENTERED,
            },
        ),
        _when(
            "ambiguous",
            {
                "value": _NULL,
                "ambiguity_reason": _NOT_NULL,
                "evidence": {"minItems": 1},
                **_NOT_ENTERED,
            },
        ),
        _when(
            "employee_entered",
            {
                "value": _NOT_NULL,
                "candidates": _EMPTY,
                "ambiguity_reason": _NULL,
                "evidence": _EMPTY,
                "entered_by": _NOT_NULL,
                "entered_at": _NOT_NULL,
            },
        ),
    ]
}


class TrackedField(ContractModel, Generic[T]):
    model_config = ConfigDict(json_schema_extra=_FIELD_STATE_RULES)

    state: FieldState
    value: T | None
    candidates: list[T]
    ambiguity_reason: AmbiguityReason | None
    evidence: list[Evidence]
    entered_by: UUID | None
    entered_at: UtcDatetime | None

    @model_validator(mode="after")
    def _state_rules(self) -> TrackedField[T]:
        state = self.state
        has_value = self.value is not None
        entered = self.entered_by is not None or self.entered_at is not None

        if state in (FieldState.EXTRACTED, FieldState.EMPLOYEE_ENTERED):
            if not has_value or self.candidates or self.ambiguity_reason:
                raise ValueError(f"{state} needs a value and no candidates or ambiguity reason")
        elif has_value:
            raise ValueError(f"{state} must not carry a value")

        if state == FieldState.EXTRACTED and not any(
            e.role == EvidenceRole.SUPPORTS for e in self.evidence
        ):
            raise ValueError("extracted needs supporting evidence")
        if state == FieldState.MISSING and (
            self.candidates or self.ambiguity_reason or self.evidence
        ):
            raise ValueError("missing carries no candidates, reason or evidence")
        if state == FieldState.AMBIGUOUS and (not self.ambiguity_reason or not self.evidence):
            raise ValueError("ambiguous needs a reason and evidence")

        if state == FieldState.EMPLOYEE_ENTERED:
            if self.entered_by is None or self.entered_at is None or self.evidence:
                raise ValueError("employee_entered needs entered_by and entered_at, no evidence")
        elif entered:
            raise ValueError("only employee_entered may set entered_by or entered_at")
        return self


class TextField(TrackedField[str]):
    pass


class QuantityField(TrackedField[PositiveDecimal]):
    pass


class UnitField(TrackedField[UnitCode]):
    pass


class MeasureField(TrackedField[Measure]):
    pass


class FulfillmentField(TrackedField[Literal["delivery", "pickup"]]):
    pass


# ---------------------------------------------------------------------------
# Catalog and matching
# ---------------------------------------------------------------------------


class SkuSnapshot(ContractModel):
    """Catalog values as they were when shown to the employee."""

    sku_id: UUID
    code: ShortText
    description: ShortText
    thickness: Measure | None
    width: Measure | None
    length: Measure | None
    species: str | None
    grade: str | None
    treatment: str | None
    sell_unit: UnitCode
    active: bool


class AttributeEvidence(ContractModel):
    attribute: Literal[
        "product", "thickness", "width", "length", "species", "grade", "treatment"
    ]
    request_value: str | None
    sku_value: str | None
    outcome: Literal[
        "exact_match",
        "synonym_match",
        "mismatch",
        "not_resolved_in_request",
        "not_defined_on_sku",
    ]
    synonym_rule_id: UUID | None

    @model_validator(mode="after")
    def _synonym_has_rule(self) -> AttributeEvidence:
        if (self.synonym_rule_id is not None) != (self.outcome == "synonym_match"):
            raise ValueError("synonym_rule_id is set exactly for synonym_match")
        return self


class UnitCheck(ContractModel):
    status: Literal[
        "same_unit", "converted", "no_approved_conversion", "request_unit_unresolved"
    ]
    conversion_rule_id: UUID | None
    conversion_factor: PositiveDecimal | None
    converted_quantity: PositiveDecimal | None = Field(
        description="Null when quantity is unresolved or no approved rule applies."
    )

    @model_validator(mode="after")
    def _conversion_is_traceable(self) -> UnitCheck:
        rule = (self.conversion_rule_id, self.conversion_factor)
        if self.status == "converted":
            if None in rule:
                raise ValueError("converted needs a rule ID and factor")
        elif rule != (None, None) or self.converted_quantity is not None:
            raise ValueError("conversion values are only allowed for status 'converted'")
        return self


class CatalogCandidate(ContractModel):
    rank: Annotated[int, Field(ge=1)]
    sku: SkuSnapshot
    attribute_evidence: list[AttributeEvidence]
    unit_check: UnitCheck


class SkuSelection(ContractModel):
    sku: SkuSnapshot
    attribute_evidence: list[AttributeEvidence]
    unit_check: UnitCheck
    selected_by: UUID
    selected_at: UtcDatetime


class MatchResult(ContractModel):
    status: Literal["not_run", "no_candidate", "single_candidate", "multiple_candidates"]
    catalog_version: str | None
    matcher_version: str | None
    candidates: Annotated[list[CatalogCandidate], Field(max_length=10)]
    selection: SkuSelection | None

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

LINE_FIELDS = (
    "product",
    "quantity",
    "unit",
    "dimension_text",
    "thickness",
    "width",
    "length",
    "species",
    "grade",
    "treatment",
)


class MaterialLine(ContractModel):
    line_id: UUID
    position: Annotated[int, Field(ge=1)]
    origin: Literal["model", "employee"]
    status: Literal["active", "removed"]
    raw_wording: str | None = Field(description="Verbatim source wording. Never edited.")
    source_evidence: list[Evidence]
    product: TextField
    quantity: QuantityField
    unit: UnitField
    dimension_text: TextField
    thickness: MeasureField
    width: MeasureField
    length: MeasureField
    species: TextField
    grade: TextField
    treatment: TextField
    match: MatchResult

    @model_validator(mode="after")
    def _origin_rules(self) -> MaterialLine:
        if self.origin == "model":
            if not self.raw_wording or not self.source_evidence:
                raise ValueError("model lines need raw_wording and source_evidence")
            if self.raw_wording != self.source_evidence[0].quote:
                raise ValueError("raw_wording must equal the first source evidence quote")
        else:
            if self.raw_wording is not None or self.source_evidence:
                raise ValueError("employee lines carry no source wording or evidence")
            allowed = (FieldState.MISSING, FieldState.EMPLOYEE_ENTERED)
            if any(getattr(self, name).state not in allowed for name in LINE_FIELDS):
                raise ValueError("employee lines cannot hold model field states")
        return self


class JobDetails(ContractModel):
    fulfillment_method: FulfillmentField
    requested_date_text: TextField
    delivery_address: TextField
    job_reference: TextField
    notes: TextField


class RequestContent(ContractModel):
    lines: Annotated[list[MaterialLine], Field(max_length=500)]
    job_details: JobDetails

    @model_validator(mode="after")
    def _line_ids_unique(self) -> RequestContent:
        ids = [line.line_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("line_id values must be unique")
        return self


class ReviewWarning(ContractModel):
    warning_id: ShortText = Field(description="Stable while the condition is unchanged.")
    code: WarningCode
    message: ShortText
    line_id: UUID | None
    requires_acknowledgement: bool


class ApprovalBlocker(ContractModel):
    code: BlockerCode
    message: ShortText
    line_id: UUID | None
    field: str | None
    warning_id: str | None


class ExtractionRunInfo(ContractModel):
    run_id: UUID
    provider: ShortText
    model_version: ShortText
    prompt_version: ShortText
    schema_version: Literal["0.1"]
    completed_at: UtcDatetime


class ApprovalRecord(ContractModel):
    """Internal approval of one reviewed version. It authorizes nothing external."""

    approval_id: UUID
    request_id: UUID
    approved_version: Annotated[int, Field(ge=1)]
    content_sha256: Sha256
    approved_by: UUID
    approved_at: UtcDatetime
    acknowledged_warning_ids: list[str]
    status: Literal["active", "revoked"]
    revoked_by: UUID | None
    revoked_at: UtcDatetime | None

    @model_validator(mode="after")
    def _revocation_is_complete(self) -> ApprovalRecord:
        revoked = (self.revoked_by is not None, self.revoked_at is not None)
        if revoked != ((True, True) if self.status == "revoked" else (False, False)):
            raise ValueError("revoked_by and revoked_at are set exactly when revoked")
        return self


class RequestDetail(ContractModel):
    schema_version: Literal["0.1"]
    request_id: UUID
    yard_id: UUID
    version: Annotated[int, Field(ge=1)]
    review_state: ReviewState
    origin_communication_id: UUID
    related_communication_ids: list[UUID] = Field(
        description="Later or linked messages. They never change this request."
    )
    created_at: UtcDatetime
    updated_at: UtcDatetime
    content: RequestContent
    warnings: list[ReviewWarning]
    approval_blockers: list[ApprovalBlocker]
    approval: ApprovalRecord | None
    extraction: ExtractionRunInfo | None
    inventory_status: Literal["not_assessed"]
    pricing_status: Literal["not_calculated"]

    @model_validator(mode="after")
    def _approval_matches_state(self) -> RequestDetail:
        active = self.approval is not None and self.approval.status == "active"
        if active != (self.review_state == ReviewState.INTERNALLY_APPROVED):
            raise ValueError("an active approval exists exactly when internally_approved")
        return self


# ---------------------------------------------------------------------------
# Employee edits and decisions
# ---------------------------------------------------------------------------

TextLineField = Literal["product", "dimension_text", "species", "grade", "treatment"]
MeasureLineField = Literal["thickness", "width", "length"]
JobTextField = Literal["requested_date_text", "delivery_address", "job_reference", "notes"]
EditedText = Annotated[str, Field(min_length=1, max_length=4000)]


class MeasureInput(ContractModel):
    raw: ShortText
    magnitude: PositiveDecimal
    unit: LengthUnit


# In every "set" operation value is required. An explicit null marks the field missing.


class SetTextField(ContractModel):
    op: Literal["set_text_field"]
    line_id: UUID
    field: TextLineField
    value: EditedText | None


class SetQuantity(ContractModel):
    op: Literal["set_quantity"]
    line_id: UUID
    value: PositiveDecimal | None


class SetUnit(ContractModel):
    op: Literal["set_unit"]
    line_id: UUID
    value: UnitCode | None


class SetMeasure(ContractModel):
    op: Literal["set_measure"]
    line_id: UUID
    field: MeasureLineField
    value: MeasureInput | None


class SetJobText(ContractModel):
    op: Literal["set_job_text"]
    field: JobTextField
    value: EditedText | None


class SetFulfillment(ContractModel):
    op: Literal["set_fulfillment"]
    value: Literal["delivery", "pickup"] | None


class SelectSku(ContractModel):
    op: Literal["select_sku"]
    line_id: UUID
    sku_id: UUID


class ClearSkuSelection(ContractModel):
    op: Literal["clear_sku_selection"]
    line_id: UUID


class NewLine(ContractModel):
    product: EditedText | None
    quantity: PositiveDecimal | None
    unit: UnitCode | None
    dimension_text: EditedText | None
    thickness: MeasureInput | None
    width: MeasureInput | None
    length: MeasureInput | None
    species: EditedText | None
    grade: EditedText | None
    treatment: EditedText | None


class AddLine(ContractModel):
    op: Literal["add_line"]
    line: NewLine


class RemoveLine(ContractModel):
    op: Literal["remove_line"]
    line_id: UUID


EditOperation = Annotated[
    Union[
        SetTextField,
        SetQuantity,
        SetUnit,
        SetMeasure,
        SetJobText,
        SetFulfillment,
        SelectSku,
        ClearSkuSelection,
        AddLine,
        RemoveLine,
    ],
    Field(discriminator="op"),
]


class RequestEdit(ContractModel):
    expected_version: Annotated[int, Field(ge=1)]
    operations: Annotated[list[EditOperation], Field(min_length=1, max_length=200)]
    note: Annotated[str, Field(max_length=2000)] | None = None


class ManualRequestCreate(ContractModel):
    reason: ShortText


class ApproveInternal(ContractModel):
    action: Literal["approve_internal"]
    expected_version: Annotated[int, Field(ge=1)]
    acknowledged_warning_ids: Annotated[list[str], Field(max_length=500)]
    note: Annotated[str, Field(max_length=2000)] | None = None


class Decline(ContractModel):
    action: Literal["decline"]
    expected_version: Annotated[int, Field(ge=1)]
    reason: ShortText


class Reopen(ContractModel):
    action: Literal["reopen"]
    expected_version: Annotated[int, Field(ge=1)]
    reason: ShortText


class DecisionRequest(
    RootModel[Annotated[Union[ApproveInternal, Decline, Reopen], Field(discriminator="action")]]
):
    """Flat JSON body, selected by 'action'. There is no 'send' action."""


# ---------------------------------------------------------------------------
# History and audit
# ---------------------------------------------------------------------------


class Actor(ContractModel):
    type: Literal["system", "employee"]
    user_id: UUID | None

    @model_validator(mode="after")
    def _employee_is_identified(self) -> Actor:
        if (self.user_id is not None) != (self.type == "employee"):
            raise ValueError("user_id is set exactly for employee actors")
        return self


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


class RevisionDetail(ContractModel):
    summary: RevisionSummary
    content: RequestContent


class AuditEvent(ContractModel):
    """Storage shape only. No v0.1 endpoint exposes it."""

    audit_id: UUID
    yard_id: UUID
    actor_type: Literal["system", "employee", "integration"]
    actor_id: UUID | None
    action: ShortText
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


# ---------------------------------------------------------------------------
# Model-adapter output (validated before any draft is created)
# ---------------------------------------------------------------------------


class ProposedEvidence(ContractModel):
    """The model quotes; the server locates the quote and computes offsets."""

    source: SourceKind
    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    occurrence: Annotated[int, Field(ge=0)]
    role: EvidenceRole


class ProposedMeasure(ContractModel):
    raw: ShortText
    magnitude: PositiveDecimal
    unit: LengthUnit | None = Field(description="Only if the source states it.")


class ProposedField(ContractModel, Generic[T]):
    state: Literal["extracted", "missing", "ambiguous"]
    value: T | None
    candidates: list[T]
    ambiguity_reason: AmbiguityReason | None
    evidence: list[ProposedEvidence]

    @model_validator(mode="after")
    def _state_rules(self) -> ProposedField[T]:
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
        if self.state == "extracted" and not any(
            e.role == EvidenceRole.SUPPORTS for e in self.evidence
        ):
            raise ValueError("extracted fields need supporting evidence")
        return self


class ProposedText(ProposedField[str]):
    """Text is copied, not normalized: each value must appear in quoted source."""

    @model_validator(mode="after")
    def _values_are_verbatim(self) -> ProposedText:
        if self.state == "extracted":
            values = [self.value]
            quotes = [e.quote for e in self.evidence if e.role == EvidenceRole.SUPPORTS]
        else:
            values = self.candidates
            quotes = [e.quote for e in self.evidence]
        for value in values:
            if not value or not any(value in quote for quote in quotes):
                raise ValueError("text values must appear verbatim in an evidence quote")
        return self


class ProposedQuantity(ProposedField[PositiveDecimal]):
    pass


class ProposedUnit(ProposedField[UnitCode]):
    pass


class ProposedMeasureField(ProposedField[ProposedMeasure]):
    pass


class ProposedFulfillment(ProposedField[Literal["delivery", "pickup"]]):
    pass


class ProposedLine(ContractModel):
    source_evidence: Annotated[list[ProposedEvidence], Field(min_length=1)]
    product: ProposedText
    quantity: ProposedQuantity
    unit: ProposedUnit
    dimension_text: ProposedText
    thickness: ProposedMeasureField
    width: ProposedMeasureField
    length: ProposedMeasureField
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
    """No SKU, price, inventory or approval keys exist here, and extras are rejected."""

    schema_version: Literal["0.1"]
    classification: Classification
    lines: Annotated[list[ProposedLine], Field(max_length=500)]
    job_details: ProposedJobDetails


# ---------------------------------------------------------------------------
# Lists, identity and errors
# ---------------------------------------------------------------------------


class InboxRequestSummary(ContractModel):
    request_id: UUID
    review_state: ReviewState
    version: int
    active_line_count: int
    blocker_count: int


class InboxItem(ContractModel):
    communication_id: UUID
    channel: Literal["email"]
    received_at: UtcDatetime
    sender: EmailParty
    subject: str | None
    processing_state: ProcessingState
    classification: Classification | None
    attachment_count: int
    warning_codes: list[WarningCode]
    request: InboxRequestSummary | None


class InboxPage(ContractModel):
    items: list[InboxItem]
    next_cursor: str | None


class RevisionPage(ContractModel):
    items: list[RevisionSummary]
    next_cursor: str | None


class SkuPage(ContractModel):
    catalog_version: str
    items: list[SkuSnapshot]
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
    location: str
    message: str


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str = Field(description="Never echoes source content or secrets.")
    details: list[ErrorDetail]
    blockers: list[ApprovalBlocker]
    current_version: int | None
    trace_id: UUID


class ErrorResponse(ContractModel):
    error: ErrorBody
