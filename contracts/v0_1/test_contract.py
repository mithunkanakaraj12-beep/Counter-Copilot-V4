"""Checks on the contract artifacts themselves. These are not application tests."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import generate_openapi  # noqa: E402
import models as m  # noqa: E402

SPEC = yaml.safe_load((HERE / "openapi.yaml").read_text(encoding="utf-8"))
SCHEMAS = SPEC["components"]["schemas"]
OPERATIONS = [
    (path, method, op) for path, item in SPEC["paths"].items() for method, op in item.items()
]
UUID_A = "00000000-0000-4000-8000-000000000001"


def example(name: str) -> dict:
    return json.loads((HERE / "examples" / name).read_text(encoding="utf-8"))


def schema_valid(component: str, data) -> bool:
    schema = {"$ref": f"#/components/schemas/{component}", "components": SPEC["components"]}
    return Draft202012Validator(schema).is_valid(data)


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


def test_employee_mutations_require_csrf_and_idempotency_headers():
    for path, method, op in OPERATIONS:
        if method != "get" and path != "/api/v1/inbound/events":
            headers = {p["name"] for p in op["parameters"] if p["in"] == "header" and p["required"]}
            assert headers == {"Idempotency-Key", "X-CSRF-Token"}


def test_no_external_action_endpoints():
    for path, _, _ in OPERATIONS:
        assert not re.search(r"send|follow-up|order|export|reserve|quotes", path)
    assert not any("send" in p.value for p in m.Permission)


# --- Examples ---------------------------------------------------------------

EXAMPLES = {
    "inbound-email-event.json": m.InboundEmailEvent,
    "request-detail.draft.json": m.RequestDetail,
    "request-edit.json": m.RequestEdit,
    "decision.approve.json": m.DecisionRequest,
}


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_api_example_passes_both_validators(name):
    data = example(name)
    EXAMPLES[name].model_validate(data)
    assert schema_valid(EXAMPLES[name].__name__, data)


def test_extraction_proposal_example():
    m.ExtractionProposal.model_validate(example("extraction-proposal.json"))


def test_example_evidence_matches_source_text():
    body = example("inbound-email-event.json")["body_text"]
    spans = [n for n in walk(example("request-detail.draft.json")) if "quote" in n]
    assert spans
    for span in spans:
        assert body[span["start"] : span["end"]] == span["quote"]
    proposed = [n for n in walk(example("extraction-proposal.json")) if "quote" in n]
    for span in proposed:
        assert body.count(span["quote"]) > span["occurrence"]


def test_example_raw_email_contains_the_body():
    raw = (HERE / "examples" / "synthetic-email.eml").read_bytes().decode()
    assert example("inbound-email-event.json")["body_text"] in raw.replace("\r\n", "\n")


# --- Rules that must reject bad data ----------------------------------------


def quantity_field(state: str) -> dict:
    lines = example("request-detail.draft.json")["content"]["lines"]
    source = {
        "extracted": lines[0]["quantity"],
        "ambiguous": lines[1]["quantity"],
        "missing": lines[0]["treatment"],
    }
    if state == "employee_entered":
        return {
            **source["missing"],
            "state": state,
            "value": "24",
            "entered_by": UUID_A,
            "entered_at": "2026-11-25T16:00:00Z",
        }
    return copy.deepcopy(source[state])


@pytest.mark.parametrize("state", ["extracted", "ambiguous", "missing", "employee_entered"])
def test_valid_field_states(state):
    data = quantity_field(state)
    m.QuantityField.model_validate(data)
    assert schema_valid("QuantityField", data)


@pytest.mark.parametrize(
    "state,change",
    [
        ("extracted", {"value": None}),
        ("extracted", {"evidence": []}),
        ("extracted", {"candidates": ["1"]}),
        ("missing", {"value": "1"}),
        ("missing", {"ambiguity_reason": "range_given"}),
        ("ambiguous", {"value": "20"}),
        ("ambiguous", {"ambiguity_reason": None}),
        ("ambiguous", {"evidence": []}),
        ("employee_entered", {"entered_by": None}),
        ("employee_entered", {"value": None}),
        ("extracted", {"entered_by": UUID_A}),
    ],
)
def test_invalid_field_states_rejected(state, change):
    data = {**quantity_field(state), **change}
    with pytest.raises(ValidationError):
        m.QuantityField.model_validate(data)
    assert not schema_valid("QuantityField", data)


@pytest.mark.parametrize("bad", [40, 40.0, "0", "0.0", "-1", "1e3", "1,000", "", "01", "NaN"])
def test_bad_quantities_rejected(bad):
    data = {"op": "set_quantity", "line_id": UUID_A, "value": bad}
    with pytest.raises(ValidationError):
        m.SetQuantity.model_validate(data)
    assert not schema_valid("SetQuantity", data)


def test_edit_requires_explicit_value():
    with pytest.raises(ValidationError):
        m.SetQuantity.model_validate({"op": "set_quantity", "line_id": UUID_A})


@pytest.mark.parametrize("key", ["yard_id", "idempotency_key", "source_reference"])
def test_intake_rejects_server_owned_keys(key):
    data = {**example("inbound-email-event.json"), key: "x"}
    with pytest.raises(ValidationError):
        m.InboundEmailEvent.model_validate(data)
    assert not schema_valid("InboundEmailEvent", data)


def test_intake_rejects_non_utc_time():
    data = {**example("inbound-email-event.json"), "received_at": "2026-11-25T09:00:00-06:00"}
    with pytest.raises(ValidationError):
        m.InboundEmailEvent.model_validate(data)


def test_wording_is_not_trimmed():
    data = {**example("inbound-email-event.json"), "body_text": "  40 2x4  \n"}
    assert m.InboundEmailEvent.model_validate(data).body_text == "  40 2x4  \n"


@pytest.mark.parametrize("action", ["send", "send_quote", "convert_to_order"])
def test_decision_cannot_trigger_external_actions(action):
    data = {"action": action, "expected_version": 1}
    with pytest.raises(ValidationError):
        m.DecisionRequest.model_validate(data)
    assert not schema_valid("DecisionRequest", data)


@pytest.mark.parametrize("key", ["selected_sku_id", "candidate_skus", "price", "review_state"])
def test_model_output_cannot_add_business_decisions(key):
    data = example("extraction-proposal.json")
    data["lines"][0][key] = "x"
    with pytest.raises(ValidationError):
        m.ExtractionProposal.model_validate(data)


def test_model_cannot_claim_employee_entry():
    data = example("extraction-proposal.json")
    data["lines"][0]["quantity"]["state"] = "employee_entered"
    with pytest.raises(ValidationError):
        m.ExtractionProposal.model_validate(data)


@pytest.mark.parametrize("field,invented", [("treatment", "untreated"), ("species", "SPF")])
def test_model_text_must_be_quoted_from_source(field, invented):
    data = example("extraction-proposal.json")
    data["lines"][0][field] = {
        "state": "extracted",
        "value": invented,
        "candidates": [],
        "ambiguity_reason": None,
        "evidence": data["lines"][0]["source_evidence"],
    }
    with pytest.raises(ValidationError):
        m.ExtractionProposal.model_validate(data)


def test_evidence_span_length_must_match_quote():
    data = quantity_field("extracted")["evidence"][0]
    with pytest.raises(ValidationError):
        m.Evidence.model_validate({**data, "end": data["end"] + 1})


def test_employee_line_cannot_hold_model_states():
    data = example("request-detail.draft.json")["content"]["lines"][0]
    data.update(origin="employee", raw_wording=None, source_evidence=[])
    with pytest.raises(ValidationError):
        m.MaterialLine.model_validate(data)


def test_raw_wording_must_match_source_evidence():
    data = example("request-detail.draft.json")["content"]["lines"][0]
    with pytest.raises(ValidationError):
        m.MaterialLine.model_validate({**data, "raw_wording": "rewritten"})


def test_approved_state_requires_approval_record():
    data = {**example("request-detail.draft.json"), "review_state": "internally_approved"}
    with pytest.raises(ValidationError):
        m.RequestDetail.model_validate(data)
