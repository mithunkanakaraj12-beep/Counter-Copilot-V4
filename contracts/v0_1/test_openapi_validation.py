"""The committed document passes the official schemas, and the check can fail."""

from __future__ import annotations

import copy

import pytest
import yaml

import validate_openapi
from conftest import HERE

SPEC = yaml.safe_load((HERE / "openapi.yaml").read_text(encoding="utf-8"))


def test_openapi_is_valid_against_the_official_31_schemas():
    assert validate_openapi.errors(SPEC) == []


def _first_schema(document):
    return document["components"]["schemas"]["Health"]


def _first_operation(document):
    return document["paths"]["/api/v1/health"]["get"]


@pytest.mark.parametrize(
    "break_it",
    [
        lambda d: d["info"].pop("title"),
        lambda d: d["info"].update(unknown_field=1),
        lambda d: _first_operation(d).update(responses=[]),
        lambda d: _first_operation(d).update(parameters=[{"name": "q", "in": "body"}]),
        lambda d: _first_schema(d).update(type="strin"),
        lambda d: _first_schema(d).update(required="status"),
        lambda d: _first_schema(d)["properties"]["status"].update(maxLength=-1),
        lambda d: d.update(openapi="3.0.3"),
    ],
    ids=[
        "no-title", "unknown-info-key", "responses-list", "parameter-in", "schema-type",
        "schema-required", "schema-keyword", "version",
    ],
)
def test_the_validator_rejects_broken_documents(break_it):
    document = copy.deepcopy(SPEC)
    break_it(document)
    assert validate_openapi.errors(document)
