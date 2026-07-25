"""Day-window tests. Getting these wrong misattributes observations by a day."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from metar_extremes import (
    BOUNDARY_LOCAL,
    BOUNDARY_LOCAL_STANDARD,
    local_date_of,
    local_day_window,
)


def test_window_is_local_midnight_to_midnight():
    start, end = local_day_window(date(2026, 7, 26), "America/New_York")
    assert start == datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc)   # EDT = UTC-4
    assert end == datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)


def test_spring_forward_day_is_23_hours():
    """A naive start + 24h overshoots into the next local day."""
    start, end = local_day_window(date(2026, 3, 8), "America/New_York")
    assert (end - start).total_seconds() == 23 * 3600


def test_autumn_fallback_day_is_25_hours():
    start, end = local_day_window(date(2026, 11, 1), "America/New_York")
    assert (end - start).total_seconds() == 25 * 3600


def test_southern_hemisphere_offset():
    start, end = local_day_window(date(2026, 7, 26), "Pacific/Auckland")
    assert start == datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)  # NZST = UTC+12
    assert (end - start).total_seconds() == 24 * 3600


def test_local_standard_boundary_shifts_during_dst():
    """In summer the standard-time day starts an hour later than wall clock, so
    the first wall-clock hour belongs to the previous reporting day."""
    wall_start, _ = local_day_window(date(2026, 7, 26), "America/New_York",
                                     BOUNDARY_LOCAL)
    std_start, std_end = local_day_window(date(2026, 7, 26), "America/New_York",
                                          BOUNDARY_LOCAL_STANDARD)
    assert (std_start - wall_start).total_seconds() == 3600
    assert (std_end - std_start).total_seconds() == 24 * 3600


def test_local_standard_matches_wall_clock_outside_dst():
    wall = local_day_window(date(2026, 1, 15), "America/New_York", BOUNDARY_LOCAL)
    std = local_day_window(date(2026, 1, 15), "America/New_York",
                           BOUNDARY_LOCAL_STANDARD)
    assert wall == std


def test_unknown_boundary_raises():
    with pytest.raises(ValueError):
        local_day_window(date(2026, 7, 26), "America/New_York", "sidereal")


def test_local_date_of():
    # 03:00 UTC on the 27th is still the 26th in Miami.
    inst = datetime(2026, 7, 27, 3, 0, tzinfo=timezone.utc)
    assert local_date_of(inst, "America/New_York") == date(2026, 7, 26)


def test_local_date_of_assumes_utc_for_naive_input():
    naive = datetime(2026, 7, 27, 3, 0)
    assert local_date_of(naive, "America/New_York") == date(2026, 7, 26)
