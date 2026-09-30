"""Build and rank the best decks a pool can make.

For each of the ten color pairs with enough castable spells: fill the deck by card value
(at least twelve creatures when the pair has them), choose lands, then hill-climb single
swaps within a bounded neighborhood (the weakest included and strongest excluded cards,
plus the best and worst by role) until no swap helps, at most 25 steps. Splashes are tried
only where an upper bound on what they could gain reaches the current third-best deck, so
the bound never discards a deck that could have made the list. Ties break by name, so the
same inputs always give the same decks.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType

from arena_wizard.domain.cards import WUBRG, Card, Color, Rarity
from arena_wizard.domain.decks import CardValue, ScoredDeck
from arena_wizard.domain.pool import Pool, PoolEntry
from arena_wizard.domain.scoring import ScoringConfig
from arena_wizard.domain.stats import Snapshot
from arena_wizard.engine.bombs import CuratedBomb, bomb_scores, bombs
from arena_wizard.engine.castability import shortfall
from arena_wizard.engine.event_values import DataLayer, event_value
from arena_wizard.engine.grades import GradeScores
from arena_wizard.engine.lands import Manabase, build_manabase, land_count
from arena_wizard.engine.mana import can_cast, castable_cost, requirements
from arena_wizard.engine.roles import Role, classify
from arena_wizard.engine.scoring import DeckState, SpellFacts, state_of, terms, total
from arena_wizard.engine.values import FormatMeans, PairValue, card_value, format_means, pair_value

PAIRS: tuple[tuple[Color, Color], ...] = tuple(combinations(WUBRG, 2))
DECK_SIZE = 40
MIN_CREATURES_IN_FILL = 12
MAX_STEPS = 25
NEIGHBOURS = 8
ROLE_IN = 4
ROLE_OUT = 2
TOP_N = 3


@dataclass(frozen=True, slots=True)
class BuildInputs:
    """Everything the builder needs besides the pool, computed once per pool."""

    values: Mapping[str, CardValue]
    pairs: Mapping[str, PairValue]
    bombs: Mapping[str, float]
    config: ScoringConfig
    max_decks: int | None = None
    """Event mode lists at most this many decks; None keeps every close deck."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    """The ranked decks and how much work finding them took."""

    decks: tuple[ScoredDeck, ...]
    evaluations: int


def pair_code(colors: Iterable[Color]) -> str:
    """Colors as a WUBRG-ordered code, the way 17Lands writes them: "BG"."""
    present = set(colors)
    return "".join(color.value for color in WUBRG if color in present)


def prepare_inputs(
    pool: Pool,
    snapshot: Snapshot | None,
    rarity_of: Mapping[str, Rarity],
    config: ScoringConfig,
    curated: tuple[CuratedBomb, ...] = (),
) -> BuildInputs:
    """Value every card in the pool and every color pair. Pure.

    Args:
        pool: The pool.
        snapshot: The statistics, or None when none are loaded for the set.
        rarity_of: Rarity by name for every card in the set, for the shrinkage targets.
        config: The scoring configuration.
        curated: The set's curated bomb list.

    Returns:
        The inputs for `build_decks`.
    """
    means: FormatMeans | None = format_means(snapshot, rarity_of) if snapshot else None
    label = snapshot.source.label if snapshot else "no data loaded"
    counts = snapshot.cards if snapshot else {}
    values = {
        entry.card.front_name: card_value(
            entry.card.front_name,
            entry.card.rarity,
            counts.get(entry.card.front_name),
            means,
            config,
            label,
        )
        for entry in pool.entries
    }
    pairs = {
        pair_code(p): pair_value(
            pair_code(p), snapshot.pairs.get(pair_code(p)) if snapshot else None, means, config
        )
        for p in PAIRS
    }
    scores = bomb_scores(
        counts,
        rarity_of,
        means,
        config.bombs,
        config.shrinkage.prior_games,
        config.shrinkage.iwd_prior_games,
    )
    return BuildInputs(
        values=values,
        pairs=pairs,
        bombs=bombs(scores, config.bombs.threshold, curated),
        config=config,
    )


def prepare_event_inputs(
    pool: Pool,
    grades: GradeScores | None,
    proxy: DataLayer | None,
    direct: DataLayer | None,
    config: ScoringConfig,
    curated: tuple[CuratedBomb, ...] = (),
    automatic: Mapping[str, float] = MappingProxyType({}),
) -> BuildInputs:
    """Value a pool without the public Sealed file (decisions 0007, 0010). Pure.

    Args:
        pool: The pool.
        grades: Standardized grades for the set, or None.
        proxy: Premier Draft win rates, or None.
        direct: Arena Direct or pasted Sealed win rates, or None.
        config: The scoring configuration.
        curated: The group's curated bomb list.
        automatic: Automatic bomb scores from pasted win rates (`event_bomb_scores`).

    Returns:
        The inputs for `build_decks`, listing at most `config.event.max_decks` decks.

    Raises:
        ValueError: No grades and no data layers.
    """
    values = {
        entry.card.front_name: event_value(entry.card, grades, proxy, direct, config)
        for entry in pool.entries
    }
    return BuildInputs(
        values=values,
        pairs={pair_code(p): pair_value(pair_code(p), None, None, config) for p in PAIRS},
        bombs=bombs(automatic, config.bombs.threshold, curated),
        config=config,
        max_decks=config.event.max_decks,
    )


@dataclass(frozen=True, slots=True)
class _Option:
    """One copy of a spell the deck could play, with its facts for this deck's mana."""

    card: Card
    facts: SpellFacts


def _is_land(card: Card) -> bool:
    """True for lands, which fill land slots rather than spell slots."""
    return Role.LAND in classify(card)


def _facts(
    card: Card,
    copy: int,
    inputs: BuildInputs,
    main: tuple[Color, ...],
    manabase: Manabase,
) -> SpellFacts:
    """Reduce one copy of a spell to what the objective needs, given the deck's sources."""
    cost = castable_cost(card)
    roles = classify(card)
    value = inputs.values[card.front_name]
    c = inputs.config.castability
    return SpellFacts(
        key=f"{card.oracle_id}#{copy}",
        name=card.front_name,
        q=value.q,
        se=value.se,
        creature=Role.CREATURE in roles,
        removal=Role.REMOVAL in roles,
        mana_value=card.mana_value,
        shortfall=shortfall(
            requirements(cost, manabase.sources),
            manabase.sources,
            card.mana_value,
            baseline_sources=c.baseline_sources,
            deck_size=c.deck_size,
            scale=c.scale,
        ),
        bomb=inputs.bombs.get(card.front_name),
        splash=not can_cast(cost, main),
    )


def _copies(entries: Iterable[PoolEntry]) -> list[tuple[Card, int]]:
    """Expand entries into (card, copy index) pairs."""
    return [(entry.card, i) for entry in entries for i in range(entry.count)]


def _order(inputs: BuildInputs, items: Iterable[tuple[Card, int]]) -> list[tuple[Card, int]]:
    """Best value first; ties by name, then copy."""
    return sorted(
        items, key=lambda ci: (-inputs.values[ci[0].front_name].q, ci[0].front_name, ci[1])
    )


def _fill(
    inputs: BuildInputs, main_copies: list[tuple[Card, int]], size: int
) -> list[tuple[Card, int]]:
    """Take the best creatures up to the minimum, then the best of everything else."""
    ordered = _order(inputs, main_copies)
    creatures = [ci for ci in ordered if Role.CREATURE in classify(ci[0])]
    chosen = creatures[:MIN_CREATURES_IN_FILL]
    taken = set(chosen)
    for ci in ordered:
        if len(chosen) >= size:
            break
        if ci not in taken:
            chosen.append(ci)
            taken.add(ci)
    return chosen[:size]


def _group(items: Sequence[tuple[Card, int]]) -> list[tuple[Card, int]]:
    """Collapse copies back into (card, count), in name order."""
    counts: dict[str, int] = {}
    cards: dict[str, Card] = {}
    for card, _ in items:
        counts[card.oracle_id] = counts.get(card.oracle_id, 0) + 1
        cards[card.oracle_id] = card
    return sorted(((cards[k], n) for k, n in counts.items()), key=lambda cn: cn[0].front_name)


def _manabase(
    pool: Pool,
    chosen: Sequence[tuple[Card, int]],
    main: tuple[Color, ...],
    splash: Color | None,
    inputs: BuildInputs,
) -> Manabase:
    """Lands for exactly these spells."""
    spells = _group(chosen)
    lands = [(e.card, e.count) for e in pool.entries if _is_land(e.card)]
    return build_manabase(
        spells,
        main,
        splash,
        lands,
        DECK_SIZE - len(chosen),
        inputs.config.targets.splash_min_sources,
    )


def _neighbours(facts: Sequence[SpellFacts], best_first: bool, per_role: int) -> list[SpellFacts]:
    """The weakest (or strongest) by value, plus the weakest (strongest) of each role."""
    ordered = sorted(facts, key=lambda f: ((-f.q if best_first else f.q), f.name, f.key))
    picked = ordered[:NEIGHBOURS]
    picked += [f for f in ordered if f.creature][:per_role]
    picked += [f for f in ordered if f.removal][:per_role]
    seen: set[str] = set()
    unique = []
    for f in picked:
        if f.key not in seen:
            seen.add(f.key)
            unique.append(f)
    return unique


def _climb(
    included: list[SpellFacts],
    excluded: list[SpellFacts],
    pair_points: float,
    config: ScoringConfig,
) -> tuple[list[SpellFacts], int]:
    """Hill-climb single swaps; return the final spells and how many swaps were scored."""
    state = state_of(included)
    current = total(state, pair_points, config)
    evaluations = 0
    for _ in range(MAX_STEPS):
        best: tuple[float, SpellFacts, SpellFacts, DeckState] | None = None
        for out in _neighbours(included, best_first=False, per_role=ROLE_OUT):
            for into in _neighbours(excluded, best_first=True, per_role=ROLE_IN):
                if (
                    into.splash
                    and not out.splash
                    and (state.splash_cards >= config.targets.splash_max_cards)
                ):
                    continue
                candidate = state.swap(out, into)
                evaluations += 1
                gain = total(candidate, pair_points, config) - current
                if gain > 1e-9 and (best is None or gain > best[0] + 1e-9):
                    best = (gain, out, into, candidate)
        if best is None:
            break
        gain, out, into, state = best
        current += gain
        included = [f for f in included if f.key != out.key] + [into]
        excluded = [f for f in excluded if f.key != into.key] + [out]
    return included, evaluations


def _score(
    pool: Pool,
    chosen: list[tuple[Card, int]],
    main: tuple[Color, ...],
    splash: Color | None,
    inputs: BuildInputs,
) -> ScoredDeck:
    """Score a finished spell list with lands recomputed for exactly those spells."""
    manabase = _manabase(pool, chosen, main, splash, inputs)
    facts = [_facts(card, i, inputs, main, manabase) for card, i in chosen]
    state = state_of(facts)
    pair = inputs.pairs[pair_code(main)]
    breakdown = terms(state, pair.points, inputs.config)
    spells = _group(chosen)
    return ScoredDeck(
        colors=pair_code(main),
        splash=splash,
        spells=tuple(PoolEntry(card, n) for card, n in spells),
        lands=manabase.lands,
        total=sum(t.contribution for t in breakdown),
        total_se=math.sqrt(
            sum(
                (inputs.config.weights.card_quality * n * inputs.values[c.front_name].se) ** 2
                for c, n in spells
            )
            + _pair_se(pair_code(main), inputs) ** 2
        ),
        terms=breakdown,
        values=tuple(inputs.values[card.front_name] for card, _ in spells),
        sources=tuple(
            (color, manabase.sources[color]) for color in WUBRG if color in manabase.sources
        ),
    )


def _candidate(
    pool: Pool,
    main: tuple[Color, ...],
    splash: Color | None,
    inputs: BuildInputs,
) -> tuple[ScoredDeck | None, int]:
    """Build the best deck for one pair and optional splash; None when it cannot be built."""
    spells = [e for e in pool.entries if not _is_land(e.card)]
    main_copies = _copies(e for e in spells if can_cast(castable_cost(e.card), main))
    if len(main_copies) < DECK_SIZE - 17:
        return None, 0
    splash_copies: list[tuple[Card, int]] = []
    if splash is not None:
        for card, i in _copies(e for e in spells if not can_cast(castable_cost(e.card), main)):
            cost = castable_cost(card)
            if (
                can_cast(cost, (*main, splash))
                and cost.pips.get(splash, 0) == 1
                and (card.mana_value >= 4 or Role.REMOVAL in classify(card))
            ):
                splash_copies.append((card, i))
        if not splash_copies:
            return None, 0
    size = DECK_SIZE - land_count(_group(_fill(inputs, main_copies, DECK_SIZE - 17)))
    chosen = _fill(inputs, main_copies, size)
    manabase = _manabase(pool, chosen, main, splash, inputs)
    facts_of = {
        (card.oracle_id, i): _facts(card, i, inputs, main, manabase)
        for card, i in main_copies + splash_copies
    }
    included = [facts_of[(card.oracle_id, i)] for card, i in chosen]
    chosen_keys = {f.key for f in included}
    excluded = [f for f in facts_of.values() if f.key not in chosen_keys]
    final, evaluations = _climb(
        included, excluded, inputs.pairs[pair_code(main)].points, inputs.config
    )
    by_key = {f"{card.oracle_id}#{i}": (card, i) for card, i in main_copies + splash_copies}
    final_copies = [by_key[f.key] for f in final]
    if splash is not None and not any(f.splash for f in final):
        return None, evaluations
    deck = _score(pool, final_copies, main, splash, inputs)
    if splash is not None and dict(deck.sources).get(splash, 0) < (
        inputs.config.targets.splash_min_sources
    ):
        return None, evaluations
    return deck, evaluations


def _splash_bound(deck: ScoredDeck, pool: Pool, splash: Color, inputs: BuildInputs) -> float:
    """The most a splash could add to a pair's deck; never an underestimate."""
    main = tuple(Color(c) for c in deck.colors)
    config = inputs.config
    candidates = []
    for entry in pool.entries:
        cost = castable_cost(entry.card)
        if (
            not _is_land(entry.card)
            and not can_cast(cost, main)
            and can_cast(cost, (*main, splash))
        ):
            candidates += [entry.card] * entry.count
    best = sorted((inputs.values[c.front_name].q for c in candidates), reverse=True)
    best = best[: config.targets.splash_max_cards]
    weakest = sorted(inputs.values[e.card.front_name].q for e in deck.spells)[: len(best)]
    w = config.weights
    bomb_gain = w.bomb * sum(1 for c in candidates if c.front_name in inputs.bombs)
    removal_gain = w.removal * sum(1 for c in candidates if Role.REMOVAL in classify(c))
    return w.card_quality * (sum(best) - sum(weakest)) + bomb_gain + removal_gain


def _pair_se(colors: str, inputs: BuildInputs) -> float:
    """Sampling error of a pair's term, in score points."""
    pair = inputs.pairs[colors]
    if pair.used is None:
        return 0.0
    k = inputs.config.shrinkage.pair_prior_games
    points = 100 * math.sqrt(pair.used * (1 - pair.used) / (pair.games + k))
    return inputs.config.weights.pair_strength * points


def _gap_se(a: ScoredDeck, b: ScoredDeck, inputs: BuildInputs) -> float:
    """Standard error of the difference between two decks' scores.

    Card values count only where the decks differ; copies of one card move together, so a
    difference of two copies counts four times the variance of one. The pair terms count
    when the decks' colors differ. Model error is not included.
    """
    weight = inputs.config.weights.card_quality
    se_of = {v.name: v.se for v in (*a.values, *b.values)}
    count_a = {e.card.front_name: e.count for e in a.spells}
    count_b = {e.card.front_name: e.count for e in b.spells}
    variance = sum(
        ((count_a.get(name, 0) - count_b.get(name, 0)) * weight * se_of[name]) ** 2
        for name in set(count_a) | set(count_b)
    )
    if a.colors != b.colors:
        variance += _pair_se(a.colors, inputs) ** 2 + _pair_se(b.colors, inputs) ** 2
    return math.sqrt(variance)


def build_decks(pool: Pool, inputs: BuildInputs) -> BuildResult:
    """Build every candidate deck and return the best few. Pure and deterministic.

    Args:
        pool: The resolved pool.
        inputs: Card values, pair values, bombs, and the configuration.

    Returns:
        The top three decks plus any deck within one standard error of the third (at most
        `inputs.max_decks`), best first, each with its gap to the next; empty when no pair
        has enough spells.
    """
    evaluations = 0
    candidates: list[ScoredDeck] = []
    for main in PAIRS:
        deck, used = _candidate(pool, main, None, inputs)
        evaluations += used
        if deck is not None:
            candidates.append(deck)
    for base in sorted(candidates, key=lambda d: (-d.total, d.label)):
        ranked = sorted((d.total for d in candidates), reverse=True)
        cutoff = ranked[TOP_N - 1] if len(ranked) >= TOP_N else -math.inf
        base_colors = tuple(Color(c) for c in base.colors)
        for splash in (c for c in WUBRG if c not in base_colors):
            if base.total + _splash_bound(base, pool, splash, inputs) <= cutoff:
                continue
            deck, used = _candidate(pool, base_colors, splash, inputs)
            evaluations += used
            if deck is not None:
                candidates.append(deck)
    ranked_decks = sorted(candidates, key=lambda d: (-d.total, d.label))
    keep = ranked_decks[:TOP_N]
    if len(ranked_decks) > TOP_N:
        last = keep[-1]
        keep += [d for d in ranked_decks[TOP_N:] if last.total - d.total < _gap_se(last, d, inputs)]
    if inputs.max_decks is not None:
        keep = keep[: inputs.max_decks]
    final = []
    for i, deck in enumerate(keep):
        if i + 1 < len(keep):
            nxt = keep[i + 1]
            deck = dataclasses.replace(
                deck, gap_to_next=deck.total - nxt.total, gap_se=_gap_se(deck, nxt, inputs)
            )
        final.append(deck)
    return BuildResult(decks=tuple(final), evaluations=evaluations)


def build_for_pair(pool: Pool, inputs: BuildInputs, colors: str) -> ScoredDeck | None:
    """The best unsplashed deck in exactly these two colors, or None when it cannot be built.

    Used to ask "what would the engine have built in the colors the player chose".
    """
    main = tuple(Color(c) for c in colors)
    return _candidate(pool, main, None, inputs)[0]


def score_spells(
    pool: Pool,
    spells: Sequence[tuple[Card, int]],
    colors: str,
    splash: Color | None,
    inputs: BuildInputs,
) -> ScoredDeck:
    """Score a given spell list (for example the deck a player built) the engine's way.

    Lands are chosen by the engine for those spells, so decks are compared on their spells.
    """
    copies = [(card, i) for card, n in spells for i in range(n)]
    return _score(pool, copies, tuple(Color(c) for c in colors), splash, inputs)
