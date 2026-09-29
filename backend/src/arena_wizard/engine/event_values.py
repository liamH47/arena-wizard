"""Card values when the public Sealed file is absent or embargoed (decision 0007).

Sources stack as a Bayesian chain in points of game-in-hand win rate (q), each weighted
by its inverse variance, so a thin sample tightens what is already known instead of
replacing it:

1. the prior: the card's expert grades, or its rarity's average grade when the reviewers
   skipped it, or, with no grades at all, its rarity's average in the top data layer;
2. Premier Draft win rates, scaled to sealed, with a structural draft-to-sealed error;
3. Arena Direct (or pasted Sealed) win rates, with binomial error.

Each layer is measured against its own format mean, because Arena Direct entrants win more
than draft players. Improvement when drawn comes from the top layer that has not-seen
games, and is left out when none does.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from arena_wizard.domain.cards import Card, Rarity
from arena_wizard.domain.decks import CardValue, LayerShare, ValueBasis
from arena_wizard.domain.scoring import ScoringConfig
from arena_wizard.domain.stats import CardCounts, Snapshot
from arena_wizard.engine.grades import GradeScores
from arena_wizard.engine.roles import Role, classify
from arena_wizard.engine.values import FormatMeans, format_means, iwd_points, shrink


@dataclass(frozen=True, slots=True)
class DataLayer:
    """One source of win rates: its snapshot, its format means, and its name for labels."""

    name: str
    snapshot: Snapshot
    means: FormatMeans
    proxy: bool


def data_layer(
    name: str, snapshot: Snapshot | None, rarity_of: Mapping[str, Rarity], proxy: bool
) -> DataLayer | None:
    """Wrap a snapshot as a layer, or None when it has no in-hand games. Pure."""
    if snapshot is None:
        return None
    means = format_means(snapshot, rarity_of)
    return None if means is None else DataLayer(name, snapshot, means, proxy)


def _bonus(card: Card, config: ScoringConfig) -> float:
    """What sealed adds beyond a draft grade or draft rate: removal, and rarity."""
    event = config.event
    bonus = event.removal_bonus if Role.REMOVAL in classify(card) else 0.0
    if card.rarity in (Rarity.RARE, Rarity.MYTHIC):
        bonus += event.rare_bonus
    return bonus


def _usable(counts: CardCounts | None) -> CardCounts | None:
    return counts if counts is not None and counts.games_gih > 0 else None


def _prior(
    card: Card, grades: GradeScores | None, top: DataLayer | None, config: ScoringConfig
) -> tuple[float, float, ValueBasis, str]:
    """The chain's starting point: mean, variance, basis, and label."""
    event = config.event
    name = card.front_name
    if grades is not None:
        if name in grades.z:
            mean = event.center + event.slope * grades.z[name] + _bonus(card, config)
            return mean, event.sigma**2, ValueBasis.GRADES, "draft grades"
        # An ungraded card sits at its rarity's average grade, one grade spread wide.
        z = grades.rarity_z.get(card.rarity, 0.0)
        mean = event.center + event.slope * z + _bonus(card, config)
        return (
            mean,
            event.sigma**2 + event.slope**2,
            ValueBasis.RARITY_GRADE,
            f"{card.rarity.value} average grade",
        )
    if top is None:
        raise ValueError("event values need grades or at least one data layer")
    m = top.means.gih
    rarity_mean = top.means.gih_by_rarity.get(card.rarity, m)
    variance = 100**2 * rarity_mean * (1 - rarity_mean) / config.shrinkage.prior_games
    return 100 * (rarity_mean - m), variance, ValueBasis.RARITY, f"{card.rarity.value} average"


def _observation(
    layer: DataLayer, counts: CardCounts, card: Card, config: ScoringConfig
) -> tuple[float, float]:
    """A layer's reading of one card, in sealed q, and its variance."""
    m = layer.means.gih
    rate = counts.wins_gih / counts.games_gih
    sampling = 100**2 * m * (1 - m) / counts.games_gih
    if not layer.proxy:
        return 100 * (rate - m), sampling
    event = config.event
    return (
        event.proxy_slope * 100 * (rate - m) + _bonus(card, config),
        event.proxy_sigma**2 + event.proxy_slope**2 * sampling,
    )


def _iwd(layers: tuple[DataLayer, ...], card: Card, config: ScoringConfig) -> tuple[float, bool]:
    """Weighted improvement-when-drawn points from the top layer with not-seen games."""
    for layer in reversed(layers):
        counts = _usable(layer.snapshot.cards.get(card.front_name))
        if counts is None or counts.games_gns == 0 or layer.means.iwd is None:
            continue
        prior = layer.means.gih_by_rarity.get(card.rarity, layer.means.gih)
        used = shrink(counts.wins_gih, counts.games_gih, prior, config.shrinkage.prior_games)
        points = config.weights.iwd * iwd_points(counts, card.rarity, used, layer.means, config)
        return (config.event.proxy_slope * points if layer.proxy else points), True
    return 0.0, False


def event_value(
    card: Card,
    grades: GradeScores | None,
    proxy: DataLayer | None,
    direct: DataLayer | None,
    config: ScoringConfig,
) -> CardValue:
    """Value one card through the chain. Pure.

    Args:
        card: The card, for its rarity and roles.
        grades: Standardized grades for the set, or None when none are pasted.
        proxy: Premier Draft win rates, or None.
        direct: Arena Direct or pasted Sealed win rates, or None.
        config: The scoring configuration; its `event` section sets the chain.

    Returns:
        The value, its standard error, its basis, and each layer's share of the weight.

    Raises:
        ValueError: There are no grades and no data layers, so nothing values the card.
    """
    layers = tuple(layer for layer in (proxy, direct) if layer is not None)
    mean0, var0, basis, prior_label = _prior(card, grades, layers[-1] if layers else None, config)
    readings: list[tuple[str, float, float, DataLayer]] = []
    for layer in layers:
        counts = _usable(layer.snapshot.cards.get(card.front_name))
        if counts is not None:
            x, v = _observation(layer, counts, card, config)
            readings.append((layer.name, x, v, layer))
    precision = 1 / var0 + sum(1 / v for _, _, v, _ in readings)
    variance = 1 / precision
    mean = variance * (mean0 / var0 + sum(x / v for _, x, v, _ in readings))
    iwd, has_iwd = _iwd(layers, card, config)
    shares = (LayerShare(prior_label, variance / var0),) + tuple(
        LayerShare(name, variance / v) for name, _, v, _ in readings
    )
    top = readings[-1][3] if readings else None
    top_counts = top.snapshot.cards[card.front_name] if top else None
    if top is not None:
        basis = ValueBasis.DRAFT_PROXY if top.proxy else ValueBasis.WIN_RATES
    source = top.name if top else prior_label
    if top is not None and not has_iwd:
        source += "; improvement when drawn not available"
    return CardValue(
        name=card.front_name,
        q=mean + iwd,
        observed=top_counts.gih_wr if top_counts else None,
        used=None,
        prior_share=variance / var0,
        games=top_counts.games_gih if top_counts else 0,
        source=source,
        se=math.sqrt(variance),
        basis=basis,
        layers=shares,
        grades=grades.raw.get(card.front_name, ()) if grades else (),
    )
