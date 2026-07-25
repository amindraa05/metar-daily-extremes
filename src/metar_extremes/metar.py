"""Raw METAR text parsing, focused on temperature.

The METAR body reports temperature as whole degrees Celsius. That is not precise
enough to reconstruct a Fahrenheit daily extreme: after conversion, the body
value alone can be off by up to about 1 degrees F. The remarks section carries
the tenth-of-a-degree value in the T-group, plus periodic extreme groups that
record spikes which never appear in an hourly observation.

Groups parsed here:

    T[s]TTT[s]DDD    precise temperature and dewpoint, tenths of a degree C
    1sTTT            6-hour maximum
    2sTTT            6-hour minimum
    4sTTTsTTT        24-hour maximum and minimum

`s` is a sign digit: 0 positive, 1 negative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# RMK ... T02220178 -> temp +22.2C, dewpoint +17.8C
TGROUP_RE = re.compile(r"\bT(?P<ts>[01])(?P<tt>\d{3})(?:(?P<ds>[01])(?P<dd>\d{3}))?\b")
SIX_MAX_RE = re.compile(r"(?<![\dA-Z/])1(?P<s>[01])(?P<t>\d{3})(?![\d])")
SIX_MIN_RE = re.compile(r"(?<![\dA-Z/])2(?P<s>[01])(?P<t>\d{3})(?![\d])")
DAY_MAXMIN_RE = re.compile(
    r"(?<![\dA-Z/])4(?P<s1>[01])(?P<t1>\d{3})(?P<s2>[01])(?P<t2>\d{3})(?![\d])"
)

# Temperature from the METAR body group, e.g. "34/27" or "M02/M08".
BODY_TEMP_RE = re.compile(r"\s(M?\d{2})/(M?\d{2}|//)\s")


def _signed_tenths(sign: str, digits: str) -> float:
    value = int(digits) / 10.0
    return -value if sign == "1" else value


@dataclass(frozen=True)
class MetarExtras:
    """Precise and extreme temperatures recoverable from the remarks section."""

    temp_c_precise: float | None = None
    dewpoint_c_precise: float | None = None
    six_hour_max_c: float | None = None
    six_hour_min_c: float | None = None
    day_max_c: float | None = None
    day_min_c: float | None = None


def parse_metar_remarks(raw: str | None) -> MetarExtras:
    """Extract precise and extreme temperatures from a raw METAR string."""
    if not raw:
        return MetarExtras()
    text = raw.upper()
    rmk_idx = text.find(" RMK")
    remarks = text[rmk_idx:] if rmk_idx >= 0 else ""

    temp = dew = None
    m = TGROUP_RE.search(remarks or text)
    if m:
        temp = _signed_tenths(m.group("ts"), m.group("tt"))
        if m.group("ds") is not None:
            dew = _signed_tenths(m.group("ds"), m.group("dd"))

    six_max = six_min = day_max = day_min = None
    if remarks:
        # Strip groups whose digit runs a loose regex misreads as a 1x/2x group:
        # "T02220178" and "SLP108" both contain such runs.
        scan = TGROUP_RE.sub(" ", remarks)
        scan = re.sub(r"\bSLP\d{3}\b", " ", scan)
        scan = re.sub(r"\bP\d{4}\b", " ", scan)
        mm = DAY_MAXMIN_RE.search(scan)
        if mm:
            day_max = _signed_tenths(mm.group("s1"), mm.group("t1"))
            day_min = _signed_tenths(mm.group("s2"), mm.group("t2"))
            scan = scan[: mm.start()] + " " + scan[mm.end():]
        m1 = SIX_MAX_RE.search(scan)
        if m1:
            six_max = _signed_tenths(m1.group("s"), m1.group("t"))
        m2 = SIX_MIN_RE.search(scan)
        if m2:
            six_min = _signed_tenths(m2.group("s"), m2.group("t"))

    return MetarExtras(
        temp_c_precise=temp,
        dewpoint_c_precise=dew,
        six_hour_max_c=six_max,
        six_hour_min_c=six_min,
        day_max_c=day_max,
        day_min_c=day_min,
    )


def body_temperature_c(raw: str | None) -> float | None:
    """Temperature from the METAR body group, in whole degrees Celsius."""
    if not raw:
        return None
    match = BODY_TEMP_RE.search(" " + raw.upper() + " ")
    if not match:
        return None
    token = match.group(1)
    value = float(token[1:]) if token.startswith("M") else float(token)
    return -value if token.startswith("M") else value


def is_speci(raw: str | None, metar_type: str | None = None) -> bool:
    """Whether a report is a SPECI (unscheduled special observation).

    Worth distinguishing: a SPECI is issued because something changed abruptly,
    and a lone SPECI reading is exactly the sort of value that later gets
    corrected. Callers that need corroboration before trusting an extreme can
    use this to require a second witness.
    """
    if metar_type and metar_type.upper().startswith("SPECI"):
        return True
    return bool(raw) and raw.strip().upper().startswith("SPECI")


def parse_observation(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise one aviationweather.gov METAR JSON row.

    Keeps the precise temperature (T-group when available, else the body value)
    and the body value *separately*, so competing rounding conventions can be
    compared on identical inputs. Returns None when the row lacks a station,
    timestamp or temperature -- an unusable row is dropped, never defaulted.
    """
    station = row.get("icaoId")
    obs_epoch = row.get("obsTime")
    if not station or obs_epoch is None:
        return None
    body_temp = row.get("temp")
    if body_temp is None:
        return None
    extras = parse_metar_remarks(row.get("rawOb"))
    precise = extras.temp_c_precise
    if precise is None:
        precise = float(body_temp)
    return {
        "station_id": str(station).upper(),
        "obs_time": datetime.fromtimestamp(int(obs_epoch), tz=timezone.utc),
        "temp_c": float(precise),
        "temp_c_body": float(body_temp),
        "six_max_c": extras.six_hour_max_c,
        "six_min_c": extras.six_hour_min_c,
        "is_speci": is_speci(row.get("rawOb"), row.get("metarType")),
        "raw": row.get("rawOb"),
        "extras": extras,
    }


def parse_raw_observation(raw: str, obs_time: datetime,
                          station_id: str = "") -> dict[str, Any] | None:
    """Build an observation dict from raw METAR text plus its timestamp.

    Used for archive sources that hand back the raw report rather than a parsed
    JSON row, so the same parser serves live and historical data. Sharing one
    implementation is deliberate: if a validation run measured one method and
    production used another, the measured number would say nothing about
    production behaviour.
    """
    extras = parse_metar_remarks(raw)
    body = body_temperature_c(raw)
    precise = extras.temp_c_precise if extras.temp_c_precise is not None else body
    if precise is None:
        return None
    return {
        "station_id": station_id.upper(),
        "obs_time": obs_time,
        "temp_c": float(precise),
        "temp_c_body": float(body if body is not None else precise),
        "six_max_c": extras.six_hour_max_c,
        "six_min_c": extras.six_hour_min_c,
        "is_speci": is_speci(raw),
        "raw": raw,
        "extras": extras,
    }
