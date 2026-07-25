"""Reconstruct a weather station's published daily high and low from raw METAR.

Quick start:

    from metar_extremes import local_day_window, daily_extreme_report

    start, end = local_day_window(date(2026, 7, 26), "America/New_York")
    high = daily_extreme_report(observations, start, end, kind="max", unit="F")

To find out which convention a source uses instead of guessing:

    from metar_extremes import Reference, reconcile

    result = reconcile(observations, references, "America/New_York",
                       kind="max", unit="F")
    print(result.summary())
    if not result.decided_by_evidence:
        ...   # the sample could not separate the top conventions
"""

from .extremes import (
    DEFAULT_EXTREME_SOURCE,
    EXTREME_PLUS_SIX_HOURLY,
    EXTREME_REGULAR,
    EXTREME_SOURCES,
    KIND_MAX,
    KIND_MIN,
    candidate_temperatures,
    count_at_extreme,
    daily_extreme_celsius,
    daily_extreme_report,
)
from .metar import (
    MetarExtras,
    body_temperature_c,
    is_speci,
    parse_metar_remarks,
    parse_observation,
    parse_raw_observation,
)
from .reconcile import (
    ConventionScore,
    ReconcileResult,
    Reference,
    reconcile,
)
from .units import (
    ALL_RULES,
    RULE_C_BODY,
    RULE_C_PRECISE,
    RULE_C_PRECISE_EVEN,
    RULE_F_BODY,
    RULE_F_PRECISE,
    RULE_F_PRECISE_EVEN,
    RULES_C,
    RULES_F,
    c_to_f,
    f_to_c,
    round_half_even,
    round_half_up,
    rules_for_unit,
    to_official_integer,
    value_in_range,
)
from .windows import (
    BOUNDARY_LOCAL,
    BOUNDARY_LOCAL_STANDARD,
    DAY_BOUNDARIES,
    local_date_of,
    local_day_window,
)

__version__ = "0.1.0"

__all__ = [
    "ALL_RULES", "BOUNDARY_LOCAL", "BOUNDARY_LOCAL_STANDARD",
    "ConventionScore", "DAY_BOUNDARIES", "DEFAULT_EXTREME_SOURCE",
    "EXTREME_PLUS_SIX_HOURLY", "EXTREME_REGULAR", "EXTREME_SOURCES",
    "KIND_MAX", "KIND_MIN", "MetarExtras", "ReconcileResult", "Reference",
    "RULES_C", "RULES_F", "RULE_C_BODY", "RULE_C_PRECISE",
    "RULE_C_PRECISE_EVEN", "RULE_F_BODY", "RULE_F_PRECISE",
    "RULE_F_PRECISE_EVEN", "body_temperature_c", "c_to_f",
    "candidate_temperatures", "count_at_extreme", "daily_extreme_celsius",
    "daily_extreme_report", "f_to_c", "is_speci", "local_date_of",
    "local_day_window", "parse_metar_remarks", "parse_observation",
    "parse_raw_observation", "reconcile", "round_half_even", "round_half_up",
    "rules_for_unit", "to_official_integer", "value_in_range",
]
