"""Validate openapi.yaml against the official OpenAPI 3.1 JSON Schemas, offline.

Usage: python validate_openapi.py [path/to/openapi.yaml]

'schema-base' checks the document structure and every Schema Object against the
OpenAPI 3.1 dialect. It does not check that $ref targets exist; test_contract.py does.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "oas-3.1"


def _load() -> tuple[dict, Registry]:
    pinned = dict(
        reversed(line.split()) for line in (VENDOR / "SHA256SUMS").read_text().splitlines()
    )
    documents = {}
    for name in ("schema.json", "schema-base.json", "dialect.json", "meta.json"):
        data = (VENDOR / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != pinned[name]:
            raise SystemExit(f"{name} does not match its pinned digest")
        documents[name] = json.loads(data)
    registry = Registry().with_resources(
        (d["$id"], Resource.from_contents(d)) for d in documents.values()
    )
    return documents["schema-base.json"], registry


def errors(document: dict) -> list[str]:
    schema, registry = _load()
    validator = Draft202012Validator(schema, registry=registry)
    found = sorted(validator.iter_errors(document), key=lambda e: e.json_path)
    return [f"{e.json_path}: {e.message[:300]}" for e in found]


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else HERE / "openapi.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = errors(document)
    for problem in problems[:50]:
        print(problem)
    schema_id = _load()[0]["$id"]
    if problems:
        print(f"FAILED: {len(problems)} error(s) against {schema_id}")
        return 1
    print(f"VALID: {path.name} against {schema_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
