"""Computing a day's high or low from a set of observations.

The subtle part is deciding *which readings count*. Two candidate sources:

    regular            routine hourly (and SPECI) observations only
    plus_six_hourly    the above, plus the 6-hour extreme groups from remarks

Including the 6-hour groups looks obviously correct -- the daily extreme often
occurs between routine reports, and those groups exist precisely to record it.
Measured against real published values, it made accuracy *worse* everywhere it
was tested: one station's maximum fell from a perfect match rate to 0.588. The
source evidently derives its daily extreme from routine observations alone.

That result is the reason this module treats the choice as a parameter instead
of a constant. Both variants stay scoreable, so if a source ever changes its
convention the measurement says so rather than the pipeline quietly degrading.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from .units import to_official_integer

EXTREME_REGULAR = "regular"
EXTREME_PLUS_SIX_HOURLY = "plus_six_hourly"
EXTREME_SOURCES = (EXTREME_REGULAR, EXTREME_PLUS_SIX_HOURLY)

# The default is the one that measured better, not the one that sounds better.
DEFAULT_EXTREME_SOURCE = EXTREME_REGULAR

# A 6-hourly group summarises the preceding six hours.
SIX_HOUR_LOOKBACK = timedelta(hours=6)

KIND_MAX = "max"
KIND_MIN = "min"


def candidate_temperatures(observations: Iterable[dict[str, Any]],
                           window_start: datetime, window_end: datetime,
                           kind: str,
                           extreme_source: str = DEFAULT_EXTREME_SOURCE,
                           ) -> list[tuple[float, float]]:
    """Collect (precise_c, body_c) pairs that fall inside the day.

    A 6-hourly group is admitted only when its entire six-hour lookback lies
    inside the window. Otherwise the 02:00-local report -- which summarises the
    previous evening -- would attribute yesterday's extreme to today, inventing
    observations that never happened on the day being measured.
    """
    if kind not in (KIND_MAX, KIND_MIN):
        raise ValueError(f"kind must be 'max' or 'min', got {kind!r}")
    if extreme_source not in EXTREME_SOURCES:
        raise ValueError(f"unknown extreme source {extreme_source!r}")

    out: list[tuple[float, float]] = []
    for obs in observations:
        when = obs.get("obs_time")
        if when is None or not (window_start <= when < window_end):
            continue
        precise = obs.get("temp_c")
        if precise is None:
            continue
        body = obs.get("temp_c_body")
        out.append((float(precise), float(body if body is not None else precise)))

        if extreme_source != EXTREME_PLUS_SIX_HOURLY:
            continue
        if when - SIX_HOUR_LOOKBACK < window_start:
            continue
        group = obs.get("six_max_c") if kind == KIND_MAX else obs.get("six_min_c")
        if group is not None:
            # The group carries tenth-degree precision and has no separate body
            # value, so it stands in for both and body-based rules see the same
            # number.
            out.append((float(group), float(group)))
    return out


def daily_extreme_report(observations: Sequence[dict[str, Any]],
                         window_start: datetime, window_end: datetime,
                         kind: str, unit: str, rule: str | None = None,
                         extreme_source: str = DEFAULT_EXTREME_SOURCE) -> int | None:
    """The whole-degree value this day would be published as, under one convention."""
    candidates = candidate_temperatures(observations, window_start, window_end,
                                        kind, extreme_source)
    values: list[int] = []
    for precise, body in candidates:
        value = to_official_integer(precise, unit, rule, temp_c_body=body)
        if value is not None:
            values.append(value)
    if not values:
        return None
    return max(values) if kind == KIND_MAX else min(values)


def daily_extreme_celsius(observations: Sequence[dict[str, Any]],
                          window_start: datetime, window_end: datetime, kind: str,
                          extreme_source: str = DEFAULT_EXTREME_SOURCE) -> float | None:
    """The same extreme in raw Celsius, before any rounding convention applies."""
    candidates = candidate_temperatures(observations, window_start, window_end,
                                        kind, extreme_source)
    if not candidates:
        return None
    temps = [precise for precise, _ in candidates]
    return max(temps) if kind == KIND_MAX else min(temps)


def count_at_extreme(observations: Sequence[dict[str, Any]],
                     window_start: datetime, window_end: datetime,
                     kind: str, unit: str, rule: str | None = None,
                     extreme_source: str = DEFAULT_EXTREME_SOURCE) -> int:
    """How many candidate readings sit at the extreme.

    A corroboration count. One reading at the extreme may be a blip that later
    gets corrected; two independent readings is a materially different claim,
    and callers that act on an extreme can require a second witness.
    """
    extreme = daily_extreme_report(observations, window_start, window_end, kind,
                                   unit, rule, extreme_source)
    if extreme is None:
        return 0
    candidates = candidate_temperatures(observations, window_start, window_end,
                                        kind, extreme_source)
    return sum(
        1 for precise, body in candidates
        if to_official_integer(precise, unit, rule, temp_c_body=body) == extreme
    )
