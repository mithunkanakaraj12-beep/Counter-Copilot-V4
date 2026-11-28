"""The QA coverage map stays complete and points at tests that exist."""

from __future__ import annotations

import ast
import json
from collections import Counter

from conftest import HERE

MATRIX = json.loads((HERE / "qa" / "matrix.json").read_text(encoding="utf-8"))["tests"]


def functions(filename: str) -> set[str]:
    tree = ast.parse((HERE / filename).read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_all_57_tests_are_listed_once():
    ids = [test["id"] for test in MATRIX]
    assert len(ids) == len(set(ids)) == 57
    assert Counter(t["severity"] for t in MATRIX) == {"Critical": 13, "High": 42, "Medium": 2}


def test_referenced_tests_exist():
    for test in MATRIX:
        for reference in test["contract_tests"] + test.get("safeguard_tests", []):
            filename, name = reference.split("::")
            assert name in functions(filename), reference


def test_coverage_claims_are_backed():
    for test in MATRIX:
        covered = test["contract_coverage"] in ("reference_function", "contract_shape_only")
        assert bool(test["contract_tests"]) is covered, test["id"]
        if test["contract_coverage"] != "reference_function":
            assert test["not_covered"], test["id"]


def test_every_contract_stage_test_has_reference_coverage():
    c1 = [t for t in MATRIX if t["group"] == "C1"]
    assert len(c1) == 15
    assert all(t["contract_coverage"] == "reference_function" for t in c1)


def test_line_recall_stays_an_open_model_quality_gate():
    """A safeguard warning is not a passing extraction result."""
    gate = next(t for t in MATRIX if t["id"] == "LIN-001")
    assert gate["contract_coverage"] == "open_acceptance_gate"
    assert gate["contract_tests"] == [] and gate["safeguard_tests"]
    assert gate["pass_condition_change"] is None
    assert gate["acceptance_gate"]["status"] == "open"
    assert gate["acceptance_gate"]["pass_condition"] == gate["workbook_expected"]


def test_coverage_totals():
    assert Counter(t["contract_coverage"] for t in MATRIX) == {
        "reference_function": 31,
        "contract_shape_only": 17,
        "needs_application": 8,
        "open_acceptance_gate": 1,
    }
    assert sum(t["pass_condition_change"] is not None for t in MATRIX) == 6
