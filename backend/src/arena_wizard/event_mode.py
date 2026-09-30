"""Build decks without the public Sealed file: FRA event mode (decision 0007).

`choose_sources` is pure: given what is cached and pasted, it picks each layer of the
value chain and records why every other source was not used. `data_block` turns that into
the lines a build prints first, and `build_event` ranks the decks.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from arena_wizard.domain.cards import Rarity
from arena_wizard.domain.decks import ScoredDeck
from arena_wizard.domain.pool import Pool
from arena_wizard.domain.scoring import EventScoring, ScoringConfig
from arena_wizard.domain.sets import EventType, SetConfig
from arena_wizard.domain.stats import Snapshot
from arena_wizard.engine.bombs import CuratedBomb, event_bomb_scores
from arena_wizard.engine.builder import build_decks, prepare_event_inputs
from arena_wizard.engine.event_values import DataLayer, data_layer
from arena_wizard.engine.explain import arena_list, describe_event, value_line
from arena_wizard.engine.grades import GradeScores, GradeSource, grade_scores
from arena_wizard.pastes.sources import source_for
from arena_wizard.pastes.store import (
    LAYER_NAMES,
    StoredPaste,
    latest_card_data,
    latest_grades,
    source_label,
    to_snapshot,
)

Echo = Callable[[str], None]
DIRECT_ORDER = (EventType.ARENA_DIRECT_SEALED, EventType.SEALED)
USAGE_GUIDELINES = "https://www.17lands.com/usage_guidelines"


@dataclass(frozen=True, slots=True)
class Sources:
    """What event mode will use, and what it found but set aside, with the reason."""

    grades: tuple[StoredPaste, ...]
    proxy_name: str | None
    proxy: Snapshot | None
    direct: StoredPaste | None
    not_used: tuple[tuple[StoredPaste, str], ...]


def choose_sources(
    pastes: Sequence[StoredPaste],
    public_draft: Snapshot | None,
    public_draft_label: str,
    covered: frozenset[EventType],
) -> Sources:
    """Pick the chain's layers. Pure.

    Premier Draft: the cached public file, else the newest Premier Draft paste. Direct win
    rates: the newest Arena Direct paste, else the newest Sealed paste. Grades: the newest
    paste of each reviewer. Pastes that automated data covers are never chosen.
    """
    draft_paste = latest_card_data(pastes, EventType.PREMIER_DRAFT, covered)
    direct = next(
        (p for e in DIRECT_ORDER if (p := latest_card_data(pastes, e, covered)) is not None),
        None,
    )
    grades = latest_grades(pastes)
    chosen = {id(p) for p in (*grades, direct)} | (
        {id(draft_paste)} if public_draft is None and draft_paste is not None else set()
    )
    not_used = []
    for paste in pastes:
        if id(paste) in chosen:
            continue
        if paste.key.event_type in covered:
            reason = "the public file replaces it"
        elif paste.key.event_type is EventType.PREMIER_DRAFT and public_draft is not None:
            reason = "the public Premier Draft file is used instead"
        elif paste.key.event_type is EventType.SEALED and direct is not None:
            reason = "the Arena Direct paste is preferred"
        else:
            reason = "a newer paste from this source is used"
        not_used.append((paste, reason))
    if public_draft is not None:
        return Sources(grades, public_draft_label, public_draft, direct, tuple(not_used))
    proxy = to_snapshot(draft_paste) if draft_paste else None
    name = source_label(draft_paste) if draft_paste else None
    return Sources(grades, name, proxy, direct, tuple(not_used))


def grade_inputs(grades: Sequence[StoredPaste]) -> tuple[GradeSource, ...]:
    """Each grade paste as a source of values and grades as written."""
    return tuple(
        GradeSource(
            label=source_for(p.key.source_id).label,
            values={r.name: r.value for r in p.grade_rows if r.value is not None},
            raw={r.name: r.raw for r in p.grade_rows if r.value is not None},
        )
        for p in grades
    )


def _game_range(snapshot: Snapshot) -> str:
    games = sorted(c.games_gih for c in snapshot.cards.values() if c.games_gih)
    if not games:
        return "no cards with games"
    return (
        f"game-in-hand counts {games[0]:,} to {games[-1]:,} per card, median "
        f"{statistics.median(games):,.0f}; {len(games)} cards"
    )


WEB_HOW = {
    "direct": "Add it on the Pastes page: 17Lands card data, Arena Direct Sealed.",
    "draft": "Add it on the Pastes page: 17Lands card data, Premier Draft (sign in to 17Lands).",
    "grades": "Add it on the Pastes page: one reviewer's grades per paste.",
    "public": "17Lands publishes it weeks after release; the app loads it then.",
}


def data_block(
    config: SetConfig,
    event: EventScoring,
    sources: Sources,
    scores: GradeScores | None,
    curated: tuple[CuratedBomb, ...],
    today: dt.date,
    public_embargoed: bool,
    web: bool = False,
    auto: tuple[str, int] | None = None,
) -> list[str]:
    """What this build rests on, what is missing, and how to add it.

    `web` turns the CLI commands into directions to the web app's Pastes page, because a
    friend on the web cannot run the CLI and its pastes live in another store.
    """
    lines = _data_block(config, event, sources, scores, curated, today, public_embargoed, auto)
    if not web:
        return lines
    replaced = []
    skip = False
    for line in lines:
        if skip:
            skip = False
            continue
        if "missing  Copy" in line:
            replaced.append(line.split("missing")[0] + "missing  " + WEB_HOW["direct"])
            skip = True
        elif "missing  Sign in to 17Lands" in line:
            replaced.append(line.split("missing")[0] + "missing  " + WEB_HOW["draft"])
            skip = True
        elif line.startswith("  Grades       missing"):
            replaced.append("  Grades       missing  " + WEB_HOW["grades"])
        elif line.startswith("  Public file"):
            status = "embargoed" if public_embargoed else "missing"
            replaced.append(f"  Public file  {status:8} {WEB_HOW['public']}")
        else:
            replaced.append(line)
    return replaced


def _data_block(
    config: SetConfig,
    event: EventScoring,
    sources: Sources,
    scores: GradeScores | None,
    curated: tuple[CuratedBomb, ...],
    today: dt.date,
    public_embargoed: bool,
    auto: tuple[str, int] | None = None,
) -> list[str]:
    """The Data block with the CLI's commands."""
    code = config.code
    lines = [f"{code} data for this build ({code} reached Arena {config.arena_release_date}):"]
    if sources.direct is not None:
        snap = to_snapshot(sources.direct)
        lines.append(f"  Win rates    used     {source_label(sources.direct)}.")
        lines.append(f"                        {_game_range(snap)}; date range not recorded.")
    else:
        lines.append(
            f"  Win rates    missing  Copy {code} card data from 17Lands (Arena Direct Sealed, "
            "Table view, filters cleared, Ever in Hand and Not Seen ticked), then:"
        )
        lines.append(
            f"                        arena-wizard paste --set {code} --dataset card-data "
            "--event-type ArenaDirect_Sealed --source 17lands-card-data --file PATH"
        )
    if sources.proxy is not None and sources.proxy_name is not None:
        lines.append(f"  Draft data   used     {sources.proxy_name}.")
        lines.append(
            f"                        {_game_range(sources.proxy)}; draft results used as a "
            f"proxy for sealed ({event.proxy_slope:g} × draft, plus removal and rarity "
            "adjustments)."
        )
    else:
        lines.append(
            "  Draft data   missing  Sign in to 17Lands and copy Premier Draft card data "
            "the same way, then:"
        )
        lines.append(
            f"                        arena-wizard paste --set {code} --dataset card-data "
            "--event-type PremierDraft --source 17lands-card-data --file PATH"
        )
    if scores is not None:
        lines.append("  Grades       used     Draft grades; no source grades for sealed.")
        for paste in sources.grades:
            graded = sum(r.value is not None for r in paste.grade_rows)
            published = f", published {paste.published_on}" if paste.published_on else ""
            lines.append(
                f"                        {source_for(paste.key.source_id).label}, copied "
                f"{paste.copied_on}{published}: {graded} cards graded."
            )
        lines.append(
            f"                        Grade to value: slope {event.slope:g}, error "
            f"±{event.sigma:g} points per card, assumed, not yet tested against results."
        )
    else:
        lines.append(
            f"  Grades       missing  arena-wizard paste --set {code} --dataset grades "
            "--source llu-marc --file PATH   (one reviewer per paste)"
        )
    added = [c for c in curated if c.action == "add"]
    counted = f"{auto[1]} cards" if auto and auto[1] else "none reach the bomb bar"
    used = ([f"automatic from {auto[0]} ({counted})"] if auto else []) + (
        [f"the group's curated list ({len(added)} cards)"] if curated else []
    )
    if used:
        text = "; ".join(used)
        lines.append(f"  Bombs        used     {text[0].upper()}{text[1:]}.")
    else:
        lines.append(
            "  Bombs        missing  The automatic list needs at least 150 games per card in "
            f"pasted win rates; the group's list, config/bombs/{code}.yaml, is not written."
        )
    status = "embargoed" if public_embargoed else "missing"
    lines.append(
        f"  Public file  {status:8} 17Lands publishes it weeks after release; then run: "
        f"arena-wizard load-file --set {code}"
    )
    for paste, reason in sources.not_used:
        lines.append(f"  Not used     {source_label(paste)}: {reason}.")
    if today < config.embargo_until:
        lines.append(
            f"  17Lands asks tools not to show {code} data before {config.embargo_until} "
            f"({USAGE_GUIDELINES}). Arena Wizard shows no automated 17Lands {code} data before "
            "then; pasted win rates are ones you copied by hand, kept private (decision 0005)."
        )
    return lines


def _deck_lines(rank: int, deck: ScoredDeck, show_values: bool) -> list[str]:
    lines = [f"#{rank} {deck.label}  score {deck.total:.1f}"]
    lines += [f"  {sentence}" for sentence in deck.explanations]
    lines.append("  Breakdown (score points):")
    lines += [
        f"    {t.name.replace('_', ' '):17} {t.contribution:+7.1f}  {t.detail}" for t in deck.terms
    ]
    if show_values:
        lines.append("  Card values (points; ± is the uncertainty):")
        ordered = sorted(deck.values, key=lambda v: (-v.q, v.name))
        lines += [f"    {value_line(v)}" for v in ordered]
    lines.append("  Deck (click these into Arena):")
    lines += [f"    {line}" for line in arena_list(deck).splitlines()]
    return lines


NO_VALUES = (
    "No card values for {code}, so no deck is ranked. Rarity averages alone cannot tell one "
    "common from another, so a ranking would mostly reflect deck shape. Add draft grades or "
    "card win rates as described above."
)
NO_DECK = "No color pair has enough castable spells for a 40-card deck."


@dataclass(frozen=True, slots=True)
class EventResult:
    """An event-mode build: its Data block, its ranked decks, or why there are none."""

    data_lines: tuple[str, ...]
    decks: tuple[ScoredDeck, ...]
    refusal: str | None


def event_result(
    config: SetConfig,
    pool: Pool,
    rarity_of: dict[str, Rarity],
    sources: Sources,
    scoring: ScoringConfig,
    curated: tuple[CuratedBomb, ...],
    today: dt.date,
    public_embargoed: bool,
    web: bool = False,
) -> EventResult:
    """Rank decks in event mode. Pure: the CLI prints the result, the web app stores it."""
    scores = grade_scores(grade_inputs(sources.grades), rarity_of)
    proxy: DataLayer | None = data_layer("draft data", sources.proxy, rarity_of, True)
    direct = (
        data_layer(
            LAYER_NAMES[sources.direct.key.event_type or EventType.SEALED],
            to_snapshot(sources.direct),
            rarity_of,
            False,
        )
        if sources.direct
        else None
    )
    layers = [layer for layer in (direct, proxy) if layer is not None]
    automatic, source = event_bomb_scores(layers, rarity_of, scoring)
    auto = (
        (source, sum(s >= scoring.bombs.threshold for s in automatic.values())) if source else None
    )
    lines = tuple(
        data_block(
            config, scoring.event, sources, scores, curated, today, public_embargoed, web, auto
        )
    )
    if scores is None and proxy is None and direct is None:
        return EventResult(lines, (), NO_VALUES.format(code=config.code))
    inputs = prepare_event_inputs(pool, scores, proxy, direct, scoring, curated, automatic)
    listed = frozenset(c.name for c in curated if c.action == "add") if curated else None
    decks = describe_event(build_decks(pool, inputs).decks, inputs.bombs, listed, source)
    return EventResult(lines, decks, None if decks else NO_DECK)


def build_event(
    config: SetConfig,
    pool: Pool,
    rarity_of: dict[str, Rarity],
    sources: Sources,
    scoring: ScoringConfig,
    curated: tuple[CuratedBomb, ...],
    today: dt.date,
    public_embargoed: bool,
    echo: Echo,
) -> int:
    """Rank decks in event mode and print them after the Data block."""
    result = event_result(
        config, pool, rarity_of, sources, scoring, curated, today, public_embargoed
    )
    for line in result.data_lines:
        echo(line)
    if result.refusal is not None:
        if not result.decks and result.refusal != NO_DECK:
            echo("")
        echo(result.refusal)
        return 1
    for rank, deck in enumerate(result.decks, start=1):
        echo("")
        for line in _deck_lines(rank, deck, show_values=rank == 1):
            echo(line)
    return 0
