"""Rounding and unit-conversion tests.

These lock down the arithmetic that decides what whole-degree value a day gets
published as. Which rule a given source *uses* is an empirical question answered
by `reconcile`; what is tested here is that each named rule computes what it
claims to.
"""

from __future__ import annotations

import pytest

from metar_extremes import (
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
from metar_extremes.units import RULE_PREFERENCE, rule_rank


def test_c_to_f_reference_points():
    assert c_to_f(0) == pytest.approx(32.0)
    assert c_to_f(100) == pytest.approx(212.0)
    assert c_to_f(-40) == pytest.approx(-40.0)
    assert c_to_f(22.2) == pytest.approx(71.96)


def test_f_to_c_roundtrip():
    for c in (-40.0, -12.3, 0.0, 15.5, 33.3, 41.7):
        assert f_to_c(c_to_f(c)) == pytest.approx(c)


def test_round_half_up_breaks_ties_away_from_zero():
    assert round_half_up(22.5) == 23, "banker's rounding would give 22"
    assert round_half_up(23.5) == 24
    assert round_half_up(-22.5) == -23
    assert round_half_up(22.49) == 22
    assert round_half_up(22.51) == 23


def test_round_half_up_survives_float_representation_noise():
    """A tie reached through float noise must still round as a tie.

    Documents the 1e-6 tolerance contract: noise-level deviation snaps to the
    tie and rounds away from zero, while a genuine near-miss stays below.
    """
    assert round_half_up(22.5 * 9.0 / 5.0 + 32.0) == 73
    assert round_half_up(72.49999999999999) == 73, "noise below 1e-6 counts as a tie"
    assert round_half_up(72.49999) == 72, "a real near-miss must not be promoted"
    assert round_half_up(-72.49999999999999) == -73


def test_round_half_even_differs_on_ties_only():
    assert round_half_even(22.5) == 22
    assert round_half_even(23.5) == 24
    assert round_half_even(22.4) == round_half_up(22.4) == 22


def test_precise_and_body_rules_can_disagree():
    """Why both values are kept: 21.6C body-rounds to 22C -> 72F, but the
    precise value gives 71F. One degree, decided entirely by convention."""
    precise, body = 21.6, 22.0
    assert to_official_integer(precise, "F", RULE_F_PRECISE, body) == 71
    assert to_official_integer(precise, "F", RULE_F_BODY, body) == 72


def test_f_rules_on_a_real_observation():
    # KLAX 22.2C precise, body 22C -> 71.96F and 71.6F respectively.
    assert to_official_integer(22.2, "F", RULE_F_PRECISE, 22.0) == 72
    assert to_official_integer(22.2, "F", RULE_F_BODY, 22.0) == 72


def test_c_rules():
    assert to_official_integer(33.3, "C", RULE_C_PRECISE, 33.0) == 33
    assert to_official_integer(33.6, "C", RULE_C_PRECISE, 34.0) == 34
    assert to_official_integer(33.6, "C", RULE_C_BODY, 34.0) == 34
    assert to_official_integer(-1.7, "C", RULE_C_PRECISE, -2.0) == -2


def test_tie_rules_diverge_predictably():
    assert to_official_integer(22.5, "C", RULE_C_PRECISE, 22.0) == 23
    assert to_official_integer(22.5, "C", RULE_C_PRECISE_EVEN, 22.0) == 22
    assert to_official_integer(22.5, "F", RULE_F_PRECISE, 22.0) == 73
    assert to_official_integer(22.5, "F", RULE_F_PRECISE_EVEN, 22.0) == 72


def test_missing_input_returns_none_not_zero():
    """A silent 0 here would read as a real freezing observation."""
    assert to_official_integer(None, "F", RULE_F_PRECISE, None) is None
    assert to_official_integer(None, "C", RULE_C_PRECISE) is None
    assert to_official_integer(22.2, "F", RULE_F_BODY, None) is None


def test_rules_for_unit():
    assert rules_for_unit("F") == RULES_F
    assert rules_for_unit("c") == RULES_C
    with pytest.raises(ValueError):
        rules_for_unit("K")


def test_unknown_rule_raises():
    with pytest.raises(ValueError):
        to_official_integer(20.0, "C", "made_up_rule")


def test_rule_preference_prefers_half_up_over_bankers():
    """Regression guard. Ties between conventions must not be settled by label
    ordering, which once silently selected banker's rounding."""
    assert rule_rank(RULE_F_PRECISE) < rule_rank(RULE_F_PRECISE_EVEN)
    assert rule_rank(RULE_C_PRECISE) < rule_rank(RULE_C_PRECISE_EVEN)
    assert rule_rank("not_a_rule") == len(RULE_PREFERENCE)


@pytest.mark.parametrize("value,low,high,expected", [
    (92, 92.0, 93.0, True),
    (93, 92.0, 93.0, True),
    (91, 92.0, 93.0, False),
    (94, 92.0, 93.0, False),
    (70, None, 79.0, True),      # "79 or below"
    (79, None, 79.0, True),
    (80, None, 79.0, False),
    (98, 98.0, None, True),      # "98 or higher"
    (120, 98.0, None, True),
    (97, 98.0, None, False),
    (32, 32.0, 32.0, True),      # single-degree band
    (33, 32.0, 32.0, False),
])
def test_value_in_range(value, low, high, expected):
    assert value_in_range(value, low, high) is expected
