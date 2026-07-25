"""Fetch a station's METAR history and show what the conventions disagree about.

    # How much do the twelve conventions disagree for Miami's daily maximum?
    python examples/reconcile_station.py KMIA America/New_York --days 30 --unit F

    # Same, but score them against values you know were published.
    python examples/reconcile_station.py KMIA America/New_York --days 30 --unit F \
        --reference miami_highs.csv

The reference CSV is two columns, no header needed beyond `date,value`:

    date,value
    2026-07-01,91
    2026-07-02,89

Requires the optional HTTP extra:  pip install -e ".[http]"
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from metar_extremes import (  # noqa: E402
    DAY_BOUNDARIES,
    EXTREME_SOURCES,
    Reference,
    daily_extreme_report,
    local_day_window,
    parse_raw_observation,
    reconcile,
    rules_for_unit,
)
from metar_extremes.sources import HttpClient, IemClient  # noqa: E402


async def fetch(station: str, start: date, end: date) -> list[dict]:
    async with HttpClient() as http:
        got = await IemClient(http).history(station, start, end + timedelta(days=1))
    rows = IemClient.parse_csv(got.data if isinstance(got.data, str) else "")
    out = []
    for row in rows:
        obs = parse_raw_observation(row["rawOb"], row["valid"], station)
        if obs is not None:
            out.append(obs)
    return out


def load_references(path: Path) -> list[Reference]:
    refs = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            refs.append(Reference(date.fromisoformat(row["date"].strip()),
                                  value=int(row["value"])))
    return refs


def spread_report(observations, days, tz, kind, unit) -> None:
    """How often the conventions produce different answers for the same day.

    Useful without any reference data: if every convention agrees, the choice
    does not matter for this station. If they disagree on a third of days, you
    cannot skip the measurement.
    """
    combos = [(r, s, b) for r in rules_for_unit(unit)
              for s in EXTREME_SOURCES for b in DAY_BOUNDARIES]
    disagreements = 0
    scored = 0
    spread_counts: Counter[int] = Counter()

    for day in days:
        values = set()
        for rule, source, boundary in combos:
            start, end = local_day_window(day, tz, boundary)
            v = daily_extreme_report(observations, start, end, kind, unit, rule, source)
            if v is not None:
                values.add(v)
        if not values:
            continue
        scored += 1
        spread_counts[max(values) - min(values)] += 1
        if len(values) > 1:
            disagreements += 1

    if not scored:
        print("  no day produced a value -- is the station id right?")
        return
    pct = 100.0 * disagreements / scored
    print(f"  days scored              : {scored}")
    print(f"  days where they disagree : {disagreements} ({pct:.0f}%)")
    for gap in sorted(spread_counts):
        print(f"    spread of {gap} deg{'' if gap == 1 else 's'}: "
              f"{spread_counts[gap]} days")
    if disagreements == 0:
        print("  -> every convention agrees here; the choice does not matter"
              " for this station and window.")
    else:
        print("  -> the choice changes the answer. Supply --reference to settle it.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("station", help="ICAO id, e.g. KMIA")
    ap.add_argument("tz", help="IANA timezone, e.g. America/New_York")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--kind", choices=("max", "min"), default="max")
    ap.add_argument("--unit", choices=("F", "C"), default="F")
    ap.add_argument("--reference", type=Path,
                    help="CSV of known published values (date,value)")
    ap.add_argument("--min-obs", type=int, default=12,
                    help="skip days with fewer observations than this")
    args = ap.parse_args()

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days)
    print(f"Fetching {args.station} from {start} to {end} ...")
    observations = asyncio.run(fetch(args.station, start, end))
    print(f"  {len(observations)} observations parsed\n")
    if not observations:
        print("Nothing to analyse.")
        return 1

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    print(f"Convention spread for {args.kind} in degrees {args.unit}:")
    spread_report(observations, days, args.tz, args.kind, args.unit)

    if not args.reference:
        print("\nNo --reference supplied, so no convention can be confirmed.")
        return 0

    refs = load_references(args.reference)
    print(f"\nScoring against {len(refs)} reference days ...")
    result = reconcile(observations, refs, args.tz, kind=args.kind, unit=args.unit,
                       min_obs_per_day=args.min_obs)
    print(f"  {result.summary()}")
    if result.best is None:
        return 1

    print("\n  Top conventions:")
    for score in sorted(result.scores, key=lambda s: (-s.rate, s.label))[:5]:
        if score.total:
            print(f"    {score.rate:.3f}  {score.matches:>3}/{score.total:<3}  "
                  f"{score.label}")
    if result.best.misses:
        print("\n  Days it could not reproduce:")
        for miss in result.best.misses[:10]:
            print(f"    {miss.day}  computed {miss.computed}, "
                  f"published {miss.expected}")
    if not result.decided_by_evidence:
        print(f"\n  WARNING: {result.tied_at_top} conventions tied at the top. "
              f"This sample cannot tell them apart; the winner was chosen by\n"
              f"  preference, not evidence. Widen --days before relying on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
