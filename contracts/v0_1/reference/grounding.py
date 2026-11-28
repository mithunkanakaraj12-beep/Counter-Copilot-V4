"""Turn a model proposal into a grounded proposal.

Two outcomes only:

* structural failure: the whole run is rejected (StructuralRejection);
* otherwise every proposed value is checked against the source text. A value the
  text does not support becomes 'ambiguous' with the evidence kept. The function
  never creates a value, upgrades a state or invents a candidate.

Pure and deterministic. Word lists are versioned in ``lexicon``. Passing these
checks proves that wording exists, not that the model understood it, and nothing
proves that every requested line was found: an employee reviews the original.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
from uuid import UUID

from pydantic import ValidationError

import models as m
from reference import lexicon, values

GROUNDING_VERSION = "ground-1"


class StructuralRejection(Exception):
    def __init__(self, failures: list[m.StructuralFailure]):
        super().__init__(", ".join(sorted({f.code for f in failures})))
        self.failures = failures


@dataclass(frozen=True)
class Source:
    communication_id: UUID
    subject: str | None
    body_text: str
    quoted_spans: tuple[tuple[int, int], ...] = ()
    html_derived: bool = False

    @classmethod
    def from_parsed(cls, communication_id: UUID, parsed: m.ParsedContent) -> Source:
        if parsed.parse_status != "parsed":
            raise ValueError("a message that failed to parse is never sent to extraction")
        return cls(
            communication_id=communication_id,
            subject=parsed.subject,
            body_text=parsed.body_text,
            quoted_spans=tuple((s.start, s.end) for s in parsed.quoted_spans),
            html_derived=parsed.body_source == "text_html_derived",
        )


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def _pointer(location: tuple) -> str:
    return "".join(f"/{str(p).replace('~', '~0').replace('/', '~1')}" for p in location)


def parse_proposal(raw: str | bytes | dict) -> m.ExtractionProposal:
    """Validate shape. Raises StructuralRejection, never returns a partial result."""
    try:
        if isinstance(raw, (str, bytes)):
            return m.ExtractionProposal.model_validate_json(raw)
        return m.ExtractionProposal.model_validate_json(json.dumps(raw))
    except ValidationError as error:
        failures = []
        for item in error.errors(include_url=False, include_input=False):
            location = item["loc"]
            if item["type"] == "extra_forbidden":
                code = "unknown_key"
            elif "non_request_with_lines" in item["msg"]:
                code = "non_request_with_lines"
            elif location and location[-1] == "source_evidence" and item["type"] in (
                "too_short",
                "missing",
            ):
                code = "line_without_source_evidence"
            else:
                code = "invalid_schema"
            failures.append(m.StructuralFailure(code=code, location=_pointer(location)))
        raise StructuralRejection(failures) from None


def _locate(
    source: Source, item: m.ProposedEvidence, location: str
) -> m.Evidence | m.StructuralFailure:
    text = source.subject if item.source == "subject" else source.body_text
    position = -1
    if text is not None:
        # Overlapping occurrences each count.
        for _ in range(item.occurrence + 1):
            position = text.find(item.quote, position + 1)
            if position < 0:
                break
    if position < 0:
        return m.StructuralFailure(code="quote_not_found", location=location)
    return m.Evidence(
        communication_id=source.communication_id,
        source=item.source,
        start=position,
        end=position + len(item.quote),
        quote=item.quote,
        role=item.role,
    )


# ---------------------------------------------------------------------------
# Reading the source text
# ---------------------------------------------------------------------------

_CHUNK = r"[^\s,;()\[\]{}<>|]+"
_TOKEN_RE = re.compile(rf"{_CHUNK}(?:(?<=[0-9]),(?=[0-9]{{3}}(?![0-9])){_CHUNK})*")
_CLAUSE_BREAK = re.compile(r"[.,;:!?()\n]")
_CORRECTION_RE = re.compile(
    r"(?<![\w'’])(?:"
    + "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in lexicon.CORRECTION_PHRASES)
    + r")(?![\w'’])",
    re.IGNORECASE,
)
_PLAIN_NUMBER = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?")
_FRACTION = re.compile(r"(?:[0-9]+-)?[0-9]+/[0-9]+")
_RANGE_TOKEN = re.compile(r"([0-9]+(?:\.[0-9]+)?)[-–—]([0-9]+(?:\.[0-9]+)?)")
_PHONE_PART = re.compile(r"[0-9]{3}-[0-9]{4}")
_COMPETING_VAGUE = lexicon.VAGUE_NUMBER_WORDS - {"a", "an"}
_NUMBER_WORDS = frozenset(
    {
        *lexicon.NUMBER_UNITS,
        *lexicon.NUMBER_TEENS,
        *lexicon.NUMBER_TENS,
        *lexicon.NUMBER_SCALES,
        *lexicon.SCALE_WORDS,
        "and",
    }
)
_HEDGE = (
    r"\([ \t]*(?:" + "|".join(lexicon.APPROXIMATE_PARENTHETICAL) + r")\.?[ \t]*\)"
)
# '(approx) 20' before the number, or '20 sheets (approx)' after at most two words.
_HEDGE_BEFORE = re.compile(_HEDGE + r"[ \t]*$", re.IGNORECASE)
_HEDGE_AFTER = re.compile(r"(?:[ \t]+[A-Za-z]+){0,2}[ \t]*" + _HEDGE, re.IGNORECASE)
_BY_OPERAND = re.compile(r"[0-9]{1,3}(?:/[0-9]+)?")


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    text: str

    @property
    def lower(self) -> str:
        return self.text.lower()


@dataclass
class Mention:
    """Something in the text that reads as a count."""

    start: int
    end: int
    readings: tuple[Fraction, ...]  # two for a range, none for a vague word
    flags: set[str] = field(default_factory=set)
    restated: tuple[Fraction, ...] = ()

    @property
    def countable(self) -> bool:
        return not self.flags & {"measurement", "identifier", "dimension_part", "fraction"}


@dataclass(frozen=True)
class Measure:
    """Something in the text that reads as a size."""

    start: int
    end: int
    text: str


def tokenize(text: str) -> list[Token]:
    tokens = []
    for match in _TOKEN_RE.finditer(text):
        start, end = match.start(), match.end()
        while start < end and text[start] in "*•\"'‘“":
            start += 1
        while start < end:
            last = text[end - 1]
            if last in ".:!?" or (
                last in "\"'’”" and not (end - 2 >= start and text[end - 2].isdigit())
            ):
                end -= 1
            else:
                break
        if start < end:
            tokens.append(Token(start, end, text[start:end]))
    return tokens


class Text:
    """One source string with everything grounding needs to know about it."""

    def __init__(self, value: str):
        self.value = value
        self.tokens = tokenize(value)
        self.starts = [t.start for t in self.tokens]
        self.mentions = self._mentions()
        self.units = self._phrases(lexicon.UNIT_SPELLINGS, 2)
        self.fulfillment = self._phrases(lexicon.FULFILLMENT_PHRASES, 2)
        self.treatments = self._phrases(lexicon.TREATMENT_TERMS, 2)
        self.measures = self._measures()
        self.corrections = [(c.start(), c.end()) for c in _CORRECTION_RE.finditer(value)]

    # -- neighbourhood ------------------------------------------------------

    def _joined(self, left: int, right: int) -> bool:
        """No clause punctuation between two token indexes."""
        gap = self.value[self.tokens[left].end : self.tokens[right].start]
        if self.tokens[left].lower in lexicon.ABBREVIATIONS and gap.startswith("."):
            gap = gap[1:]
        return not _CLAUSE_BREAK.search(gap)

    def before(self, index: int, count: int) -> list[str]:
        """Up to `count` earlier words in the same clause, nearest first."""
        words = []
        cursor = index
        while cursor > 0 and len(words) < count and self._joined(cursor - 1, cursor):
            cursor -= 1
            words.append(self.tokens[cursor].lower)
        return words

    def after(self, index: int, count: int) -> list[str]:
        words = []
        cursor = index
        while (
            cursor + 1 < len(self.tokens)
            and len(words) < count
            and self._joined(cursor, cursor + 1)
        ):
            cursor += 1
            words.append(self.tokens[cursor].lower)
        return words

    def token_index(self, position: int) -> int:
        """Index of the token containing or following `position`."""
        index = bisect_right(self.starts, position) - 1
        if index >= 0 and self.tokens[index].end > position:
            return index
        return index + 1

    def counted_noun(self, mention: Mention) -> str | None:
        """The word naming what is counted ('40 studs' -> 'stud'), if one follows."""
        following = self.after(self.token_index(mention.end - 1), 1)
        if not following or not following[0].isalpha():
            return None
        if following[0] in lexicon.NOT_A_COUNTED_NOUN:
            return None
        return following[0].removesuffix("s")

    def negated(self, position: int) -> bool:
        index = self.token_index(position)
        if index >= len(self.tokens):
            return False
        return any(w in lexicon.NEGATORS for w in self.before(index, lexicon.NEGATION_WINDOW))

    # -- numbers ------------------------------------------------------------

    def _mentions(self) -> list[Mention]:
        found: list[tuple[int, int, Mention]] = []  # first and last token index
        index = 0
        while index < len(self.tokens):
            run = self._number_words(index)
            if run:
                for first, last, value in run:
                    flags = set() if value is not None else {"unreadable_number"}
                    readings = () if value is None else (value,)
                    start, end = self.tokens[first].start, self.tokens[last].end
                    found.append((first, last, Mention(start, end, readings, flags)))
                index = run[-1][1] + 1
                continue
            mention = self._digit_number(self.tokens[index])
            if mention:
                found.append((index, index, mention))
            elif self.tokens[index].lower in lexicon.VAGUE_NUMBER_WORDS:
                token = self.tokens[index]
                found.append((index, index, Mention(token.start, token.end, (), {"vague"})))
            index += 1
        for first, last, mention in found:
            self._flag(first, last, mention)
        mentions = [item[2] for item in found]
        self._link(found)
        return mentions

    def _parts(self, index: int) -> list[str] | None:
        """The number words in one token, or None if it is not made of them."""
        parts = self.tokens[index].lower.split("-")
        return parts if all(p in _NUMBER_WORDS for p in parts) else None

    def _number_words(self, index: int) -> list[tuple[int, int, Fraction | None]]:
        """The run of number words starting here, as (first, last, value) segments.

        A run is read only when it is one or more well-formed cardinals joined by
        'and'. Anything else ('fifteen hundred', 'ten one') is returned whole with
        no value, so that no part of it can be taken as a quantity."""
        if self._parts(index) in (None, ["and"]):
            return []
        end = index
        while end + 1 < len(self.tokens):
            gap = self.value[self.tokens[end].end : self.tokens[end + 1].start]
            if gap.strip(" ") or self._parts(end + 1) is None:
                break
            end += 1
        while self.tokens[end].lower == "and":
            end -= 1
        segments: list[tuple[int, int, Fraction | None]] = []
        cursor = index
        while cursor <= end:
            words: list[str] = []
            best = None
            for position in range(cursor, end + 1):
                words.extend(self._parts(position))
                value = values.words_to_int(words)
                if value is not None:
                    best = (position, Fraction(value))
            if best is None:
                return [(index, end, None)]
            segments.append((cursor, best[0], best[1]))
            cursor = best[0] + 1
            if cursor <= end:
                if self.tokens[cursor].lower != "and":
                    return [(index, end, None)]
                cursor += 1
        return segments

    def _digit_number(self, token: Token) -> Mention | None:
        text, flags = token.lower, set()
        if text.startswith("~"):
            text, flags = text[1:], {"approximate"}
        elif text.startswith("+"):
            text, flags = text[1:], {"relative"}
        elif text.startswith("#"):
            text, flags = text[1:], {"identifier"}
        if text.endswith("ish"):
            text = text[:-3]
            flags.add("approximate")
        elif text.endswith("+"):
            text = text[:-1]
            flags.add("approximate")
        ranged = _RANGE_TOKEN.fullmatch(text)
        if ranged:
            if _PHONE_PART.fullmatch(text):
                flags.add("identifier")
            readings = (Fraction(ranged[1]), Fraction(ranged[2]))
            return Mention(token.start, token.end, readings, flags | {"range"})
        if _FRACTION.fullmatch(text):
            flags.add("fraction")
        elif not _PLAIN_NUMBER.fullmatch(text):
            return None
        try:
            return Mention(token.start, token.end, (values.parse_number(text),), flags)
        except values.UnreadableValue:
            return None

    def _flag(self, first: int, last: int, mention: Mention) -> None:
        previous = self.before(first, 2)
        following = self.after(last, 3)
        nearest_previous = self.tokens[first - 1].lower if first else ""
        nearest_next = self.tokens[last + 1].lower if last + 1 < len(self.tokens) else ""
        if any(w in lexicon.APPROXIMATE_BEFORE for w in previous):
            mention.flags.add("approximate")
        after_text = " ".join(following)
        # A trailing qualifier may follow the number directly or after one noun.
        tails = (after_text, " ".join(following[1:]))

        def trails(phrases) -> bool:
            return any(t == p or t.startswith(p + " ") for t in tails for p in phrases)

        if trails(lexicon.APPROXIMATE_AFTER):
            mention.flags.add("approximate")
        if _HEDGE_BEFORE.search(self.value, 0, mention.start) or _HEDGE_AFTER.match(
            self.value, mention.end
        ):
            mention.flags.add("approximate")
        leading = " " + " ".join(reversed(self.before(first, 2)))
        delivered = (
            previous[:1] == ["over"]
            and previous[1:2]
            and previous[1] in lexicon.DELIVERY_VERBS_BEFORE_OVER
        )
        bound_before = any(leading.endswith(" " + p) for p in lexicon.BOUND_BEFORE)
        if (bound_before and not delivered) or trails(lexicon.BOUND_AFTER):
            mention.flags.add("bounded")
        if any(w in lexicon.RELATIVE_BEFORE for w in previous):
            mention.flags.add("relative")
        if following and (
            following[0] in lexicon.RELATIVE_AFTER
            or (
                len(following) > 1
                and (following[0] in lexicon.UNIT_SPELLINGS or following[0].endswith("s"))
                and following[1] in lexicon.RELATIVE_AFTER
            )
        ):
            mention.flags.add("relative")
        if any(w in lexicon.NEGATORS for w in self.before(first, lexicon.NEGATION_WINDOW)):
            mention.flags.add("negated")
        if following[:1] and following[0] in lexicon.DOZEN_WORDS:
            mention.flags.add("vague")
        # '15 hundred', 'one and a half' and '2 1/2 sheets' are not read.
        if (
            (following[:1] and following[0] in lexicon.SCALE_WORDS)
            or any(
                after_text == p or after_text.startswith(p + " ") for p in lexicon.FRACTION_TAILS
            )
            or (following[:1] == ["and"] and following[1:] and _FRACTION.fullmatch(following[1]))
            or (
                len(following) > 1
                and _FRACTION.fullmatch(following[0])
                and following[1] in lexicon.UNIT_SPELLINGS
            )
        ):
            mention.flags.add("unreadable_number")
            mention.readings = ()
        if "x" in (nearest_previous, nearest_next) or "×" in (nearest_previous, nearest_next):
            mention.flags.add("dimension_part")
        if self._joined_by(first, last):
            mention.flags.add("dimension_part")
        if nearest_next in lexicon.MEASUREMENT_FOLLOWERS:
            mention.flags.add("measurement")
        if nearest_next in lexicon.PLURAL_LENGTH_WORDS and last + 2 < len(self.tokens):
            if self.tokens[last + 2].lower in lexicon.SIZE_ADJECTIVES:
                mention.flags.add("measurement")
        if nearest_previous.rstrip(".") in lexicon.IDENTIFIER_PREFIXES or nearest_previous == "#":
            mention.flags.add("identifier")
        if nearest_previous == "no" and first:
            gap = self.value[self.tokens[first - 1].end : self.tokens[first].start]
            if gap.startswith("."):  # "No. 2" is a grade or reference, not a count
                mention.flags.add("identifier")

    def _joined_by(self, first: int, last: int) -> bool:
        """'one by six': a number on both sides of 'by' is a size, not a count."""

        def operand(index: int) -> bool:
            if not 0 <= index < len(self.tokens):
                return False
            word = self.tokens[index].lower
            return bool(_BY_OPERAND.fullmatch(word)) or word.split("-")[0] in (
                _NUMBER_WORDS - {"and"}
            )

        def by(index: int) -> bool:
            return 0 <= index < len(self.tokens) and self.tokens[index].lower == "by"

        return (by(last + 1) and operand(last + 2)) or (by(first - 1) and operand(first - 2))

    def _link(self, found: list[tuple[int, int, Mention]]) -> None:
        """Ranges across tokens and restatements such as 'twenty (10)'."""
        for (_, left_last, left), (right_first, _, right) in zip(found, found[1:]):
            between = [t.lower for t in self.tokens[left_last + 1 : right_first]]
            gap = self.value[left.end : right.start].strip()
            joining = [w for w in between if w not in lexicon.APPROXIMATE_BEFORE]
            if (len(joining) == 1 and joining[0] in lexicon.RANGE_CONNECTORS) or (
                not between and gap in ("-", "–", "—")
            ):
                left.flags.add("range")
                right.flags.add("range")
                both = left.readings + right.readings
                left.readings = right.readings = both
            elif between == ["and"] and "between" in self.before(
                self.token_index(left.start), 2
            ):
                left.flags.add("range")
                right.flags.add("range")
                both = left.readings + right.readings
                left.readings = right.readings = both
            elif not between and gap == "(" and self.value[right.end :].lstrip().startswith(")"):
                if left.readings and right.readings and left.readings != right.readings:
                    pair = left.readings + right.readings
                    left.restated = right.restated = pair

    # -- words and sizes ----------------------------------------------------

    def _phrases(self, table: dict[str, str], longest: int) -> list[tuple[int, int, str]]:
        found = []
        index = 0
        while index < len(self.tokens):
            for size in range(longest, 0, -1):
                chunk = self.tokens[index : index + size]
                if len(chunk) < size:
                    continue
                if any(
                    self.value[a.end : b.start].strip(" ") for a, b in zip(chunk, chunk[1:])
                ):
                    continue
                phrase = " ".join(t.lower for t in chunk)
                if phrase in table:
                    found.append((chunk[0].start, chunk[-1].end, table[phrase]))
                    index += size - 1
                    break
            index += 1
        return found

    _SIZE = (
        r"(?:[ -]?(?:feet|footers?|foot|ft|inches|inch|in(?=\.))(?![A-Za-z])|['\"\u2032\u2033])"
    )
    _MEASURE_RE = re.compile(
        rf"(?<![A-Za-z0-9/.#_-]){values.NUMBER}{_SIZE}?"
        rf"(?: ?[xX\u00d7] ?{values.NUMBER}{_SIZE}?)*",
        re.IGNORECASE,
    )

    def _measures(self) -> list[Measure]:
        found = []
        for match in self._MEASURE_RE.finditer(self.value):
            text = match.group(0)
            sized = re.search(r"[xX×/]|[A-Za-z'\"′″]", text)
            if sized:
                found.append(Measure(match.start(), match.end(), text))
        return found


# ---------------------------------------------------------------------------
# Occurrences of written values
# ---------------------------------------------------------------------------


def _text_occurrences(text: str, value: str, start: int, end: int):
    """Positions where `value` stands as whole tokens inside text[start:end]."""
    position = text.find(value, start, end)
    while position >= 0:
        stop = position + len(value)
        left = text[position - 1] if position else ""
        right = text[stop] if stop < len(text) else ""
        left_ok = not (
            left.isalnum()
            or (left and left in "-_#/'’")
            or (left == "." and position > 1 and text[position - 2].isdigit())
        )
        right_ok = not (
            right.isalnum()
            or (right and right in "-_#/'’")
            or (right == "." and stop + 1 < len(text) and text[stop + 1].isdigit())
        )
        if left_ok and right_ok:
            yield position, stop
        position = text.find(value, position + 1, end)


_FOOT_INCH_MARKS = "'\"′″’”"


def _dimension_occurrences(text: str, value: str, start: int, end: int):
    """Positions where `value` is a complete written dimension.

    A trailing plural 's' is allowed ('2x4x8s'). A value cut out of a longer
    expression, or leaving a written unit behind, is not an occurrence."""
    position = text.find(value, start, end)
    while position >= 0:
        stop = position + len(value)
        left = text[position - 1] if position else ""
        head = text[max(0, position - 4) : position]
        left_ok = not (
            left.isalnum()
            or (left and left in "/.-#_" + _FOOT_INCH_MARKS)
            or re.search(r"[0-9'\"] ?[xX×] ?$", head)
        )
        tail = stop
        plural = re.match(r"(?:['’])?s(?![A-Za-z0-9/-])", text[stop:])
        if plural and value[-1].isdigit():
            tail += plural.end()
        rest = text[tail:]
        right = rest[:1]
        right_ok = not (
            right.isalnum()
            or (right and right in "/#_" + _FOOT_INCH_MARKS)
            or re.match(r"-[A-Za-z0-9]", rest)
            or re.match(r"\.[0-9]", rest)
            or re.match(r" ?[xX×] ?[0-9]", rest)
            or re.match(r" [0-9]+/[0-9]+", rest)
        )
        if right_ok and value[-1].isdigit():
            right_ok = not re.match(r"[ -](?:feet|foot|ft|inches|inch)\b", rest, re.IGNORECASE)
        if left_ok and right_ok:
            yield position, stop
        position = text.find(value, position + 1, end)


# ---------------------------------------------------------------------------
# Grounding one field
# ---------------------------------------------------------------------------


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


@dataclass(frozen=True)
class _Span:
    source: str
    start: int
    end: int


class _Run:
    def __init__(self, source: Source, run_id: UUID):
        self.source = source
        self.run_id = run_id
        self.texts = {"body_text": Text(source.body_text)}
        if source.subject is not None:
            self.texts["subject"] = Text(source.subject)

    def whole_texts(self) -> list[_Span]:
        return [_Span(kind, 0, len(text.value)) for kind, text in self.texts.items()]

    def quoted(self, kind: str, start: int, end: int) -> bool:
        return kind == "body_text" and any(
            _overlaps(start, end, s, e) for s, e in self.source.quoted_spans
        )

    @staticmethod
    def within_line(spans: list[m.Evidence] | None, kind: str, start: int, end: int) -> bool:
        return spans is None or any(
            s.source == kind and s.start <= start and end <= s.end for s in spans
        )

    def record(self, cls, evidence, *, state, value=None, candidates=(), reason=None, rules=()):
        return cls(
            state=state,
            value=value,
            candidates=list(candidates)[: m.Limits.CANDIDATES],
            ambiguity_reason=reason,
            evidence=evidence,
            extraction_run_id=self.run_id,
            grounding=m.Grounding(
                outcome="downgraded" if rules else "accepted", rule_codes=list(rules)
            ),
        )

    def downgrade(self, cls, evidence, reason: str, rule: str, candidates=()):
        candidates = list(candidates)
        if len(candidates) > m.Limits.CANDIDATES:
            candidates = []  # never show a partial set of readings
        return self.record(
            cls, evidence, state="ambiguous", reason=reason, rules=[rule], candidates=candidates
        )

    # -- shared shape -------------------------------------------------------

    def ground(self, cls, proposed, evidence, spans, reader):
        """`reader` supplies the type-specific checks."""
        if proposed.state == "missing":
            return self.record(cls, [], state="missing")
        if proposed.state == "ambiguous":
            reason = proposed.ambiguity_reason
            kept = list(proposed.candidates)
            if kept:
                blocked = reason in (
                    "negated",
                    "relative_quantity",
                    "number_word",
                    "quoted_history_only",
                    "separate_measurements",
                )
                grounded = None if blocked else reader.candidates(kept, evidence, spans)
                if grounded is None:
                    return self.record(
                        cls,
                        evidence,
                        state="ambiguous",
                        reason=reason,
                        rules=["candidates_removed"],
                    )
                kept = grounded
            return self.record(cls, evidence, state="ambiguous", reason=reason, candidates=kept)

        if any(e.role == "conflicts" for e in evidence):
            return self.downgrade(
                cls,
                evidence,
                "conflicting_statements",
                "conflicting_evidence",
                reader.readings(proposed.value, evidence),
            )
        failure = reader.check(proposed.value, evidence, spans)
        if isinstance(failure, tuple):
            reason, rule, candidates = failure
            return self.downgrade(cls, evidence, reason, rule, candidates)
        return self.record(cls, evidence, state="extracted", value=failure.value)


@dataclass(frozen=True)
class _Accepted:
    value: object


_UNSUPPORTED = ("unsupported_by_source", "not_in_evidence", ())
_OUTSIDE = ("unsupported_by_source", "outside_line_evidence", ())
_QUOTED = ("quoted_history_only", "quoted_only", ())
_NEGATED = ("negated", "negated", ())


class _Reader:
    def __init__(self, run: _Run):
        self.run = run

    def supported(self, evidence, spans, finder):
        """(inside, outside): matches inside supporting quotes, split by line span."""
        inside, outside = [], []
        for item in evidence:
            if item.role != "supports":
                continue
            for start, end, match in finder(self.run.texts[item.source], item.start, item.end):
                target = (
                    inside
                    if self.run.within_line(spans, item.source, start, end)
                    else outside
                )
                target.append((item.source, start, end, match))
        return inside, outside

    def line_matches(self, spans, finder):
        found = []
        for span in spans or []:
            for start, end, match in finder(self.run.texts[span.source], span.start, span.end):
                found.append((span.source, start, end, match))
        return found

    def has_correction(self, spans) -> bool:
        return any(
            span.start <= s and e <= span.end and not self.run.quoted(span.source, s, e)
            for span in spans or []
            for s, e in self.run.texts[span.source].corrections
        )

    def all_quoted(self, found) -> bool:
        return all(self.run.quoted(kind, start, end) for kind, start, end, _ in found)


class _Quantity(_Reader):
    def __init__(self, run: _Run):
        super().__init__(run)
        self.accepted_positions: set[tuple[str, int]] = set()

    @staticmethod
    def _find(text: Text, start: int, end: int):
        for mention in text.mentions:
            if start <= mention.start and mention.end <= end:
                yield mention.start, mention.end, mention

    @staticmethod
    def _canonical(readings) -> list[str] | None:
        try:
            return list(dict.fromkeys(values.canonical_decimal(r) for r in readings))
        except (values.InexactValue, values.UnreadableValue):
            return None

    def readings(self, value, evidence) -> list[str]:
        """Every competing total, or nothing if any of them cannot be read."""
        collected: list[Fraction] = []
        for item in evidence:
            mentions = [x for _, _, x in self._find(self.run.texts[item.source], item.start, item.end)]
            if any(self._unread(item.source, x) for x in mentions):
                return []
            countable = [x for x in mentions if x.countable and x.readings]
            if not countable:
                return []
            for x in countable:
                if x.flags & {"relative", "negated", "vague"}:
                    return []
                collected.extend(x.readings)
        return self._canonical(collected) or []

    def _word(self, kind: str, mention: Mention) -> str:
        return self.run.texts[kind].value[mention.start : mention.end].lower()

    def _unread(self, kind: str, mention: Mention) -> bool:
        """A competing amount that exists in the text but has no readable value."""
        if mention.readings:
            return False
        if "unreadable_number" in mention.flags:
            return mention.countable
        return self._word(kind, mention) in _COMPETING_VAGUE

    def candidates(self, proposed, evidence, spans) -> list[str] | None:
        found: set[Fraction] = set()
        for item in evidence:
            for start, end, x in self._find(self.run.texts[item.source], item.start, item.end):
                if self._unread(item.source, x):
                    return None
                in_scope = item.role == "conflicts" or self.run.within_line(
                    spans, item.source, start, end
                )
                if x.countable and in_scope and not x.flags & {"relative", "negated", "vague"}:
                    found.update(x.readings)
        if any(Fraction(c) not in found for c in proposed):
            return None
        return self._canonical(Fraction(c) for c in proposed)

    def check(self, value: str, evidence, spans):
        wanted = Fraction(value)

        def countable(x: Mention) -> bool:
            return x.countable and wanted in x.readings

        inside, outside = self.supported(evidence, spans, self._find)
        matches = [f for f in inside if countable(f[3])]
        if not matches:
            if any(countable(f[3]) for f in outside):
                return _OUTSIDE
            if any("vague" in f[3].flags for f in inside):
                return ("number_word", "vague_number", ())
            if any(
                f[3].countable and f[3].readings and self._canonical(f[3].readings) is None
                for f in inside
            ):
                return ("inexact_normalization", "inexact", ())
            return _UNSUPPORTED
        if self.all_quoted(matches):
            return _QUOTED
        flags = set().union(*(f[3].flags for f in matches))
        if "negated" in flags:
            return _NEGATED
        if "relative" in flags:
            return ("relative_quantity", "relative", ())
        if "vague" in flags:
            return ("number_word", "vague_number", ())
        if "range" in flags:
            ends = [r for f in matches if "range" in f[3].flags for r in f[3].readings]
            return ("range_given", "range", self._canonical(ends) or [])
        if "bounded" in flags:
            return ("range_given", "range", self._canonical([wanted]) or [])
        if "approximate" in flags:
            return ("approximate", "approximate", self._canonical([wanted]) or [])
        in_line = [
            f[3]
            for f in self.line_matches(spans, self._find)
            if f[3].countable and f[3].readings and not self.run.quoted(f[0], f[1], f[2])
        ]
        if self.has_correction(spans):
            if any(
                "unreadable_number" in f[3].flags
                and f[3].countable
                and not self.run.quoted(f[0], f[1], f[2])
                for f in self.line_matches(spans, self._find)
            ):
                return ("conflicting_statements", "correction_language", [])
            distinct = list(dict.fromkeys(r for x in in_line for r in x.readings))
            if len(distinct) > 1:
                usable = not any(x.flags & {"relative", "negated", "vague"} for x in in_line)
                return (
                    "conflicting_statements",
                    "correction_language",
                    (self._canonical(distinct) or []) if usable else [],
                )
        for f in matches:
            if f[3].restated:
                return (
                    "conflicting_statements",
                    "restated_differently",
                    self._canonical(f[3].restated) or [],
                )
        # '40 studs, 50 studs': two amounts of the same thing on one line.
        for f in matches:
            noun = self.run.texts[f[0]].counted_noun(f[3])
            if noun is None:
                continue
            amounts = [
                r
                for g in self.line_matches(spans, self._find)
                if g[3].countable
                and not self.run.quoted(g[0], g[1], g[2])
                and self.run.texts[g[0]].counted_noun(g[3]) == noun
                for r in g[3].readings
            ]
            distinct = list(dict.fromkeys(amounts))
            if len(distinct) > 1:
                return (
                    "conflicting_statements",
                    "restated_differently",
                    self._canonical(distinct) or [],
                )
        self.accepted_positions.update((f[0], f[1]) for f in matches)
        return _Accepted(values.canonical_decimal(wanted))


class _Phrase(_Reader):
    """Units and fulfillment: a closed value found through a versioned word list."""

    def __init__(self, run: _Run, attribute: str):
        super().__init__(run)
        self.attribute = attribute

    def _find(self, text: Text, start: int, end: int):
        for s, e, code in getattr(text, self.attribute):
            if start <= s and e <= end:
                yield s, e, code

    def readings(self, value, evidence) -> list[str]:
        collected = []
        for item in evidence:
            codes = [c for _, _, c in self._find(self.run.texts[item.source], item.start, item.end)]
            if not codes:
                return []
            collected.extend(codes)
        return list(dict.fromkeys(collected))

    def candidates(self, proposed, evidence, spans) -> list | None:
        found = {
            code
            for item in evidence
            for s, e, code in self._find(self.run.texts[item.source], item.start, item.end)
            if item.role == "conflicts" or self.run.within_line(spans, item.source, s, e)
        }
        return list(proposed) if all(c in found for c in proposed) else None

    def check(self, value, evidence, spans):
        inside, outside = self.supported(evidence, spans, self._find)
        matches = [f for f in inside if f[3] == value]
        if not matches:
            return _OUTSIDE if any(f[3] == value for f in outside) else _UNSUPPORTED
        if self.all_quoted(matches):
            return _QUOTED
        if any(self.run.texts[f[0]].negated(f[1]) for f in matches):
            return _NEGATED
        # Job details have no line span, so a correction anywhere in new text counts.
        scope = self.run.whole_texts() if spans is None else spans
        if self.has_correction(scope):
            named = self.line_matches(scope, self._find)
            if spans is None:
                named = [f for f in named if not self.run.quoted(f[0], f[1], f[2])]
            distinct = list(dict.fromkeys(f[3] for f in named))
            if len(distinct) > 1:
                return ("conflicting_statements", "correction_language", distinct)
        return _Accepted(value)


class _Text(_Reader):
    def __init__(self, run: _Run, negatable: bool, treatment: bool = False):
        super().__init__(run)
        self.negatable = negatable
        self.treatment = treatment

    @staticmethod
    def _finder(value: str):
        def find(text: Text, start: int, end: int):
            for s, e in _text_occurrences(text.value, value, start, end):
                yield s, e, value

        return find

    def readings(self, value, evidence) -> list:
        # Competing wording cannot be isolated reliably, so none is suggested.
        return []

    def candidates(self, proposed, evidence, spans) -> list | None:
        for value in proposed:
            found = value == value.strip() and any(
                item.role == "conflicts" or self.run.within_line(spans, item.source, s, e)
                for item in evidence
                for s, e, _ in self._finder(value)(
                    self.run.texts[item.source], item.start, item.end
                )
            )
            if not found:
                return None
        return list(proposed)

    def check(self, value: str, evidence, spans):
        if value != value.strip():
            return _UNSUPPORTED
        inside, outside = self.supported(evidence, spans, self._finder(value))
        if not inside:
            return _OUTSIDE if outside else _UNSUPPORTED
        if self.all_quoted(inside):
            return _QUOTED
        if self.negatable and any(self.run.texts[f[0]].negated(f[1]) for f in inside):
            return _NEGATED
        if self.treatment and self.has_correction(spans):
            named = {f[3] for f in self.line_matches(spans, self._treatments)}
            if len(named) > 1:
                return ("conflicting_statements", "correction_language", ())
        return _Accepted(value)

    @staticmethod
    def _treatments(text: Text, start: int, end: int):
        for s, e, kind in text.treatments:
            if start <= s and e <= end:
                yield s, e, kind


class _Dimension(_Reader):
    def __init__(self, run: _Run, quantity_positions: set[tuple[str, int]]):
        super().__init__(run)
        self.quantity_positions = quantity_positions

    @staticmethod
    def _finder(value: str):
        def find(text: Text, start: int, end: int):
            for s, e in _dimension_occurrences(text.value, value, start, end):
                yield s, e, value

        return find

    @staticmethod
    def _measures(text: Text, start: int, end: int):
        for measure in text.measures:
            if start <= measure.start and measure.end <= end:
                yield measure.start, measure.end, measure.text

    @staticmethod
    def _parse(value: str) -> m.Dimensions | None:
        try:
            return m.dimensions_from_text(value)
        except (values.InexactValue, values.UnreadableValue):
            return None

    def readings(self, value, evidence) -> list:
        collected: dict[str, m.Dimensions] = {}
        for item in evidence:
            found = list(self._measures(self.run.texts[item.source], item.start, item.end))
            if not found:
                return []
            for _, _, text in found:
                parsed = self._parse(text)
                if parsed is None:
                    return []
                collected[text] = parsed
        return list(collected.values())

    def candidates(self, proposed, evidence, spans) -> list | None:
        result = []
        for value in proposed:
            parsed = self._parse(value)
            found = parsed is not None and any(
                item.role == "conflicts" or self.run.within_line(spans, item.source, s, e)
                for item in evidence
                for s, e, _ in self._finder(value)(
                    self.run.texts[item.source], item.start, item.end
                )
            )
            if not found:
                return None
            result.append(parsed)
        return result

    def check(self, value: str, evidence, spans):
        inside, outside = self.supported(evidence, spans, self._finder(value))
        inexact = False
        parsed = None
        try:
            parsed = m.dimensions_from_text(value)
        except values.InexactValue:
            inexact = True
        except values.UnreadableValue:
            pass
        if parsed is None:
            if inexact and any(value in e.quote for e in evidence):
                return ("inexact_normalization", "inexact", ())
            if len(re.findall(r"[0-9]+(?:/[0-9]+)?", value)) > 1 and any(
                value in e.quote for e in evidence
            ):
                return ("separate_measurements", "separate_measurements", ())
            return ("unsupported_by_source", "unreadable_dimension", ())
        if not inside:
            return _OUTSIDE if outside else _UNSUPPORTED
        if self.all_quoted(inside):
            return _QUOTED
        if any(self.run.texts[f[0]].negated(f[1]) for f in inside):
            return _NEGATED
        others = [
            f
            for f in self.line_matches(spans, self._measures)
            if not any(f[0] == i[0] and _overlaps(f[1], f[2], i[1], i[2]) for i in inside)
            and (f[0], f[1]) not in self.quantity_positions
            and not self.run.quoted(f[0], f[1], f[2])
        ]
        if others and self.has_correction(spans):
            return (
                "conflicting_statements",
                "correction_language",
                self.readings(value, spans),
            )
        if others:
            return ("separate_measurements", "separate_measurements", ())
        # "92 5/8": a whole number before a fraction belongs to it unless it is the count.
        if "/" in parsed.components[0].raw.split("-")[0]:
            for kind, start, _, _ in inside:
                lead = re.search(r"([0-9]+) $", self.run.texts[kind].value[:start])
                if lead and (kind, lead.start(1)) not in self.quantity_positions:
                    return ("separate_measurements", "separate_measurements", ())
        return _Accepted(parsed)


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def _merged(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _evidence(run: _Run, kind: str, start: int, end: int) -> m.Evidence:
    text = run.texts[kind].value
    return m.Evidence(
        communication_id=run.source.communication_id,
        source=kind,
        start=start,
        end=end,
        quote=text[start:end],
        role="supports",
    )


def _warnings(run: _Run, lines: list[m.GroundedLine], job, jobs_evidence):
    warnings: list[m.GroundingWarning] = []

    def add(code: str, line_index: int | None, evidence: list[m.Evidence]) -> None:
        warnings.append(
            m.GroundingWarning(
                code=code, line_index=line_index, evidence=evidence[: m.Limits.EVIDENCE_ITEMS]
            )
        )

    cited: dict[str, list[tuple[int, int]]] = {"body_text": [], "subject": []}
    by_owner: list[tuple[int | None, list[m.Evidence]]] = []
    for index, line in enumerate(lines):
        items = list(line.source_evidence)
        items += [e for name in m.LINE_FIELDS for e in getattr(line, name).evidence]
        by_owner.append((index, items))
    by_owner.append((None, [e for name in m.JOB_FIELDS for e in getattr(job, name).evidence]))
    for _, items in by_owner:
        for e in items:
            cited[e.source].append((e.start, e.end))

    for index, items in by_owner:
        quoted = {
            (e.source, e.start, e.end): e
            for e in items
            if run.quoted(e.source, e.start, e.end)
        }
        if quoted:
            add("evidence_in_quoted_text", index, list(quoted.values()))

    # Correction wording, attributed to the first line whose source contains it.
    corrections: dict[int | None, list[m.Evidence]] = {}
    for kind, text in run.texts.items():
        for start, end in text.corrections:
            if run.quoted(kind, start, end):
                continue
            owner = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if run.within_line(line.source_evidence, kind, start, end)
                ),
                None,
            )
            corrections.setdefault(owner, []).append(_evidence(run, kind, start, end))
    for owner, items in corrections.items():
        add("possible_correction_language", owner, items)

    uncited: list[m.Evidence] = []
    for kind, text in run.texts.items():
        spans = _merged(cited[kind])
        starts = [s for s, _ in spans]
        for mention in text.mentions:
            readable = mention.readings or "unreadable_number" in mention.flags
            if not readable or not mention.countable:
                continue
            if run.quoted(kind, mention.start, mention.end):
                continue
            index = bisect_left(starts, mention.start + 1) - 1
            if index >= 0 and mention.end <= spans[index][1]:
                continue
            uncited.append(_evidence(run, kind, mention.start, mention.end))
    if uncited:
        add("uncited_quantity_text", None, uncited)

    # Lines whose source spans share characters.
    flat = sorted(
        (e.source, e.start, e.end, i)
        for i, line in enumerate(lines)
        for e in line.source_evidence
    )
    overlapping: dict[int, list[tuple[str, int, int]]] = {}
    active: list[tuple[str, int, int, int]] = []
    for kind, start, end, index in flat:
        active = [a for a in active if a[0] == kind and a[2] > start]
        for other_kind, other_start, other_end, other in active:
            if other != index:
                overlapping.setdefault(index, []).append((kind, start, end))
                overlapping.setdefault(other, []).append((other_kind, other_start, other_end))
        active.append((kind, start, end, index))
    for index in sorted(overlapping):
        add(
            "overlapping_line_evidence",
            index,
            [_evidence(run, *span) for span in dict.fromkeys(overlapping[index])],
        )

    if jobs_evidence:
        add("multiple_jobs_detected", None, jobs_evidence)
    if run.source.html_derived:
        add("html_derived_text", None, [])
    return warnings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_LINE_RECORDS = {
    "product": m.TextProposalRecord,
    "quantity": m.QuantityProposalRecord,
    "unit": m.UnitProposalRecord,
    "dimensions": m.DimensionsProposalRecord,
    "species": m.TextProposalRecord,
    "grade": m.TextProposalRecord,
    "treatment": m.TextProposalRecord,
}


def ground_proposal(
    source: Source, proposal: str | bytes | dict, extraction_run_id: UUID
) -> m.GroundedProposal:
    parsed = parse_proposal(proposal)
    failures: list[m.StructuralFailure] = []

    def locate(items, location: str) -> list[m.Evidence]:
        found = []
        for position, item in enumerate(items):
            result = _locate(source, item, f"{location}/{position}")
            if isinstance(result, m.StructuralFailure):
                failures.append(result)
            else:
                found.append(result)
        return found

    line_evidence = [
        (
            locate(line.source_evidence, f"/lines/{i}/source_evidence"),
            {
                name: locate(getattr(line, name).evidence, f"/lines/{i}/{name}/evidence")
                for name in m.LINE_FIELDS
            },
        )
        for i, line in enumerate(parsed.lines)
    ]
    job_evidence = {
        name: locate(
            getattr(parsed.job_details, name).evidence, f"/job_details/{name}/evidence"
        )
        for name in m.JOB_FIELDS
    }
    jobs_evidence = locate(parsed.multiple_jobs_evidence, "/multiple_jobs_evidence")
    if failures:
        raise StructuralRejection(failures)

    run = _Run(source, extraction_run_id)
    lines = []
    for proposed, (spans, evidence) in zip(parsed.lines, line_evidence):
        quantity = _Quantity(run)
        grounded = {
            "quantity": run.ground(
                m.QuantityProposalRecord,
                proposed.quantity,
                evidence["quantity"],
                spans,
                quantity,
            )
        }
        readers = {
            "unit": _Phrase(run, "units"),
            "dimensions": _Dimension(run, quantity.accepted_positions),
            "product": _Text(run, negatable=True),
            "species": _Text(run, negatable=True),
            "grade": _Text(run, negatable=True),
            "treatment": _Text(run, negatable=True, treatment=True),
        }
        for name, reader in readers.items():
            grounded[name] = run.ground(
                _LINE_RECORDS[name], getattr(proposed, name), evidence[name], spans, reader
            )
        lines.append(m.GroundedLine(source_evidence=spans, **grounded))

    job = {}
    for name in m.JOB_FIELDS:
        if name == "fulfillment_method":
            cls, reader = m.FulfillmentProposalRecord, _Phrase(run, "fulfillment")
        else:
            cls, reader = m.TextProposalRecord, _Text(run, negatable=False)
        job[name] = run.ground(
            cls, getattr(parsed.job_details, name), job_evidence[name], None, reader
        )
    job_details = m.GroundedJobDetails(**job)

    return m.GroundedProposal(
        schema_version="0.1",
        extraction_run_id=extraction_run_id,
        grounding_version=GROUNDING_VERSION,
        lexicon_version=lexicon.LEXICON_VERSION,
        classification=parsed.classification,
        lines=lines,
        job_details=job_details,
        warnings=_warnings(run, lines, job_details, jobs_evidence),
    )
