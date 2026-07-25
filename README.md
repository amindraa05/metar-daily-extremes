# metar-daily-extremes

[![CI](https://github.com/amindraa05/metar-daily-extremes/actions/workflows/ci.yml/badge.svg)](https://github.com/amindraa05/metar-daily-extremes/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Reconstruct a weather station's **published daily high and low** from raw METAR — and
measure which rounding convention a source actually uses instead of guessing.

---

## The problem

You want yesterday's high for an airport station. You have the METAR reports. This should
be arithmetic.

It isn't, because two things are undocumented for essentially every source:

1. **Which reading counts.** The METAR body reports temperature as whole degrees Celsius.
   The remarks section carries a tenth-of-a-degree value in the T-group, plus 6-hour
   extreme groups that capture spikes no hourly observation recorded. Different sources
   use different subsets.
2. **How rounding works.** Whole-degree Fahrenheit can be derived from the precise value
   or from the already-rounded body value, and ties at exactly `.5` can break up or to
   even. These disagree by a full degree often enough to matter.

Multiply that by two plausible day boundaries — wall-clock midnight, or local *standard*
time midnight, which several US climate products use — and there are **twelve candidate
conventions**. Picking the one that sounds right is how you get a pipeline that looks
healthy and is quietly wrong.

This library implements all twelve and lets you measure which one a source uses.

---

## Install

```bash
pip install git+https://github.com/amindraa05/metar-daily-extremes.git
```

Core parsing and computation have **no dependencies**. The optional HTTP clients need
`httpx`:

```bash
pip install "metar-daily-extremes[http] @ git+https://github.com/amindraa05/metar-daily-extremes.git"
```

---

## Compute a daily extreme

```python
from datetime import date
from metar_extremes import local_day_window, daily_extreme_report, parse_observation

observations = [parse_observation(row) for row in metar_json]
observations = [o for o in observations if o]

start, end = local_day_window(date(2026, 7, 26), "America/New_York")
high = daily_extreme_report(observations, start, end, kind="max", unit="F")
```

`local_day_window` handles daylight-saving transitions: a spring-forward day is 23 hours
long, and a naive `start + 24h` silently attributes an hour of observations to the wrong
day.

## Measure the convention instead of assuming it

Give it days whose published value you already know:

```python
from metar_extremes import Reference, reconcile

references = [
    Reference(date(2026, 7, 1), value=91),
    Reference(date(2026, 7, 2), value=89),
    # a band works too, for sources that publish ranges:
    Reference(date(2026, 7, 3), low=None, high=79),   # "79 or below"
]

result = reconcile(observations, references, "America/New_York",
                   kind="max", unit="F")

print(result.summary())
# f_from_precise|regular|local matched 1.000 over 28 days

if not result.decided_by_evidence:
    print(f"{result.tied_at_top} conventions tied — the sample cannot separate them")
```

`reconcile` **reports, it does not decide.** It will happily tell you the best convention
matches 0.6 of the time. Whether 0.6 is good enough is your policy, and a library that
silently applied a threshold would be hiding the only number that matters.

### The tie count is the point

Several conventions differ *only* on exact `.5` ties, which appear a handful of times a
month. A short sample frequently cannot distinguish them. When `tied_at_top > 1`, the
winner came from a documented preference order rather than from your data — and you should
know that before building on it.

This is not hypothetical. In the codebase this library was extracted from, ties were
initially broken by label sort order, which silently selected **banker's rounding** —
a convention no meteorological source uses — because `"_"` sorts before `"|"`. That is
curve-fitting the measurement apparatus itself. There is now an explicit
`RULE_PREFERENCE` and a regression test.

---

## Try it on a real station

```bash
pip install -e ".[http]"
python examples/reconcile_station.py KMIA America/New_York --days 30 --unit F
```

Without reference data it reports how often the twelve conventions **disagree with each
other**. If they all agree for your station and window, the choice does not matter and you
can stop. If they disagree on a third of days, you cannot skip the measurement.

Add `--reference highs.csv` (columns `date,value`) to score them properly.

---

## A finding worth repeating

Folding the 6-hour extreme groups into the daily extreme looks obviously correct — those
groups exist precisely to record extremes that fall between routine reports, and omitting
them means systematically missing spikes.

Measured against real published values, it made accuracy **worse at every station tested**.
One station's maximum fell from a perfect match rate to 0.588. The source evidently derives
its daily extreme from routine observations alone.

The same happened with local-standard-time day boundaries: equally plausible, equally
wrong.

Both remain available and scoreable rather than deleted, so if a source ever changes its
convention the measurement says so instead of the pipeline quietly degrading. That is why
`DEFAULT_EXTREME_SOURCE` is `regular` — it is the one that measured better, not the one
that sounded better.

---

## API

| Module | What it does |
|---|---|
| `metar_extremes.units` | Six rounding conventions, `to_official_integer`, half-up rounding that survives float noise |
| `metar_extremes.metar` | T-group, 6-hour and 24-hour remark parsing; observation normalisation |
| `metar_extremes.windows` | Local day windows, DST-correct, two boundary conventions |
| `metar_extremes.extremes` | Daily extreme computation, corroboration counting |
| `metar_extremes.reconcile` | Scores all twelve conventions against known values |
| `metar_extremes.sources` | Optional async clients for aviationweather.gov and the IEM ASOS archive |

### Notes on `sources`

Each feed gets its own token bucket, because the rate limit belongs to the provider — one
global limiter makes the fast feed queue behind the slow one for no reason. HTTP 429 raises
immediately and never sleeps inside the client, so one provider's rate limit cannot stall
everything else a caller is running. Retries cover transport errors and 5xx only, with
exponential backoff and jitter; a 4xx means the request was wrong and repeating it will not
help.

---

## Development

```bash
git clone https://github.com/amindraa05/metar-daily-extremes.git
cd metar-daily-extremes
pip install -e ".[dev]"
pytest
```

72 tests, no network access required — the suite runs on synthetic observations and real
METAR strings, so it is fast and deterministic.

---

## Origin

Extracted from a larger weather-data reconciliation system, keeping the parts that are
generally useful: the parsing, the arithmetic, and the measurement harness. The lessons
embedded in the comments were paid for in that project, and the regression tests exist
because each one was once a real bug.

## License

MIT
