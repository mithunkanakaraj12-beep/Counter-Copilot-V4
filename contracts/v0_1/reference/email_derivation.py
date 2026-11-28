"""Versioned, deterministic derivation of parsed content from preserved email bytes.

The raw bytes stay the authority and are never modified. The only change made to
decoded text is CRLF to LF: no trimming and no Unicode normalization.

Pure: no network, filesystem or database. The time limit is checked cooperatively
between steps using the supplied clock; a service must also enforce it with a
worker it can stop.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from email import errors as email_errors
from email import policy
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser

import models as m

PARSER_VERSION = "email-derive-1"


class LimitExceeded(Exception):
    """The submission is over an approved limit: respond 413 and store nothing."""

    def __init__(self, limit: str):
        super().__init__(limit)
        self.limit = limit


class _Unreadable(Exception):
    """Within limits but not decodable: preserve it as failed_terminal / parse_failed."""


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


def _clean_header(raw: str) -> str:
    # The compat32 parser keeps undeclared 8-bit bytes as surrogates.
    try:
        return raw.encode("ascii", "surrogateescape").decode("utf-8")
    except UnicodeError as error:
        raise _Unreadable("header bytes") from error


def _decode_words(raw: str) -> str:
    """Unfold and decode RFC 2047 encoded words, strictly."""
    unfolded = re.sub(r"\r?\n(?=[ \t])", "", _clean_header(raw))
    try:
        parts = []
        for chunk, charset in decode_header(unfolded):
            if isinstance(chunk, str):
                parts.append(chunk)
            else:
                name = charset or "ascii"
                if name == "unknown-8bit":
                    name = "utf-8"
                codec = "raw-unicode-escape" if charset is None else name
                parts.append(chunk.decode(codec, "strict"))
        return "".join(parts)
    except (LookupError, UnicodeError, ValueError, email_errors.HeaderParseError) as error:
        raise _Unreadable("encoded header") from error


def _header(message: Message, name: str) -> str | None:
    raw = message.get(name)
    return None if raw is None else str(raw)


def _parties(message: Message, *names: str) -> list[m.EmailParty]:
    values = [_clean_header(str(v)) for n in names for v in message.get_all(n, [])]
    parties = []
    for display, address in getaddresses(values):
        if not address or "@" not in address or len(address) > 320:
            continue
        name = _decode_words(display) if display else None
        parties.append(m.EmailParty(name=name[:500] if name else None, address=address))
    return parties


def _message_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [i for i in re.findall(r"<[^<>\s]+>", _clean_header(raw)) if len(i) <= 998]


# ---------------------------------------------------------------------------
# MIME structure
# ---------------------------------------------------------------------------


def _walk(message: Message):
    """Yield (part_id, depth, part). The root is depth 1. Iterative on purpose."""
    stack = [("1", 1, message)]
    while stack:
        part_id, depth, part = stack.pop()
        yield part_id, depth, part
        if part.is_multipart():
            children = part.get_payload()
            for index in range(len(children), 0, -1):
                child_id = f"{part_id}.{index}"
                stack.append((child_id, depth + 1, children[index - 1]))


def _check_structure(message: Message) -> list[tuple[str, Message]]:
    leaves: list[tuple[str, Message]] = []
    parts = 0
    header_bytes = 0
    containers: set[int] = set()
    for part_id, depth, part in _walk(message):
        parts += 1
        if parts > m.Limits.MIME_PARTS:
            raise LimitExceeded("mime_parts")
        if depth > m.Limits.MIME_DEPTH:
            raise LimitExceeded("mime_depth")
        header_bytes += sum(
            len(str(k).encode("utf-8", "surrogateescape"))
            + len(str(v).encode("utf-8", "surrogateescape"))
            + 4
            for k, v in part.raw_items()
        )
        if header_bytes > m.Limits.HEADER_BYTES:
            raise LimitExceeded("header_bytes")
        inside_attached = any(part_id.startswith(f"{c}.") for c in containers)
        attached_message = part.get_content_type() == "message/rfc822"
        if attached_message and not inside_attached:
            containers.add(part_id)
            leaves.append((part_id, part))
        elif not part.is_multipart() and not inside_attached:
            leaves.append((part_id, part))
    return leaves


def _decoded_bytes(part: Message) -> bytes:
    if part.is_multipart():  # an attached message: informational digest only
        return b"".join(child.as_bytes() for child in part.get_payload())
    encoding = str(part.get("content-transfer-encoding", "")).strip().lower()
    if encoding not in ("", "7bit", "8bit", "binary", "base64", "quoted-printable"):
        raise _Unreadable("transfer encoding")
    payload = part.get_payload(decode=True)
    if payload is None:
        return b""
    if any(
        isinstance(d, (email_errors.InvalidBase64PaddingDefect,
                       email_errors.InvalidBase64CharactersDefect,
                       email_errors.InvalidBase64LengthDefect))
        for d in part.defects
    ):
        raise _Unreadable("base64")
    return payload


def _decoded_text(part: Message) -> str:
    charset = part.get_content_charset() or "us-ascii"
    data = _decoded_bytes(part)
    if charset in ("us-ascii", "ascii"):
        charset = "utf-8"  # undeclared 8-bit mail; strict UTF-8 is a superset
    try:
        text = data.decode(charset, "strict")
    except (LookupError, UnicodeError) as error:
        raise _Unreadable("charset") from error
    if "\x00" in text:
        raise _Unreadable("nul character")
    return text.replace("\r\n", "\n")


def _disposition(part: Message) -> str | None:
    value = part.get_content_disposition()
    return value if value in ("attachment", "inline") else None


def _filename(part: Message) -> str | None:
    name = part.get_filename()
    if name is None:
        return None
    return _decode_words(str(name))[:500]


# ---------------------------------------------------------------------------
# HTML and quoted history
# ---------------------------------------------------------------------------

_BLOCK_TAGS = frozenset(
    "address article blockquote br caption div dl dt dd footer h1 h2 h3 h4 h5 h6 "
    "header hr li ol p pre section table tr ul".split()
)
_SKIP_TAGS = frozenset("script style head title noscript template".split())


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.length = 0
        self.skip = 0
        self.quote_depth = 0
        self.quote_start = 0
        self.quotes: list[tuple[int, int]] = []

    def _add(self, text: str) -> None:
        self.parts.append(text)
        self.length += len(text)

    def _break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self._add("\n")

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if tag in _BLOCK_TAGS:
            self._break()
        if tag in ("td", "th"):
            self._add(" ")
        if tag == "blockquote":
            if self.quote_depth == 0:
                self.quote_start = self.length
            self.quote_depth += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "blockquote" and self.quote_depth:
            self.quote_depth -= 1
            if self.quote_depth == 0 and self.length > self.quote_start:
                self.quotes.append((self.quote_start, self.length))
        if tag in _BLOCK_TAGS:
            self._break()

    def handle_data(self, data):
        if not self.skip:
            self._add(data)

    def close(self):
        super().close()
        if self.quote_depth and self.length > self.quote_start:
            self.quotes.append((self.quote_start, self.length))


def html_to_text(html: str) -> tuple[str, list[tuple[int, int]]]:
    """Visible-ish text plus blockquote ranges. CSS hiding is not interpreted."""
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts), parser.quotes


# Everything after one of these lines is history.
_HISTORY_MARKERS = re.compile(
    r"^[ \t]*(?:-{2,}[ \t]*(?:original message|forwarded message)[ \t]*-{2,}"
    r"|begin forwarded message:)",
    re.IGNORECASE,
)
_ATTRIBUTION = re.compile(r"^[ \t]*On\b.{0,300}\bwrote:[ \t]*$", re.IGNORECASE)
_OUTLOOK_FROM = re.compile(r"^[ \t]*From:[ \t]+\S", re.IGNORECASE)
_OUTLOOK_NEXT = re.compile(r"^[ \t]*(?:Sent|Date):[ \t]+\S", re.IGNORECASE)


def find_quoted_spans(body: str) -> list[tuple[int, int]]:
    """Heuristic: '>' lines, reply attributions and forwarded or original blocks."""
    lines = body.split("\n")
    starts, position = [], 0
    for line in lines:
        starts.append(position)
        position += len(line) + 1

    def end_of(index: int) -> int:
        return starts[index] + len(lines[index])

    spans: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        following = [i for i in range(index + 1, len(lines)) if lines[i].strip()][:1]
        outlook = bool(_OUTLOOK_FROM.match(line)) and any(
            _OUTLOOK_NEXT.match(other) for other in lines[index + 1 : index + 4]
        )
        attribution = bool(_ATTRIBUTION.match(line))
        quoted_next = bool(following) and lines[following[0]].lstrip().startswith(">")
        if _HISTORY_MARKERS.match(line) or outlook or (attribution and not quoted_next):
            spans.append((starts[index], len(body)))
            break
        if line.lstrip().startswith(">") or attribution:
            spans.append((starts[index], end_of(index)))

    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _failed() -> m.ParsedContent:
    return m.ParsedContent(
        parser_version=PARSER_VERSION,
        parse_status="failed",
        sender=None,
        recipients=None,
        subject=None,
        body_text=None,
        body_source=None,
        thread=None,
        attachments=None,
        quoted_spans=None,
    )


def derive_email(
    raw: bytes, clock: Callable[[], float] = time.monotonic
) -> m.ParsedContent:
    """Parsed content, a 'failed' result, or LimitExceeded. Never a partial result."""
    if len(raw) > m.Limits.RAW_EMAIL_BYTES:
        raise LimitExceeded("raw_bytes")
    started = clock()

    def check_time() -> None:
        if clock() - started > m.Limits.PARSE_SECONDS:
            raise LimitExceeded("parse_seconds")

    head_end = re.search(rb"\r?\n\r?\n", raw)
    if (head_end.start() if head_end else len(raw)) > m.Limits.HEADER_BYTES:
        raise LimitExceeded("header_bytes")
    try:
        message = BytesParser(policy=policy.compat32).parsebytes(raw)
        check_time()
        leaves = _check_structure(message)
        check_time()
        content = _content(message, leaves)
        check_time()
        return content
    except LimitExceeded:
        raise
    except RecursionError as error:
        raise LimitExceeded("mime_depth") from error
    except _Unreadable:
        check_time()
        return _failed()
    except Exception:  # any other parser failure on hostile input
        check_time()
        return _failed()


def _content(message: Message, leaves: list[tuple[str, Message]]) -> m.ParsedContent:
    if any(
        isinstance(d, (email_errors.NoBoundaryInMultipartDefect,
                       email_errors.StartBoundaryNotFoundDefect))
        for _, _, part in _walk(message)
        for d in part.defects
    ):
        raise _Unreadable("multipart boundary")
    senders = _parties(message, "From")
    if not senders:
        raise _Unreadable("no sender")

    def inline_text(part: Message, subtype: str) -> bool:
        return (
            part.get_content_type() == f"text/{subtype}"
            and _disposition(part) != "attachment"
            and part.get_filename() is None
        )

    plain = next(((i, p) for i, p in leaves if inline_text(p, "plain")), None)
    html = next(((i, p) for i, p in leaves if inline_text(p, "html")), None)

    # The HTML twin of a plain body is an alternative rendering, not an attachment.
    alternatives: set[str] = set()
    for part_id, _, part in _walk(message):
        if part.get_content_type() == "multipart/alternative":
            inside = [i for i, p in leaves if i.startswith(f"{part_id}.")
                      and (inline_text(p, "plain") or inline_text(p, "html"))]
            chosen = plain or html
            if chosen and chosen[0].startswith(f"{part_id}."):
                alternatives.update(inside)

    body, body_source, quoted = "", "none", []
    body_id = None
    if plain:
        body_id, body, body_source = plain[0], _decoded_text(plain[1]), "text_plain"
        if len(body) <= m.Limits.BODY_CHARS:
            quoted = find_quoted_spans(body)
    elif html:
        source = _decoded_text(html[1])
        body, blockquotes = html_to_text(source)
        body_id, body_source = html[0], "text_html_derived"
        if len(body) <= m.Limits.BODY_CHARS:
            quoted = _merge(blockquotes + find_quoted_spans(body))
    if len(body) > m.Limits.BODY_CHARS:
        raise LimitExceeded("body_chars")

    attachments = []
    for part_id, part in leaves:
        if part_id == body_id or part_id in alternatives:
            continue
        data = _decoded_bytes(part)
        content_id = _header(part, "Content-ID")
        attachments.append(
            m.AttachmentMetadata(
                part_id=part_id,
                filename=_filename(part),
                media_type=part.get_content_type()[:200],
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                disposition=_disposition(part),
                content_id=_clean_header(content_id)[:998] if content_id else None,
                processing="not_processed",
            )
        )
        if len(attachments) > m.Limits.ATTACHMENTS:
            raise LimitExceeded("attachments")

    subject = _header(message, "Subject")
    if subject is not None:
        subject = _decode_words(subject)
    own_ids = _message_ids(_header(message, "Message-ID"))
    return m.ParsedContent(
        parser_version=PARSER_VERSION,
        parse_status="parsed",
        sender=senders[0],
        recipients=_parties(message, "To", "Cc")[:1000],
        subject=subject,
        body_text=body,
        body_source=body_source,
        thread=m.EmailThread(
            rfc_message_id=own_ids[0] if own_ids else None,
            in_reply_to=_message_ids(_header(message, "In-Reply-To"))[:100],
            references=_message_ids(_header(message, "References"))[-100:],
        ),
        attachments=attachments,
        quoted_spans=[m.TextSpan(start=s, end=e) for s, e in quoted],
    )


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def content_fingerprint(raw: bytes, parsed: m.ParsedContent) -> str:
    """Decides 'identical redelivery' for one message identity.

    Added transport headers do not change it. An unreadable message is compared
    byte for byte."""
    if parsed.parse_status == "failed":
        return hashlib.sha256(raw).hexdigest()
    material = {
        "sender": parsed.sender.address,
        "recipients": sorted(p.address for p in parsed.recipients),
        "subject": parsed.subject,
        "body_text": parsed.body_text,
        "attachments": sorted(a.sha256 for a in parsed.attachments),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
