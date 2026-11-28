"""Builders shared by the contract tests. All content is synthetic."""

from __future__ import annotations

import uuid

import models as m
from reference import grounding

COMMUNICATION = uuid.UUID(int=1)
RUN = uuid.UUID(int=2)


def ev(quote: str, role: str = "supports", occurrence: int = 0, source: str = "body_text"):
    return {"source": source, "quote": quote, "occurrence": occurrence, "role": role}


def ex(value, quote: str, **kwargs):
    return {
        "state": "extracted",
        "value": value,
        "candidates": [],
        "ambiguity_reason": None,
        "evidence": [ev(quote, **kwargs)],
    }


def missing():
    return {
        "state": "missing",
        "value": None,
        "candidates": [],
        "ambiguity_reason": None,
        "evidence": [],
    }


def amb(reason: str, quotes, candidates=()):
    items = [ev(q) if isinstance(q, str) else q for q in quotes]
    return {
        "state": "ambiguous",
        "value": None,
        "candidates": list(candidates),
        "ambiguity_reason": reason,
        "evidence": items,
    }


def line(source, **fields):
    spans = [source] if isinstance(source, (str, dict)) else source
    result = {"source_evidence": [ev(s) if isinstance(s, str) else s for s in spans]}
    for name in m.LINE_FIELDS:
        result[name] = fields.get(name, missing())
    return result


def proposal(lines, classification="material_request", jobs_evidence=(), **job):
    return {
        "schema_version": "0.1",
        "classification": classification,
        "lines": lines,
        "job_details": {name: job.get(name, missing()) for name in m.JOB_FIELDS},
        "multiple_jobs_evidence": [ev(q) for q in jobs_evidence],
    }


def source(body: str, subject=None, quoted=(), html=False):
    return grounding.Source(COMMUNICATION, subject, body, tuple(quoted), html)


def ground(body: str, lines, **kwargs):
    src = {k: kwargs.pop(k) for k in ("subject", "quoted", "html") if k in kwargs}
    return grounding.ground_proposal(source(body, **src), proposal(lines, **kwargs), RUN)


def one(body: str, name: str, field, **kwargs):
    """Ground one field of a one-line message whose line span is the whole body."""
    return getattr(ground(body, [line(body, **{name: field})], **kwargs).lines[0], name)


def codes(result) -> set[str]:
    return {w.code.value for w in result.warnings}
