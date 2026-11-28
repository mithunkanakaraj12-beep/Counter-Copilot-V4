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
        for reference in test["contract_tests"]:
            filename, name = reference.split("::")
            assert name in functions(filename), reference


def test_coverage_claims_are_backed():
    for test in MATRIX:
        covered = test["contract_coverage"] != "needs_application"
        assert bool(test["contract_tests"]) is covered, test["id"]
        if test["contract_coverage"] != "reference_function":
            assert test["not_covered"], test["id"]


def test_every_contract_stage_test_has_reference_coverage():
    c1 = [t for t in MATRIX if t["group"] == "C1"]
    assert len(c1) == 15
    assert all(t["contract_coverage"] == "reference_function" for t in c1)
