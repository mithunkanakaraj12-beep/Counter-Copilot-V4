"""The 30 benchmark cases keep Gemini's wording and labels. No model is run here."""

from __future__ import annotations

import hashlib
import json
import re

import pytest
from jsonschema import Draft202012Validator

import build_benchmark
import models as m
from benchmark.mapping import MAPPING
from conftest import HERE
from reference import email_derivation

DIRECTORY = HERE / "benchmark"
CASES = build_benchmark.labels()["cases"]
IDS = [f"TC-{int(c['id']):03d}" for c in CASES]
EXTRACTION = json.loads((HERE / "extraction-proposal.schema.json").read_text(encoding="utf-8"))
REPORT = json.loads((DIRECTORY / "compatibility.json").read_text(encoding="utf-8"))

# Digest of the id, email wording and all of Gemini's label cells as first transcribed.
# Changing it means a benchmark case changed, which only the label owner may do.
LABEL_DIGEST = "a78ca179c11a54450e0f5042c125ea578b2bd99b56fdd1bdf71259135a40c562"


def label_digest() -> str:
    canonical = json.dumps(CASES, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_the_30_original_case_ids_are_present():
    assert [c["id"] for c in CASES] == [str(n) for n in range(1, 31)]
    assert sorted(MAPPING) == list(range(1, 31))
    assert sorted(p.name for p in (DIRECTORY / "cases").iterdir()) == IDS


def test_wording_and_labels_are_unchanged():
    assert label_digest() == LABEL_DIGEST


def test_generated_files_are_current():
    assert build_benchmark.main(["--check"]) == 0


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_email_wording_is_preserved_exactly(case):
    raw = (DIRECTORY / "cases" / f"TC-{int(case['id']):03d}" / "input.eml").read_bytes()
    assert email_derivation.derive_email(raw).body_text == case["email_text"]


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["id"] != "28"], ids=[i for i in IDS if i != "TC-028"]
)
def test_label_proposal_is_schema_valid_and_quotes_the_email(case):
    folder = DIRECTORY / "cases" / f"TC-{int(case['id']):03d}"
    data = json.loads((folder / "label.proposal.json").read_text(encoding="utf-8"))
    assert Draft202012Validator(EXTRACTION).is_valid(data)
    m.ExtractionProposal.model_validate_json(json.dumps(data))
    for line in data["lines"]:
        for field in ("source_evidence", *m.LINE_FIELDS):
            node = line[field]
            for item in node if field == "source_evidence" else node["evidence"]:
                assert item["quote"] in case["email_text"]
    json_grounded = (folder / "reference.grounded.json").read_text(encoding="utf-8")
    m.GroundedProposal.model_validate_json(json_grounded)


def test_unmapped_class_is_not_chosen_for_gemini():
    assert MAPPING[28]["classification"] is None
    assert not (DIRECTORY / "cases" / "TC-028" / "label.proposal.json").exists()


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_literal_label_values_are_not_rewritten(case):
    """Extracted text and dimension values are copied from the label cells."""
    cells = case["expected_extractions_and_evidence"] + case["expected_ambiguities_warnings"]
    for line in MAPPING[int(case["id"])]["lines"]:
        for name, label in line["fields"].items():
            if label["state"] != "extracted":
                continue
            if name in ("product", "dimensions", "species", "grade", "treatment"):
                assert label["value"] in cells, (name, label["value"])
            if name == "quantity":
                assert re.search(rf"\b{label['value']}\b", cells), label["value"]


def test_every_incompatible_case_states_why():
    for case in REPORT["cases"]:
        reasons = (
            case["changed_by_grounding"] + case["inexpressible"] + case["rule_conflicts"]
        )
        assert bool(reasons) is (case["status"] == "incompatible"), case["id"]


def test_reported_counts():
    """Pinned so that a rule or mapping change cannot move cases silently."""
    assert REPORT["summary"]["status"] == {
        "compatible": 4,
        "incompatible": 18,
        "needs_gemini_confirmation": 8,
    }
    assert REPORT["summary"]["labeled_fields"] == 97
    assert REPORT["summary"]["labeled_fields_changed"] == 14
