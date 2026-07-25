"""Which hours belong to "a day" at a given station.

A daily extreme is only defined once you fix the window it is taken over, and
that window is a station-local calendar day -- not a UTC day, and not a fixed
24 hours from any particular instant.

Two boundary conventions are supported because real sources disagree:

    local           wall-clock midnight, shifting with daylight saving
    local_standard  standard-time midnight all year

The second is not exotic. Several US climate products are compiled on local
standard time, which during summer pushes the first hour of the wall-clock day
into the previous reporting day. Which convention a given source uses is a
question for measurement, not assumption -- see `metar_extremes.reconcile`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BOUNDARY_LOCAL = "local"
BOUNDARY_LOCAL_STANDARD = "local_standard"
DAY_BOUNDARIES = (BOUNDARY_LOCAL, BOUNDARY_LOCAL_STANDARD)


def local_day_window(target: date, tz_name: str,
                     boundary: str = BOUNDARY_LOCAL) -> tuple[datetime, datetime]:
    """UTC half-open window [start, end) covering the station's local day.

    Handles daylight-saving transitions correctly: a spring-forward day is 23
    hours long and an autumn day is 25, so a naive "start + 24h" overshoots or
    undershoots and silently attributes observations to the wrong day.
    """
    if boundary not in DAY_BOUNDARIES:
        raise ValueError(f"unknown day boundary {boundary!r}")
    tz = ZoneInfo(tz_name)
    start_local = datetime(target.year, target.month, target.day, 0, 0, tzinfo=tz)
    if boundary == BOUNDARY_LOCAL_STANDARD:
        offset = start_local.dst() or timedelta(0)
        start_utc = start_local.astimezone(timezone.utc) + offset
        return start_utc, start_utc + timedelta(days=1)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_date_of(instant: datetime, tz_name: str) -> date:
    """The station-local calendar date an instant falls on.

    Naive datetimes are assumed UTC rather than rejected, because most feeds
    hand back UTC timestamps without tzinfo attached.
    """
    tz = ZoneInfo(tz_name)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(tz).date()
