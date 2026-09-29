"""Evaluate the engine on the fixed sample and render the report.

Two kinds of measure, kept apart on purpose:

- Outcome measures can show the engine being right when it disagrees with players:
  whether the engine's score of each player's actual deck predicts that deck's wins
  better than raw win rates do (`deck_score`), and how the same pool did in the engine's
  colors versus other colors (`within_pool_switch`).
- Imitation measures compare the engine's pick with the player's: pair agreement, the
  naive baselines, deck overlap. The gate only ratchets these against the base branch.

Everything here is deterministic for fixed inputs: builds are deterministic and every
bootstrap is seeded.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from arena_wizard.catalog import CardTable
from arena_wizard.domain.cards import Card, Color, Rarity
from arena_wizard.domain.decks import ScoredDeck
from arena_wizard.domain.pool import Pool, PoolEntry
from arena_wizard.domain.scoring import ScoringConfig
from arena_wizard.domain.sets import Format
from arena_wizard.domain.stats import Snapshot
from arena_wizard.engine.bombs import CuratedBomb, bomb_scores
from arena_wizard.engine.builder import (
    PAIRS,
    BuildInputs,
    build_decks,
    build_for_pair,
    pair_code,
    prepare_inputs,
    score_spells,
)
from arena_wizard.engine.mana import can_cast, castable_cost
from arena_wizard.engine.resolver import CardIndex
from arena_wizard.engine.roles import Role, classify
from arena_wizard.engine.values import FormatMeans, format_means, spell_rarities
from arena_wizard.eval.metrics import (
    Binomial,
    Estimate,
    Group,
    Observation,
    Scored,
    auc,
    auc_margin,
    jaccard,
    logistic_fit,
    mean,
    mean_difference,
    paired_rate_difference,
    rate_difference,
    standardize,
    weighted_share,
    wilson,
)
from arena_wizard.eval.records import PoolRecord

REPORT_FORMAT = 2
ENGINE_VERSION = "2"
STRONG_WIN_RATE = 0.6
STRONG_GAMES = 50
SKILL_MIN_GAMES = 50
LEDGER_ROWS_SHOWN = 25
BUCKET_WIDTH = 0.02
SEED = 20260928


@dataclass(frozen=True, slots=True)
class PoolOutcome:
    """Everything the metrics need from one evaluated pool."""

    record: PoolRecord
    decks: tuple[ScoredDeck, ...]
    legal: bool
    naive: Mapping[str, str]
    overlap: float | None
    player_pair_total: float | None
    build_scores: tuple[Scored, ...]
    bombs_in_pool: int
    top_cards: tuple[str, ...]
    evaluations: int
    unresolved: int

    @property
    def player_pair(self) -> str:
        """The main colors of the player's first deck."""
        return self.record.first_build.main_colors

    @property
    def engine_pair(self) -> str | None:
        """The main colors of the engine's top deck."""
        return self.decks[0].colors if self.decks else None


def _is_land(card: Card) -> bool:
    """True for lands, which are never spells in a deck list."""
    return Role.LAND in classify(card)


def resolve_record(record: PoolRecord, index: CardIndex, set_code: str) -> tuple[Pool, int]:
    """Turn a record's card names into a Pool; returns it and how many names did not resolve."""
    entries = []
    unresolved = 0
    for name, count in sorted(record.pool.items()):
        card = index.by_name.get(name)
        if card is None:
            unresolved += 1
        else:
            entries.append(PoolEntry(card, count))
    return Pool(set_code, Format.BO1_SEALED, tuple(entries), (), ()), unresolved


def is_legal(deck: ScoredDeck, pool: Pool) -> bool:
    """40 to 44 cards, 16 or 17 lands, no card beyond its pool count, every spell castable."""
    available = {e.card.oracle_id: e.count for e in pool.entries}
    colors = [Color(c) for c in deck.colors] + ([deck.splash] if deck.splash else [])
    return (
        40 <= deck.spell_count + deck.land_count <= 44
        and deck.land_count in (16, 17)
        and all(e.count <= available.get(e.card.oracle_id, 0) for e in deck.spells)
        and all(can_cast(castable_cost(e.card), colors) for e in deck.spells)
    )


def naive_picks(pool: Pool, inputs: BuildInputs, format_gih: float | None) -> dict[str, str]:
    """What three simple rules would pick, for the engine to be compared against. Pure.

    best_pair: the pair with the best observed record in the format. most_playables: the
    pair with the most castable spells. raw_gih: the pair whose 23 best castable spells
    have the highest total observed win rate in hand, with no shrinkage and no deck-shape
    terms.
    """
    fallback = format_gih if format_gih is not None else 0.0
    counts: dict[str, int] = {}
    raw: dict[str, float] = {}
    for main in PAIRS:
        code = pair_code(main)
        rates = []
        for entry in pool.entries:
            if not _is_land(entry.card) and can_cast(castable_cost(entry.card), main):
                observed = inputs.values[entry.card.front_name].observed
                rates += [observed if observed is not None else fallback] * entry.count
        counts[code] = len(rates)
        raw[code] = sum(sorted(rates, reverse=True)[:23])
    order = [pair_code(p) for p in PAIRS]

    def record(code: str) -> float:
        observed = inputs.pairs[code].observed
        return -1.0 if observed is None else observed

    return {
        "best_pair": max(order, key=lambda c: (record(c), -order.index(c))),
        "most_playables": max(order, key=lambda c: (counts[c], -order.index(c))),
        "raw_gih": max(order, key=lambda c: (raw[c], -order.index(c))),
    }


def raw_deck_score(
    deck: Mapping[str, int], index: CardIndex, inputs: BuildInputs, means: FormatMeans | None
) -> float:
    """The baseline score of a deck: the sum of its spells' observed win rates in hand.

    A spell with no games counts at the format mean.
    """
    fallback = means.gih if means else 0.0
    total = 0.0
    for name, count in deck.items():
        card = index.by_name.get(name)
        if card is None or _is_land(card):
            continue
        value = inputs.values.get(card.front_name)
        observed = value.observed if value is not None else None
        total += count * (observed if observed is not None else fallback)
    return total


def evaluate_pool(
    record: PoolRecord,
    index: CardIndex,
    snapshot: Snapshot,
    rarity_of: Mapping[str, Rarity],
    config: ScoringConfig,
    curated: tuple[CuratedBomb, ...],
    set_code: str,
) -> PoolOutcome:
    """Build, score, and compare one pool. Pure."""
    pool, unresolved = resolve_record(record, index, set_code)
    inputs = prepare_inputs(pool, snapshot, rarity_of, config, curated)
    result = build_decks(pool, inputs)
    means = format_means(snapshot, rarity_of)
    player = record.first_build
    overlap = player_total = None
    if len(player.main_colors) == 2:
        mine = build_for_pair(pool, inputs, player.main_colors)
        if mine is not None:
            player_total = mine.total
            theirs = {
                name: n
                for name, n in player.deck.items()
                if name in index.by_name and not _is_land(index.by_name[name])
            }
            overlap = jaccard({e.card.front_name: e.count for e in mine.spells}, theirs)
    scores = []
    for build in record.builds:
        if len(build.main_colors) != 2 or len(build.splash_colors) > 1:
            continue
        spells = [
            (index.by_name[name], n)
            for name, n in sorted(build.deck.items())
            if name in index.by_name
            and not _is_land(index.by_name[name])
            and index.by_name[name].front_name in inputs.values
        ]
        splash = Color(build.splash_colors) if build.splash_colors else None
        deck = score_spells(pool, spells, build.main_colors, splash, inputs)
        raw = raw_deck_score(build.deck, index, inputs, means)
        scores.append(Scored(deck.total, raw, build.games, build.wins))
    top = sorted(inputs.values.values(), key=lambda v: (-v.q, v.name))[:5]
    return PoolOutcome(
        record=record,
        decks=result.decks,
        legal=bool(result.decks) and all(is_legal(d, pool) for d in result.decks),
        naive=naive_picks(pool, inputs, means.gih if means else None),
        overlap=overlap,
        player_pair_total=player_total,
        build_scores=tuple(scores),
        bombs_in_pool=sum(e.count for e in pool.entries if e.card.front_name in inputs.bombs),
        top_cards=tuple(v.name for v in top),
        evaluations=result.evaluations,
        unresolved=unresolved,
    )


def _estimate(e: Estimate) -> dict[str, Any]:
    return {"value": e.value, "low": e.low, "high": e.high, "n": e.n}


def _strong(record: PoolRecord) -> bool:
    """A player with a high win-rate bucket over many games."""
    return (record.win_rate_bucket or 0.0) >= STRONG_WIN_RATE and (
        record.games_bucket or 0
    ) >= STRONG_GAMES


def _skill_known(record: PoolRecord) -> bool:
    """The whole-file skill bucket includes the sample's own games; it says much about
    skill only for players with many other games."""
    return record.win_rate_bucket is not None and (record.games_bucket or 0) >= SKILL_MIN_GAMES


def deck_score_metrics(outcomes: Sequence[PoolOutcome], rng: random.Random) -> dict[str, Any]:
    """Does the engine's score of a player's deck predict its wins, and better than raw
    win rates in hand? Pure given the seeded `rng`."""
    by_build = [(o, s) for o in outcomes for s in o.build_scores]
    flat = [s for _, s in by_build]
    z = standardize([s.engine for s in flat]) if flat else []
    adjusted = logistic_fit(
        [
            Observation((x, o.record.win_rate_bucket or 0.0), s.games, s.wins)
            for x, (o, s) in zip(z, by_build, strict=True)
            if _skill_known(o.record)
        ]
    )
    clusters = [o.build_scores for o in outcomes if o.build_scores]
    return {
        "engine_auc": auc([Binomial(s.engine, s.games, s.wins) for s in flat]),
        "raw_gih_auc": auc([Binomial(s.baseline, s.games, s.wins) for s in flat]),
        "auc_margin_over_raw_gih": _estimate(auc_margin(clusters, rng)),
        "slope_per_sd_skill_adjusted": None if adjusted is None else adjusted[1],
        "builds": len(flat),
        "games": sum(s.games for s in flat),
    }


def switch_metrics(outcomes: Sequence[PoolOutcome], rng: random.Random) -> dict[str, Any]:
    """The same pool in the engine's colors against the other colors the player tried.

    Only pools the player registered in at least two two-color pairs, one of them the
    engine's. Split by whether the engine's colors were the player's first build, because
    players abandon losing builds.
    """
    first: list[tuple[Group, Group]] = []
    later: list[tuple[Group, Group]] = []
    for o in outcomes:
        pairs = {b.main_colors for b in o.record.builds if len(b.main_colors) == 2}
        if len(pairs) < 2 or o.engine_pair not in pairs:
            continue
        chosen = [b for b in o.record.builds if b.main_colors == o.engine_pair]
        others = [b for b in o.record.builds if b.main_colors != o.engine_pair]
        pair = (
            Group(sum(b.wins for b in chosen), sum(b.games for b in chosen)),
            Group(sum(b.wins for b in others), sum(b.games for b in others)),
        )
        (first if o.record.first_build.main_colors == o.engine_pair else later).append(pair)
    return {
        "all": _estimate(paired_rate_difference(first + later, rng)),
        "engine_colors_built_first": _estimate(paired_rate_difference(first, rng)),
        "engine_colors_built_later": _estimate(paired_rate_difference(later, rng)),
    }


def confidence_table(two: Sequence[PoolOutcome], hits: Sequence[bool]) -> dict[str, dict[str, int]]:
    """Agreement split by whether the engine called its top deck a toss-up and splashed."""
    cells: dict[str, dict[str, int]] = {}
    for hit, o in zip(hits, two, strict=True):
        top = o.decks[0] if o.decks else None
        key = (
            f"{'toss-up' if top is not None and top.is_toss_up else 'confident'}, "
            f"{'splash' if top is not None and top.splash is not None else 'no splash'}"
        )
        cell = cells.setdefault(key, {"pools": 0, "agree": 0, "most_playables_only": 0})
        cell["pools"] += 1
        cell["agree"] += hit
        cell["most_playables_only"] += (not hit) and o.naive["most_playables"] == o.player_pair
    return dict(sorted(cells.items()))


def set_metrics(
    outcomes: Sequence[PoolOutcome], switch: Sequence[PoolOutcome], rng: random.Random
) -> dict[str, Any]:
    """Every metric for one set. Pure given the seeded `rng`."""
    two = [o for o in outcomes if len(o.player_pair) == 2]
    hit1 = [o.engine_pair == o.player_pair for o in two]
    hit3 = [o.player_pair in [d.colors for d in o.decks[:3]] for o in two]
    weighted = [
        (h, o.record.win_rate_bucket + BUCKET_WIDTH / 2)
        for h, o in zip(hit1, two, strict=True)
        if o.record.win_rate_bucket is not None
    ]
    metrics: dict[str, Any] = {
        "legality": _estimate(wilson(sum(o.legal for o in outcomes), len(outcomes))),
        "pools_without_deck": sum(not o.decks for o in outcomes),
        "pair_agreement_at_1": _estimate(wilson(sum(hit1), len(two))),
        "pair_agreement_at_3": _estimate(wilson(sum(hit3), len(two))),
        "pair_agreement_at_1_skill_weighted": weighted_share(
            [h for h, _ in weighted], [w for _, w in weighted]
        ),
        "mean_decks_returned": mean([float(len(o.decks)) for o in outcomes]).value,
    }
    for name in ("best_pair", "most_playables", "raw_gih"):
        naive_hits = [o.naive[name] == o.player_pair for o in two]
        metrics[f"naive_{name}_at_1"] = _estimate(wilson(sum(naive_hits), len(two)))
        metrics[f"flips_vs_{name}"] = {
            "engine_only": sum(h and not n for h, n in zip(hit1, naive_hits, strict=True)),
            "baseline_only": sum(n and not h for h, n in zip(hit1, naive_hits, strict=True)),
        }
    agree = [Group(o.record.wins, o.record.games) for h, o in zip(hit1, two, strict=True) if h]
    disagree = [
        Group(o.record.wins, o.record.games) for h, o in zip(hit1, two, strict=True) if not h
    ]
    metrics["agreement_lift"] = _estimate(rate_difference(agree, disagree, rng))
    residual = [
        (h, o.record.wins / o.record.games - (o.record.win_rate_bucket or 0.0) - BUCKET_WIDTH / 2)
        for h, o in zip(hit1, two, strict=True)
        if _skill_known(o.record) and o.record.games
    ]
    metrics["skill_residual_lift"] = _estimate(
        mean_difference([r for h, r in residual if h], [r for h, r in residual if not h], rng)
    )
    metrics["deck_score"] = deck_score_metrics(outcomes, rng)
    metrics["within_pool_switch"] = switch_metrics(switch, rng)
    overlaps = [o.overlap for o in outcomes if o.overlap is not None]
    strong = [o.overlap for o in outcomes if o.overlap is not None and _strong(o.record)]
    metrics["deck_overlap_at_pair"] = _estimate(mean(overlaps))
    metrics["deck_overlap_at_pair_strong"] = _estimate(mean(strong))
    metrics["three_color_share"] = _estimate(
        wilson(sum(len(o.player_pair) >= 3 for o in outcomes), len(outcomes))
    )
    metrics["player_splash_share"] = _estimate(
        wilson(sum(bool(o.record.first_build.splash_colors) for o in outcomes), len(outcomes))
    )
    metrics["engine_splash_share"] = _estimate(
        wilson(
            sum(bool(o.decks) and o.decks[0].splash is not None for o in outcomes), len(outcomes)
        )
    )
    metrics["bombs_per_pool"] = mean([float(o.bombs_in_pool) for o in outcomes]).value
    metrics["by_confidence_and_splash"] = confidence_table(two, hit1)
    evaluations = [o.evaluations for o in outcomes]
    metrics["evaluations_per_pool"] = {
        "mean": sum(evaluations) / len(evaluations) if evaluations else None,
        "max": max(evaluations, default=0),
    }
    metrics["unresolved_names"] = sum(o.unresolved for o in outcomes)
    return metrics


def ledger(outcomes: Sequence[PoolOutcome]) -> list[dict[str, Any]]:
    """Strong two-color players' pools where the engine chose other colors, largest gap first.

    The gap is the engine's score for its own deck minus its score for the player's
    colors: how confident the engine is that the player was wrong. Three-color players are
    left out because the builder cannot build their decks at all.
    """
    rows: list[dict[str, Any]] = []
    for o in outcomes:
        if (
            not _strong(o.record)
            or not o.decks
            or len(o.player_pair) != 2
            or o.engine_pair == o.player_pair
        ):
            continue
        top = o.decks[0]
        rows.append(
            {
                "draft_id": o.record.draft_id,
                "player_colors": o.player_pair,
                "player_record": f"{o.record.wins}-{o.record.games - o.record.wins}",
                "engine_deck": top.label,
                "engine_total": top.total,
                "player_colors_total": o.player_pair_total,
                "gap": None if o.player_pair_total is None else top.total - o.player_pair_total,
                "toss_up": top.is_toss_up,
                "later_switched": any(b.main_colors == top.colors for b in o.record.builds[1:]),
                "top_cards": list(o.top_cards),
            }
        )
    rows.sort(key=lambda r: (r["gap"] is None, -(r["gap"] or 0.0), r["draft_id"]))
    return rows


def decision_digest(outcomes: Sequence[PoolOutcome]) -> str:
    """A hash of every pool's top deck, so any change in a decision changes the digest."""
    lines = []
    for o in sorted(outcomes, key=lambda o: o.record.draft_id):
        top = o.decks[0] if o.decks else None
        spells = (
            "" if top is None else ",".join(f"{e.count}x{e.card.front_name}" for e in top.spells)
        )
        lines.append(f"{o.record.draft_id}:{top.label if top else '-'}:{spells}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def automatic_bombs(
    snapshot: Snapshot, rarity_of: Mapping[str, Rarity], config: ScoringConfig
) -> list[str]:
    """The automatic bomb names for a snapshot, strongest first."""
    means = format_means(snapshot, rarity_of)
    scores = bomb_scores(
        snapshot.cards,
        rarity_of,
        means,
        config.bombs,
        config.shrinkage.prior_games,
        config.shrinkage.iwd_prior_games,
    )
    return [
        name
        for name, score in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if score >= config.bombs.threshold
    ]


def bomb_section(automatic: Sequence[str], curated: tuple[CuratedBomb, ...]) -> dict[str, Any]:
    """The bomb part of the report. Names are withheld until the set has a curated list,
    so the group writes theirs without seeing the automatic one first."""
    expert = {c.name for c in curated if c.action == "add"}
    if not expert:
        return {
            "automatic_count": len(automatic),
            "automatic_names": "withheld until the set's curated list exists",
            "curated_agreement": None,
        }
    auto = set(automatic)
    hits = auto & expert
    precision = len(hits) / len(auto) if auto else None
    recall = len(hits) / len(expert)
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    return {
        "automatic_count": len(automatic),
        "automatic_names": list(automatic),
        "curated_agreement": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "missed": sorted(expert - auto),
            "extra": sorted(auto - expert),
        },
    }


def rounded(value: Any) -> Any:
    """Round every float to four places, recursively, so reports compare stably."""
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [rounded(v) for v in value]
    return value


def evaluate_set(
    set_code: str,
    records: Sequence[PoolRecord],
    switch_records: Sequence[PoolRecord],
    snapshot: Snapshot,
    table: CardTable,
    index: CardIndex,
    config: ScoringConfig,
    curated: tuple[CuratedBomb, ...],
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Evaluate one set; return its report section and its decision digest. Pure."""
    rarity_of = spell_rarities(table.cards)

    def run(rs: Sequence[PoolRecord]) -> list[PoolOutcome]:
        return [evaluate_pool(r, index, snapshot, rarity_of, config, curated, set_code) for r in rs]

    outcomes = run(records)
    rng = random.Random(SEED)
    section = {
        "provenance": dict(provenance),
        "metrics": set_metrics(outcomes, run(switch_records), rng),
        "bombs": bomb_section(automatic_bombs(snapshot, rarity_of, config), curated),
        "ledger": ledger(outcomes),
        "pool_picks": {
            o.record.draft_id: {
                "player": o.player_pair,
                "engine": [d.colors for d in o.decks[:3]],
            }
            for o in outcomes
        },
    }
    return section, decision_digest(outcomes)


NOTES = (
    "Statistics come only from games on or before each file's split day; sample pools "
    "started after it. The share of pools and games after the split is shown per set.",
    "The 17Lands files have no user id, so a player can appear on both sides of the split; "
    "that overlap cannot be measured.",
    "The skill bucket is computed by 17Lands over a player's whole history, including the "
    "sample's own games, so skill adjustments use only players with 50 or more games.",
    "Shrinkage priors were estimated on the full files, including post-split games.",
    "Pair agreement counts two-color first decks only. The builder builds two-color decks "
    "with at most one splash, so three-color decks (three_color_share) can never match.",
    "Agreement with players is imitation. deck_score and within_pool_switch are the "
    "measures that can show the engine being right when it disagrees.",
)


def build_report(
    sections: Mapping[str, tuple[dict[str, Any], str]], config: ScoringConfig
) -> dict[str, Any]:
    """Assemble the full report from each set's section and digest. Pure."""
    digest = hashlib.sha256(
        "".join(f"{code}:{digest}" for code, (_, digest) in sorted(sections.items())).encode()
    ).hexdigest()
    report: dict[str, Any] = rounded(
        {
            "report_format": REPORT_FORMAT,
            "engine_version": ENGINE_VERSION,
            "scoring_config": {"version": config.version, "sha256": config.sha256},
            "decision_digest": digest,
            "notes": list(NOTES),
            "sets": {code: section for code, (section, _) in sorted(sections.items())},
        }
    )
    return report


def report_to_json(report: Mapping[str, Any]) -> str:
    """Serialize a report deterministically."""
    return json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _fmt(value: Any, percent: bool = True) -> str:
    """A number as a percentage or a three-place decimal; n/a when missing."""
    if value is None:
        return "n/a"
    return f"{100 * value:.1f}%" if percent else f"{value:.3f}"


def _interval(metric: Mapping[str, Any], percent: bool = True) -> str:
    """A metric's 95% interval, or n/a."""
    low, high = metric.get("low"), metric.get("high")
    if low is None or high is None:
        return "n/a"
    return f"{_fmt(low, percent)} to {_fmt(high, percent)}"


_ROWS = (
    ("legality", "Legal decks", True),
    ("pair_agreement_at_1", "Top deck matches the player's pair", True),
    ("pair_agreement_at_3", "Player's pair among the top three", True),
    ("naive_best_pair_at_1", "Baseline: format's best pair", True),
    ("naive_most_playables_at_1", "Baseline: most playable spells", True),
    ("naive_raw_gih_at_1", "Baseline: raw win rate in hand", True),
    ("agreement_lift", "Win rate, agreeing minus disagreeing", True),
    ("skill_residual_lift", "Win rate above skill, agreeing minus disagreeing", True),
    ("deck_overlap_at_pair", "Deck overlap in the player's colors", False),
    ("deck_overlap_at_pair_strong", "Deck overlap, strong players", False),
    ("three_color_share", "Players on three or more main colors", True),
    ("player_splash_share", "Players who splashed", True),
    ("engine_splash_share", "Engine top decks that splash", True),
)


def _row(label: str, metric: Mapping[str, Any], percent: bool) -> str:
    return (
        f"| {label} | {_fmt(metric['value'], percent)} | {_interval(metric, percent)} "
        f"| {metric['n']} |"
    )


def _set_markdown(code: str, section: Mapping[str, Any]) -> list[str]:
    """One set's part of the report."""
    m = section["metrics"]
    p = section["provenance"]
    score = m["deck_score"]
    margin = score["auc_margin_over_raw_gih"]
    switch = m["within_pool_switch"]
    switch_parts = [
        f"{label} {_fmt(switch[key]['value'])} ({_interval(switch[key])}, {switch[key]['n']} pools)"
        for key, label in (
            ("all", "all"),
            ("engine_colors_built_first", "engine's colors built first"),
            ("engine_colors_built_later", "built later"),
        )
    ]
    lines = [
        f"## {code}",
        "",
        f"{p.get('sample_size')} sample pools of {p.get('pools')}; split day "
        f"{p.get('split_day')}; after the split: {_fmt(p.get('eligible_pool_share'))} of pools, "
        f"{_fmt(p.get('eligible_game_share'))} of games; file sha256 "
        f"`{str(p.get('sha256'))[:16]}`.",
        "",
        "### Outcomes",
        "",
        f"The engine's score of each player's actual deck ranks wins over losses with AUC "
        f"{_fmt(score['engine_auc'], False)}, against {_fmt(score['raw_gih_auc'], False)} for "
        f"raw win rates in hand: margin {_fmt(margin['value'], False)} "
        f"({_interval(margin, False)}, {margin['n']} pools). Skill-adjusted slope "
        f"{_fmt(score['slope_per_sd_skill_adjusted'], False)} per standard deviation over "
        f"{score['builds']} builds and {score['games']} games.",
        "",
        "Same pool, engine's colors minus the other colors the player tried: "
        + "; ".join(switch_parts)
        + ".",
        "",
        "### Agreement with players",
        "",
        "| Measure | Value | 95% interval | n |",
        "|---|---|---|---|",
    ]
    lines += [_row(label, m[key], percent) for key, label, percent in _ROWS]
    flips = ", ".join(
        f"{name} {m[f'flips_vs_{name}']['engine_only']} engine-only and "
        f"{m[f'flips_vs_{name}']['baseline_only']} baseline-only"
        for name in ("best_pair", "most_playables", "raw_gih")
    )
    lines += [
        "",
        f"Pools one side gets right and the other does not: {flips}.",
        "",
        f"Skill-weighted agreement {_fmt(m['pair_agreement_at_1_skill_weighted'])}; "
        f"{_fmt(m['mean_decks_returned'], False)} decks returned per pool; "
        f"{m['pools_without_deck']} pools without a deck.",
        "",
        "| Engine's top deck | Pools | Agrees | Baseline right, engine not |",
        "|---|---|---|---|",
    ]
    for key, cell in m["by_confidence_and_splash"].items():
        lines.append(
            f"| {key} | {cell['pools']} | {cell['agree']} | {cell['most_playables_only']} |"
        )
    bombs = section["bombs"]
    names = bombs["automatic_names"]
    lines += [
        "",
        f"Automatic bombs: {bombs['automatic_count']} ({_fmt(m['bombs_per_pool'], False)} per "
        "pool); names " + (", ".join(names) if isinstance(names, list) else names) + ".",
        "",
        "### Disagreement ledger (strong two-color players, largest gap first)",
        "",
        "| Player colors | Record | Engine deck | Gap | Toss-up | Later switched | Best cards |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in section["ledger"][:LEDGER_ROWS_SHOWN]:
        gap = "n/a" if row["gap"] is None else f"{row['gap']:.1f}"
        lines.append(
            f"| {row['player_colors']} | {row['player_record']} | {row['engine_deck']} | {gap} "
            f"| {'yes' if row['toss_up'] else 'no'} | {'yes' if row['later_switched'] else 'no'} "
            f"| {', '.join(row['top_cards'])} |"
        )
    lines += ["", f"{len(section['ledger'])} rows in all; the full ledger is in report.json.", ""]
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the report for people. Pure; the same JSON always renders the same bytes."""
    lines = [
        "# Evaluation report",
        "",
        "Generated by `arena-wizard eval run`; do not edit by hand. Data derived from 17Lands",
        "public game files (CC BY 4.0), see `NOTICE`.",
        "",
        f"Engine version {report['engine_version']}, scoring config "
        f"{report['scoring_config']['version']}, decision digest "
        f"`{report['decision_digest'][:16]}`.",
        "",
    ]
    for code, section in report["sets"].items():
        lines += _set_markdown(code, section)
    lines += ["## Notes", ""] + [f"- {note}" for note in report["notes"]] + [""]
    return "\n".join(lines)
