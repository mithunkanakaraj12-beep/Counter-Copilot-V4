"""Versioned word lists. A change to any list requires a new LEXICON_VERSION.

All matching is case-insensitive on whole tokens. English only.
"""

from __future__ import annotations

LEXICON_VERSION = "en-1"

# Singular and plural of the nine contract unit names. Nothing else maps to a unit:
# abbreviations and trade terms (pcs, LF, BF, lift, bunk, sticks, feet) stay
# ambiguous until an authorized yard mapping exists (U-08).
UNIT_SPELLINGS: dict[str, str] = {
    "piece": "piece",
    "pieces": "piece",
    "sheet": "sheet",
    "sheets": "sheet",
    "linear foot": "linear_foot",
    "linear feet": "linear_foot",
    "board foot": "board_foot",
    "board feet": "board_foot",
    "bundle": "bundle",
    "bundles": "bundle",
    "box": "box",
    "boxes": "box",
    "bag": "bag",
    "bags": "bag",
    "roll": "roll",
    "rolls": "roll",
    "pallet": "pallet",
    "pallets": "pallet",
}

# Unit marks accepted inside a written dimension (U-08, U-07). No semantic axis.
DIMENSION_UNITS: dict[str, str] = {
    "ft": "ft",
    "ft.": "ft",
    "foot": "ft",
    "feet": "ft",
    "'": "ft",
    "′": "ft",  # prime
    "’": "ft",  # right single quotation mark
    "in": "in",
    "in.": "in",
    "inch": "in",
    "inches": "in",
    '"': "in",
    "″": "in",  # double prime
    "”": "in",  # right double quotation mark
}

DIMENSION_SEPARATORS = ("x", "X", "×")

# Fixed cardinal list (N-14). "zero" is excluded: quantities are positive.
NUMBER_UNITS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9,
}
NUMBER_TEENS: dict[str, int] = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
NUMBER_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
NUMBER_SCALES: dict[str, int] = {"hundred": 100, "thousand": 1000}

# Never a number (N-14). "an", "dozens" and "several" are treated the same way,
# which can only make a field more cautious.
VAGUE_NUMBER_WORDS = frozenset(
    {"a", "an", "couple", "few", "some", "dozen", "dozens", "several"}
)

# The lists below can only make a quantity more cautious, never more acceptable.
APPROXIMATE_BEFORE = frozenset(
    {
        "about", "around", "approx", "approximately", "appx", "aprx", "roughly", "maybe",
        "probably", "circa", "~", "\u2248",
    }
)
APPROXIMATE_AFTER = (
    "or so", "give or take", "ish", "approx", "approximately", "roughly", "maybe",
)

# One-sided bounds. A bounded quantity is a range with one written end.
BOUND_BEFORE = (
    "at least", "at most", "up to", "more than", "less than", "fewer than", "minimum",
    "minimum of", "min", "maximum", "maximum of", "max", "over", "under",
)
BOUND_AFTER = ("or more", "or less", "minimum", "min", "maximum", "max", "tops")

# Abbreviations after which a period does not end the clause.
ABBREVIATIONS = frozenset({"approx", "appx", "min", "max"})

# A number followed by one of these multiplies or divides it in a way that is not read.
DOZEN_WORDS = frozenset({"dozen", "dozens", "doz", "dz"})
SCALE_WORDS = frozenset({"hundred", "thousand", "million", "billion"})
FRACTION_TAILS = (
    "and a half", "and a quarter", "and a third", "and one half", "and one quarter",
)

RELATIVE_BEFORE = frozenset({"another", "additional", "extra", "add"})
# Words after a number that do not name what is being counted.
NOT_A_COUNTED_NOUN = frozenset(
    {"of", "the", "and", "or", "x", "by", "for", "in", "on", "to", "at", "more"}
)

# "Send over 40 bags" means send them: "over" straight after one of these is no bound.
DELIVERY_VERBS_BEFORE_OVER = frozenset({"send", "sending", "sent", "bring", "ship"})
# Approximation written in parentheses, directly beside the amount.
APPROXIMATE_PARENTHETICAL = ("approx", "approximately", "appx", "roughly", "about", "estimated", "est")
RELATIVE_AFTER = frozenset({"more", "additional", "extra", "less", "fewer"})

NEGATORS = frozenset(
    {"not", "no", "non", "without", "never", "don't", "don’t", "dont", "except", "cancel"}
)
NEGATION_WINDOW = 3  # tokens before the value, within the same clause

RANGE_CONNECTORS = frozenset({"-", "–", "—", "to", "or"})

CORRECTION_PHRASES = (
    "actually",
    "wait",
    "scratch that",
    "make that",
    "make it",
    "instead",
    "correction",
    "i meant",
    "change that",
    "disregard",
    "never mind",
    "nevermind",
    "on second thought",
)

# A number straight after one of these is a reference number, not a quantity.
IDENTIFIER_PREFIXES = frozenset(
    {"job", "po", "p.o", "invoice", "account", "acct", "lot", "ref", "suite"}
)

# A number straight before one of these is a measurement, not a quantity.
MEASUREMENT_FOLLOWERS = frozenset(
    {
        "foot", "ft", "ft.", "footer", "footers", "inch", "in.", "'", '"', "lb", "lbs",
        "pound", "pounds", "mm", "gauge", "ga", "am", "pm", "%",
    }
)
# "16 feet long" is a measurement; "500 feet of 2x4" may be a quantity.
PLURAL_LENGTH_WORDS = frozenset({"feet", "inches"})
SIZE_ADJECTIVES = frozenset({"long", "wide", "thick", "tall", "deep", "high"})

# Used only to notice that a corrected line names more than one treatment. A term
# here never makes a value acceptable and never becomes a candidate by itself.
TREATMENT_TERMS: dict[str, str] = {
    "treated": "treated",
    "pt": "treated",
    "pressure treated": "treated",
    "pressure-treated": "treated",
    "untreated": "untreated",
    "non-treated": "untreated",
}

FULFILLMENT_PHRASES: dict[str, str] = {
    "delivery": "delivery",
    "deliver": "delivery",
    "delivered": "delivery",
    "delivering": "delivery",
    "drop off": "delivery",
    "drop-off": "delivery",
    "pickup": "pickup",
    "pick up": "pickup",
    "pick-up": "pickup",
    "picking up": "pickup",
    "picked up": "pickup",
}
