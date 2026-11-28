"""Builds the 30-case benchmark files and the compatibility report from Gemini's labels.

Usage: python build_benchmark.py [--check]
"""

from __future__ import annotations

import json
import sys
import uuid
from collections import Counter
from pathlib import Path

import models as m
from benchmark.mapping import MAPPING
from reference import email_derivation, grounding

HERE = Path(__file__).resolve().parent
DIRECTORY = HERE / "benchmark"
REPORT = HERE.parents[1] / "docs" / "BENCHMARK_COMPATIBILITY.md"
NAMESPACE = uuid.UUID("5b0f0c1e-6c2a-4a43-9d0e-6f0f3a1c0d02")
FIELDS = m.LINE_FIELDS


def labels() -> dict:
    return json.loads((DIRECTORY / "gemini_labels.json").read_text(encoding="utf-8"))


def eml(number: int, text: str) -> bytes:
    headers = [
        "From: Synthetic Contractor <contractor@example.test>",
        "To: orders@example-yard.test",
        f"Message-ID: <benchmark-{number:03d}@example.test>",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: 8bit",
    ]
    return ("\r\n".join(headers) + "\r\n\r\n" + text).encode("utf-8")


def evidence(quotes) -> list[dict]:
    return [
        {
            "source": "body_text",
            "quote": quote,
            "occurrence": 0,
            "role": "supports" if position == 0 else "conflicts",
        }
        for position, quote in enumerate(quotes)
    ]


def proposed(label: dict | None) -> dict:
    label = label or {"state": "missing", "value": None, "quotes": ()}
    return {
        "state": label["state"],
        "value": label["value"],
        "candidates": list(label.get("candidates", ())),
        "ambiguity_reason": label.get("reason"),
        "evidence": evidence(label["quotes"]),
    }


def proposal(mapped: dict, text: str) -> dict:
    return {
        "schema_version": "0.1",
        "classification": mapped["classification"],
        "lines": [
            {
                "source_evidence": evidence([line["span"] or text]),
                **{name: proposed(line["fields"].get(name)) for name in FIELDS},
            }
            for line in mapped["lines"]
        ],
        "job_details": {name: proposed(None) for name in m.JOB_FIELDS},
        "multiple_jobs_evidence": [],
    }


def plain(value):
    return value.text if isinstance(value, m.Dimensions) else value


def describe(state, value, reason, candidates) -> str:
    if state == "extracted":
        return f"extracted '{value}'"
    if state == "ambiguous":
        listed = ", ".join(str(c) for c in candidates) or "none"
        return f"ambiguous ({reason}; candidates: {listed})"
    return "missing"


def compare(mapped: dict, grounded: m.GroundedProposal) -> list[dict]:
    """Only labeled fields are compared."""
    results = []
    for number, (line, result) in enumerate(zip(mapped["lines"], grounded.lines, strict=True), 1):
        for name in FIELDS:
            label = line["fields"].get(name)
            if label is None:
                continue
            record = getattr(result, name)
            candidates = [plain(c) for c in record.candidates]
            reason = record.ambiguity_reason.value if record.ambiguity_reason else None
            same = (
                record.state == label["state"]
                and plain(record.value) == label["value"]
                and reason == label.get("reason")
                and candidates == list(label.get("candidates", ()))
            )
            results.append(
                {
                    "line": number,
                    "field": name,
                    "label": describe(
                        label["state"], label["value"], label.get("reason"), label.get("candidates", ())
                    ),
                    "grounded": describe(record.state, plain(record.value), reason, candidates),
                    "same": same,
                }
            )
    return results


def run() -> tuple[dict[Path, bytes], dict]:
    files: dict[Path, bytes] = {}
    cases = []
    for entry in labels()["cases"]:
        number = int(entry["id"])
        mapped = MAPPING[number]
        folder = DIRECTORY / "cases" / f"TC-{number:03d}"
        raw = eml(number, entry["email_text"])
        files[folder / "input.eml"] = raw
        parsed = email_derivation.derive_email(raw)
        if parsed.body_text != entry["email_text"]:
            raise AssertionError(f"case {number}: derived body differs from the email text")
        fields, warnings = [], []
        if mapped["classification"] is not None:
            data = proposal(mapped, entry["email_text"])
            source = grounding.Source.from_parsed(uuid.uuid5(NAMESPACE, f"message-{number}"), parsed)
            grounded = grounding.ground_proposal(source, data, uuid.uuid5(NAMESPACE, f"run-{number}"))
            files[folder / "label.proposal.json"] = dump(data)
            files[folder / "reference.grounded.json"] = dump(grounded.model_dump(mode="json"))
            fields = compare(mapped, grounded)
            warnings = sorted({w.code.value for w in grounded.warnings})
        changed = [f for f in fields if not f["same"]]
        if changed or mapped["inexpressible"] or mapped["rule_conflicts"]:
            status = "incompatible"
        elif mapped["open_points"]:
            status = "needs_gemini_confirmation"
        else:
            status = "compatible"
        cases.append(
            {
                "id": entry["id"],
                "directory": folder.name,
                "category": entry["category"],
                "status": status,
                "label_classification": entry["classification"],
                "contract_classification": mapped["classification"],
                "labeled_fields": len(fields),
                "changed_by_grounding": changed,
                "inexpressible": mapped["inexpressible"],
                "rule_conflicts": mapped["rule_conflicts"],
                "open_points": mapped["open_points"],
                "label_warning_text": entry["expected_ambiguities_warnings"],
                "grounding_warning_codes": warnings,
            }
        )
    summary = {
        "grounding_version": grounding.GROUNDING_VERSION,
        "cases": len(cases),
        "schema_valid_proposals": sum(c["contract_classification"] is not None for c in cases),
        "status": dict(sorted(Counter(c["status"] for c in cases).items())),
        "labeled_fields": sum(c["labeled_fields"] for c in cases),
        "labeled_fields_changed": sum(len(c["changed_by_grounding"]) for c in cases),
    }
    report = {"summary": summary, "cases": cases}
    files[DIRECTORY / "compatibility.json"] = dump(report)
    files[REPORT] = markdown(report).encode("utf-8")
    return files, report


def dump(data) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def numbers(cases, status) -> str:
    return ", ".join(c["id"] for c in cases if c["status"] == status) or "none"


def markdown(report: dict) -> str:
    summary, cases = report["summary"], report["cases"]
    out = [
        "# Benchmark compatibility",
        "",
        "Generated by `contracts/v0_1/build_benchmark.py`. Do not edit by hand.",
        "",
        "This checks whether Gemini's 30 labels can be expressed in the v0.1 contract and survive the",
        "reference grounding rules. **No model was run.** It is not an accuracy result, and the 30-case",
        "suite is not complete until Gemini resolves the items below. Labels and email wording are",
        "unchanged (`contracts/v0_1/benchmark/gemini_labels.json`).",
        "",
        "## Result",
        "",
        "| Status | Cases | IDs |",
        "|---|---|---|",
    ]
    for status in ("compatible", "needs_gemini_confirmation", "incompatible"):
        out.append(f"| {status} | {summary['status'].get(status, 0)} | {numbers(cases, status)} |")
    out += [
        "",
        f"- Email text reproduced exactly by email derivation: {summary['cases']} of {summary['cases']}.",
        f"- Label proposals that pass the schema and ground without structural rejection: "
        f"{summary['schema_valid_proposals']} of {summary['cases']}.",
        f"- Labeled fields compared: {summary['labeled_fields']}; changed by grounding: "
        f"{summary['labeled_fields_changed']}.",
        "- `compatible` covers extraction fields only. Free-text warnings are listed per case; the",
        "  contract uses fixed warning codes and several label warnings have none.",
        "",
        "## Method",
        "",
        "Label values are copied literally into the schema. Claude 1 chose evidence quotes and line",
        "spans, because the labels give none. Fields a label does not mention are filled with `missing`",
        "to satisfy the schema and are not compared. Grounding output is saved as",
        "`reference.grounded.json`; it is what the rules produce, not a Gemini-approved expected result.",
        "",
        "## Questions that affect scoring",
        "",
        "- The rubric names three classes (Quote Request, General Inquiry, Non-Material); the contract",
        "  has four, with no General Inquiry. Quote Request is read as `material_request`, Non-Material",
        "  as `non_request`, and Follow-up as `follow_up`.",
        "- 'Field-Level Precision ... matching exact source evidence' needs a rule for normalized values",
        "  (unit codes, canonical numbers). Proposed: score normalized values, require exact evidence.",
        "- Raw model output and the grounded draft should be scored separately, with zero unsupported",
        "  values in the draft. The rubric's percentages remain proposed targets.",
        "",
        "## Cases",
    ]
    for case in cases:
        out += ["", f"### Case {case['id']}: {case['status']}", ""]
        for change in case["changed_by_grounding"]:
            out.append(
                f"- Line {change['line']} {change['field']}: label {change['label']}; "
                f"grounded result {change['grounded']}."
            )
        out += [f"- No contract representation: {text}" for text in case["inexpressible"]]
        out += [f"- Conflicts with an approved rule: {text}" for text in case["rule_conflicts"]]
        out += [f"- To confirm: {text}" for text in case["open_points"]]
        codes = ", ".join(f"`{c}`" for c in case["grounding_warning_codes"]) or "none"
        out.append(f'- Label warning text: "{case["label_warning_text"]}" Grounding codes: {codes}.')
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    files, report = run()
    if "--check" in argv:
        stale = [p for p, data in files.items() if not p.exists() or p.read_bytes() != data]
        expected = {p for p in files if (DIRECTORY / "cases") in p.parents}
        extra = [p for p in (DIRECTORY / "cases").rglob("*") if p.is_file() and p not in expected]
        for path in stale + extra:
            print(f"stale: {path}")
        return 1 if stale or extra else 0
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
