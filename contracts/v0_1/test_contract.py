"""Checks on the contract artifacts themselves. These are not application tests."""

from __future__ import annotations

import copy
import json
import re
import uuid

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

import build_examples
import generate_openapi
import models as m
from conftest import HERE

SPEC = yaml.safe_load((HERE / "openapi.yaml").read_text(encoding="utf-8"))
SCHEMAS = SPEC["components"]["schemas"]
EXTRACTION = json.loads((HERE / "extraction-proposal.schema.json").read_text(encoding="utf-8"))
OPERATIONS = [
    (path, method, op) for path, item in SPEC["paths"].items() for method, op in item.items()
]
UUID_A = "00000000-0000-4000-8000-000000000001"
PERSON = {"user_id": UUID_A, "display_name": "Synthetic", "active": True}


def example(name: str) -> dict:
    return json.loads((HERE / "examples" / name).read_text(encoding="utf-8"))


def component_schema(component: str) -> dict:
    return {"$ref": f"#/components/schemas/{component}", "components": SPEC["components"]}


def schema_valid(component: str, data) -> bool:
    return Draft202012Validator(
        component_schema(component), format_checker=FormatChecker()
    ).is_valid(data)


def model_valid(component: str, data) -> bool:
    try:
        model = getattr(m, component)
        if component in ("TextField", "QuantityField", "UnitField", "DimensionsField"):
            from pydantic import TypeAdapter

            TypeAdapter(model).validate_json(json.dumps(data))
        else:
            model.model_validate_json(json.dumps(data))
    except ValidationError:
        return False
    return True


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


# --- OpenAPI structure ------------------------------------------------------


def test_openapi_matches_models():
    assert (HERE / "openapi.yaml").read_text(encoding="utf-8") == generate_openapi.render()


def test_extraction_schema_matches_models():
    committed = (HERE / "extraction-proposal.schema.json").read_text(encoding="utf-8")
    assert committed == generate_openapi.render_extraction_schema()
    Draft202012Validator.check_schema(EXTRACTION)


def test_every_reference_resolves():
    for node in walk(SPEC):
        refs = [node["$ref"]] if "$ref" in node else []
        refs += list(node.get("discriminator", {}).get("mapping", {}).values())
        for ref in refs:
            assert ref.startswith("#/components/schemas/")
            assert ref.rsplit("/", 1)[1] in SCHEMAS


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_component_is_valid_json_schema(name):
    Draft202012Validator.check_schema(SCHEMAS[name])


def test_component_names_are_stable_for_generated_clients():
    assert all(re.fullmatch(r"[A-Z][A-Za-z0-9]*", name) for name in SCHEMAS)


def test_operation_ids_unique_and_path_parameters_declared():
    ids = [op["operationId"] for _, _, op in OPERATIONS]
    assert len(ids) == len(set(ids))
    for path, _, op in OPERATIONS:
        declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
        assert declared == set(re.findall(r"{(\w+)}", path))


def test_authentication_is_required_everywhere_but_health():
    for path, _, op in OPERATIONS:
        if path == "/api/v1/health":
            assert op["security"] == []
        elif path == "/api/v1/inbound/events":
            assert op["security"] == [{"integrationToken": []}]
        else:
            assert op["security"] == [{"employeeSession": []}]


def test_tenant_resources_are_yard_scoped():
    unscoped = {"/api/v1/health", "/api/v1/inbound/events", "/api/v1/me"}
    for path, _, _ in OPERATIONS:
        assert path in unscoped or path.startswith("/api/v1/yards/{yard_id}/")


def test_every_yard_operation_declares_a_permission():
    for path, _, op in OPERATIONS:
        if path.startswith("/api/v1/yards/"):
            assert op.get("x-required-permission") or op.get("x-conditional-permissions")
            assert {"401", "403", "404"} <= set(op["responses"])


def test_employee_mutations_require_csrf_and_idempotency_headers():
    for path, method, op in OPERATIONS:
        if method != "get" and path != "/api/v1/inbound/events":
            headers = {p["name"] for p in op["parameters"] if p["in"] == "header" and p["required"]}
            assert headers == {"Idempotency-Key", "X-CSRF-Token"}


def test_no_external_action_endpoints():
    for path, _, _ in OPERATIONS:
        assert not re.search(r"send|follow-up|order|export|reserve|quotes", path)
    assert not any("send" in p.value for p in m.Permission)


def test_no_attachment_download_route_and_the_limitation_is_stated():
    assert not any("attachment" in path for path, _, _ in OPERATIONS)
    download = SPEC["paths"]["/api/v1/yards/{yard_id}/communications/{communication_id}/original"]
    for text in (SPEC["info"]["description"], download["get"]["description"]):
        assert "no individual attachment download" in text


def test_download_headers_are_declared():
    path = "/api/v1/yards/{yard_id}/communications/{communication_id}/original"
    headers = SPEC["paths"][path]["get"]["responses"]["200"]["headers"]
    assert set(headers) == {"Content-Disposition", "X-Content-Type-Options", "Cache-Control"}
    assert headers["Cache-Control"]["schema"]["const"] == "no-store"


def test_approved_limits_are_published_exactly():
    assert SPEC["info"]["x-limits"] == {
        "raw_email_bytes": 25_000_000,
        "body_chars": 200_000,
        "lines": 500,
        "attachments": 100,
        "mime_parts": 200,
        "mime_depth": 20,
        "header_bytes": 256_000,
        "parse_seconds": 30,
        "json_bytes": 1_000_000,
        "evidence_items": 20,
        "candidates": 10,
        "operations": 200,
        "idempotency_hours": 24,
        "preview_chars": 200,
    }
    for path, method, op in OPERATIONS:
        if "requestBody" in op:
            assert op["x-max-body-bytes"] in (1_000_000, 26_000_000)
            assert "413" in op["responses"] and "415" in op["responses"]


def test_error_codes_are_documented_per_status():
    documented = set()
    for _, _, op in OPERATIONS:
        for status, response in op["responses"].items():
            if int(status) >= 400:
                assert response["x-error-codes"]
                documented.update(response["x-error-codes"])
    assert documented == {code.value for code in m.ErrorCode}


def test_server_owned_facts_cannot_be_posted_back():
    """No request body accepts an approval, review state, version or computed flag."""
    for component in ("RequestEdit", "ManualRequestCreate", "DecisionRequest", "HandlingRequest"):
        seen, queue = set(), [component]
        while queue:
            name = queue.pop()
            if name in seen:
                continue
            seen.add(name)
            for node in walk(SCHEMAS[name]):
                if "$ref" in node:
                    queue.append(node["$ref"].rsplit("/", 1)[1])
                if "mapping" in node:
                    queue.extend(r.rsplit("/", 1)[1] for r in node["mapping"].values())
                keys = set(node.get("properties", {}))
                assert not keys & {"review_state", "approval", "yard_id", "warnings", "proposal"}


# --- Examples ---------------------------------------------------------------


def test_examples_are_generated_and_current():
    for name, text in build_examples.render().items():
        assert (HERE / "examples" / name).read_text(encoding="utf-8") == text, name


@pytest.mark.parametrize(
    "name", sorted(set(build_examples.MODELS) - {"grounded-proposal.json"})
)
def test_api_example_passes_both_validators(name):
    data = example(name)
    component = build_examples.MODELS[name].__name__
    assert model_valid(component, data)
    if component == "ExtractionProposal":
        assert Draft202012Validator(EXTRACTION).is_valid(data)
    else:
        assert schema_valid(component, data)


def test_example_evidence_matches_source_text():
    body = example("communication-detail.json")["record"]["body_text"]
    for name in ("request-detail.draft.json", "request-detail.approved.json"):
        spans = [n for n in walk(example(name)) if "quote" in n]
        assert spans
        for span in spans:
            assert body[span["start"] : span["end"]] == span["quote"]
    for span in (n for n in walk(example("extraction-proposal.json")) if "quote" in n):
        assert body.count(span["quote"]) > span["occurrence"]


def test_example_digests_match_the_raw_email():
    import hashlib

    raw = (HERE / "examples" / "synthetic-email.eml").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert example("inbound-email-event.json")["original_sha256"] == digest
    assert example("communication-detail.json")["record"]["original"]["sha256"] == digest


# --- Field states -----------------------------------------------------------


def quantity_field(state: str) -> dict:
    draft = example("request-detail.draft.json")["content"]["lines"]
    approved = example("request-detail.approved.json")["content"]["lines"]
    if state == "extracted":
        return copy.deepcopy(draft[0]["quantity"])
    if state == "ambiguous":
        return copy.deepcopy(draft[1]["quantity"])
    if state == "employee_entered":
        return copy.deepcopy(approved[1]["quantity"])
    base = {
        "state": state,
        "value": None,
        "candidates": [],
        "ambiguity_reason": None,
        "evidence": [],
        "proposal": None,
    }
    if state == "employee_cleared":
        base.update(cleared_by=PERSON, cleared_at="2026-11-25T16:00:00Z")
    return base


STATES = ["extracted", "ambiguous", "missing", "employee_entered", "employee_cleared"]


@pytest.mark.parametrize("state", STATES)
def test_valid_field_states(state):
    data = quantity_field(state)
    assert model_valid("QuantityField", data)
    assert schema_valid("QuantityField", data)


TYPED = {"method": "typed", "candidate_index": None}


@pytest.mark.parametrize(
    "state,change",
    [
        ("extracted", {"value": None}),
        ("extracted", {"evidence": []}),
        ("extracted", {"candidates": ["1"]}),
        ("extracted", {"entered_by": PERSON}),
        ("extracted", {"ambiguity_reason": "range_given"}),
        ("missing", {"value": "1"}),
        ("missing", {"ambiguity_reason": "range_given"}),
        ("missing", {"cleared_by": PERSON}),
        ("ambiguous", {"value": "20"}),
        ("ambiguous", {"ambiguity_reason": None}),
        ("ambiguous", {"evidence": []}),
        ("ambiguous", {"candidates": [str(i) for i in range(1, 12)]}),
        ("employee_entered", {"entered_by": None}),
        ("employee_entered", {"value": None}),
        ("employee_entered", {"resolution": TYPED}),
        ("employee_entered", {"evidence": []}),
        ("employee_cleared", {"value": "1"}),
        ("employee_cleared", {"cleared_by": None}),
        ("missing", {"state": "confirmed"}),
    ],
)
def test_invalid_field_states_rejected(state, change):
    data = {**quantity_field(state), **change}
    assert not model_valid("QuantityField", data)
    assert not schema_valid("QuantityField", data)


@pytest.mark.parametrize("bad", [40, 40.0, "0", "0.0", "-1", "1e3", "1,000", "", "01", "NaN"])
def test_bad_quantities_rejected(bad):
    data = {"op": "set_quantity", "line_id": UUID_A, "value": bad}
    assert not model_valid("SetQuantity", data)
    assert not schema_valid("SetQuantity", data)


# --- Parity: both validators reject the same bad payloads --------------------


def edit(*operations, version=1):
    return {"expected_version": version, "operations": list(operations)}


GOOD_OP = {"op": "clear_sku_selection", "line_id": UUID_A}


def intake(**changes) -> dict:
    return {**example("inbound-email-event.json"), **changes}


def approve(**changes) -> dict:
    return {**example("decision.approve.json"), **changes}


def mark(**changes) -> dict:
    return {**example("handling.mark.json"), **changes}


def warning(**changes) -> dict:
    return {**example("request-detail.draft.json")["warnings"][0], **changes}


def extraction(mutate) -> dict:
    data = example("extraction-proposal.json")
    mutate(data)
    return data


PARITY = [
    ("RequestEdit", edit()),
    ("RequestEdit", {"operations": [GOOD_OP]}),
    ("RequestEdit", edit(*[GOOD_OP] * 201)),
    ("RequestEdit", edit(GOOD_OP, version="1")),
    ("RequestEdit", edit(GOOD_OP, version=0)),
    ("RequestEdit", edit({"op": "set_quantity", "line_id": UUID_A})),
    ("RequestEdit", edit({"op": "set_quantity", "line_id": UUID_A, "value": None})),
    ("RequestEdit", edit({"op": "set_unit", "line_id": UUID_A, "value": "pcs"})),
    ("RequestEdit", edit({"op": "set_measure", "line_id": UUID_A})),
    ("RequestEdit", edit({"op": "remove_line", "line_id": UUID_A})),
    ("RequestEdit", edit({"op": "select_sku", "line_id": UUID_A, "sku_id": "x"})),
    ("RequestEdit", edit({**GOOD_OP, "price": "1"})),
    (
        "RequestEdit",
        edit({"op": "clear_field", "target": {"scope": "line", "field": "quantity"}}),
    ),
    (
        "RequestEdit",
        edit(
            {
                "op": "clear_field",
                "target": {"scope": "job_detail", "field": "quantity"},
            }
        ),
    ),
    ("InboundEmailEvent", intake(yard_id=UUID_A)),
    ("InboundEmailEvent", intake(idempotency_key="x")),
    ("InboundEmailEvent", intake(source_reference="x")),
    ("InboundEmailEvent", intake(sender={"name": None, "address": "a@example.test"})),
    ("InboundEmailEvent", intake(recipients=[])),
    ("InboundEmailEvent", intake(subject="x")),
    ("InboundEmailEvent", intake(body_text="40")),
    ("InboundEmailEvent", intake(thread={})),
    ("InboundEmailEvent", intake(attachments=[])),
    ("InboundEmailEvent", intake(original_sha256="ABC")),
    ("InboundEmailEvent", intake(envelope_recipients=[])),
    ("InboundEmailEvent", intake(channel="sms")),
    ("InboundEmailEvent", intake(received_at=1_700_000_000)),
    ("DecisionRequest", {"action": "send", "expected_version": 1}),
    ("DecisionRequest", {"action": "send_quote", "expected_version": 1}),
    ("DecisionRequest", {"action": "convert_to_order", "expected_version": 1}),
    ("DecisionRequest", {"action": "decline", "expected_version": 1}),
    ("DecisionRequest", approve(expected_version="2")),
    ("DecisionRequest", approve(approved_by=UUID_A)),
    ("HandlingRequest", mark(note=None)),
    ("HandlingRequest", {k: v for k, v in mark().items() if k != "note"}),
    ("HandlingRequest", mark(reason="processing_failed")),
    ("HandlingRequest", {k: v for k, v in mark().items() if k != "reason"}),
    ("HandlingRequest", mark(force=True)),
    ("HandlingRequest", {"action": "reopen", "expected_handling_version": 1}),
    ("HandlingRequest", {"action": "delete", "expected_handling_version": 1, "reason": "x"}),
    ("ReviewWarning", warning(requires_acknowledgement=False)),
    ("ReviewWarning", warning(heuristic=False)),
    ("ReviewWarning", warning(target={"scope": "request", "line_id": UUID_A, "field": None})),
    (
        "ReviewWarning",
        warning(
            code="possible_follow_up_same_sender",
            requires_acknowledgement=False,
            heuristic=False,
            related_communication_ids=[UUID_A],
        ),
    ),
]


@pytest.mark.parametrize("component,data", PARITY, ids=[f"{c}-{i}" for i, (c, _) in enumerate(PARITY)])
def test_both_validators_reject(component, data):
    assert not model_valid(component, data), "pydantic accepted"
    assert not schema_valid(component, data), "json schema accepted"


def _set(path, value):
    def mutate(data):
        node = data
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutate


EXTRACTION_PARITY = [
    _set(["lines", 0, "selected_sku_id"], UUID_A),
    _set(["lines", 0, "quantity", "state"], "employee_entered"),
    _set(["lines", 0, "quantity", "value"], None),
    _set(["lines", 0, "quantity", "evidence"], []),
    _set(["lines", 0, "source_evidence"], []),
    _set(["lines", 1, "quantity", "value"], "20"),
    _set(["lines", 1, "quantity", "ambiguity_reason"], "unsupported_by_source"),
    _set(["lines", 0, "dimensions", "value"], {"components": []}),
    _set(["classification"], "non_request"),
    _set(["review_state"], "internally_approved"),
]


@pytest.mark.parametrize("mutate", EXTRACTION_PARITY, ids=range(len(EXTRACTION_PARITY)))
def test_extraction_schema_and_model_reject(mutate):
    data = extraction(mutate)
    assert not model_valid("ExtractionProposal", data)
    assert not Draft202012Validator(EXTRACTION).is_valid(data)


def test_intake_rejects_non_utc_time():
    data = intake(received_at="2026-11-25T09:00:00-06:00")
    assert not model_valid("InboundEmailEvent", data)


def test_wording_is_not_trimmed():
    data = intake(external_message_id="  spaced  ")
    assert m.InboundEmailEvent.model_validate(data).external_message_id == "  spaced  "


def test_evidence_span_length_must_match_quote():
    data = quantity_field("extracted")["evidence"][0]
    assert not model_valid("Evidence", {**data, "end": data["end"] + 1})


# --- Rules that need more than a schema -------------------------------------


def line_data(name="request-detail.draft.json", index=0) -> dict:
    return copy.deepcopy(example(name)["content"]["lines"][index])


def test_employee_line_cannot_hold_model_states():
    data = line_data()
    data.update(origin="employee", raw_wording=None, source_evidence=[])
    assert not model_valid("MaterialLine", data)


def test_raw_wording_must_match_source_evidence():
    assert not model_valid("MaterialLine", {**line_data(), "raw_wording": "rewritten"})


def test_ai_value_cannot_be_changed_while_claiming_to_be_the_ai():
    data = line_data()
    data["quantity"]["value"] = "41"
    assert not model_valid("MaterialLine", data)


def test_ai_proposal_survives_an_employee_edit():
    entered = line_data("request-detail.approved.json", 1)["quantity"]
    assert entered["state"] == "employee_entered"
    assert entered["proposal"] == line_data(index=1)["quantity"]["proposal"]


def test_chosen_candidate_must_come_from_the_proposal():
    data = line_data("request-detail.approved.json", 1)
    data["quantity"]["value"] = "25"
    assert not model_valid("MaterialLine", data)
    data = line_data("request-detail.approved.json", 1)
    data["quantity"]["resolution"]["candidate_index"] = 5
    assert not model_valid("MaterialLine", data)


def test_removed_line_records_why():
    assert not model_valid("MaterialLine", {**line_data(), "status": "removed"})
    removal = {"reason": "duplicate", "removed_by": PERSON, "removed_at": "2026-11-25T16:00:00Z"}
    assert model_valid("MaterialLine", {**line_data(), "status": "removed", "removal": removal})


def approved(mutate) -> dict:
    data = example("request-detail.approved.json")
    mutate(data)
    return data


def _line(index, name, value):
    return _set(["content", "lines", index, name], value)


def cleared() -> dict:
    proposal = line_data()["quantity"]["proposal"]
    return {**quantity_field("employee_cleared"), "proposal": proposal}


def blocker(identifier="b1", field="sku") -> dict:
    return {
        "blocker_id": identifier,
        "code": "sku_inactive",
        "message": "Inactive.",
        "target": {"scope": "line", "line_id": line_data()["line_id"], "field": field},
        "warning_id": None,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        _set(["approval"], None),
        _set(["content", "lines"], []),
        _line(0, "quantity", cleared()),
        _line(1, "quantity", line_data(index=1)["quantity"]),
        _line(0, "match", line_data()["match"]),
        _line(1, "position", 1),
        _set(["approval", "approved_version"], 3),
        _set(["approval", "request_id"], UUID_A),
        _set(["origin_communication_id"], UUID_A),
        _set(["approval_blockers"], [blocker("b1"), blocker("b2")]),
    ],
    ids=[
        "no-record", "no-lines", "cleared-quantity", "ambiguous-quantity", "no-sku",
        "positions", "version", "other-request", "foreign-evidence", "duplicate-blocker",
    ],
)
def test_invalid_approved_requests_rejected(mutate):
    assert not model_valid("RequestDetail", approved(mutate))


def test_later_inactive_sku_stays_visible_on_an_approved_request():
    assert model_valid("RequestDetail", approved(_set(["approval_blockers"], [blocker()])))


def test_approved_state_requires_approval_record():
    data = {**example("request-detail.draft.json"), "review_state": "internally_approved"}
    assert not model_valid("RequestDetail", data)


def test_only_heuristic_warnings_can_be_false_positives():
    record = example("request-detail.approved.json")["approval"]["acknowledged_warnings"][1]
    assert record["code"] not in [c.value for c in m.HEURISTIC_WARNINGS]
    assert not model_valid("AcknowledgedWarning", {**record, "marked_false_positive": True})


OWNER_ACKNOWLEDGED = {
    "selected_sku_attribute_mismatch",
    "selected_sku_attribute_unverified",
    "selected_sku_changed",
    "newer_related_message",
    "possible_follow_up",
    "uncertain_classification",
    "possible_correction_language",
    "uncited_quantity_text",
    "evidence_in_quoted_text",
    "overlapping_line_evidence",
    "model_line_removed",
    "multiple_jobs_detected",
    "unprocessed_attachment",
}
KEPT_FROM_EARLIER_PROPOSAL = {"possible_duplicate", "conflicting_redelivery"}
INFORMATIONAL = {"possible_follow_up_same_sender", "html_derived_text"}


def test_acknowledgment_table():
    every = {c.value for c in m.WarningCode}
    assert every == OWNER_ACKNOWLEDGED | KEPT_FROM_EARLIER_PROPOSAL | INFORMATIONAL
    assert {c.value for c in m.INFORMATIONAL_WARNINGS} == INFORMATIONAL


def detail(**status) -> dict:
    data = example("communication-detail.json")
    data["status"].update(status)
    return data


def non_request(handled: bool, **status) -> dict:
    handling = {
        "status": "handled" if handled else "open",
        "version": 1 if handled else 0,
        "mark_handled_allowed": not handled,
        "reason": "not_a_request" if handled else None,
        "note": None,
        "changed_by": PERSON if handled else None,
        "changed_at": "2026-11-25T16:00:00Z" if handled else None,
    }
    return detail(
        classification="non_request", origin_request_id=None, handling=handling, **status
    )


def test_only_completed_non_requests_without_a_request_can_be_handled():
    assert model_valid("CommunicationDetail", non_request(True))
    assert model_valid("CommunicationDetail", non_request(False))
    for changes in (
        {"classification": "follow_up"},
        {"classification": "material_request"},
        {"origin_request_id": UUID_A},
        {
            "processing_state": "failed_terminal",
            "classification": None,
            "failure_code": "parse_failed",
            "employee_message": m.FAILURE_MESSAGES["parse_failed"],
        },
        {"processing_state": "processing", "classification": None},
    ):
        data = non_request(True)
        data["status"].update(changes)
        assert not model_valid("CommunicationDetail", data), changes


def test_failure_details_are_consistent():
    failed = dict(
        processing_state="failed_retryable",
        classification=None,
        failure_code="model_timeout",
        employee_message=m.FAILURE_MESSAGES["model_timeout"],
        next_retry_at="2026-11-25T16:00:00Z",
        origin_request_id=None,
    )
    assert model_valid("CommunicationDetail", detail(**failed))
    for change in (
        {"failure_code": None},
        {"employee_message": "echo of the email body"},
        {"failure_code": "parse_failed", "employee_message": m.FAILURE_MESSAGES["parse_failed"]},
    ):
        assert not model_valid("CommunicationDetail", detail(**{**failed, **change}))


def test_failed_parse_records_carry_no_parsed_fields():
    data = example("communication-detail.json")
    data["record"]["parse_status"] = "failed"
    assert not model_valid("CommunicationDetail", data)
    assert not schema_valid("CommunicationDetail", data)


def test_dimensions_must_follow_their_text():
    good = m.dimensions_from_text("7/16").model_dump(mode="json")
    assert model_valid("Dimensions", good)
    good["components"][0]["magnitude"] = "0.44"
    assert not model_valid("Dimensions", good)


def test_person_is_set_exactly_for_employees():
    assert not model_valid("Actor", {"type": "system", "person": PERSON})
    assert not model_valid("Actor", {"type": "employee", "person": None})


def test_run_record_keeps_raw_output_apart():
    assert "raw_output" in m.ExtractionRunRecord.model_fields
    assert "ExtractionRunRecord" not in SCHEMAS


def test_synthetic_catalog_loads():
    path = HERE.parents[1] / "tests" / "fixtures" / "synthetic_yard.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["fixture_type"] == "synthetic_only" and len(data["yards"]) == 2
    ids = []
    for yard in data["yards"]:
        assert yard["pricing_enabled"] is False and yard["synonym_rules"] == []
        for item in yard["skus"]:
            ids.append(m.SkuSnapshot.model_validate(item).sku_id)
    assert len(ids) == len(set(ids))
    assert uuid.UUID(data["yards"][0]["yard_id"])


def operation(operation_id: str) -> dict:
    return next(op for _, _, op in OPERATIONS if op["operationId"] == operation_id)


def test_decision_and_download_permissions_are_separate():
    decisions = operation("decideRequest")["x-conditional-permissions"]
    assert set(decisions.values()) == {
        "request:approve_internal",
        "request:decline",
        "request:reopen",
    }
    assert operation("downloadOriginal")["x-required-permission"] == "communication:read_original"
    assert operation("getCommunication")["x-required-permission"] == "communication:read"


def test_nothing_can_re_extract_or_overwrite_a_request():
    assert not any(re.search(r"reprocess|extract|retry", path) for path, _, _ in OPERATIONS)


def test_attachments_share_one_grouped_warning():
    data = example("request-detail.draft.json")
    grouped = {
        **data["warnings"][0],
        "warning_id": "w-attach",
        "code": "unprocessed_attachment",
        "target": {"scope": "request", "line_id": None, "field": None},
        "requires_acknowledgement": True,
        "heuristic": False,
    }
    data["warnings"] = [grouped]
    assert model_valid("RequestDetail", data) and schema_valid("RequestDetail", data)
    data["warnings"] = [grouped, {**grouped, "warning_id": "w-attach-2"}]
    assert not model_valid("RequestDetail", data) and not schema_valid("RequestDetail", data)
    on_line = {"scope": "line", "line_id": line_data()["line_id"], "field": None}
    assert not model_valid("ReviewWarning", {**grouped, "target": on_line})
    assert not schema_valid("ReviewWarning", {**grouped, "target": on_line})
