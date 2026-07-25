"""METAR parsing tests, written against real reports."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from metar_extremes import (
    body_temperature_c,
    is_speci,
    parse_metar_remarks,
    parse_observation,
    parse_raw_observation,
)


def test_tgroup_precise_temperature():
    raw = ("METAR KLAX 250353Z 25005KT 10SM FEW260 SCT300 22/18 A2986 "
           "RMK AO2 SLP108 T02220178")
    ex = parse_metar_remarks(raw)
    assert ex.temp_c_precise == pytest.approx(22.2)
    assert ex.dewpoint_c_precise == pytest.approx(17.8)


def test_tgroup_negative_temperature():
    raw = ("METAR KORD 120153Z 27012KT 10SM OVC050 M02/M08 A3012 "
           "RMK AO2 SLP201 T10171083")
    ex = parse_metar_remarks(raw)
    assert ex.temp_c_precise == pytest.approx(-1.7)
    assert ex.dewpoint_c_precise == pytest.approx(-8.3)


def test_six_hourly_and_daily_groups():
    raw = ("METAR KMIA 260153Z 09008KT 10SM FEW040 33/24 A3001 "
           "RMK AO2 SLP162 T03330244 10339 20289 401120267")
    ex = parse_metar_remarks(raw)
    assert ex.temp_c_precise == pytest.approx(33.3)
    assert ex.six_hour_max_c == pytest.approx(33.9)
    assert ex.six_hour_min_c == pytest.approx(28.9)
    assert ex.day_max_c == pytest.approx(11.2)
    assert ex.day_min_c == pytest.approx(26.7)


def test_remarks_absent_is_not_an_error():
    ex = parse_metar_remarks("METAR RJTT 250400Z 16010KT 9999 FEW030 34/27 Q1007 NOSIG")
    assert ex.temp_c_precise is None
    assert ex.six_hour_max_c is None


def test_slp_and_precip_groups_not_misread_as_six_hourly():
    """SLP108 and P0003 contain digit runs a loose regex reads as a 1x/2x group."""
    ex = parse_metar_remarks(
        "METAR KLAX 250353Z 22/18 A2986 RMK AO2 SLP108 P0003 T02220178")
    assert ex.six_hour_max_c is None
    assert ex.six_hour_min_c is None


def test_empty_input_is_safe():
    assert parse_metar_remarks(None).temp_c_precise is None
    assert parse_metar_remarks("").temp_c_precise is None


def test_body_temperature():
    assert body_temperature_c("METAR RJTT 250400Z 34/27 Q1007") == pytest.approx(34.0)
    assert body_temperature_c("METAR KORD 120153Z M02/M08 A3012") == pytest.approx(-2.0)
    assert body_temperature_c(None) is None
    assert body_temperature_c("METAR KXXX 120153Z AUTO A3012") is None


def test_body_temperature_survives_a_missing_dewpoint():
    """`22///` is a valid report: temperature 22, dewpoint unavailable. The
    temperature is still usable and must not be discarded with the dewpoint."""
    assert body_temperature_c("METAR KXXX 120153Z 22/// A3012") == pytest.approx(22.0)


def test_parse_observation_prefers_tgroup_over_body():
    row = {
        "icaoId": "KLAX", "obsTime": 1784951580, "temp": 22,
        "rawOb": "METAR KLAX 250353Z 22/18 A2986 RMK AO2 SLP108 T02220178",
        "metarType": "METAR",
    }
    obs = parse_observation(row)
    assert obs is not None
    assert obs["temp_c"] == pytest.approx(22.2), "should use the precise T-group"
    assert obs["temp_c_body"] == pytest.approx(22.0), "body kept for rule comparison"
    assert obs["obs_time"] == datetime(2026, 7, 25, 3, 53, tzinfo=timezone.utc)
    assert obs["is_speci"] is False


def test_parse_observation_falls_back_to_body_without_tgroup():
    row = {"icaoId": "RJTT", "obsTime": 1784952000, "temp": 34,
           "rawOb": "METAR RJTT 250400Z 34/27 Q1007 NOSIG", "metarType": "METAR"}
    obs = parse_observation(row)
    assert obs["temp_c"] == pytest.approx(34.0)
    assert obs["temp_c_body"] == pytest.approx(34.0)


def test_parse_observation_flags_speci():
    row = {"icaoId": "KDEN", "obsTime": 1784952000, "temp": 30,
           "rawOb": "SPECI KDEN 250412Z 30/12 A3001", "metarType": "SPECI"}
    assert parse_observation(row)["is_speci"] is True


def test_parse_observation_rejects_missing_temperature():
    assert parse_observation(
        {"icaoId": "KMIA", "obsTime": 1784952000, "temp": None}) is None
    assert parse_observation({"obsTime": 1784952000, "temp": 20}) is None


def test_is_speci_from_either_field():
    assert is_speci("SPECI KDEN 250412Z") is True
    assert is_speci("METAR KDEN 250412Z", "SPECI") is True
    assert is_speci("METAR KDEN 250412Z") is False
    assert is_speci(None) is False


def test_parse_raw_observation_matches_json_path():
    """The archive path and the live path must agree, or a validation run
    measures one implementation while production uses another."""
    raw = "METAR KLAX 250353Z 22/18 A2986 RMK AO2 SLP108 T02220178"
    when = datetime(2026, 7, 25, 3, 53, tzinfo=timezone.utc)
    from_raw = parse_raw_observation(raw, when, "KLAX")
    from_json = parse_observation(
        {"icaoId": "KLAX", "obsTime": int(when.timestamp()), "temp": 22,
         "rawOb": raw, "metarType": "METAR"})
    assert from_raw["temp_c"] == from_json["temp_c"]
    assert from_raw["temp_c_body"] == from_json["temp_c_body"]
    assert from_raw["obs_time"] == from_json["obs_time"]


def test_parse_raw_observation_without_temperature_returns_none():
    assert parse_raw_observation("METAR KLAX 250353Z AUTO",
                                 datetime(2026, 7, 25, tzinfo=timezone.utc)) is None
