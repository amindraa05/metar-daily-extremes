"""Measure which convention a source actually uses.

The problem this solves: you have raw METAR observations for a station, and a
handful of daily high/low values that some authority published for the same
days. You want to compute those published values yourself for days the authority
has not covered -- but you do not know which rounding rule, which reading set,
or which day boundary it uses, and no documentation says.

There are 3 rounding rules x 2 extreme sources x 2 day boundaries = 12 candidate
conventions. `reconcile` scores all twelve against the reference values and
reports the winner, the runner-up, and -- importantly -- how many conventions
tied at the top.

That tie count is not decoration. Several conventions differ only on exact .5
ties, which appear a few times a month, so a short sample frequently cannot
distinguish them. When the count is greater than one, the choice rests on
`units.RULE_PREFERENCE` rather than on evidence, and the caller deserves to know
that before relying on it.

Design note: reconcile deliberately reports rather than decides. It will happily
tell you the best convention matches 0.6 of the time. Whether 0.6 is good enough
is the caller's policy, and a library that silently applied a threshold would be
hiding the only number that matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

from .extremes import EXTREME_REGULAR, EXTREME_SOURCES, daily_extreme_report
from .units import rule_rank, rules_for_unit, value_in_range
from .windows import BOUNDARY_LOCAL, DAY_BOUNDARIES, local_day_window


@dataclass(frozen=True)
class Reference:
    """One day whose published value is known.

    Give either an exact `value`, or a `low`/`high` band when the source
    published a range. An open end is expressed as None, so "79 or below" is
    `Reference(day, low=None, high=79)`.
    """

    day: date
    value: int | None = None
    low: float | None = None
    high: float | None = None

    def matches(self, computed: int) -> bool:
        if self.value is not None:
            return computed == self.value
        if self.low is None and self.high is None:
            raise ValueError(f"reference for {self.day} has neither value nor bounds")
        return value_in_range(computed, self.low, self.high)

    def describe(self) -> str:
        if self.value is not None:
            return str(self.value)
        lo = "-inf" if self.low is None else f"{self.low:g}"
        hi = "+inf" if self.high is None else f"{self.high:g}"
        return f"[{lo}, {hi}]"


@dataclass
class Miss:
    day: date
    computed: int
    expected: str


@dataclass
class ConventionScore:
    rule: str
    extreme_source: str
    boundary: str
    matches: int = 0
    total: int = 0
    misses: list[Miss] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.matches / self.total if self.total else 0.0

    @property
    def label(self) -> str:
        return f"{self.rule}|{self.extreme_source}|{self.boundary}"


@dataclass
class ReconcileResult:
    """What the measurement found. `scored_days` is the sample size that matters."""

    unit: str
    kind: str
    best: ConventionScore | None = None
    runner_up: ConventionScore | None = None
    tied_at_top: int = 0
    scores: list[ConventionScore] = field(default_factory=list)
    skipped_days: list[tuple[date, str]] = field(default_factory=list)
    note: str = ""

    @property
    def match_rate(self) -> float:
        return self.best.rate if self.best else 0.0

    @property
    def scored_days(self) -> int:
        return self.best.total if self.best else 0

    @property
    def decided_by_evidence(self) -> bool:
        """False when the sample could not separate the top conventions."""
        return self.tied_at_top == 1

    def summary(self) -> str:
        if self.best is None:
            return f"no result: {self.note}"
        tie = "" if self.decided_by_evidence else \
            f"; {self.tied_at_top} conventions tied (chosen by preference, not evidence)"
        return (f"{self.best.label} matched {self.match_rate:.3f} over "
                f"{self.scored_days} days{tie}")


def reconcile(observations: Sequence[dict[str, Any]],
              references: Sequence[Reference],
              tz_name: str,
              kind: str,
              unit: str,
              min_obs_per_day: int = 12) -> ReconcileResult:
    """Score every candidate convention against known published values.

    Args:
        observations: dicts as produced by `metar.parse_observation` --
            each needs `obs_time`, `temp_c`, and ideally `temp_c_body`.
        references: days whose published value is known.
        tz_name: IANA zone for the station, e.g. "America/New_York".
        kind: 'max' or 'min'.
        unit: 'F' or 'C' -- the unit the source publishes in.
        min_obs_per_day: days with fewer readings than this are skipped rather
            than scored. A day with three observations cannot distinguish
            conventions, and letting it vote adds noise while inflating the
            apparent sample size.

    Returns a `ReconcileResult`; it never raises on thin data, it reports it.
    """
    candidates = [
        (rule, source, boundary)
        for rule in rules_for_unit(unit)
        for source in EXTREME_SOURCES
        for boundary in DAY_BOUNDARIES
    ]
    scores = {
        f"{r}|{s}|{b}": ConventionScore(r, s, b) for r, s, b in candidates
    }
    result = ReconcileResult(unit=unit.upper(), kind=kind,
                             scores=list(scores.values()))

    if not references:
        result.note = "no reference days supplied"
        return result

    for ref in references:
        base_start, base_end = local_day_window(ref.day, tz_name)
        in_window = [o for o in observations
                     if o.get("obs_time") is not None
                     and base_start <= o["obs_time"] < base_end]
        if len(in_window) < min_obs_per_day:
            result.skipped_days.append(
                (ref.day, f"only {len(in_window)} observations "
                          f"(< {min_obs_per_day})"))
            continue

        for rule, source, boundary in candidates:
            start, end = local_day_window(ref.day, tz_name, boundary)
            computed = daily_extreme_report(observations, start, end, kind, unit,
                                            rule, source)
            if computed is None:
                continue
            score = scores[f"{rule}|{source}|{boundary}"]
            score.total += 1
            if ref.matches(computed):
                score.matches += 1
            else:
                score.misses.append(Miss(ref.day, computed, ref.describe()))

    ranked = sorted(scores.values(), key=_rank_key)
    best = ranked[0]
    if best.total == 0:
        result.note = ("no day had enough observations to score"
                       if result.skipped_days else "no convention produced a value")
        return result

    result.best = best
    result.runner_up = ranked[1] if len(ranked) > 1 else None
    result.tied_at_top = sum(1 for s in scores.values()
                             if s.total > 0 and abs(s.rate - best.rate) < 1e-9)
    result.note = result.summary()
    return result


def _rank_key(score: ConventionScore) -> tuple:
    """Sort key: accuracy first, then evidence, then the simplest convention.

    Ties break toward half-up rounding of routine observations on the wall-clock
    day. Letting a tie be settled by label ordering would curve-fit the
    measurement apparatus itself -- and in the original implementation it did,
    briefly selecting banker's rounding purely because of how the labels sorted.
    """
    return (
        -score.rate,
        -score.total,
        0 if score.extreme_source == EXTREME_REGULAR else 1,
        0 if score.boundary == BOUNDARY_LOCAL else 1,
        rule_rank(score.rule),
        score.label,
    )
