"""What each card and color pair is worth, with sample-size shrinkage.

A card's game-in-hand win rate is shrunk toward the mean of its own rarity, because
mythics accrue about a tenth of a common's games and a format-wide target would tax them.
Its value `q` is in win-rate points above the format mean, plus a centered
improvement-when-drawn term. A card with no games is worth its rarity's mean, labelled as
such. Every value records the observed rate, the rate used, and how much of it is prior.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from arena_wizard.domain.cards import Card, Rarity
from arena_wizard.domain.decks import CardValue
from arena_wizard.domain.scoring import ScoringConfig
from arena_wizard.domain.stats import CardCounts, PairCounts, Snapshot
from arena_wizard.engine.roles import Role, classify


def shrink(wins: int, games: int, prior: float, prior_games: float) -> float:
    """Add `prior_games` pseudo-games at the prior rate, then take the rate. Pure."""
    return (wins + prior * prior_games) / (games + prior_games)


@dataclass(frozen=True, slots=True)
class FormatMeans:
    """Games-weighted means that shrinkage pulls toward and values are measured from.

    `iwd` is None, and `gns_by_rarity` empty, when the source has no not-seen games at all
    (a pasted export without the Not Seen columns); values then use win rate in hand only.
    """

    gih: float
    gih_by_rarity: Mapping[Rarity, float]
    gns_by_rarity: Mapping[Rarity, float]
    iwd: float | None
    pair: float | None


def _weighted_mean(pairs: Iterable[tuple[int, int]]) -> float | None:
    """Total wins over total games for (wins, games) pairs; None with no games."""
    wins = games = 0
    for w, g in pairs:
        wins += w
        games += g
    return wins / games if games else None


def format_means(snapshot: Snapshot, rarity_of: Mapping[str, Rarity]) -> FormatMeans | None:
    """Compute the format's means from a snapshot. Pure.

    Args:
        snapshot: The statistics.
        rarity_of: Rarity by 17Lands card name; cards missing from it are ignored.

    Returns:
        The means, or None when the snapshot has no game-in-hand games at all.
    """
    known = {name: c for name, c in snapshot.cards.items() if name in rarity_of}
    gih = _weighted_mean((c.wins_gih, c.games_gih) for c in known.values())
    gns = _weighted_mean((c.wins_gns, c.games_gns) for c in known.values())
    if gih is None:
        return None
    by_rarity: dict[Rarity, float] = {}
    gns_by_rarity: dict[Rarity, float] = {}
    for rarity in {rarity_of[name] for name in known}:
        members = [c for name, c in known.items() if rarity_of[name] is rarity]
        rarity_gih = _weighted_mean((c.wins_gih, c.games_gih) for c in members)
        rarity_gns = _weighted_mean((c.wins_gns, c.games_gns) for c in members)
        # A rarity with no games falls back to the format; one that won nothing keeps 0.0.
        by_rarity[rarity] = gih if rarity_gih is None else rarity_gih
        if gns is not None:
            gns_by_rarity[rarity] = gns if rarity_gns is None else rarity_gns
    pair = _weighted_mean((p.wins, p.games) for p in snapshot.pairs.values())
    return FormatMeans(
        gih=gih,
        gih_by_rarity=by_rarity,
        gns_by_rarity=gns_by_rarity,
        iwd=None if gns is None else gih - gns,
        pair=pair,
    )


def iwd_points(
    counts: CardCounts,
    rarity: Rarity,
    used: float,
    means: FormatMeans,
    config: ScoringConfig,
) -> float:
    """Improvement when drawn above its rarity's, in points, before the IWD weight. Pure.

    The not-seen rate shrinks toward the rarity's, so a card with in-hand games but none
    unseen gets the Bayesian estimate from its in-hand rate alone. Zero when the source has
    no not-seen games at all, so a missing column never becomes a made-up term.
    """
    if means.iwd is None:
        return 0.0
    prior = means.gih_by_rarity.get(rarity, means.gih)
    gns_prior = means.gns_by_rarity.get(rarity, used - means.iwd)
    gns_used = shrink(
        counts.wins_gns, counts.games_gns, gns_prior, config.shrinkage.iwd_prior_games
    )
    return 100 * ((used - gns_used) - (prior - gns_prior))


def card_value(
    name: str,
    rarity: Rarity,
    counts: CardCounts | None,
    means: FormatMeans | None,
    config: ScoringConfig,
    source_label: str,
) -> CardValue:
    """Value one card. Pure.

    Args:
        name: The 17Lands (front-face) name.
        rarity: Its rarity, which picks the shrinkage target.
        counts: Its counts, or None when the source never saw it.
        means: The format means, or None when there is no data at all.
        config: Supplies the prior sizes and the IWD weight.
        source_label: Names the source for the breakdown.

    Returns:
        The value, labelled with where it came from.
    """
    k = config.shrinkage.prior_games
    if means is None:
        return CardValue(
            name, 0.0, None, None, None, 0, "no data loaded", 100 * math.sqrt(0.25 / k)
        )
    prior = means.gih_by_rarity.get(rarity, means.gih)
    if counts is None or counts.games_gih == 0:
        se = 100 * math.sqrt(prior * (1 - prior) / k)
        return CardValue(
            name, 100 * (prior - means.gih), None, prior, 1.0, 0, f"{rarity.value} average", se
        )
    used = shrink(counts.wins_gih, counts.games_gih, prior, k)
    q = 100 * (used - means.gih) + config.weights.iwd * iwd_points(
        counts, rarity, used, means, config
    )
    se = 100 * math.sqrt(used * (1 - used) / (counts.games_gih + k))
    return CardValue(
        name=name,
        q=q,
        observed=counts.gih_wr,
        used=used,
        prior_share=k / (counts.games_gih + k),
        games=counts.games_gih,
        source=source_label,
        se=se,
    )


@dataclass(frozen=True, slots=True)
class PairValue:
    """A color pair's win-rate term, in points above the mean of all pairs."""

    colors: str
    points: float
    observed: float | None
    used: float | None
    prior_share: float | None
    games: int


def pair_value(
    colors: str, counts: PairCounts | None, means: FormatMeans | None, config: ScoringConfig
) -> PairValue:
    """Value a deck's main colors from how decks of those colors did. Pure.

    Returns a zero term with no games behind it, never a guess.
    """
    if means is None or means.pair is None or counts is None or counts.games == 0:
        return PairValue(colors, 0.0, None, None, None, 0)
    k = config.shrinkage.pair_prior_games
    used = shrink(counts.wins, counts.games, means.pair, k)
    return PairValue(
        colors=colors,
        points=100 * (used - means.pair),
        observed=counts.win_rate,
        used=used,
        prior_share=k / (counts.games + k),
        games=counts.games,
    )


def estimate_prior_games(counts: Iterable[CardCounts], min_games: int = 200) -> float | None:
    """Estimate how many pseudo-games of prior fit the data, by the method of moments. Pure.

    The spread of observed win rates is the spread of true win rates plus sampling noise;
    subtracting the average sampling variance leaves the true spread, and the prior size
    that matches it is mean(p(1-p)) / true variance.

    Args:
        counts: Every card's counts.
        min_games: Cards with fewer game-in-hand games are left out.

    Returns:
        The estimate, or None with fewer than three usable cards or no true spread.
    """
    rates = [(c.wins_gih / c.games_gih, c.games_gih) for c in counts if c.games_gih >= min_games]
    if len(rates) < 3:
        return None
    mean = sum(p for p, _ in rates) / len(rates)
    observed_var = sum((p - mean) ** 2 for p, _ in rates) / (len(rates) - 1)
    sampling_var = sum(p * (1 - p) / n for p, n in rates) / len(rates)
    true_var = observed_var - sampling_var
    if true_var <= 0:
        return None
    return sum(p * (1 - p) for p, _ in rates) / len(rates) / true_var


def spell_rarities(cards: Iterable[Card]) -> dict[str, Rarity]:
    """Rarity by 17Lands name for every non-land card. Pure.

    Lands are left out on purpose: basics are in every deck and drawn in most games, so
    counting them would drag the format mean toward the overall win rate, and a land is
    never a bomb. Everything keyed by this map (means, shrinkage targets, bomb scoring)
    therefore describes spells only.
    """
    return {card.front_name: card.rarity for card in cards if Role.LAND not in classify(card)}
