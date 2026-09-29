"""What each CLI command does. Every dependency is a parameter, so each is unit tested."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena_wizard.catalog import (
    CardTable,
    load_packaged_card_table,
    unresolved_names,
    write_card_table,
)
from arena_wizard.domain.decks import ScoredDeck
from arena_wizard.domain.pool import Pool, WarningKind
from arena_wizard.domain.scoring import load_scoring_config
from arena_wizard.domain.sets import (
    EventType,
    Format,
    SetConfig,
    load_set_config,
    packaged_set_codes,
)
from arena_wizard.domain.stats import Snapshot
from arena_wizard.engine.bombs import load_curated
from arena_wizard.engine.builder import build_decks, prepare_inputs
from arena_wizard.engine.explain import arena_list, describe
from arena_wizard.engine.export_parser import parse_export
from arena_wizard.engine.resolver import build_index, resolve_pool
from arena_wizard.engine.values import spell_rarities
from arena_wizard.etl.game_cache import cache_dir, file_path, load_file, read_cached
from arena_wizard.etl.games import count_daily, read_games, snapshot
from arena_wizard.etl.sync_cards import compute_card_table, fetch_card_sources
from arena_wizard.eval.build_set import choose_split_day, collect_pools, select_sample
from arena_wizard.eval.gate import gate
from arena_wizard.eval.report import (
    build_report,
    evaluate_set,
    leave_one_out,
    rarity_baseline,
    render_markdown,
    report_to_json,
)
from arena_wizard.eval.storage import (
    json_text,
    presplit_path,
    read_json,
    reports_match,
    sample_path,
    samples_from_text,
    samples_to_text,
    snapshot_from_json,
    snapshot_to_json,
    switch_path,
    write_text,
)
from arena_wizard.event_mode import build_event, choose_sources
from arena_wizard.pastes.store import StoredPaste
from arena_wizard.sources.http import SourceContext
from arena_wizard.sources.seventeenlands_files import public_file_url

Echo = Callable[[str], None]
SEALED_LABEL = "17Lands public Sealed game data"
DRAFT_LABEL = "17Lands public Premier Draft game data"


def sync_cards(
    codes: tuple[str, ...],
    out_dir: Path,
    ctx: SourceContext,
    load_config: Callable[[str], SetConfig],
    echo: Echo,
) -> int:
    """Regenerate card tables; 1 when any 17Lands header name does not resolve."""
    status = 0
    for code in codes:
        config = load_config(code)
        table = compute_card_table(config, fetch_card_sources(ctx, config))
        changed = write_card_table(table, out_dir / f"{code}.json")
        header = "no 17Lands file yet" if table.header is None else table.header.event_type
        echo(
            f"{code}: {len(table.cards)} printings, header: {header}, "
            f"{'written' if changed else 'unchanged'}"
        )
        missing = unresolved_names(table)
        if missing:
            status = 1
            echo(f"{code}: {len(missing)} header names did not resolve: {', '.join(missing)}")
    return status


STATUS_TEXT = {
    "downloaded": "downloaded",
    "recounted": "recounted from the cached file",
    "unchanged": "unchanged, cache kept",
}


def load_game_file(
    code: str, event_type: EventType, ctx: SourceContext, cache: Path | None, echo: Echo
) -> int:
    """Download and count one public game file into the local cache."""
    cached, status = load_file(ctx, code, event_type, cache)
    days = sorted(cached.daily.cards)
    echo(
        f"{code} {event_type.value}: {STATUS_TEXT[status]}; "
        f"{len(days)} days ({days[0] if days else '-'} to {days[-1] if days else '-'}), "
        f"sha256 {cached.sha256[:16]}"
    )
    return 0


def statistics_for(
    code: str, cache: Path | None, event_type: EventType = EventType.SEALED
) -> Snapshot | None:
    """The full-file snapshot for a set and event type, or None when it is not cached."""
    cached = read_cached(code, event_type, cache)
    if cached is None:
        return None
    label = SEALED_LABEL if event_type is EventType.SEALED else DRAFT_LABEL
    return snapshot(cached.daily, code, label, cached.sha256)


def _deck_text(rank: int, deck: ScoredDeck) -> list[str]:
    """One deck as printed lines: score, reasons, breakdown, and the list to click in."""
    lines = [f"#{rank} {deck.label}  score {deck.total:.1f}"]
    lines += [f"  {sentence}" for sentence in deck.explanations]
    lines.append("  Breakdown (score points):")
    lines += [
        f"    {t.name.replace('_', ' '):17} {t.contribution:+7.1f}  {t.detail}" for t in deck.terms
    ]
    lines.append("  Deck (click these into Arena):")
    lines += [f"    {line}" for line in arena_list(deck).splitlines()]
    return lines


def _warning_lines(pool: Pool) -> list[str]:
    """Warnings grouped by what the player should do about them."""
    lines = []
    unknown = [w for w in pool.warnings if w.kind is WarningKind.UNKNOWN_NAME]
    if unknown:
        lines.append(f"Not recognised, in no deck ({len(unknown)}):")
        for w in unknown:
            hint = f" Did you mean: {', '.join(w.suggestions)}?" if w.suggestions else ""
            lines.append(f"  line {w.line_no}: {w.raw}.{hint}")
    unparsed = [w for w in pool.warnings if w.kind is WarningKind.UNPARSED]
    if unparsed:
        lines.append(f"Not an export line, ignored ({len(unparsed)}):")
        lines += [f"  line {w.line_no}: {w.raw}" for w in unparsed]
    for w in pool.warnings:
        if w.kind is WarningKind.WRONG_SET:
            lines.append(f"From another set: {w.message}.")
    by_name = sum(w.kind is WarningKind.ALTERNATE_PRINTING for w in pool.warnings)
    if by_name:
        lines.append(
            f"{by_name} lines matched by card name rather than set and number; "
            "values are unaffected."
        )
    return lines


@dataclass(frozen=True, slots=True)
class BuildData:
    """Everything a build can value cards from, gathered by the caller.

    `public_sealed` and `public_draft` are the cached 17Lands public files; `pastes` are
    the set's private pastes (decision 0005), and `stale` names any that must be pasted
    again. `covered` lists event types whose public file replaces pastes.
    """

    public_sealed: Snapshot | None = None
    public_draft: Snapshot | None = None
    pastes: tuple[StoredPaste, ...] = ()
    stale: tuple[str, ...] = ()
    covered: frozenset[EventType] = frozenset()


def build(
    code: str,
    fmt: Format,
    export_text: str,
    data: BuildData,
    today: dt.date,
    echo: Echo,
) -> int:
    """Parse a pasted pool, build the best decks, and print them with their reasons.

    With the public Sealed file past its embargo, values come from it (milestone 1).
    Otherwise event mode values cards from grades and pasted or public draft and Arena
    Direct win rates (decision 0007), and refuses only when there are none of those.
    """
    config = load_set_config(code)
    embargoed = today < config.embargo_until
    home = load_packaged_card_table(code)
    others = [load_packaged_card_table(c) for c in packaged_set_codes() if c != config.code]
    pool: Pool = resolve_pool(
        parse_export(export_text),
        config,
        build_index([home], config.code),
        build_index(others),
        fmt,
    )
    low, high = config.nonbasic_pool_range
    echo(f"{code} pool: {pool.nonbasic_count} non-basic cards ({code} pools run {low} to {high}).")
    for line in _warning_lines(pool):
        echo(line)
    for problem in data.stale:
        echo(f"Stored paste not used: {problem}.")
    scoring = load_scoring_config(fmt, config.code)
    curated = load_curated(config.code)
    rarity_of = spell_rarities(home.cards)
    stats = data.public_sealed
    if stats is None or embargoed:
        sources = choose_sources(
            data.pastes,
            None if embargoed else data.public_draft,
            DRAFT_LABEL,
            data.covered,
        )
        return build_event(
            config,
            pool,
            rarity_of,
            sources,
            scoring,
            curated,
            today,
            stats is not None and embargoed,
            echo,
        )
    echo(
        f"Statistics: {stats.source.label}, {stats.source.first_day} to {stats.source.last_day} "
        f"({stats.source.games:,} games)."
    )
    inputs = prepare_inputs(pool, stats, rarity_of, scoring, curated)
    decks = describe(
        build_decks(pool, inputs).decks,
        inputs.pairs,
        inputs.bombs,
        stats.source,
        curated={c.name for c in curated if c.action == "add"},
        pair_weight=scoring.weights.pair_strength,
    )
    if not decks:
        echo("No color pair has enough castable spells for a 40-card deck.")
        return 1
    for rank, deck in enumerate(decks, start=1):
        echo("")
        for line in _deck_text(rank, deck):
            echo(line)
    return 0


@dataclass(frozen=True, slots=True)
class DerivedSet:
    """One set's evaluation files, derived from a game file's exact bytes."""

    sample_text: str
    switch_text: str
    presplit_text: str
    pin: dict[str, Any]


def derive_eval_set(code: str, data: bytes, size: int) -> DerivedSet:
    """Derive a set's sample, switch pools, and pre-split counts from the file's bytes. Pure.

    Everything comes from these bytes, so the pin's sha256 always describes the data the
    files were made from. The switch pools are every post-split pool the player registered
    in at least two two-color pairs, for the same-pool comparison.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    text = gzip.decompress(data).decode("utf-8")
    layout, games = read_games(io.StringIO(text, newline=""))
    daily = count_daily(layout.names, games)
    _, games_again = read_games(io.StringIO(text, newline=""))
    records = collect_pools(layout.names, games_again)
    games_per_day = {
        day: sum(p.games for p in pairs.values()) for day, pairs in daily.pairs.items()
    }
    split_day = choose_split_day(games_per_day)
    eligible = [r for r in records.values() if r.first_day > split_day]
    sample = select_sample(records, split_day, size)
    switch = sorted(
        (
            r
            for r in eligible
            if len({b.main_colors for b in r.builds if len(b.main_colors) == 2}) >= 2
        ),
        key=lambda r: r.draft_id,
    )
    presplit = snapshot(daily, code, f"{SEALED_LABEL} (pre-split)", sha256, None, split_day)
    sample_text = samples_to_text(sample)
    switch_text = samples_to_text(switch)
    presplit_text = snapshot_to_json(presplit)
    total_games = sum(games_per_day.values())

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    return DerivedSet(
        sample_text=sample_text,
        switch_text=switch_text,
        presplit_text=presplit_text,
        pin={
            "url": public_file_url(code, EventType.SEALED),
            "sha256": sha256,
            "bytes": len(data),
            "games": total_games,
            "pools": len(records),
            "split_day": split_day.isoformat(),
            "eligible_pool_share": len(eligible) / len(records),
            "eligible_game_share": sum(r.games for r in eligible) / total_games,
            "sample_size": len(sample),
            "sample_sha256": digest(sample_text),
            "switch_size": len(switch),
            "switch_sha256": digest(switch_text),
            "presplit_sha256": digest(presplit_text),
        },
    )


def build_eval_set(
    codes: tuple[str, ...],
    size: int,
    repin: bool,
    eval_dir: Path,
    cache: Path | None,
    echo: Echo,
) -> int:
    """Derive every requested set first, then write all of them, or nothing on any error."""
    pins: dict[str, Any] = read_json(eval_dir / "pins.json") or {}
    derived: dict[str, DerivedSet] = {}
    for code in codes:
        gz = file_path(cache or cache_dir(), code, EventType.SEALED)
        if not gz.is_file():
            echo(f"{code}: no cached Sealed file; run arena-wizard load-file --set {code}")
            return 1
        data = gz.read_bytes()
        result = derive_eval_set(code, data, size)
        pinned = pins.get(code, {}).get("sha256")
        if pinned is not None and pinned != result.pin["sha256"] and not repin:
            echo(
                f"{code}: the file's sha256 {result.pin['sha256'][:16]} is not the pinned "
                f"{pinned[:16]}; 17Lands re-uploaded it. Re-run with --repin to accept it."
            )
            return 1
        derived[code] = result
    for code, result in derived.items():
        write_text(sample_path(eval_dir, code), result.sample_text)
        write_text(switch_path(eval_dir, code), result.switch_text)
        write_text(presplit_path(eval_dir, code), result.presplit_text)
        pins[code] = result.pin
        echo(
            f"{code}: {result.pin['sample_size']} sample pools and {result.pin['switch_size']} "
            f"switch pools of {result.pin['pools']}; split day {result.pin['split_day']}"
        )
    write_text(eval_dir / "pins.json", json_text(pins))
    return 0


def verdict(
    report: dict[str, Any],
    committed_json: dict[str, Any] | None,
    committed_md: str | None,
    check: bool,
    base_report: dict[str, Any] | None,
    accepted: list[dict[str, str]],
) -> tuple[str, ...]:
    """Every problem with a fresh report: staleness (in check mode) and gate failures. Pure."""
    problems: list[str] = []
    if check:
        if committed_json is None or not reports_match(report, committed_json):
            problems.append("report.json is stale: re-run arena-wizard eval run and commit it")
        elif committed_md != render_markdown(committed_json):
            problems.append("report.md does not match report.json: re-run arena-wizard eval run")
    problems += [
        f"gate: {f.set_code} {f.check}: {f.message}" for f in gate(report, base_report, accepted)
    ]
    return tuple(problems)


def _file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run_eval(
    eval_dir: Path,
    check: bool,
    base_report: dict[str, Any] | None,
    echo: Echo,
) -> int:
    """Evaluate every pinned set, then check against the committed report and gate."""
    pins: dict[str, Any] = read_json(eval_dir / "pins.json") or {}
    if not pins:
        echo("No pinned evaluation sets; run arena-wizard eval build-set first.")
        return 1
    scoring = load_scoring_config(Format.BO1_SEALED)
    package = Path(__file__).resolve().parent
    loaded: dict[str, tuple[dict[str, Any], dict[str, str], CardTable, dict[str, Any], Snapshot]]
    loaded = {}
    for code, pin in sorted(pins.items()):
        paths = {
            "sample_sha256": sample_path(eval_dir, code),
            "switch_sha256": switch_path(eval_dir, code),
            "presplit_sha256": presplit_path(eval_dir, code),
        }
        texts = {}
        for key, path in paths.items():
            if not path.is_file() or _file_sha256(path) != pin.get(key):
                echo(f"{code}: {path.name} is missing or does not match its pin")
                return 1
            texts[key] = path.read_text(encoding="utf-8")
        table = load_packaged_card_table(code)
        provenance = dict(pin) | {
            "card_table_sha256": _file_sha256(package / "data" / "cards" / f"{code}.json"),
            "curated_bombs_sha256": _file_sha256(package / "config" / "bombs" / f"{code}.yaml"),
        }
        snap = snapshot_from_json(texts["presplit_sha256"])
        loaded[code] = (pin, texts, table, provenance, snap)
    # The data-free baseline values each set's cards at the other set's rarity averages
    # (decision 0007), so every set is loaded before any is evaluated.
    baselines = leave_one_out(
        {code: rarity_baseline(item[4], item[2], scoring) for code, item in loaded.items()}
    )
    sections = {}
    for code, (pin, texts, table, provenance, snap) in loaded.items():
        sections[code] = evaluate_set(
            code,
            samples_from_text(texts["sample_sha256"]),
            samples_from_text(texts["switch_sha256"]),
            snap,
            table,
            build_index([table], code),
            scoring,
            load_curated(code),
            provenance,
            baselines[code],
        )
        echo(f"{code}: evaluated {pin['sample_size']} pools and {pin['switch_size']} switch pools")
    report = build_report(sections, scoring)
    json_path, md_path = eval_dir / "report.json", eval_dir / "report.md"
    repository = eval_dir.resolve().parents[1]
    accepted = [
        entry
        for entry in (read_json(eval_dir / "accepted.json") or [])
        if (repository / entry.get("decision", "")).is_file()
    ]
    problems = verdict(
        report,
        read_json(json_path),
        md_path.read_text(encoding="utf-8") if md_path.is_file() else None,
        check,
        base_report,
        accepted,
    )
    if not check:
        write_text(json_path, report_to_json(report))
        write_text(md_path, render_markdown(report))
    for problem in problems:
        echo(problem)
    return 1 if problems else 0
