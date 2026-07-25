"""Async HTTP clients for the two METAR feeds this library reads.

    aviationweather.gov   current observations (last few hours), JSON
    IEM ASOS archive      historical observations including raw text, CSV

Operational rules, enforced here rather than left to call sites:

  * Each source gets its own token bucket. The limit belongs to the provider,
    so one global limiter would make the fast feed queue behind the slow one for
    no reason.
  * HTTP 429 raises immediately and never sleeps inside the client. A caller
    running several concurrent tasks must be able to back off *one* of them; a
    sleep in here turns one provider's rate limit into a stall for everything.
  * Retries apply to transport errors and 5xx only, with exponential backoff and
    jitter. A 4xx means the request was wrong and repeating it will not help.
  * Every response carries `fetched_at`, so callers doing time-sensitive work
    can enforce that a decision only reads data that existed when it was made.

This module is optional: the parsing, extremes and reconcile modules have no
dependency on it, so you can feed them observations from anywhere.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Sequence

import httpx

METAR_BASE = "https://aviationweather.gov/api/data/metar"
IEM_ASOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"


class ApiError(RuntimeError):
    pass


class RateLimited(ApiError):
    """Raised on 429. Callers back off their own loop; the process keeps running."""

    def __init__(self, source: str, retry_after: float | None = None) -> None:
        super().__init__(f"{source} rate limited (retry_after={retry_after})")
        self.source = source
        self.retry_after = retry_after


class TokenBucket:
    """Global pacing so bursts cannot trip provider limits."""

    def __init__(self, rate_per_sec: float, burst: int) -> None:
        self.rate = rate_per_sec
        self.capacity = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity,
                                   self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep(min((1.0 - self._tokens) / self.rate, 1.0))


@dataclass
class Fetched:
    """A payload plus the instant it was retrieved."""

    data: Any
    fetched_at: datetime


class HttpClient:
    def __init__(self, user_agent: str = "metar-extremes/1.0",
                 timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            follow_redirects=True,
        )
        self._buckets = {
            "metar": TokenBucket(4.0, 8),
            "iem": TokenBucket(1.0, 2),
        }

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, source: str, url: str, params: dict[str, Any] | None = None,
                  max_retries: int = 2, expect_json: bool = True) -> Fetched:
        bucket = self._buckets.get(source)
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            if bucket is not None:
                await bucket.acquire()
            try:
                resp = await self._client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= max_retries:
                    raise ApiError(f"{source} transport error: {exc}") from exc
                await asyncio.sleep(min(2 ** attempt, 4) + random.random())
                continue

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                raise RateLimited(source, float(retry_after) if retry_after else None)
            if resp.status_code >= 500:
                last_exc = ApiError(f"{source} HTTP {resp.status_code}")
                if attempt >= max_retries:
                    raise last_exc
                await asyncio.sleep(min(2 ** attempt, 4) + random.random())
                continue
            if resp.status_code >= 400:
                raise ApiError(f"{source} HTTP {resp.status_code}: {resp.text[:300]}")

            fetched_at = datetime.now(timezone.utc)
            if not expect_json:
                return Fetched(resp.text, fetched_at)
            try:
                return Fetched(resp.json(), fetched_at)
            except ValueError as exc:
                raise ApiError(f"{source} returned non-JSON: {resp.text[:200]}") from exc

        raise ApiError(f"{source} failed") from last_exc


class MetarClient:
    """Recent observations from aviationweather.gov."""

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def latest(self, station_ids: Sequence[str], hours: int = 2) -> Fetched:
        if not station_ids:
            return Fetched([], datetime.now(timezone.utc))
        params = {"ids": ",".join(station_ids), "format": "json", "hours": hours}
        got = await self.http.get("metar", METAR_BASE, params)
        return Fetched(got.data if isinstance(got.data, list) else [], got.fetched_at)


class IemClient:
    """Historical ASOS/METAR archive from the Iowa Environmental Mesonet.

    Returns CSV including the raw METAR text, so the same remark parser used on
    live data reconstructs historical precise temperatures and extreme groups.
    """

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def history(self, station_id: str, start: date, end: date) -> Fetched:
        station = station_id.upper()
        # IEM indexes US stations without the leading 'K'.
        network_station = (station[1:] if len(station) == 4 and station.startswith("K")
                           else station)
        params = {
            "station": network_station,
            "data": "tmpf,metar",
            "year1": start.year, "month1": start.month, "day1": start.day,
            "year2": end.year, "month2": end.month, "day2": end.day,
            "tz": "UTC",
            "format": "onlycomma",
            "latlon": "no",
            "missing": "empty",
            "trace": "empty",
            "direct": "no",
            "report_type": "3",
        }
        return await self.http.get("iem", IEM_ASOS, params, expect_json=False,
                                   max_retries=1)

    @staticmethod
    def parse_csv(text: str) -> list[dict[str, Any]]:
        """Rows of {station, valid, rawOb} from an IEM CSV response."""
        rows: list[dict[str, Any]] = []
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            return rows
        header = [h.strip().lower() for h in lines[0].split(",")]
        try:
            i_station = header.index("station")
            i_valid = header.index("valid")
        except ValueError:
            return rows
        i_metar = header.index("metar") if "metar" in header else None
        for line in lines[1:]:
            # The raw METAR field can itself contain commas, so split with a cap
            # and let the trailing remainder stay intact.
            parts = line.split(",", len(header) - 1)
            if len(parts) < len(header):
                continue
            try:
                valid = datetime.strptime(parts[i_valid].strip(),
                                          "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            rows.append({
                "station": parts[i_station].strip().upper(),
                "valid": valid,
                "rawOb": parts[i_metar].strip() if i_metar is not None else "",
            })
        return rows
