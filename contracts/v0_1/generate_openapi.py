"""Write openapi.yaml and extraction-proposal.schema.json from models.py and api.py.

Usage:  python generate_openapi.py          (rewrite)
        python generate_openapi.py --check  (fail if a committed file is stale)
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
from api import ATTACHMENT_LIMITATION, EMPLOYEE, INTEGRATION, OPERATIONS  # noqa: E402

OUTPUT = HERE / "openapi.yaml"
EXTRACTION_SCHEMA = HERE / "extraction-proposal.schema.json"
REF = "#/components/schemas/{model}"

ERROR_TEXT = {
    401: "Missing or invalid credentials",
    403: "Authenticated but lacking permission, or failed CSRF check",
    404: "Not found, including resources belonging to another yard",
    409: "Conflicts with current state, version, idempotency key or an earlier delivery",
    413: "Over an approved size or parser limit",
    415: "Unsupported media type",
    422: "Validation failed, approval blocked or original hash mismatch",
    429: "Rate limited; retry after the stated delay",
    503: "Temporarily unavailable; safe to retry with the same Idempotency-Key",
}

DOWNLOAD_HEADERS = {
    "Content-Disposition": {
        "description": "attachment with a server-chosen filename, never the sender's",
        "required": True,
        "schema": {"type": "string", "pattern": "^attachment; filename="},
    },
    "X-Content-Type-Options": {"required": True, "schema": {"type": "string", "const": "nosniff"}},
    "Cache-Control": {"required": True, "schema": {"type": "string", "const": "no-store"}},
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
        parameters.extend(dict(p) for p in op.query)
        if op.idempotency_header:
            parameters.append(
                _header(
                    "Idempotency-Key",
                    "Client-generated, scoped to yard, user, method and path. "
                    f"Kept {m.Limits.IDEMPOTENCY_HOURS} hours.",
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
        if op.conditional_permissions:
            item["x-conditional-permissions"] = op.conditional_permissions
        if op.request:
            item["x-max-body-bytes"] = (
                m.Limits.RAW_EMAIL_BYTES + m.Limits.JSON_BYTES
                if op.operation_id == "ingestEmailEvent"
                else m.Limits.JSON_BYTES
            )
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
                                    "description": "Raw bytes, authoritative.",
                                    "x-max-bytes": m.Limits.RAW_EMAIL_BYTES,
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
                    "headers": DOWNLOAD_HEADERS,
                    "content": {
                        "message/rfc822": {
                            "schema": {"type": "string", "contentMediaType": "message/rfc822"}
                        }
                    },
                }
            else:
                responses[str(status)] = {
                    "description": "Success",
                    "content": {"application/json": {"schema": {"$ref": refs[model]}}},
                }
        for status in op.errors:
            responses[str(status)] = {
                "description": ERROR_TEXT[status],
                "x-error-codes": [code.value for code in m.ERROR_STATUS[status]],
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
            "version": "0.1.0-proposal.2",
            "description": (
                "Contract for the email-to-reviewed-draft slice, revised for independent "
                "review. Not frozen and not implemented. Behavioural rules are in "
                "docs/DATA_CONTRACT.md. " + ATTACHMENT_LIMITATION + " Generated by "
                "generate_openapi.py: do not edit by hand."
            ),
            "x-limits": {
                name.lower(): value
                for name, value in vars(m.Limits).items()
                if name.isupper()
            },
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


def render_extraction_schema() -> str:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:counter-copilot:v0.1:extraction-proposal",
        **m.ExtractionProposal.model_json_schema(),
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


class _NoAlias(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def render() -> str:
    # Round-trip through JSON so enum members become plain strings.
    spec = json.loads(json.dumps(build()))
    return yaml.dump(spec, Dumper=_NoAlias, sort_keys=False, width=100, allow_unicode=True)


if __name__ == "__main__":
    outputs = {OUTPUT: render(), EXTRACTION_SCHEMA: render_extraction_schema()}
    stale = []
    for path, text in outputs.items():
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
            else:
                print(f"{path.name} is up to date")
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.name}")
    if stale:
        sys.exit(f"out of date: {', '.join(stale)}")
