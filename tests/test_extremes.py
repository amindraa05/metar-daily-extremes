"""Daily-extreme computation tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import TZ_MIAMI, hourly_day, observation
from metar_extremes import (
    EXTREME_PLUS_SIX_HOURLY,
    EXTREME_REGULAR,
    candidate_temperatures,
    count_at_extreme,
    daily_extreme_celsius,
    daily_extreme_report,
    local_day_window,
)

DAY = date(2026, 7, 26)


def window(boundary: str | None = None):
    if boundary is None:
        return local_day_window(DAY, TZ_MIAMI)
    return local_day_window(DAY, TZ_MIAMI, boundary)


def test_max_and_min_of_a_simple_day():
    start, end = window()
    obs = hourly_day(DAY, [20.0, 24.4, 31.6, 28.0, 19.2])
    assert daily_extreme_celsius(obs, start, end, "max") == pytest.approx(31.6)
    assert daily_extreme_celsius(obs, start, end, "min") == pytest.approx(19.2)
    assert daily_extreme_report(obs, start, end, "max", "C") == 32
    assert daily_extreme_report(obs, start, end, "min", "C") == 19


def test_observations_outside_the_window_are_ignored():
    start, end = window()
    obs = hourly_day(DAY, [20.0, 25.0])
    # A scorching reading one hour before the local day begins.
    obs.append(observation(start - timedelta(hours=1), 40.0))
    # And one exactly at the end, which is exclusive.
    obs.append(observation(end, 45.0))
    assert daily_extreme_celsius(obs, start, end, "max") == pytest.approx(25.0)


def test_six_hourly_group_included_only_when_requested():
    start, end = window()
    obs = hourly_day(DAY, [20.0] * 12)
    # A spike recorded only in the 6-hour group, on the 12th hour.
    obs[11] = observation(obs[11]["obs_time"], 20.0, six_max_c=29.4)

    plain = daily_extreme_celsius(obs, start, end, "max", EXTREME_REGULAR)
    with_groups = daily_extreme_celsius(obs, start, end, "max",
                                        EXTREME_PLUS_SIX_HOURLY)
    assert plain == pytest.approx(20.0)
    assert with_groups == pytest.approx(29.4)


def test_six_hourly_group_rejected_when_its_lookback_precedes_the_day():
    """The 02:00 report summarises last evening; crediting it to today would
    invent observations that never happened on the day being measured."""
    start, end = window()
    obs = hourly_day(DAY, [20.0, 20.0, 20.0])          # 00:00, 01:00, 02:00 local
    obs[2] = observation(obs[2]["obs_time"], 20.0, six_max_c=35.0)
    assert daily_extreme_celsius(obs, start, end, "max",
                                 EXTREME_PLUS_SIX_HOURLY) == pytest.approx(20.0)


def test_six_hourly_group_admitted_once_lookback_fits():
    start, end = window()
    obs = hourly_day(DAY, [20.0] * 8)                  # through 07:00 local
    obs[7] = observation(obs[7]["obs_time"], 20.0, six_max_c=35.0)
    assert daily_extreme_celsius(obs, start, end, "max",
                                 EXTREME_PLUS_SIX_HOURLY) == pytest.approx(35.0)


def test_fahrenheit_report_uses_precise_value_by_default():
    start, end = window()
    # 21.6C -> 70.88F (precise, rounds to 71) but body 22C -> 71.6F (rounds to 72).
    obs = hourly_day(DAY, [21.6], body_c=22.0)
    assert daily_extreme_report(obs, start, end, "max", "F") == 71


def test_no_observations_returns_none_not_zero():
    start, end = window()
    assert daily_extreme_report([], start, end, "max", "F") is None
    assert daily_extreme_celsius([], start, end, "max") is None
    assert count_at_extreme([], start, end, "max", "F") == 0


def test_count_at_extreme_corroboration():
    start, end = window()
    obs = hourly_day(DAY, [20.0, 31.5, 25.0, 31.5, 18.0])
    # Two readings round to the same maximum.
    assert count_at_extreme(obs, start, end, "max", "C") == 2
    obs_single = hourly_day(DAY, [20.0, 31.5, 25.0])
    assert count_at_extreme(obs_single, start, end, "max", "C") == 1


def test_candidate_temperatures_rejects_bad_arguments():
    start, end = window()
    with pytest.raises(ValueError):
        candidate_temperatures([], start, end, "median")
    with pytest.raises(ValueError):
        candidate_temperatures([], start, end, "max", "telepathy")


def test_local_standard_boundary_can_change_the_answer():
    """During DST the standard-time day starts an hour later, so a spike in the
    first wall-clock hour falls outside it."""
    obs = hourly_day(DAY, [33.0] + [20.0] * 12)
    wall_start, wall_end = window()
    std_start, std_end = window("local_standard")
    assert daily_extreme_celsius(obs, wall_start, wall_end, "max") == pytest.approx(33.0)
    assert daily_extreme_celsius(obs, std_start, std_end, "max") == pytest.approx(20.0)
