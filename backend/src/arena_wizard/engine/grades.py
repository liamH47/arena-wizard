"""Turn expert grade lists into one standardized score per card (decision 0007).

Each source's grades become z-scores over the set's spells it grades, so letter tiers and
numeric scales need no hand mapping. A card's score is the mean z over the sources that
grade it, re-standardized across the set, because the mean of imperfectly correlated
z-scores has a spread below one and the slope was set for unit spread.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from arena_wizard.domain.cards import Rarity


@dataclass(frozen=True, slots=True)
class GradeSource:
    """One reviewer's grades, resolved to 17Lands (front-face) names.

    `values` holds each graded card's position on the source's scale (higher is better);
    `raw` holds the grade as the reviewer wrote it, for display.
    """

    label: str
    values: Mapping[str, float]
    raw: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class GradeScores:
    """Standardized grade scores for a set.

    `z` covers every spell that at least one source grades. `rarity_z` is the mean z of the
    graded spells of each rarity, the scale an ungraded card is placed on. `raw` lists
    (source label, grade as written) for each graded card.
    """

    z: Mapping[str, float]
    rarity_z: Mapping[Rarity, float]
    raw: Mapping[str, tuple[tuple[str, str], ...]]
    labels: tuple[str, ...]


def _standardize(values: Mapping[str, float]) -> dict[str, float]:
    """z-scores with the population spread.

    Raises:
        ValueError: Fewer than two values, or all values equal, so no spread exists.
    """
    if len(values) < 2:
        raise ValueError("a grade source needs at least two graded cards")
    mean = statistics.fmean(values.values())
    sd = statistics.pstdev(values.values(), mu=mean)
    if sd == 0:
        raise ValueError("every grade is the same, so grades cannot rank cards")
    return {name: (v - mean) / sd for name, v in values.items()}


def grade_scores(
    sources: Sequence[GradeSource], rarity_of: Mapping[str, Rarity]
) -> GradeScores | None:
    """Combine grade sources into one standardized score per spell. Pure.

    Args:
        sources: The grade lists, already checked for coverage and scale when pasted.
        rarity_of: Rarity by name for the set's spells; other names are ignored.

    Returns:
        The scores, or None when there are no sources.

    Raises:
        ValueError: A source grades fewer than two spells or grades them all the same.
    """
    if not sources:
        return None
    per_card: dict[str, list[float]] = {}
    raw: dict[str, list[tuple[str, str]]] = {}
    for source in sources:
        graded = {n: v for n, v in source.values.items() if n in rarity_of}
        for name, score in _standardize(graded).items():
            per_card.setdefault(name, []).append(score)
            raw.setdefault(name, []).append((source.label, source.raw[name]))
    means = {name: statistics.fmean(zs) for name, zs in per_card.items()}
    z = _standardize(means) if len(sources) > 1 else means
    by_rarity: dict[Rarity, list[float]] = {}
    for name, score in z.items():
        by_rarity.setdefault(rarity_of[name], []).append(score)
    return GradeScores(
        z=z,
        rarity_z={rarity: statistics.fmean(scores) for rarity, scores in by_rarity.items()},
        raw={name: tuple(pairs) for name, pairs in raw.items()},
        labels=tuple(source.label for source in sources),
    )
