"""Which cards count as bombs: a data-driven score plus a curated per-set list.

The score is the standardized sum of the z-score of a card's shrunk game-in-hand win rate
and the z-score of its shrunk improvement when drawn, among cards with enough games.
Improvement when drawn gets full weight because it strips out the "good deck" inflation
that makes expensive rares look like bombs. No automatic list is produced for a set with
too few qualifying cards.
The curated file (`config/bombs/{SET}.yaml`) adds, removes, or annotates; it is written by
the group from set reviews, before the automatic list is shown.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

import yaml

from arena_wizard.domain.cards import Rarity
from arena_wizard.domain.scoring import BombRules, ScoringConfig
from arena_wizard.domain.sets import ConfigError
from arena_wizard.domain.stats import CardCounts
from arena_wizard.engine.event_values import DataLayer
from arena_wizard.engine.values import FormatMeans, shrink

PROVENANCE = re.compile(r"own|permission \d{4}")


@dataclass(frozen=True, slots=True)
class CuratedBomb:
    """One entry of a set's curated bomb list."""

    name: str
    action: str
    note: str
    source: str


def _z_scores(values: Mapping[str, float]) -> dict[str, float]:
    """Standardize values; all zeros when they do not vary."""
    mean = sum(values.values()) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values.values()) / len(values))
    return {name: (v - mean) / sd if sd else 0.0 for name, v in values.items()}


def bomb_scores(
    counts: Mapping[str, CardCounts],
    rarity_of: Mapping[str, Rarity],
    means: FormatMeans | None,
    rules: BombRules,
    prior_games: float,
    iwd_prior_games: float,
) -> dict[str, float]:
    """Score every qualifying card. Pure.

    Args:
        counts: Card counts by name.
        rarity_of: Rarity by name, for the shrinkage target.
        means: The format means; no scores without them or without not-seen games.
        rules: The game floor and the minimum number of qualifying cards.
        prior_games: Pseudo-games for the game-in-hand rate.
        iwd_prior_games: Pseudo-games for the not-seen rate.

    Returns:
        Bomb score by name for cards with at least `rules.min_games` games in hand; empty
        when fewer than `rules.min_cards` cards qualify.
    """
    if means is None or means.iwd is None:
        return {}
    gih: dict[str, float] = {}
    iwd: dict[str, float] = {}
    for name, c in counts.items():
        if c.games_gih < rules.min_games or name not in rarity_of:
            continue
        rarity = rarity_of[name]
        used = shrink(
            c.wins_gih, c.games_gih, means.gih_by_rarity.get(rarity, means.gih), prior_games
        )
        gns_prior = means.gns_by_rarity.get(rarity, means.gih - means.iwd)
        gih[name] = used
        iwd[name] = used - shrink(c.wins_gns, c.games_gns, gns_prior, iwd_prior_games)
    if len(gih) < rules.min_cards:
        return {}
    z_gih, z_iwd = _z_scores(gih), _z_scores(iwd)
    # The two z-scores correlate (about 0.7 to 0.8 on SOS and HOB), so their sum is
    # re-standardized; otherwise a threshold of 2.0 would be about one standard deviation.
    return _z_scores({name: z_gih[name] + z_iwd[name] for name in gih})


def parse_curated(raw: Any) -> tuple[CuratedBomb, ...]:
    """Validate a curated bomb file.

    The file must say whose judgment it is (decision 0007): `provenance: own` for the
    group's own list, or `provenance: permission NNNN` naming the decision that records a
    third party's permission. Third-party lists are never committed otherwise. Code can
    check that the label is present, not that it is true.

    Raises:
        ConfigError: No valid provenance, or an entry lacks a name, a valid action, or a
            source (who decided).
    """
    provenance = raw.get("provenance") if isinstance(raw, Mapping) else None
    if not isinstance(provenance, str) or not PROVENANCE.fullmatch(provenance):
        raise ConfigError(
            "curated bomb file needs 'provenance: own' (the group's own list) or "
            "'provenance: permission NNNN' (a decision recording permission)"
        )
    entries = raw.get("curated") if isinstance(raw, Mapping) else None
    if not isinstance(entries, list):
        raise ConfigError("curated bomb file needs a 'curated' list")
    result = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not entry.get("name") or not entry.get("source"):
            raise ConfigError(f"curated bomb entry needs a name and a cited source: {entry!r}")
        if entry.get("action") not in {"add", "remove", "annotate"}:
            raise ConfigError(f"curated bomb action must be add, remove, or annotate: {entry!r}")
        result.append(
            CuratedBomb(entry["name"], entry["action"], str(entry.get("note", "")), entry["source"])
        )
    return tuple(result)


def load_curated(set_code: str, directory: Traversable | None = None) -> tuple[CuratedBomb, ...]:
    """Load a set's curated bomb list; empty when the group has not written one yet.

    Args:
        set_code: The set, in any case.
        directory: Where the lists live; defaults to the packaged `config/bombs`.
    """
    folder = directory or resources.files("arena_wizard").joinpath("config", "bombs")
    path = folder.joinpath(f"{set_code.upper()}.yaml")
    if not path.is_file():
        return ()
    return parse_curated(yaml.safe_load(path.read_text(encoding="utf-8")))


def bombs(
    scores: Mapping[str, float], threshold: float, curated: tuple[CuratedBomb, ...]
) -> dict[str, float]:
    """Combine the automatic list with the curated one. Pure.

    Returns:
        Bomb strength by name: automatic bombs at their score, curated additions at the
        threshold or their score if higher, curated removals dropped.
    """
    result = {name: score for name, score in scores.items() if score >= threshold}
    for entry in curated:
        if entry.action == "add":
            result[entry.name] = max(scores.get(entry.name, threshold), threshold)
        elif entry.action == "remove":
            result.pop(entry.name, None)
    return result


def event_bomb_scores(
    layers: Sequence[DataLayer], rarity_of: Mapping[str, Rarity], config: ScoringConfig
) -> tuple[dict[str, float], str | None]:
    """Automatic bomb scores from the first layer with enough games, and that layer's name."""
    for layer in layers:
        scores = bomb_scores(
            layer.snapshot.cards,
            rarity_of,
            layer.means,
            config.bombs,
            config.shrinkage.prior_games,
            config.shrinkage.iwd_prior_games,
        )
        if scores:
            return scores, layer.name
    return {}, None
