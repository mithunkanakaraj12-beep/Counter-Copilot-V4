"""Reference parser: byte-preserving, bounded and deterministic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

import models as m
from reference import email_derivation as parser
from reference import grounding
from testkit import COMMUNICATION

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HEAD = b"From: Contractor <contractor@example.test>\r\nTo: orders@example-yard.test\r\n"


def mail(body: bytes = b"40 studs", headers: bytes = b"") -> bytes:
    return HEAD + headers + b"\r\n" + body


def fixture(name: str) -> m.ParsedContent:
    return parser.derive_email((FIXTURES / name).read_bytes())


BODY_TEXT_SCHEMA = m.ParsedContent.model_json_schema()["properties"]["body_text"]


def model_valid(name: str, data: dict) -> bool:
    try:
        getattr(m, name).model_validate_json(json.dumps(data))
    except ValidationError:
        return False
    return True


def over(raw: bytes, **kwargs) -> str:
    with pytest.raises(parser.LimitExceeded) as caught:
        parser.derive_email(raw, **kwargs)
    return caught.value.limit


# --- Decoding ----------------------------------------------------------------


def test_only_crlf_changes():
    parsed = parser.derive_email(mail(b"  40 studs \r\n\r\n x\ry  \r\n\r\n"))
    assert parsed.body_text == "  40 studs \n\n x\ry  \n\n"


def test_uni003_encoded_words_quoted_printable_and_combining_marks():
    raw = (FIXTURES / "encoded-unicode.eml").read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    parsed = parser.derive_email(raw)
    assert parsed.sender.name == "José Synthetic"
    assert parsed.subject == "Need \U0001fab5 lumber"
    assert "café pine" in parsed.body_text  # not composed
    assert parsed.body_text.startswith("  Need \U0001fab5 40")
    assert hashlib.sha256(raw).hexdigest() == before


@pytest.mark.parametrize(
    "headers,body,expected",
    [
        (b"Content-Type: text/plain; charset=iso-8859-1\r\n", b"caf\xe9", "café"),
        (b"Content-Transfer-Encoding: base64\r\n", b"NDAgc3R1ZHM=", "40 studs"),
        (b"", "40 études".encode(), "40 études"),
    ],
)
def test_declared_encodings(headers, body, expected):
    assert parser.derive_email(mail(body, headers)).body_text == expected


def test_reply_headers_and_recipients():
    parsed = fixture("reply-quoted.eml")
    assert parsed.thread.in_reply_to == ["<synthetic-0001@example.test>"]
    assert parsed.thread.references == ["<synthetic-0001@example.test>"]
    assert [p.address for p in parsed.recipients] == ["orders@example-yard.test"]


def test_att001_html_is_converted_to_inert_text_and_flagged():
    parsed = fixture("html-only.eml")
    assert parsed.body_source == "text_html_derived"
    for hidden in ("alert", "approve", "color", "tracker", "onclick", "<"):
        assert hidden not in parsed.body_text
    assert "Need 40 pieces of 2x6x12" in parsed.body_text
    quoted = parsed.body_text[parsed.quoted_spans[0].start : parsed.quoted_spans[0].end]
    assert "Earlier: 20 pieces" in quoted and "Need 40" not in quoted
    assert grounding.Source.from_parsed(COMMUNICATION, parsed).html_derived


def test_plain_text_is_preferred_and_its_html_twin_is_not_an_attachment():
    raw = mail(
        b"--b\r\nContent-Type: text/html\r\n\r\n<p>HTML 99</p>\r\n"
        b"--b\r\nContent-Type: text/plain\r\n\r\nPLAIN 40\r\n--b--\r\n",
        b"Content-Type: multipart/alternative; boundary=b\r\n",
    )
    parsed = parser.derive_email(raw)
    assert (parsed.body_text, parsed.body_source) == ("PLAIN 40", "text_plain")
    assert parsed.attachments == []


def test_src003_att003_attachments_are_derived_and_never_processed():
    parsed = fixture("attachments-inline.eml")
    assert parsed.body_text == "See attached lumber list for the Smith job."
    names = [(a.filename, a.disposition, a.size_bytes) for a in parsed.attachments]
    assert names == [("logo.png", "inline", 15), ("invoice.pdf.exe", "attachment", 15)]
    assert parsed.attachments[1].sha256 == hashlib.sha256(b"synthetic-bytes").hexdigest()
    assert {a.processing for a in parsed.attachments} == {"not_processed"}
    assert parsed.attachments[0].content_id == "<logo@example.test>"


def test_attached_message_is_not_read_as_the_body():
    raw = mail(
        b"--b\r\nContent-Type: text/plain\r\n\r\nouter\r\n"
        b"--b\r\nContent-Type: message/rfc822\r\n\r\n"
        b"From: x@example.test\r\nContent-Type: text/plain\r\n\r\ninner 99\r\n--b--\r\n",
        b"Content-Type: multipart/mixed; boundary=b\r\n",
    )
    parsed = parser.derive_email(raw)
    assert parsed.body_text == "outer"
    assert [a.media_type for a in parsed.attachments] == ["message/rfc822"]


def test_a_second_text_part_is_listed_not_merged():
    raw = mail(
        b"--b\r\nContent-Type: text/plain\r\n\r\nfirst\r\n"
        b"--b\r\nContent-Type: text/plain\r\n\r\nsecond\r\n--b--\r\n",
        b"Content-Type: multipart/mixed; boundary=b\r\n",
    )
    parsed = parser.derive_email(raw)
    assert parsed.body_text == "first" and len(parsed.attachments) == 1


# --- Quoted history ----------------------------------------------------------


def quoted(body: str) -> list[str]:
    return [body[s:e] for s, e in parser.find_quoted_spans(body)]


@pytest.mark.parametrize(
    "body,history",
    [
        ("new\n> old\nmore new", ["> old"]),
        ("new\nOn Tue, A wrote:\n> old\nbelow", ["On Tue, A wrote:\n> old"]),
        ("new\nOn Tue, A wrote:\nold\nolder", ["On Tue, A wrote:\nold\nolder"]),
        ("new\n-----Original Message-----\nold", ["-----Original Message-----\nold"]),
        (
            "fyi\n---------- Forwarded message ---------\nold",
            ["---------- Forwarded message ---------\nold"],
        ),
        ("new\nBegin forwarded message:\nold", ["Begin forwarded message:\nold"]),
        (
            "new\nFrom: A <a@example.test>\nSent: Monday\nold",
            ["From: A <a@example.test>\nSent: Monday\nold"],
        ),
        ("From: the barn we need 20", []),
        ("no history here", []),
    ],
)
def test_quoted_and_forwarded_history(body, history):
    assert quoted(body) == history


# --- Unreadable mail is preserved as failed, never partly parsed ------------


@pytest.mark.parametrize(
    "raw",
    [
        (FIXTURES / "unparseable-charset.eml").read_bytes(),
        mail(b"\xff\xfe\xfa", b"Content-Type: text/plain; charset=utf-8\r\n"),
        mail(b"abc", b"Content-Transfer-Encoding: base64\r\n"),
        mail(b"!!!!", b"Content-Transfer-Encoding: base64\r\n"),
        mail(b"x", b"Content-Transfer-Encoding: x-synthetic\r\n"),
        mail(b"x", b"Content-Type: multipart/mixed; boundary=zz\r\n"),
        mail(b"x", b"Content-Type: multipart/mixed\r\n"),
        mail(b"x\x00y"),
        b"To: orders@example-yard.test\r\n\r\nno sender",
        b"\x00\x01\x02\x03",
        b"",
    ],
    ids=[
        "charset", "bytes", "base64-padding", "base64-chars", "transfer", "boundary",
        "no-boundary", "nul", "no-from", "garbage", "empty",
    ],
)
def test_unreadable_mail_fails_closed(raw):
    parsed = parser.derive_email(raw)
    assert parsed.parse_status == "failed"
    assert parsed.body_text is None and parsed.sender is None and parsed.attachments is None
    assert parser.content_fingerprint(raw, parsed) == hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        grounding.Source.from_parsed(COMMUNICATION, parsed)


# --- Limits (ATT-002) --------------------------------------------------------


def sized(total: int) -> bytes:
    start = mail(
        b"--b\r\nContent-Type: text/plain\r\n\r\n40 studs\r\n"
        b"--b\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"Content-Type: multipart/mixed; boundary=b\r\n",
    )
    end = b"\r\n--b--\r\n"
    fill = total - len(start) - len(end)
    block = b"A" * 998 + b"\r\n"
    padding = (block * (fill // len(block) + 1))[:fill]
    return start + padding + end


def test_raw_size_limit_is_exact():
    exact = sized(m.Limits.RAW_EMAIL_BYTES)
    assert len(exact) == 25_000_000
    assert parser.derive_email(exact, clock=lambda: 0).parse_status == "parsed"
    assert over(exact + b"x") == "raw_bytes"


def test_body_limit_is_exact():
    limit = m.Limits.BODY_CHARS
    assert len(parser.derive_email(mail(b"x" * limit)).body_text) == limit
    assert over(mail(b"x" * (limit + 1))) == "body_chars"


def test_body_limit_counts_code_points_not_bytes():
    body = ("é" * m.Limits.BODY_CHARS).encode()
    parsed = parser.derive_email(mail(body, b"Content-Type: text/plain; charset=utf-8\r\n"))
    assert len(parsed.body_text) == m.Limits.BODY_CHARS


@pytest.mark.parametrize("ending", [b"", b"\r\n"], ids=["no-final-newline", "final-newline"])
def test_u16_body_line_limit_is_exact(ending):
    limit = m.Limits.EMAIL_BODY_LINES

    def body(lines: int) -> bytes:
        return b"\r\n".join([b"x"] * lines) + ending

    parsed = parser.derive_email(mail(body(limit)))
    assert parsed.parse_status == "parsed" and parsed.body_text.count("x") == limit
    assert over(mail(body(limit + 1))) == "body_lines"


def test_u16_blank_and_quoted_lines_count():
    limit = m.Limits.EMAIL_BODY_LINES
    assert over(mail(b"\r\n" * limit + b"x")) == "body_lines"
    assert over(mail(b"> old\r\n" * limit + b"x")) == "body_lines"


def test_u16_html_derived_text_obeys_the_line_limit():
    def html(rows: int) -> bytes:
        return mail(b"<p>x</p>" * rows, b"Content-Type: text/html\r\n")

    limit = m.Limits.EMAIL_BODY_LINES
    assert parser.derive_email(html(limit)).parse_status == "parsed"
    assert over(html(limit + 1)) == "body_lines"


def test_u16_oversized_line_counts_are_refused_before_history_detection(monkeypatch):
    def unreachable(body):
        raise AssertionError("quoted history was searched in an over-limit body")

    monkeypatch.setattr(parser, "find_quoted_spans", unreachable)
    assert over(mail(b"\r\n" * 40_000 + b"x")) == "body_lines"


def test_u16_parsed_content_cannot_hold_more_lines():
    limit = m.Limits.EMAIL_BODY_LINES
    data = parser.derive_email(mail(b"x")).model_dump(mode="json")
    for text, valid in (
        ("x\n" * limit, True),
        ("x\n" * limit + "x", False),
        ("\n" * (limit + 1), False),
    ):
        payload = {**data, "body_text": text}
        assert model_valid("ParsedContent", payload) is valid
        assert Draft202012Validator(BODY_TEXT_SCHEMA).is_valid(text) is valid


def test_material_lines_and_email_lines_are_separate_limits():
    assert (m.Limits.EMAIL_BODY_LINES, m.Limits.MATERIAL_LINES) == (500, 500)
    assert not hasattr(m.Limits, "LINES")


def test_header_limit():
    def with_header(size: int) -> bytes:
        folded = b"X-Pad: " + (b"a" * 900 + b"\r\n ") * (size // 903) + b"a\r\n"
        return mail(headers=folded)

    assert parser.derive_email(with_header(250_000)).parse_status == "parsed"
    assert over(with_header(260_000)) == "header_bytes"


def attachments(count: int) -> bytes:
    parts = b"--b\r\nContent-Type: text/plain\r\n\r\nx\r\n"
    parts += b"--b\r\nContent-Type: application/pdf\r\n\r\ny\r\n" * count
    return mail(parts + b"--b--\r\n", b"Content-Type: multipart/mixed; boundary=b\r\n")


def test_attachment_limit():
    assert len(parser.derive_email(attachments(100)).attachments) == 100
    assert over(attachments(101)) == "attachments"


def wrapped(wrappers: int, extra: int) -> bytes:
    """Root, one text part, `wrappers` pairs of container and leaf, `extra` leaves."""
    parts = b"--r\r\nContent-Type: text/plain\r\n\r\nx\r\n"
    for i in range(wrappers):
        parts += (
            f"--r\r\nContent-Type: multipart/mixed; boundary=w{i}x\r\n\r\n"
            f"--w{i}x\r\nContent-Type: application/pdf\r\n\r\ny\r\n--w{i}x--\r\n"
        ).encode()
    parts += b"--r\r\nContent-Type: application/pdf\r\n\r\ny\r\n" * extra
    return mail(parts + b"--r--\r\n", b"Content-Type: multipart/mixed; boundary=r\r\n")


def test_mime_part_limit():
    assert parser.derive_email(wrapped(99, 0)).parse_status == "parsed"  # 200 parts
    assert over(wrapped(99, 1)) == "mime_parts"


def nested(depth: int) -> bytes:
    """A text part at the given depth; the root message is depth 1."""
    inner = b"Content-Type: text/plain\r\n\r\nx\r\n"
    for i in range(depth - 1):
        boundary = f"n{i}x".encode()
        inner = (
            b"Content-Type: multipart/mixed; boundary=" + boundary + b"\r\n\r\n--"
            + boundary + b"\r\n" + inner + b"\r\n--" + boundary + b"--\r\n"
        )
    return HEAD + inner


def test_mime_depth_limit():
    assert parser.derive_email(nested(20)).parse_status == "parsed"
    assert over(nested(21)) == "mime_depth"


def test_very_deep_nesting_is_a_limit_not_a_crash():
    assert over(nested(1500)) in {"mime_depth", "mime_parts"}


def test_parse_time_limit_uses_the_injected_clock():
    ticks = iter([0.0, 31.0, 62.0, 93.0, 124.0])
    assert over(mail(), clock=lambda: next(ticks)) == "parse_seconds"
    assert parser.derive_email(mail(), clock=lambda: 0.0).parse_status == "parsed"


def test_a_long_subject_inside_the_header_limit_is_kept_whole():
    subject = " ".join(["studs"] * 2000)
    folded = "\r\n ".join(["studs"] * 2000)
    raw = f"From: a@example.test\r\nSubject: {folded}\r\n\r\nbody".encode()
    parsed = parser.derive_email(raw)
    assert parsed.parse_status == "parsed" and parsed.subject == subject


# --- Identity and determinism ------------------------------------------------


def test_fingerprint_ignores_transport_headers_only():
    def fingerprint(raw: bytes) -> str:
        return parser.content_fingerprint(raw, parser.derive_email(raw))

    base = fingerprint(mail())
    assert fingerprint(mail(headers=b"Received: by relay.example.test\r\n")) == base
    assert fingerprint(mail(b"41 studs")) != base
    assert fingerprint(mail(headers=b"Subject: other\r\n")) != base


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.eml")), ids=lambda p: p.name)
def test_parsing_is_deterministic_and_versioned(path):
    first, second = fixture(path.name), fixture(path.name)
    assert first == second and first.parser_version == "email-derive-1"
