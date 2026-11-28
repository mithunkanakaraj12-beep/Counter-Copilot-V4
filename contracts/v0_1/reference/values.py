"""Exact reading of written numbers and dimensions.

Arithmetic uses fractions, so nothing is rounded. This module imports no contract
model: ``models`` uses it to check that stored magnitudes follow from the wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from reference import lexicon

MAX_INTEGER_DIGITS = 9
MAX_DECIMAL_PLACES = 6
MAX_DIMENSION_COMPONENTS = 8

# Order matters: mixed number, fraction, grouped thousands, plain decimal.
NUMBER = r"(?:[0-9]+-[0-9]+/[0-9]+|[0-9]+/[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
_NUMBER_RE = re.compile(NUMBER)

_UNIT = r"(?:feet|foot|ft\.?|inches|inch|in\.?|'|\"|′|″|’|”)"
_COMPONENT_RE = re.compile(
    rf"(?P<number>{NUMBER})(?:(?:[ -])?(?P<unit>{_UNIT}))?", re.IGNORECASE
)
_SEPARATOR_RE = re.compile(r" ?[xX×] ?")


class InexactValue(ValueError):
    """The wording is a number that cannot be stored exactly."""


class UnreadableValue(ValueError):
    """The wording is not a number or dimension this contract understands."""


def parse_number(text: str) -> Fraction:
    """Exact value of '40', '1,000', '2.5', '7/16' or '92-5/8'."""
    if not _NUMBER_RE.fullmatch(text):
        raise UnreadableValue(text)
    plain = text.replace(",", "")
    try:
        if "-" in plain:
            whole, part = plain.split("-", 1)
            return Fraction(int(whole)) + Fraction(part)
        return Fraction(plain)
    except (ValueError, ZeroDivisionError) as error:
        raise UnreadableValue(text) from error


def canonical_decimal(value: Fraction) -> str:
    """Shortest decimal string: no separators, exponent or trailing zeros."""
    if value <= 0:
        raise UnreadableValue("value must be greater than zero")
    scaled = value * 10**MAX_DECIMAL_PLACES
    if scaled.denominator != 1:
        raise InexactValue("more than six decimal places")
    whole, rest = divmod(scaled.numerator, 10**MAX_DECIMAL_PLACES)
    if len(str(whole)) > MAX_INTEGER_DIGITS:
        raise InexactValue("more than nine integer digits")
    decimals = str(rest).rjust(MAX_DECIMAL_PLACES, "0").rstrip("0")
    return f"{whole}.{decimals}" if decimals else str(whole)


@dataclass(frozen=True)
class Component:
    raw: str
    magnitude: str
    unit: str | None  # "ft", "in" or None when unwritten


def parse_dimensions(text: str) -> list[Component]:
    """Read one contiguous written dimension, keeping the written order.

    No axis is assigned and no unit is assumed or converted.
    """
    components: list[Component] = []
    position = 0
    while True:
        match = _COMPONENT_RE.match(text, position)
        if not match:
            raise UnreadableValue(text)
        unit = match.group("unit")
        components.append(
            Component(
                raw=match.group(0),
                magnitude=canonical_decimal(parse_number(match.group("number"))),
                unit=lexicon.DIMENSION_UNITS[unit.lower()] if unit else None,
            )
        )
        if len(components) > MAX_DIMENSION_COMPONENTS:
            raise UnreadableValue("too many components")
        position = match.end()
        if position == len(text):
            return components
        separator = _SEPARATOR_RE.match(text, position)
        if not separator:
            raise UnreadableValue(text)
        position = separator.end()


def words_to_int(words: list[str]) -> int | None:
    """Value of an English cardinal such as ['one', 'hundred', 'and', 'fifty'].

    Returns None unless the whole list is one well-formed number below one million.
    """
    words = [w.lower() for w in words]
    if not words:
        return None

    def below_hundred(i: int) -> tuple[int, int] | None:
        if i >= len(words):
            return None
        word = words[i]
        if word in lexicon.NUMBER_TENS:
            if i + 1 < len(words) and words[i + 1] in lexicon.NUMBER_UNITS:
                return lexicon.NUMBER_TENS[word] + lexicon.NUMBER_UNITS[words[i + 1]], i + 2
            return lexicon.NUMBER_TENS[word], i + 1
        for table in (lexicon.NUMBER_TEENS, lexicon.NUMBER_UNITS):
            if word in table:
                return table[word], i + 1
        return None

    def below_thousand(i: int) -> tuple[int, int] | None:
        if i + 1 < len(words) and words[i] in lexicon.NUMBER_UNITS and words[i + 1] == "hundred":
            total, i = lexicon.NUMBER_UNITS[words[i]] * 100, i + 2
            j = i + 1 if i < len(words) and words[i] == "and" else i
            rest = below_hundred(j)
            return (total + rest[0], rest[1]) if rest else (total, i)
        return below_hundred(i)

    first = below_thousand(0)
    if not first:
        return None
    total, i = first
    if i < len(words) and words[i] == "thousand":
        total, i = total * 1000, i + 1
        j = i + 1 if i < len(words) and words[i] == "and" else i
        rest = below_thousand(j)
        if rest:
            total, i = total + rest[0], rest[1]
    return total if i == len(words) else None
