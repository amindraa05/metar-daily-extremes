"""Temperature units, and the conversion to a whole-degree "official" value.

Weather sources publish a daily high and low as a whole number. Recovering that
number from raw observations is not obvious, because two things are undocumented
for essentially every source:

  1. whether the whole-degree value is derived from the precise temperature
     (the METAR remarks T-group, tenths of a degree Celsius) or from the rounded
     value in the METAR body, and
  2. how ties at exactly .5 are broken.

Rather than guess, every plausible convention is implemented here as a *named
rule*, and `metar_extremes.reconcile` measures each one against values a source
actually published. A rule is chosen by evidence or not at all.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

# Candidate conventions for turning an observation into a whole-degree value.
RULE_F_PRECISE = "f_from_precise"             # F = half_up(C_precise * 9/5 + 32)
RULE_F_BODY = "f_from_body"                   # F = half_up(C_body_int * 9/5 + 32)
RULE_F_PRECISE_EVEN = "f_from_precise_even"   # same, banker's rounding on ties
RULE_C_PRECISE = "c_from_precise"             # C = half_up(C_precise)
RULE_C_BODY = "c_from_body"                   # C = C_body_int (already whole)
RULE_C_PRECISE_EVEN = "c_from_precise_even"

RULES_F = (RULE_F_PRECISE, RULE_F_BODY, RULE_F_PRECISE_EVEN)
RULES_C = (RULE_C_PRECISE, RULE_C_BODY, RULE_C_PRECISE_EVEN)
ALL_RULES = RULES_F + RULES_C

DEFAULT_RULE = {"F": RULE_F_PRECISE, "C": RULE_C_PRECISE}

# Preference order for breaking ties when two conventions score identically.
#
# This matters more than it looks. The `*_even` rules differ from their half-up
# counterparts only on exact .5 ties, which appear a handful of times in a month
# of data, so a short sample routinely cannot distinguish them. Without an
# explicit preference the winner is decided by however the labels happen to
# sort -- and in the original implementation that silently selected banker's
# rounding, which no meteorological source uses, purely because "_" sorts before
# "|". Ties therefore resolve toward the documented convention: half-up, from the
# precise value.
RULE_PREFERENCE = (
    RULE_F_PRECISE, RULE_C_PRECISE,             # half-up on the precise value
    RULE_F_BODY, RULE_C_BODY,                   # half-up on the rounded body value
    RULE_F_PRECISE_EVEN, RULE_C_PRECISE_EVEN,   # banker's rounding: last resort
)


def rule_rank(rule: str) -> int:
    """Lower is more preferred; unknown rules sort last."""
    try:
        return RULE_PREFERENCE.index(rule)
    except ValueError:
        return len(RULE_PREFERENCE)


def c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


def round_half_up(value: float) -> int:
    """Round to nearest integer, ties away from zero.

    Python's built-in `round()` uses banker's rounding (`round(22.5) == 22`),
    which is not what meteorological sources do. `Decimal` with ROUND_HALF_UP
    gives 22.5 -> 23 and -22.5 -> -23.

    Tolerance contract: the input is first quantised to 6 decimal places, so a
    value within 1e-6 of a .5 tie is treated *as* that tie and rounds away from
    zero. This is intentional. Inputs are tenth-of-a-degree Celsius readings
    pushed through `c * 9/5 + 32`, where 9/5 is not exactly representable in
    binary, so an exact 72.5 can surface as 72.49999999999999. Noise at that
    magnitude can only mean "this was meant to be a tie", while a genuine
    near-miss (72.49999) is far larger than the tolerance and still rounds down.
    """
    d = Decimal(repr(round(value, 6)))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_even(value: float) -> int:
    d = Decimal(repr(round(value, 6)))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def rules_for_unit(unit: str) -> tuple[str, ...]:
    unit = unit.upper()
    if unit == "F":
        return RULES_F
    if unit == "C":
        return RULES_C
    raise ValueError(f"unsupported unit {unit!r}")


def to_official_integer(
    temp_c_precise: float | None,
    unit: str,
    rule: str | None = None,
    temp_c_body: float | None = None,
) -> int | None:
    """Convert one observation to the whole-degree value a source would publish.

    Args:
        temp_c_precise: best available Celsius value (METAR T-group when present).
        unit: 'F' or 'C' -- the unit the *source* publishes in.
        rule: one of the RULE_* constants; defaults to the per-unit default.
        temp_c_body: the rounded whole-degree Celsius from the METAR body,
            required by the `*_from_body` rules.

    Returns None when the inputs a rule needs are unavailable, so callers must
    handle missing data explicitly rather than silently treating it as 0 -- a
    silent zero here reads as a real freezing observation.
    """
    unit = unit.upper()
    rule = rule or DEFAULT_RULE[unit]

    base = temp_c_body if rule in (RULE_F_BODY, RULE_C_BODY) else temp_c_precise
    if base is None:
        return None

    if rule in (RULE_F_PRECISE, RULE_F_BODY):
        return round_half_up(c_to_f(base))
    if rule == RULE_F_PRECISE_EVEN:
        return round_half_even(c_to_f(base))
    if rule in (RULE_C_PRECISE, RULE_C_BODY):
        return round_half_up(base)
    if rule == RULE_C_PRECISE_EVEN:
        return round_half_even(base)
    raise ValueError(f"unknown rounding rule {rule!r}")


def value_in_range(value: int, low: float | None, high: float | None) -> bool:
    """Whether an integer falls in an inclusive range.

    `low is None` means an open low tail, `high is None` an open high tail. Both
    bounds are inclusive. Useful when the reference value is published as a band
    ("79 degrees or below") rather than an exact number.
    """
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True
