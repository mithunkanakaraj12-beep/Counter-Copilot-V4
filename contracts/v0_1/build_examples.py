"""Write the synthetic API examples from one source email, so offsets, digests and
derived values always agree.

Usage:  python build_examples.py           (rewrite)
        python build_examples.py --check   (fail if a committed example is stale)

This assembles fixtures. The warning and blocker lists are written out by hand
here; it is not an implementation of the rules that produce them.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import models as m  # noqa: E402
from reference import comparison, email_derivation, grounding  # noqa: E402

EXAMPLES = HERE / "examples"
YARD_FILE = HERE.parents[1] / "tests" / "fixtures" / "synthetic_yard.json"
NS = uuid.UUID("5b0f0c1e-6c2a-4a43-9d0e-6f0f3a1c0d01")


def uid(name: str) -> uuid.UUID:
    return uuid.uuid5(NS, name)


def dump(model) -> dict:
    return model.model_dump(mode="json")


YARD = json.loads(YARD_FILE.read_text(encoding="utf-8"))["yards"][0]
SKUS = {item["code"]: m.SkuSnapshot.model_validate(item) for item in YARD["skus"]}
EMPLOYEE = m.PersonRef(user_id=uid("user-1"), display_name="Sam Ortiz (Synthetic)", active=True)
COMMUNICATION = uid("communication-1")
REQUEST = uid("request-1")
RUN = uid("run-1")
INGESTED = "2026-11-25T15:00:05Z"
CREATED = "2026-11-25T15:00:20Z"
EDITED = "2026-11-25T16:10:00Z"
APPROVED = "2026-11-25T16:12:00Z"


def evidence(quote: str, role: str = "supports", occurrence: int = 0) -> dict:
    return {"source": "body_text", "quote": quote, "occurrence": occurrence, "role": role}


def extracted(value, quote: str) -> dict:
    return {
        "state": "extracted",
        "value": value,
        "candidates": [],
        "ambiguity_reason": None,
        "evidence": [evidence(quote)],
    }


MISSING = {
    "state": "missing",
    "value": None,
    "candidates": [],
    "ambiguity_reason": None,
    "evidence": [],
}


def proposal() -> dict:
    first = {
        "source_evidence": [evidence("40 pieces of 2x6x12 SYP #2")],
        "product": MISSING,
        "quantity": extracted("40", "40 pieces"),
        "unit": extracted("piece", "pieces"),
        "dimensions": extracted("2x6x12", "2x6x12"),
        "species": extracted("SYP", "SYP"),
        "grade": extracted("#2", "#2"),
        "treatment": MISSING,
    }
    second = {
        "source_evidence": [
            evidence("20 sheets of 7/16 OSB"),
            evidence("Actually make the OSB 24 sheets", "conflicts"),
        ],
        "product": extracted("OSB", "OSB"),
        "quantity": {
            "state": "ambiguous",
            "value": None,
            "candidates": ["20", "24"],
            "ambiguity_reason": "conflicting_statements",
            "evidence": [
                evidence("20 sheets"),
                evidence("Actually make the OSB 24 sheets", "conflicts"),
            ],
        },
        "unit": extracted("sheet", "sheets"),
        "dimensions": extracted("7/16", "7/16"),
        "species": MISSING,
        "grade": MISSING,
        "treatment": MISSING,
    }
    return {
        "schema_version": "0.1",
        "classification": "material_request",
        "lines": [first, second],
        "job_details": {name: MISSING for name in m.JOB_FIELDS},
        "multiple_jobs_evidence": [],
    }


def field_from_proposal(name: str, record) -> dict:
    data = dump(record)
    base = {k: data[k] for k in ("state", "value", "candidates", "ambiguity_reason", "evidence")}
    return {**base, "proposal": data}


def warning(code: str, target: dict, message: str, found=(), related=()) -> m.ReviewWarning:
    key = json.dumps([code, target, [e.quote for e in found], message], sort_keys=True)
    return m.ReviewWarning(
        warning_id="w-" + hashlib.sha256(key.encode()).hexdigest()[:16],
        code=code,
        message=message,
        target=target,
        requires_acknowledgement=code not in m.INFORMATIONAL_WARNINGS,
        heuristic=code in m.HEURISTIC_WARNINGS,
        evidence=list(found),
        related_communication_ids=list(related),
    )


def line_target(line_id, field=None) -> dict:
    return {"scope": "line", "line_id": str(line_id), "field": field}


def blocker(code: str, target: dict, message: str) -> dict:
    return {
        "blocker_id": f"{code}:{target['line_id']}:{target['field']}",
        "code": code,
        "message": message,
        "target": target,
        "warning_id": None,
    }


def build() -> dict[str, object]:
    raw = (EXAMPLES / "synthetic-email.eml").read_bytes()
    parsed = email_derivation.derive_email(raw)
    digest = hashlib.sha256(raw).hexdigest()
    source = grounding.Source.from_parsed(COMMUNICATION, parsed)
    grounded = grounding.ground_proposal(source, proposal(), RUN)

    intake = {
        "schema_version": "0.1",
        "channel": "email",
        "external_message_id": "synthetic-mailbox-0001",
        "external_event_id": "synthetic-delivery-0001",
        "provider_thread_id": "synthetic-thread-0001",
        "received_at": "2026-11-25T15:00:00Z",
        "envelope_recipients": ["orders@example-yard.test"],
        "provider_metadata": {"source": "synthetic"},
        "original_sha256": digest,
    }

    line_ids = [uid("line-1"), uid("line-2")]
    chosen = [SKUS["SYP-2X6-12-N2"], SKUS["OSB-716"]]
    lines = []
    for index, item in enumerate(grounded.lines):
        line = {
            "line_id": str(line_ids[index]),
            "position": index + 1,
            "origin": "model",
            "status": "active",
            "removal": None,
            "raw_wording": item.source_evidence[0].quote,
            "source_evidence": [dump(e) for e in item.source_evidence],
            "employee_source_spans": [],
            **{n: field_from_proposal(n, getattr(item, n)) for n in m.LINE_FIELDS},
            "match": {
                "status": "not_run",
                "catalog_version": None,
                "matcher_version": None,
                "candidates": [],
                "selection": None,
                "last_cleared_selection": None,
            },
        }
        shown = m.MaterialLine.model_validate(line)
        preview = comparison.preview(shown, chosen[index])
        line["match"] = {
            "status": "single_candidate",
            "catalog_version": YARD["catalog_version"],
            "matcher_version": comparison.MATCHER_VERSION,
            "candidates": [{"rank": 1, "sku": dump(chosen[index]), **dump(preview)}],
            "selection": None,
            "last_cleared_selection": None,
        }
        lines.append(line)

    warnings = []
    for item in grounded.warnings:
        target = (
            {"scope": "request", "line_id": None, "field": None}
            if item.line_index is None
            else line_target(line_ids[item.line_index])
        )
        text = {
            "possible_correction_language": "Wording may correct an earlier statement.",
            "uncited_quantity_text": "A number in the message is not linked to any line.",
            "overlapping_line_evidence": "Two lines rely on the same wording.",
        }[item.code]
        warnings.append(warning(item.code, target, text, item.evidence))

    blockers = [
        blocker("sku_not_selected", line_target(line_ids[0], "sku"), "Select a catalog item."),
        blocker(
            "quantity_unresolved", line_target(line_ids[1], "quantity"), "Decide the quantity."
        ),
        blocker("sku_not_selected", line_target(line_ids[1], "sku"), "Select a catalog item."),
    ]
    job = {
        name: field_from_proposal(name, getattr(grounded.job_details, name))
        for name in m.JOB_FIELDS
    }
    draft = {
        "schema_version": "0.1",
        "request_id": str(REQUEST),
        "yard_id": YARD["yard_id"],
        "version": 1,
        "review_state": "draft_ready",
        "origin_communication_id": str(COMMUNICATION),
        "related_messages": [],
        "created_at": CREATED,
        "updated_at": CREATED,
        "updated_by": {"type": "system", "person": None},
        "content": {"lines": lines, "job_details": job},
        "warnings": [dump(w) for w in warnings],
        "approval_blockers": blockers,
        "approval": None,
        "last_decision": None,
        "extraction": {
            "run_id": str(RUN),
            "provider": "synthetic",
            "model_version": "synthetic-fixture",
            "prompt_version": "synthetic-fixture",
            "schema_version": "0.1",
            "parser_version": parsed.parser_version,
            "grounding_version": grounded.grounding_version,
            "lexicon_version": grounded.lexicon_version,
            "completed_at": CREATED,
        },
        "inventory_status": "not_assessed",
        "pricing_status": "not_calculated",
    }

    edit = {
        "expected_version": 1,
        "operations": [
            {
                "op": "choose_candidate",
                "target": {"scope": "line", "line_id": str(line_ids[1]), "field": "quantity"},
                "candidate_index": 1,
            },
            {"op": "select_sku", "line_id": str(line_ids[0]), "sku_id": str(chosen[0].sku_id)},
            {"op": "select_sku", "line_id": str(line_ids[1]), "sku_id": str(chosen[1].sku_id)},
        ],
        "note": "Contractor's second sentence changes the OSB count.",
    }

    # The approved example: the edit above, then approval of version 2.
    approved = json.loads(json.dumps(draft))
    second = approved["content"]["lines"][1]
    second["quantity"] = {
        "state": "employee_entered",
        "value": "24",
        "candidates": [],
        "ambiguity_reason": None,
        "evidence": second["quantity"]["evidence"],
        "entered_by": dump(EMPLOYEE),
        "entered_at": EDITED,
        "resolution": {"method": "chose_candidate", "candidate_index": 1},
        "proposal": second["quantity"]["proposal"],
    }
    all_warnings = list(warnings)
    for index, line in enumerate(approved["content"]["lines"]):
        preview = comparison.preview(m.MaterialLine.model_validate(line), chosen[index])
        line["match"]["candidates"] = [{"rank": 1, "sku": dump(chosen[index]), **dump(preview)}]
        line["match"]["selection"] = {
            "sku": dump(chosen[index]),
            **dump(preview),
            "catalog_version": YARD["catalog_version"],
            "selected_by": dump(EMPLOYEE),
            "selected_at": EDITED,
            "current": {
                **dump(preview),
                "sku_active": True,
                "sku_changed": False,
                "catalog_stale": False,
            },
        }
        needed = comparison.acknowledgment_attributes(preview.attribute_evidence)
        for code, attributes in needed.items():
            all_warnings.append(
                warning(
                    code,
                    line_target(line_ids[index], "sku"),
                    "Check the selected item: " + ", ".join(attributes) + ".",
                )
            )
    approve = {
        "action": "approve_internal",
        "expected_version": 2,
        "acknowledged_warning_ids": [w.warning_id for w in all_warnings],
        "false_positive_warning_ids": [],
        "note": None,
    }
    content_hash = hashlib.sha256(
        json.dumps(
            approved["content"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    catalog_check = m.ApprovalCatalogCheck(
        catalog_version=YARD["catalog_version"],
        matcher_version=comparison.MATCHER_VERSION,
        lines=[
            comparison.approval_line_check(m.MaterialLine.model_validate(line), chosen[index])
            for index, line in enumerate(approved["content"]["lines"])
        ],
    )
    approved.update(
        version=3,
        review_state="internally_approved",
        updated_at=APPROVED,
        updated_by={"type": "employee", "person": dump(EMPLOYEE)},
        warnings=[dump(w) for w in all_warnings],
        approval_blockers=[],
        approval={
            "approval_id": str(uid("approval-1")),
            "request_id": str(REQUEST),
            "approved_version": 2,
            "content_sha256": content_hash,
            "catalog_check": dump(catalog_check),
            "catalog_check_sha256": m.canonical_sha256(catalog_check),
            "approved_by": dump(EMPLOYEE),
            "approved_at": APPROVED,
            "acknowledged_warnings": [
                {
                    "warning_id": w.warning_id,
                    "code": w.code,
                    "message": w.message,
                    "target": dump(w.target),
                    "marked_false_positive": False,
                }
                for w in all_warnings
            ],
            "status": "active",
            "revoked_by": None,
            "revoked_at": None,
            "revocation_reason": None,
        },
        last_decision={
            "action": "approve_internal",
            "actor": dump(EMPLOYEE),
            "occurred_at": APPROVED,
            "resulting_version": 3,
            "reason": None,
            "note": None,
            "false_positive_warning_ids": [],
        },
    )

    communication = {
        "record": {
            **dump(parsed),
            "communication_id": str(COMMUNICATION),
            "yard_id": YARD["yard_id"],
            "integration_id": str(uid("integration-1")),
            "channel": "email",
            "direction": "inbound",
            "external_message_id": intake["external_message_id"],
            "provider_thread_id": intake["provider_thread_id"],
            "content_fingerprint": email_derivation.content_fingerprint(raw, parsed),
            "received_at": intake["received_at"],
            "ingested_at": INGESTED,
            "envelope_recipients": intake["envelope_recipients"],
            "provider_metadata": intake["provider_metadata"],
            "original": {
                "media_type": "message/rfc822",
                "size_bytes": len(raw),
                "sha256": digest,
                "stored_at": INGESTED,
            },
        },
        "status": {
            "processing_state": "completed",
            "classification": "material_request",
            "failure_code": None,
            "employee_message": None,
            "attempt_count": 1,
            "processing_started_at": "2026-11-25T15:00:10Z",
            "next_retry_at": None,
            "possible_duplicate_of": [],
            "related_messages": [],
            "has_conflicting_redelivery": False,
            "origin_request_id": str(REQUEST),
            "handling": {
                "status": "open",
                "version": 0,
                "mark_handled_allowed": False,
                "reason": None,
                "note": None,
                "changed_by": None,
                "changed_at": None,
            },
        },
        "handling_history": [],
    }
    handling = {
        "action": "mark_handled",
        "expected_handling_version": 0,
        "reason": "other",
        "note": "Billing question forwarded by phone (synthetic).",
    }

    return {
        "inbound-email-event.json": intake,
        "extraction-proposal.json": proposal(),
        "grounded-proposal.json": dump(grounded),
        "communication-detail.json": communication,
        "request-detail.draft.json": draft,
        "request-edit.json": edit,
        "decision.approve.json": approve,
        "request-detail.approved.json": approved,
        "handling.mark.json": handling,
    }


MODELS = {
    "inbound-email-event.json": m.InboundEmailEvent,
    "extraction-proposal.json": m.ExtractionProposal,
    "grounded-proposal.json": m.GroundedProposal,
    "communication-detail.json": m.CommunicationDetail,
    "request-detail.draft.json": m.RequestDetail,
    "request-edit.json": m.RequestEdit,
    "decision.approve.json": m.DecisionRequest,
    "request-detail.approved.json": m.RequestDetail,
    "handling.mark.json": m.HandlingRequest,
}


def render() -> dict[str, str]:
    outputs = {}
    for name, data in build().items():
        MODELS[name].model_validate_json(json.dumps(data))
        outputs[name] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return outputs


if __name__ == "__main__":
    stale = []
    for name, text in render().items():
        path = EXAMPLES / name
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        sys.exit(f"out of date: {', '.join(stale)}")
    print("examples are up to date" if "--check" in sys.argv else "wrote examples")
