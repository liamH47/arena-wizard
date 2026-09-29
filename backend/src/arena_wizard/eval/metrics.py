"""Statistics for the evaluation report. All pure; randomness is seeded by the caller.

Every level comes with an interval and its sample size, because at 600 pools an
agreement rate has a standard error near two points and a bare number would overstate
what the harness knows.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

Z95 = 1.959964


@dataclass(frozen=True, slots=True)
class Estimate:
    """A value with its 95% interval and sample size; None when there is no sample."""

    value: float | None
    low: float | None
    high: float | None
    n: int


def wilson(successes: int, trials: int) -> Estimate:
    """A proportion with its Wilson score interval."""
    if trials == 0:
        return Estimate(None, None, None, 0)
    p = successes / trials
    denominator = 1 + Z95**2 / trials
    centre = (p + Z95**2 / (2 * trials)) / denominator
    half = Z95 * math.sqrt(p * (1 - p) / trials + Z95**2 / (4 * trials**2)) / denominator
    return Estimate(p, centre - half, centre + half, trials)


def weighted_share(hits: Sequence[bool], weights: Sequence[float]) -> float | None:
    """The weighted share of hits; None when every weight is zero or there are none."""
    total = sum(weights)
    return sum(w for hit, w in zip(hits, weights, strict=True) if hit) / total if total else None


@dataclass(frozen=True, slots=True)
class Group:
    """One unit of a resampled comparison: wins and games (for example one pool)."""

    wins: int
    games: int


def _pooled_rate(groups: Sequence[Group]) -> float:
    """Total wins over total games; callers guarantee at least one game."""
    return sum(g.wins for g in groups) / sum(g.games for g in groups)


def rate_difference(
    first: Sequence[Group], second: Sequence[Group], rng: random.Random, resamples: int = 1000
) -> Estimate:
    """Pooled win rate of `first` minus `second`, with a percentile bootstrap interval.

    Resamples units (pools), not games, because games within a pool share a deck and a
    player. Units with no games are dropped first. The sample size reported is the number
    of units with games in both groups.
    """
    first = [g for g in first if g.games]
    second = [g for g in second if g.games]
    n = len(first) + len(second)
    if not first or not second:
        return Estimate(None, None, None, n)
    point = _pooled_rate(first) - _pooled_rate(second)
    draws = sorted(
        _pooled_rate([rng.choice(first) for _ in first])
        - _pooled_rate([rng.choice(second) for _ in second])
        for _ in range(resamples)
    )
    return Estimate(
        point, draws[int(0.025 * (resamples - 1))], draws[int(0.975 * (resamples - 1))], n
    )


def mean_difference(
    first: Sequence[float], second: Sequence[float], rng: random.Random, resamples: int = 1000
) -> Estimate:
    """Mean of `first` minus mean of `second`, with a percentile bootstrap interval."""
    n = len(first) + len(second)
    if not first or not second:
        return Estimate(None, None, None, n)
    point = sum(first) / len(first) - sum(second) / len(second)
    draws = sorted(
        sum(rng.choice(first) for _ in first) / len(first)
        - sum(rng.choice(second) for _ in second) / len(second)
        for _ in range(resamples)
    )
    return Estimate(
        point, draws[int(0.025 * (resamples - 1))], draws[int(0.975 * (resamples - 1))], n
    )


def mean(values: Sequence[float]) -> Estimate:
    """A mean with a normal-approximation interval."""
    n = len(values)
    if n == 0:
        return Estimate(None, None, None, 0)
    m = sum(values) / n
    if n == 1:
        return Estimate(m, None, None, 1)
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    half = Z95 * sd / math.sqrt(n)
    return Estimate(m, m - half, m + half, n)


@dataclass(frozen=True, slots=True)
class Binomial:
    """A covariate value with the games and wins observed at it."""

    x: float
    games: int
    wins: int


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Solve a small linear system by Gaussian elimination; None when it is singular."""
    n = len(vector)
    rows = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [rows[i][n] / rows[i][i] for i in range(n)]


@dataclass(frozen=True, slots=True)
class Observation:
    """Covariates with the games and wins observed at them."""

    xs: tuple[float, ...]
    games: int
    wins: int


def logistic_fit(rows: Sequence[Observation], iterations: int = 25) -> tuple[float, ...] | None:
    """Fit P(win) = sigmoid(b0 + b . x) by Newton's method; return (b0, b1, ...). Pure.

    Returns None when there are no games or the design is singular (for example a
    covariate that never varies). Stops early if the curvature degenerates, as it does
    under perfect separation, rather than dividing by it.
    """
    usable = [r for r in rows if r.games > 0]
    if not usable:
        return None
    k = len(usable[0].xs) + 1
    beta = [0.0] * k
    for _ in range(iterations):
        gradient = [0.0] * k
        hessian = [[0.0] * k for _ in range(k)]
        for r in usable:
            x = (1.0, *r.xs)
            prob = 1 / (1 + math.exp(-sum(b * v for b, v in zip(beta, x, strict=True))))
            residual = r.wins - r.games * prob
            weight = r.games * prob * (1 - prob)
            for i in range(k):
                gradient[i] += residual * x[i]
                for j in range(k):
                    hessian[i][j] += weight * x[i] * x[j]
        step = _solve(hessian, gradient)
        if step is None:
            return None if beta == [0.0] * k else tuple(beta)
        beta = [b + s for b, s in zip(beta, step, strict=True)]
    return tuple(beta)


def logistic_slope(points: Sequence[Binomial], iterations: int = 25) -> float | None:
    """Fit P(win) = sigmoid(a + b x) and return b; None without two distinct x values."""
    usable = [p for p in points if p.games > 0]
    if len({p.x for p in usable}) < 2:
        return None
    fit = logistic_fit([Observation((p.x,), p.games, p.wins) for p in usable], iterations)
    return None if fit is None else fit[1]


def auc(points: Sequence[Binomial]) -> float | None:
    """The probability a random win has a higher x than a random loss (ties count half).

    Returns None without both wins and losses.
    """
    wins = sum(p.wins for p in points)
    losses = sum(p.games - p.wins for p in points)
    if wins == 0 or losses == 0:
        return None
    concordant = 0.0
    losses_below = 0
    for x in sorted({p.x for p in points}):
        at = [p for p in points if p.x == x]
        w = sum(p.wins for p in at)
        loss = sum(p.games - p.wins for p in at)
        concordant += w * losses_below + 0.5 * w * loss
        losses_below += loss
    return concordant / (wins * losses)


def standardize(values: Sequence[float]) -> list[float]:
    """Z-scores; all zeros when the values do not vary."""
    m = sum(values) / len(values)
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / len(values))
    return [(v - m) / sd if sd else 0.0 for v in values]


def jaccard(a: dict[str, int], b: dict[str, int]) -> float | None:
    """Multiset Jaccard similarity: shared copies over copies in either."""
    names = set(a) | set(b)
    union = sum(max(a.get(n, 0), b.get(n, 0)) for n in names)
    shared = sum(min(a.get(n, 0), b.get(n, 0)) for n in names)
    return shared / union if union else None


def paired_rate_difference(
    pairs: Sequence[tuple[Group, Group]], rng: random.Random, resamples: int = 1000
) -> Estimate:
    """Pooled win rate of the first of each pair minus the second, resampling pairs jointly.

    Used when both groups come from the same unit (one pool played in two colors), so the
    two sides must be resampled together. Pairs where either side has no games are
    dropped; n counts pairs.
    """
    usable = [(a, b) for a, b in pairs if a.games and b.games]
    if not usable:
        return Estimate(None, None, None, 0)

    def difference(sample: Sequence[tuple[Group, Group]]) -> float:
        return _pooled_rate([a for a, _ in sample]) - _pooled_rate([b for _, b in sample])

    draws = sorted(difference([rng.choice(usable) for _ in usable]) for _ in range(resamples))
    return Estimate(
        difference(usable),
        draws[int(0.025 * (resamples - 1))],
        draws[int(0.975 * (resamples - 1))],
        len(usable),
    )


@dataclass(frozen=True, slots=True)
class Scored:
    """One build's two scores (engine and a baseline) with its games and wins."""

    engine: float
    baseline: float
    games: int
    wins: int


def auc_margin(
    clusters: Sequence[Sequence[Scored]], rng: random.Random, resamples: int = 500
) -> Estimate:
    """How much better the engine's score ranks wins over losses than the baseline's.

    AUC(engine) minus AUC(baseline) over every build, with a bootstrap that resamples
    whole pools, because builds of one pool share a player. n counts pools.
    """
    usable = [c for c in clusters if c]

    def margin(sample: Sequence[Sequence[Scored]]) -> float | None:
        flat = [s for c in sample for s in c]
        engine = auc([Binomial(s.engine, s.games, s.wins) for s in flat])
        baseline = auc([Binomial(s.baseline, s.games, s.wins) for s in flat])
        return None if engine is None or baseline is None else engine - baseline

    point = margin(usable)
    if point is None:
        return Estimate(None, None, None, len(usable))
    draws = sorted(
        m
        for m in (margin([rng.choice(usable) for _ in usable]) for _ in range(resamples))
        if m is not None
    )
    return Estimate(
        point,
        draws[int(0.025 * (len(draws) - 1))],
        draws[int(0.975 * (len(draws) - 1))],
        len(usable),
    )
