"""Shared fixtures: a small builder for synthetic observation days."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

import pytest

from metar_extremes import local_day_window

TZ_MIAMI = "America/New_York"


def observation(when: datetime, precise_c: float, body_c: float | None = None,
                six_max_c: float | None = None, six_min_c: float | None = None,
                station: str = "KTST") -> dict[str, Any]:
    """One observation in the shape the library consumes."""
    return {
        "station_id": station,
        "obs_time": when,
        "temp_c": precise_c,
        "temp_c_body": float(round(precise_c) if body_c is None else body_c),
        "six_max_c": six_max_c,
        "six_min_c": six_min_c,
        "is_speci": False,
        "raw": "",
    }


def hourly_day(day: date, temps_c: Sequence[float], tz_name: str = TZ_MIAMI,
               start_hour: int = 0, **kwargs: Any) -> list[dict[str, Any]]:
    """Observations one hour apart, starting `start_hour` into the local day."""
    start, _ = local_day_window(day, tz_name)
    return [
        observation(start + timedelta(hours=start_hour + i), t, **kwargs)
        for i, t in enumerate(temps_c)
    ]


def flat_day(day: date, base_c: float = 20.0, hours: int = 24,
             tz_name: str = TZ_MIAMI) -> list[dict[str, Any]]:
    """A featureless day, for padding a sample up to the minimum observation count."""
    return hourly_day(day, [base_c] * hours, tz_name)


@pytest.fixture()
def obs_factory():
    return observation


@pytest.fixture()
def utc():
    return timezone.utc
