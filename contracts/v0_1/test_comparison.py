"""Reference comparison: whole ordered dimensions, no conversion, no selection."""

from __future__ import annotations

import json
import uuid

import pytest

import models as m
from conftest import HERE
from reference import comparison

D = m.dimensions_from_text


def sku(**changes) -> m.SkuSnapshot:
    data = {
        "sku_id": uuid.UUID(int=9),
        "code": "SYN",
        "description": "Synthetic",
        "product": None,
        "dimension_designation": D("2x4x8"),
        "species": "SPF",
        "grade": None,
        "treatment": "untreated",
        "sell_unit": "piece",
        "active": True,
        **changes,
    }
    return m.SkuSnapshot(**data)


@pytest.mark.parametrize(
    "request_text,sku_text,outcome",
    [
        ("2x4x8", "2x4x8", "unit_unconfirmed_equal"),
        ("8 ft", "8 ft", "exact_match"),
        ("8'", "8 feet", "exact_match"),
        ("8 ft", "8", "unit_unconfirmed_equal"),
        ("0.5 inch", "1/2 inch", "exact_match"),
        ("2x4x10", "2x4x8", "mismatch"),
        ("4x2x8", "2x4x8", "mismatch"),  # written order matters
        ("96 inch", "8 ft", "different_unit_not_compared"),  # never converted
        ("2x4", "2x4x8", "different_component_count"),
        ("2x4x8", None, "not_defined_on_sku"),
        (None, "2x4x8", "not_stated_in_request"),
        (None, None, None),
    ],
)
def test_dimension_outcomes(request_text, sku_text, outcome):
    result = comparison.compare_dimensions(
        D(request_text) if request_text else None, D(sku_text) if sku_text else None
    )
    assert result == outcome


def test_text_matching_ignores_case_only():
    assert comparison.compare_text("species", "spf", "SPF")[0] == "exact_match"
    assert comparison.compare_text("treatment", "pt", "pressure treated")[0] == "mismatch"
    assert comparison.compare_text("grade", "#2", "No. 2")[0] == "mismatch"
    assert comparison.compare_text("treatment", "treated", "untreated")[0] == "mismatch"


def test_synonyms_need_an_approved_rule():
    rule = comparison.SynonymRule(uuid.UUID(int=7), "treatment", "pt", "pressure treated")
    outcome, rule_id = comparison.compare_text("treatment", "PT", "pressure treated", (rule,))
    assert (outcome, rule_id) == ("synonym_match", rule.rule_id)
    assert comparison.compare_text("species", "pt", "pressure treated", (rule,))[0] == "mismatch"


def test_unit_check_never_converts():
    assert comparison.unit_check(None, m.UnitCode.PIECE).status == "request_unit_unresolved"
    assert comparison.unit_check(m.UnitCode.PIECE, m.UnitCode.PIECE).status == "same_unit"
    assert (
        comparison.unit_check(m.UnitCode.LINEAR_FOOT, m.UnitCode.PIECE).status
        == "different_unit"
    )
    assert set(m.UnitCheck.model_fields) == {"status"}


def test_acknowledgment_groups():
    evidence = comparison.attribute_evidence(
        {"dimensions": D("2x4x10"), "species": "SPF", "grade": "#2"}, sku()
    )
    assert {e.attribute: e.outcome.value for e in evidence} == {
        "dimensions": "mismatch",
        "species": "exact_match",
        "grade": "not_defined_on_sku",
        "treatment": "not_stated_in_request",
    }
    assert comparison.acknowledgment_attributes(evidence) == {
        "selected_sku_attribute_mismatch": ["dimensions"],
        "selected_sku_attribute_unverified": ["grade", "treatment"],
    }


def test_equal_dimensions_with_unstated_units_need_no_acknowledgment():
    evidence = comparison.attribute_evidence(
        {"dimensions": D("2x4x8"), "species": "SPF", "treatment": "untreated"}, sku()
    )
    assert comparison.acknowledgment_attributes(evidence) == {}


def test_comparison_offers_no_selection_or_ranking():
    public = {n for n in dir(comparison) if not n.startswith("_")}
    assert not any("select" in n.lower() and n != "acknowledgment_attributes" for n in public)
    assert not any("rank" in n.lower() for n in public)


def selected_line() -> m.MaterialLine:
    data = json.loads((HERE / "examples" / "request-detail.approved.json").read_text("utf-8"))
    return m.MaterialLine.model_validate_json(json.dumps(data["content"]["lines"][0]))


def test_approval_check_reads_the_catalog_as_it_is_at_approval():
    line = selected_line()
    selected = line.match.selection.sku
    unchanged = comparison.approval_line_check(line, selected)
    assert unchanged.sku == selected and not unchanged.sku_changed_since_selection
    changed = selected.model_copy(update={"species": "Douglas fir"})
    check = comparison.approval_line_check(line, changed)
    assert check.sku == changed and check.sku_changed_since_selection
    outcomes = {e.attribute: e.outcome for e in check.attribute_evidence}
    assert outcomes["species"] == "mismatch"
    assert line.match.selection.sku == selected  # the selection snapshot is untouched


@pytest.mark.parametrize(
    "change",
    [{"active": False}, {"sell_unit": "box"}, {"sku_id": uuid.UUID(int=77)}],
    ids=["inactive", "unit", "other-sku"],
)
def test_approval_check_refuses_what_cannot_be_approved(change):
    line = selected_line()
    with pytest.raises(ValueError):
        comparison.approval_line_check(line, line.match.selection.sku.model_copy(update=change))
