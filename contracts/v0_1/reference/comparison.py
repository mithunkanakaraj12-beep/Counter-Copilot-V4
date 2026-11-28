"""Compare what a line states with what a catalog SKU defines.

Pure functions. They never rank or select a SKU, never convert units and never
assign dimension axes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import models as m


@dataclass(frozen=True)
class SynonymRule:
    """An approved, yard-specific equivalence. None exist unless a yard approves one."""

    rule_id: UUID
    attribute: str
    request_value: str
    sku_value: str


def compare_dimensions(
    request: m.Dimensions | None, sku: m.Dimensions | None
) -> m.MatchOutcome | None:
    """Whole written sequence, in written order (N-12). None if neither side has one."""
    if request is None:
        return m.MatchOutcome.NOT_STATED_IN_REQUEST if sku else None
    if sku is None:
        return m.MatchOutcome.NOT_DEFINED_ON_SKU
    if len(request.components) != len(sku.components):
        return m.MatchOutcome.DIFFERENT_COMPONENT_COUNT
    pairs = list(zip(request.components, sku.components))
    comparable = [(a, b) for a, b in pairs if not (a.unit and b.unit and a.unit != b.unit)]
    if any(a.magnitude != b.magnitude for a, b in comparable):
        return m.MatchOutcome.MISMATCH
    if len(comparable) != len(pairs):
        return m.MatchOutcome.DIFFERENT_UNIT_NOT_COMPARED
    if any(a.unit is None or b.unit is None for a, b in pairs):
        return m.MatchOutcome.UNIT_UNCONFIRMED_EQUAL
    return m.MatchOutcome.EXACT_MATCH


def compare_text(
    attribute: str,
    request: str | None,
    sku: str | None,
    synonyms: tuple[SynonymRule, ...] = (),
) -> tuple[m.MatchOutcome, UUID | None] | None:
    """Equality ignores letter case only. Anything else needs an approved synonym."""
    if request is None:
        return (m.MatchOutcome.NOT_STATED_IN_REQUEST, None) if sku is not None else None
    if sku is None:
        return m.MatchOutcome.NOT_DEFINED_ON_SKU, None
    if request.casefold() == sku.casefold():
        return m.MatchOutcome.EXACT_MATCH, None
    for rule in synonyms:
        if (
            rule.attribute == attribute
            and rule.request_value.casefold() == request.casefold()
            and rule.sku_value.casefold() == sku.casefold()
        ):
            return m.MatchOutcome.SYNONYM_MATCH, rule.rule_id
    return m.MatchOutcome.MISMATCH, None


def attribute_evidence(
    values: Mapping[str, object],
    sku: m.SkuSnapshot,
    synonyms: tuple[SynonymRule, ...] = (),
) -> list[m.AttributeEvidence]:
    """`values` holds resolved request values only: a missing, ambiguous or cleared
    attribute is passed as None or left out, and counts as not stated."""
    result: list[m.AttributeEvidence] = []
    for attribute in m.MATCH_ATTRIBUTES:
        request = values.get(attribute)
        if attribute == "dimensions":
            sku_dimensions = sku.dimension_designation
            outcome = compare_dimensions(request, sku_dimensions)
            if outcome is None:
                continue
            result.append(
                m.AttributeEvidence(
                    attribute=attribute,
                    request_value=request.text if request else None,
                    sku_value=sku_dimensions.text if sku_dimensions else None,
                    outcome=outcome,
                    synonym_rule_id=None,
                )
            )
            continue
        sku_value = getattr(sku, attribute)
        compared = compare_text(attribute, request, sku_value, synonyms)
        if compared is None:
            continue
        result.append(
            m.AttributeEvidence(
                attribute=attribute,
                request_value=request,
                sku_value=sku_value,
                outcome=compared[0],
                synonym_rule_id=compared[1],
            )
        )
    return result


def unit_check(request_unit: m.UnitCode | None, sku_unit: m.UnitCode) -> m.UnitCheck:
    """Quantities are never converted between units."""
    if request_unit is None:
        return m.UnitCheck(status="request_unit_unresolved")
    return m.UnitCheck(status="same_unit" if request_unit == sku_unit else "different_unit")


def resolved_value(field) -> object:
    """The value only if a person or the grounded source resolved it."""
    return field.value if field.state in m.RESOLVED_STATES else None


def preview(
    line: m.MaterialLine,
    sku: m.SkuSnapshot,
    synonyms: tuple[SynonymRule, ...] = (),
) -> m.MatchPreview:
    values = {name: resolved_value(getattr(line, name)) for name in m.MATCH_ATTRIBUTES}
    return m.MatchPreview(
        attribute_evidence=attribute_evidence(values, sku, synonyms),
        unit_check=unit_check(resolved_value(line.unit), sku.sell_unit),
    )


def acknowledgment_attributes(
    evidence: list[m.AttributeEvidence],
) -> dict[m.WarningCode, list[str]]:
    """Which selected-SKU warnings a line needs, one per code, with the attributes.

    unit_unconfirmed_equal is shown to the employee but needs no acknowledgment.
    """
    groups = (
        (m.WarningCode.SELECTED_SKU_ATTRIBUTE_MISMATCH, m.MISMATCH_OUTCOMES),
        (m.WarningCode.SELECTED_SKU_ATTRIBUTE_UNVERIFIED, m.UNVERIFIED_OUTCOMES),
    )
    found: dict[m.WarningCode, list[str]] = {}
    for code, outcomes in groups:
        attributes = [item.attribute for item in evidence if item.outcome in outcomes]
        if attributes:
            found[code] = attributes
    return found
