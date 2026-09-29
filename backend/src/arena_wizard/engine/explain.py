"""Plain sentences about each deck, and the list the player clicks into Arena.

Every sentence that cites a number names its source. A value that is mostly prior shows
both the observed and the used rate. Two decks within one standard error are called a
toss-up rather than ranked, and the standard error says what it covers. With no
statistics loaded, nothing is presented as data.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence

from arena_wizard.domain.cards import Color
from arena_wizard.domain.decks import CardValue, ScoredDeck
from arena_wizard.domain.pool import PoolEntry
from arena_wizard.domain.stats import SourceRef
from arena_wizard.engine.mana import can_cast, castable_cost
from arena_wizard.engine.roles import Role, classify
from arena_wizard.engine.values import PairValue

PRIOR_SHARE_TO_SHOW = 0.2
NAMES_TO_LIST = 5


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def window(source: SourceRef | None) -> str:
    """Name the source and its date range, or say that nothing is loaded."""
    if source is None or source.first_day is None:
        return "no statistics loaded"
    return f"{source.label}, {source.first_day} to {source.last_day}"


def pair_sentence(pair: PairValue, source: SourceRef | None) -> str:
    """The color pair's record, with observed and used rates when the prior matters."""
    if pair.games == 0:
        return f"{pair.colors} decks: no record in {window(source)}."
    share = pair.prior_share or 0.0
    rate = (
        f"{_percent(pair.observed)} observed, {_percent(pair.used)} after shrinkage"
        if share > PRIOR_SHARE_TO_SHOW
        else _percent(pair.used)
    )
    return (
        f"{pair.colors} decks: {rate} win rate (n={pair.games:,}, {100 * share:.0f}% prior) "
        f"in {window(source)}."
    )


def _names(values: Sequence[CardValue]) -> str:
    listed = [v.name for v in values[:NAMES_TO_LIST]]
    more = len(values) - len(listed)
    return ", ".join(listed) + (f", and {more} more" if more > 0 else "")


def _data_sentences(deck: ScoredDeck) -> list[str]:
    """Which card values are mostly prior, and which have no data at all."""
    sentences = []
    thin = sorted(
        (v for v in deck.values if v.games and (v.prior_share or 0.0) > PRIOR_SHARE_TO_SHOW),
        key=lambda v: (-abs(v.q), v.name),
    )[:3]
    if thin:
        sentences.append(
            "Mostly prior: "
            + "; ".join(
                f"{v.name} {_percent(v.observed)} observed, {_percent(v.used)} used "
                f"(n={v.games}, {100 * (v.prior_share or 0.0):.0f}% prior)"
                for v in thin
            )
            + "."
        )
    missing = sorted((v for v in deck.values if v.games == 0), key=lambda v: v.name)
    if missing:
        sentences.append(
            f"No games in the statistics: {_names(missing)}. Each is valued at its rarity's "
            "average."
        )
    return sentences


def _bomb_sentence(
    deck: ScoredDeck, bombs: Mapping[str, float], curated: Collection[str], source: SourceRef | None
) -> str | None:
    names = [e.card.front_name for e in deck.spells if e.card.front_name in bombs]
    if not names:
        return None
    automatic = [n for n in names if n not in curated]
    chosen = [n for n in names if n in curated]
    parts = []
    if automatic:
        parts.append(f"{', '.join(automatic)} (automatic, from {window(source)})")
    if chosen:
        parts.append(f"{', '.join(chosen)} (the group's curated list)")
    return "Bombs: " + "; ".join(parts) + "."


def _card_differences(deck: ScoredDeck, other: ScoredDeck) -> str:
    mine = {e.card.front_name for e in deck.spells}
    theirs = {e.card.front_name for e in other.spells}
    only_here = sorted(mine - theirs)
    only_there = sorted(theirs - mine)
    parts = []
    if only_here:
        parts.append("only here: " + ", ".join(only_here[:NAMES_TO_LIST]))
    if only_there:
        parts.append("only there: " + ", ".join(only_there[:NAMES_TO_LIST]))
    return ("; ".join(parts) + ".") if parts else ""


def _comparison(deck: ScoredDeck, other: ScoredDeck, has_data: bool) -> str:
    """How a deck compares with the next one: the gap, what it covers, and what differs."""
    theirs = {t.name: t for t in other.terms}
    differences = sorted(
        (t for t in deck.terms if abs(t.contribution - theirs[t.name].contribution) > 0.05),
        key=lambda t: (-abs(t.contribution - theirs[t.name].contribution), t.name),
    )[:2]
    parts = []
    for t in differences:
        delta = t.contribution - theirs[t.name].contribution
        if t.name == "card_quality":
            parts.append(
                f"card values {delta:+.1f} (sum {t.raw:+.1f} here, {theirs[t.name].raw:+.1f} there)"
            )
        else:
            parts.append(
                f"{t.name.replace('_', ' ')} {delta:+.1f} ({t.detail} here, "
                f"{theirs[t.name].detail} there)"
            )
    if not has_data:
        lead = f"Ahead of {other.label} by {deck.gap_to_next or 0.0:.1f} on deck shape alone."
    elif deck.is_toss_up:
        lead = f"Within one standard error of {other.label}: treat the order as a toss-up."
    else:
        lead = (
            f"Ahead of {other.label} by {deck.gap_to_next or 0.0:.1f} score points (standard "
            f"error {deck.gap_se or 0.0:.1f}, from sample sizes only)."
        )
    detail = (" Largest differences: " + "; ".join(parts) + ".") if parts else ""
    cards = _card_differences(deck, other)
    return lead + detail + (f" Cards {cards}" if cards else "")


def describe(
    decks: Sequence[ScoredDeck],
    pairs: Mapping[str, PairValue],
    bombs: Mapping[str, float],
    source: SourceRef | None,
    curated: Collection[str] = (),
    pair_weight: float = 1.0,
) -> tuple[ScoredDeck, ...]:
    """Attach explanation sentences to ranked decks. Pure.

    Args:
        decks: The ranked decks, best first, with gaps recorded.
        pairs: Pair values by color code.
        bombs: Bomb strength by card name.
        source: Where the statistics came from, or None when none are loaded.
        curated: Names from the set's curated bomb list, labelled as such.
        pair_weight: The pair term's weight; its sentence is left out when it is zero.

    Returns:
        The same decks with `explanations` filled in.
    """
    has_data = source is not None and source.first_day is not None
    described = []
    for i, deck in enumerate(decks):
        sentences: list[str] = []
        if has_data and pair_weight:
            sentences.append(pair_sentence(pairs[deck.colors], source))
        bomb = _bomb_sentence(deck, bombs, curated, source)
        if bomb:
            sentences.append(bomb)
        if has_data:
            sentences += _data_sentences(deck)
        if deck.splash is not None:
            main = [Color(c) for c in deck.colors]
            splashed = [
                e.card.front_name for e in deck.spells if not can_cast(castable_cost(e.card), main)
            ]
            sentences.append(
                f"Splashes {', '.join(splashed)} off {dict(deck.sources).get(deck.splash, 0)} "
                f"{deck.splash.name.lower()} land sources."
            )
        if i + 1 < len(decks):
            sentences.append(_comparison(deck, decks[i + 1], has_data))
        described.append(dataclasses.replace(deck, explanations=tuple(sentences)))
    return tuple(described)


def arena_list(deck: ScoredDeck) -> str:
    """The deck as Arena sorts it: creatures, then other spells, each by mana value and
    name, then lands. Arena cannot import during a Limited event, so this is the list to
    click in by hand.
    """
    creatures: list[PoolEntry] = []
    others: list[PoolEntry] = []
    for entry in deck.spells:
        (creatures if Role.CREATURE in classify(entry.card) else others).append(entry)
    lines = []
    for group in (creatures, others):
        for entry in sorted(group, key=lambda e: (e.card.mana_value, e.card.front_name)):
            lines.append(f"{entry.count} {entry.card.front_name}")
    lines += [f"{land.count} {land.name}" for land in deck.lands]
    return "\n".join(lines)
