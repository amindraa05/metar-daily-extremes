"""Tests for the convention-measuring harness."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import TZ_MIAMI, hourly_day
from metar_extremes import Reference, reconcile
from metar_extremes.units import RULE_C_PRECISE, RULE_F_PRECISE

DAYS = [date(2026, 7, 20) + timedelta(days=i) for i in range(6)]


def build(peaks_c, tz_name=TZ_MIAMI, filler=18.0, hours=20):
    """A run of days, each a flat filler with one peak reading."""
    obs = []
    for day, peak in zip(DAYS, peaks_c):
        temps = [filler] * hours
        temps[10] = peak
        obs += hourly_day(day, temps, tz_name)
    return obs


def test_finds_the_convention_that_reproduces_the_references():
    peaks = [30.4, 31.6, 29.5, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, value=round_c(p)) for day, p in zip(DAYS, peaks)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C")

    assert result.best is not None
    assert result.match_rate == pytest.approx(1.0)
    assert result.scored_days == len(DAYS)
    assert result.best.rule == RULE_C_PRECISE


def round_c(value: float) -> int:
    from metar_extremes import round_half_up
    return round_half_up(value)


def test_reports_a_partial_match_rather_than_deciding_it_is_good_enough():
    peaks = [30.4, 31.6, 29.5, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, value=round_c(p)) for day, p in zip(DAYS, peaks)]
    refs[0] = Reference(DAYS[0], value=round_c(peaks[0]) + 3)   # a day we cannot match
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C")

    assert 0.0 < result.match_rate < 1.0
    assert result.best.misses, "the failing day should be reported, not swallowed"
    assert result.best.misses[0].day == DAYS[0]


def test_band_references_are_supported():
    peaks = [30.4, 31.6, 29.5, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, low=round_c(p) - 1, high=round_c(p) + 1)
            for day, p in zip(DAYS, peaks)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C")
    assert result.match_rate == pytest.approx(1.0)


def test_open_ended_band():
    ref = Reference(DAYS[0], low=None, high=79)
    assert ref.matches(70) is True
    assert ref.matches(79) is True
    assert ref.matches(80) is False


def test_reference_without_value_or_bounds_is_an_error():
    with pytest.raises(ValueError):
        Reference(DAYS[0]).matches(70)


def test_thin_days_are_skipped_not_scored():
    """A three-observation day cannot distinguish conventions; letting it vote
    would add noise while inflating the apparent sample size."""
    obs = hourly_day(DAYS[0], [20.0, 25.0, 22.0])
    refs = [Reference(DAYS[0], value=25)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C")

    assert result.best is None
    assert result.scored_days == 0
    assert result.skipped_days and result.skipped_days[0][0] == DAYS[0]
    assert "no day had enough observations" in result.note


def test_min_obs_per_day_is_configurable():
    obs = hourly_day(DAYS[0], [20.0, 25.0, 22.0])
    refs = [Reference(DAYS[0], value=25)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C", min_obs_per_day=3)
    assert result.scored_days == 1
    assert result.match_rate == pytest.approx(1.0)


def test_no_references_is_reported_not_raised():
    result = reconcile([], [], TZ_MIAMI, kind="max", unit="C")
    assert result.best is None
    assert "no reference days" in result.note


def test_ties_are_flagged_so_the_caller_knows_evidence_did_not_decide():
    """Peaks nowhere near a .5 tie cannot separate half-up from banker's
    rounding, and the result must say so instead of implying a measured winner.
    """
    peaks = [30.4, 31.6, 29.4, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, value=round_c(p)) for day, p in zip(DAYS, peaks)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C")

    assert result.match_rate == pytest.approx(1.0)
    assert result.tied_at_top > 1
    assert result.decided_by_evidence is False
    assert "not evidence" in result.summary()


def test_tie_break_never_selects_bankers_rounding_by_accident():
    """Regression guard for a real bug: with the top conventions tied, the
    winner was once decided by label sort order, silently selecting banker's
    rounding -- which no meteorological source uses."""
    peaks = [30.4, 31.6, 29.4, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, value=round_c(p)) for day, p in zip(DAYS, peaks)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C")

    assert result.tied_at_top > 1, "this test is only meaningful under a tie"
    assert result.best.rule == RULE_C_PRECISE
    assert not result.best.rule.endswith("_even")


def test_fahrenheit_source_scores_fahrenheit_rules_only():
    peaks = [30.4, 31.6, 29.5, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, value=_f(p)) for day, p in zip(DAYS, peaks)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="F")

    assert result.match_rate == pytest.approx(1.0)
    assert result.best.rule == RULE_F_PRECISE
    assert all(s.rule.startswith("f_") for s in result.scores)


def _f(celsius: float) -> int:
    from metar_extremes import c_to_f, round_half_up
    return round_half_up(c_to_f(celsius))


def test_all_twelve_conventions_are_scored():
    peaks = [30.4, 31.6, 29.5, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, value=round_c(p)) for day, p in zip(DAYS, peaks)]
    result = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C")
    # 3 rounding rules x 2 extreme sources x 2 day boundaries
    assert len(result.scores) == 12
    assert len({s.label for s in result.scores}) == 12


def test_summary_is_human_readable():
    peaks = [30.4, 31.6, 29.5, 33.2, 28.8, 32.1]
    obs = build(peaks)
    refs = [Reference(day, value=round_c(p)) for day, p in zip(DAYS, peaks)]
    text = reconcile(obs, refs, TZ_MIAMI, kind="max", unit="C").summary()
    assert "matched" in text and "days" in text
