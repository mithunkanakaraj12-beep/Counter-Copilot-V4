"""Claude 1's expression of each Gemini label in the contract schema.

Label values are copied literally, even where an approved rule will change them. Evidence
quotes and line spans are chosen by Claude 1, because the labels give none. Fields a label
does not mention are filled with "missing" only because the schema requires every field;
the compatibility check ignores them.
"""

from __future__ import annotations


def ex(value, *quotes):
    return {"state": "extracted", "value": value, "quotes": quotes or (value,)}


def gone():
    return {"state": "missing", "value": None, "quotes": ()}


def amb(reason, quotes, candidates=()):
    return {
        "state": "ambiguous",
        "value": None,
        "quotes": tuple(quotes),
        "reason": reason,
        "candidates": tuple(candidates),
    }


def case(classification="material_request", lines=(), inexpressible=(), conflicts=(), open_points=()):
    return {
        "classification": classification,
        "lines": list(lines),
        "inexpressible": list(inexpressible),
        "rule_conflicts": list(conflicts),
        "open_points": list(open_points),
    }


def one(span=None, **fields):
    """A line. span=None means the whole email."""
    return {"span": span, "fields": fields}


SPLIT = (
    "The label does not say which field each word of a line belongs to. Claude 1 assigned "
    "sizes to dimensions, species and grade to their fields and the remaining noun to product."
)


def annotation(kept, dropped):
    return f"The label writes '{kept} ({dropped})'. Only '{kept}' is used as the value."


MAPPING = {
    1: case(lines=[one(quantity=ex("50"), dimensions=ex("2x4x8"), species=ex("SPF"),
                       grade=ex("Standard", "standard"))]),
    2: case(lines=[one(quantity=ex("100"), product=ex("OSB"), dimensions=ex("7/16"),
                       unit=ex("sheet", "sheets"))],
            open_points=["The unit is taken from the warnings column, which says it is marked as 'sheets'."]),
    3: case(lines=[one(quantity=ex("20"), dimensions=ex("2x6x12"), treatment=ex("treated"))],
            open_points=[annotation("treated", "PT")]),
    4: case(lines=[one(quantity=ex("40"), product=ex("Quikrete"), unit=ex("bag", "bags"))],
            inexpressible=["Weight: 80lb (no weight field)"]),
    5: case(lines=[one(quantity=ex("200"), unit=ex("linear_foot", "linear feet"), dimensions=ex("1x4"),
                       species=ex("pine"), treatment=ex("primed"))]),
    6: case(lines=[one(dimensions=ex("2x4x10"), quantity=gone())],
            conflicts=["Quantity is labeled MISSING, but 'some' is a vague number word that the approved rule keeps ambiguous (N-14)."]),
    7: case(lines=[one(quantity=ex("30"), dimensions=ex("2x6"))],
            inexpressible=["MISSING: Length (no length field; no axis is assigned, U-07)"]),
    8: case(lines=[one(quantity=ex("50"), species=ex("pine"), dimensions=gone())]),
    9: case(lines=[one(quantity=ex("1", "a bunk"), dimensions=ex("1/2 inch"), product=ex("plywood"))],
            inexpressible=["Unit 'bunk' (not a contract unit; ambiguous until a yard mapping exists, U-08)"]),
    10: case(lines=[one(dimensions=ex("2x8"), product=ex("floor joists"), quantity=gone(), species=gone())],
             inexpressible=["MISSING: Length (no length field; no axis is assigned, U-07)"]),
    11: case(lines=[one(quantity=ex("60"), dimensions=ex("2x4x8", "2x4x8s"))]),
    12: case(lines=[one(dimensions=ex("4x4x10"), treatment=ex("treated"),
                        quantity=amb("conflicting_statements", ["twenty", "10"], ["20", "10"]))],
             open_points=["The label says CONFLICT without a reason code or candidate list; conflicting_statements with 20 and 10 was used."]),
    13: case(lines=[one(dimensions=ex("2x6x16", "16 footers", "2x6x12s"))]),
    14: case(lines=[one(quantity=ex("500"), unit=ex("linear_foot", "feet"), dimensions=ex("2x4"))]),
    15: case(lines=[one(quantity=ex("100"), dimensions=ex("2x4x92-5/8"), product=ex("precut studs"))]),
    16: case(lines=[one(quantity=ex("1", "a lift"), product=ex("plywood", "plywod"), dimensions=ex("3/4"),
                        grade=ex("CDX"))],
             inexpressible=["Unit 'lift' (not a contract unit; ambiguous until a yard mapping exists, U-08)"]),
    17: case(lines=[one(quantity=ex("40"), treatment=ex("pt"), dimensions=ex("2x4x8", "2x4x8s"))],
             open_points=[annotation("pt", "pressure treated")]),
    18: case(lines=[one(quantity=ex("50"), unit=ex("piece", "sticks"), product=ex("rebar"),
                        dimensions=ex("#4 x 20ft", "#4 rebar 20ft"))]),
    19: case(lines=[one(quantity=ex("20"), unit=ex("sheet", "sheets"), dimensions=ex("1/2 inch", "half inch"),
                        product=ex("zip"))],
             inexpressible=["Mapping 'zip' to Zip System sheathing (needs an approved yard synonym)"],
             open_points=[annotation("zip", "Zip System")]),
    20: case(lines=[one(quantity=ex("50"),
                        dimensions=ex("5/4x6x16", "five-quarter by six sixteen foot"),
                        species=ex("cedar"), product=ex("decking"))]),
    21: case(lines=[
        one("50 2x4x8 SPF", quantity=ex("50"), dimensions=ex("2x4x8"), species=ex("SPF")),
        one("20 sheets 7/16 OSB", quantity=ex("20"), dimensions=ex("7/16"), product=ex("OSB")),
        one("2 boxes of 3-inch sinkers", quantity=ex("2", "2 boxes"), unit=ex("box", "boxes"),
            dimensions=ex("3-inch"), product=ex("sinkers")),
    ], open_points=[SPLIT]),
    22: case(lines=[
        one("100 2x6x10 SYP #1", quantity=ex("100"), dimensions=ex("2x6x10"), species=ex("SYP"), grade=ex("#1")),
        one("50 LU24 joist hangers", quantity=ex("50"), product=ex("LU24 joist hangers")),
    ], open_points=[SPLIT]),
    23: case(lines=[
        one("40 bags portland", quantity=ex("40"), product=ex("Portland cement", "portland")),
        one("100 1/2x10 anchor bolts", quantity=ex("100"), dimensions=ex("1/2x10"), product=ex("anchor bolts")),
    ], open_points=[SPLIT]),
    24: case(lines=[one("Send 100 2x4x8s to start.", quantity=ex("100"), dimensions=ex("2x4x8", "2x4x8s"))]),
    25: case(lines=[
        one("40 2x8x16 PT", quantity=ex("40"), dimensions=ex("2x8x16"), treatment=ex("PT")),
        one("10 rolls of tyvek housewrap", quantity=ex("10", "10 rolls"), unit=ex("roll", "rolls"),
            product=ex("Tyvek housewrap", "tyvek housewrap")),
    ], open_points=[SPLIT]),
    26: case("non_request", open_points=["'Account/Billing' has no contract field; the class used is non_request."]),
    27: case("follow_up", lines=[one(quantity=ex("20"), dimensions=ex("2x4x10", "2x4x10s"))],
             conflicts=["The label asks an employee to link the message to an existing ticket. v0.1 links only by reply headers or provider thread ID and has no manual linking (N-1, U-12)."]),
    28: case(None,
             inexpressible=[
                 "Classification 'General Inquiry' (the contract has material_request, follow_up, non_request, uncertain)",
                 "Color: Island Mist (no color field)",
             ],
             conflicts=["If the class were non_request, a material line would reject the whole run (N-5)."],
             open_points=["Gemini to choose the contract class and whether a material line is expected.",
                          "No proposal is generated, so the labeled material 'Trex Transcend' is not compared."]),
    29: case(conflicts=["The label asks the system to parse the attached file. v0.1 does not process attachments (N-9)."],
             open_points=["The benchmark email has no attachment, so no attachment warning can be produced."]),
    30: case(lines=[one(quantity=amb("approximate", ["about 100"], ["100"]), dimensions=ex("2x4", "2x4s"))],
             open_points=["The label writes '~100'; expressed as ambiguous (approximate) with candidate 100.",
                          "'Cheapest' has no contract field."]),
}
