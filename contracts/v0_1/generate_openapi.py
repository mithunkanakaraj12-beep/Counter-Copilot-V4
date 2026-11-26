"""Write openapi.yaml from models.py and api.py.

Usage:  python generate_openapi.py          (rewrite)
        python generate_openapi.py --check  (fail if the committed file is stale)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from pydantic.json_schema import models_json_schema

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import models as m  # noqa: E402
from api import EMPLOYEE, INTEGRATION, OPERATIONS  # noqa: E402

OUTPUT = HERE / "openapi.yaml"
REF = "#/components/schemas/{model}"

ERROR_TEXT = {
    401: "Missing or invalid credentials",
    403: "Authenticated but lacking permission, or failed CSRF check",
    404: "Not found, including resources belonging to another yard",
    409: "Conflicts with current state, version or idempotency key",
    413: "Payload too large",
    422: "Validation failed or approval blocked",
    503: "Temporarily unavailable; safe to retry",
}


def _component_schemas() -> tuple[dict, dict]:
    wanted: dict[type, str] = {m.ErrorResponse: "serialization"}
    for op in OPERATIONS:
        if op.request:
            wanted[op.request] = "validation"
        for model in op.responses.values():
            if model:
                wanted[model] = "serialization"
    refs, top = models_json_schema(list(wanted.items()), ref_template=REF)
    names = {model: schema["$ref"] for (model, _), schema in refs.items()}
    return names, dict(sorted(top["$defs"].items()))


def _path_parameter(name: str) -> dict:
    schema = (
        {"type": "integer", "minimum": 1}
        if name == "version"
        else {"type": "string", "format": "uuid"}
    )
    return {"name": name, "in": "path", "required": True, "schema": schema}


def _query(name: str, schema: dict) -> dict:
    return {"name": name, "in": "query", "required": False, "schema": schema}


def _header(name: str, description: str, schema: dict) -> dict:
    return {
        "name": name,
        "in": "header",
        "required": True,
        "description": description,
        "schema": schema,
    }


def build() -> dict:
    refs, schemas = _component_schemas()
    paths: dict = {}
    for op in OPERATIONS:
        parameters = [_path_parameter(n) for n in re.findall(r"{(\w+)}", op.path)]
        if op.paged:
            parameters.append(_query("cursor", {"type": "string"}))
            parameters.append(
                _query("limit", {"type": "integer", "minimum": 1, "maximum": 100, "default": 25})
            )
        if op.search:
            parameters.append(_query("q", {"type": "string", "maxLength": 200}))
        if op.inbox_filters:
            for name, enum in (
                ("review_state", m.ReviewState),
                ("processing_state", m.ProcessingState),
                ("classification", m.Classification),
            ):
                parameters.append(_query(name, {"type": "string", "enum": [e.value for e in enum]}))
        if op.idempotency_header:
            parameters.append(
                _header(
                    "Idempotency-Key",
                    "Client-generated, scoped to yard, user, method and path.",
                    {"type": "string", "minLength": 16, "maxLength": 128},
                )
            )
        unsafe = op.method in ("post", "patch", "put", "delete")
        if op.auth == EMPLOYEE and unsafe:
            parameters.append(
                _header("X-CSRF-Token", "Value from GET /api/v1/me.", {"type": "string"})
            )

        item: dict = {"operationId": op.operation_id, "summary": op.summary}
        if op.description:
            item["description"] = op.description
        item["security"] = {
            EMPLOYEE: [{"employeeSession": []}],
            INTEGRATION: [{"integrationToken": []}],
        }.get(op.auth, [])
        if op.permission:
            item["x-required-permission"] = op.permission.value
        if parameters:
            item["parameters"] = parameters

        if op.operation_id == "ingestEmailEvent":
            item["requestBody"] = {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["metadata", "original"],
                            "properties": {
                                "metadata": {"$ref": refs[op.request]},
                                "original": {
                                    "type": "string",
                                    "contentMediaType": "message/rfc822",
                                },
                            },
                        },
                        "encoding": {
                            "metadata": {"contentType": "application/json"},
                            "original": {"contentType": "message/rfc822"},
                        },
                    }
                },
            }
        elif op.request:
            item["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": refs[op.request]}}},
            }

        responses: dict = {}
        for status, model in op.responses.items():
            if model is None:
                responses[str(status)] = {
                    "description": "Original bytes",
                    "content": {"message/rfc822": {"schema": {"type": "string"}}},
                }
            else:
                responses[str(status)] = {
                    "description": "Success",
                    "content": {"application/json": {"schema": {"$ref": refs[model]}}},
                }
        for status in op.errors:
            responses[str(status)] = {
                "description": ERROR_TEXT[status],
                "content": {
                    "application/json": {"schema": {"$ref": refs[m.ErrorResponse]}}
                },
            }
        item["responses"] = dict(sorted(responses.items()))
        paths.setdefault(op.path, {})[op.method] = item

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Counter Copilot V4 API (PROPOSAL)",
            "version": "0.1.0-proposal",
            "description": (
                "Proposed contract for the email-to-reviewed-draft slice. Not approved and "
                "not implemented. Behavioural rules are in docs/DATA_CONTRACT.md. Generated "
                "by generate_openapi.py: do not edit by hand."
            ),
        },
        "paths": paths,
        "components": {
            "securitySchemes": {
                "employeeSession": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "cc_session",
                    "description": "Proposed (U-01). Secure, HttpOnly, SameSite cookie.",
                },
                "integrationToken": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Proposed (U-02). Bound to one yard, integration and channel.",
                },
            },
            "schemas": schemas,
        },
    }


class _NoAlias(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def render() -> str:
    # Round-trip through JSON so enum members become plain strings.
    spec = json.loads(json.dumps(build()))
    return yaml.dump(spec, Dumper=_NoAlias, sort_keys=False, width=100, allow_unicode=True)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            sys.exit("openapi.yaml is out of date")
        print("openapi.yaml is up to date")
    else:
        OUTPUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUTPUT.name}")
