"""Builds for the web app: resolve a pasted pool, key the build by its inputs, rank decks.

Until milestone 4 loads 17Lands public files into the database, the web app has no
public statistics, so every web build is an event-mode build from the group's pastes
(decision 0007). The inputs key hashes everything that can change the result, so an
unchanged pool with unchanged pastes reuses its build, and any new paste makes a new one.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.domain.decks import ScoredDeck
from arena_wizard.domain.pool import Pool
from arena_wizard.domain.scoring import load_scoring_config
from arena_wizard.domain.sets import (
    EventType,
    Format,
    SetConfig,
    load_set_config,
    packaged_set_codes,
)
from arena_wizard.engine.adjust import Adjustment
from arena_wizard.engine.bombs import load_curated
from arena_wizard.engine.explain import arena_list
from arena_wizard.engine.export_parser import parse_export
from arena_wizard.engine.resolver import build_index, resolve_pool
from arena_wizard.engine.values import spell_rarities
from arena_wizard.event_mode import EventResult, choose_sources, event_result
from arena_wizard.pastes.store import StoredPaste, to_json


def resolve_export(config: SetConfig, fmt: Format, text: str) -> Pool:
    """Parse and resolve an Arena export against the set's card table. Pure."""
    home = load_packaged_card_table(config.code)
    others = [load_packaged_card_table(c) for c in packaged_set_codes() if c != config.code]
    return resolve_pool(
        parse_export(text), config, build_index([home], config.code), build_index(others), fmt
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def body_hash(body: dict[str, Any]) -> str:
    """Hash of a request body, to recognise an identical replay of a create."""
    return _digest(body)


def pool_hash(pool: Pool) -> str:
    """Hash of the resolved pool: which printings, how many, and the basics."""
    return _digest(
        [
            [[e.card.set_code, e.card.collector_number, e.count] for e in pool.entries],
            [[e.card.front_name, e.count] for e in pool.basics],
        ]
    )


def tree_digest(root: Traversable) -> str:
    """One hash of every file under a directory, bytecode excluded. Each path and each
    file's contents is prefixed with its length, so no two trees can hash alike by moving
    bytes between a name and its contents."""
    files: list[tuple[str, Traversable]] = []
    stack: list[tuple[str, Traversable]] = [("", root)]
    while stack:
        prefix, folder = stack.pop()
        for entry in folder.iterdir():
            if entry.name == "__pycache__" or entry.name.endswith((".pyc", ".pyo")):
                continue
            path = f"{prefix}/{entry.name}"
            if entry.is_dir():
                stack.append((path, entry))
            else:
                files.append((path, entry))
    digest = hashlib.sha256()
    for path, entry in sorted(files, key=lambda item: item[0]):
        for part in (path.encode("utf-8"), entry.read_bytes()):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


@cache
def package_digest() -> str:
    """The installed package's tree digest: code, set and scoring configs, card tables,
    curated lists, and the source registry. Any deploy that changes any of them changes
    every build key, so a hotfix is never hidden behind a cached build. Computed once per
    process; a rebuild costs about a tenth of a second (decision 0008).
    """
    return tree_digest(resources.files("arena_wizard"))


def inputs_key(
    pool: Pool,
    pastes: Sequence[StoredPaste],
    today: dt.date,
    adjustments: Sequence[Adjustment] = (),
) -> str:
    """Everything that can change a build: the pool, every paste as stored (rows, parser
    version, dates), the group's adjustments, the package, and whether the set's embargo
    has passed."""
    config = load_set_config(pool.set_code)
    return _digest(
        {
            "pool": pool_hash(pool),
            "pastes": sorted(to_json(p) for p in pastes),
            "adjustments": sorted(dataclasses.astuple(a) for a in adjustments),
            "package": package_digest(),
            "embargo_passed": today >= config.embargo_until,
        }
    )


def covered(config: SetConfig, today: dt.date) -> frozenset[EventType]:
    """Event types whose public file is published and past the embargo (0005 rule 4).

    The server keeps no download cache, so the committed list decides; pastes of these
    are refused and ignored, even though the web app cannot read the files until
    milestone 4 loads them into the database.
    """
    return frozenset(config.public_files) if today >= config.embargo_until else frozenset()


def run_build(
    pool: Pool,
    pastes: Sequence[StoredPaste],
    today: dt.date,
    stale: Sequence[str] = (),
    adjustments: Sequence[Adjustment] = (),
) -> tuple[str, EventResult, str]:
    """Rank a pool's decks from the group's pastes.

    Args:
        pool: The resolved pool.
        pastes: The set's current pastes.
        today: The UTC day.
        stale: Messages for pastes left out because an older parser stored them.
        adjustments: The group's card adjustments for the set.

    Returns:
        The mode ("event" until milestone 4), the result, and the config version.
    """
    config = load_set_config(pool.set_code)
    scoring = load_scoring_config(pool.format, config.code)
    table = load_packaged_card_table(config.code)
    sources = choose_sources(pastes, None, "", covered(config, today))
    result = event_result(
        config,
        pool,
        spell_rarities(table.cards),
        sources,
        scoring,
        load_curated(config.code),
        today,
        False,
        web=True,
        adjustments=adjustments,
    )
    notes = tuple(f"  Not used     {message}." for message in stale)
    result = dataclasses.replace(result, data_lines=result.data_lines + notes)
    return "event", result, scoring.version


def deck_payload(deck: ScoredDeck) -> dict[str, Any]:
    """Everything the deck page shows, as JSON."""
    return {
        "label": deck.label,
        "colors": deck.colors,
        "splash": deck.splash.value if deck.splash else None,
        "total": deck.total,
        "total_se": deck.total_se,
        "gap_to_next": deck.gap_to_next,
        "gap_se": deck.gap_se,
        "toss_up": deck.is_toss_up,
        "explanations": list(deck.explanations),
        "terms": [
            {"name": t.name, "contribution": t.contribution, "detail": t.detail} for t in deck.terms
        ],
        "spells": [
            {
                "name": e.card.front_name,
                "count": e.count,
                "mana_cost": e.card.mana_cost,
                "mana_value": e.card.mana_value,
                "type_line": e.card.type_line,
                "rarity": e.card.rarity.value,
                "image_uri": e.card.image_uri,
            }
            for e in deck.spells
        ],
        "lands": [{"name": land.name, "count": land.count} for land in deck.lands],
        "values": [
            {
                "name": v.name,
                "q": v.q,
                "se": v.se,
                "basis": v.basis.value,
                "observed": v.observed,
                "games": v.games,
                "source": v.source,
                "layers": [{"name": layer.name, "share": layer.share} for layer in v.layers],
                "grades": [{"source": s, "grade": g} for s, g in v.grades],
                "adjustment": (
                    {"q_delta": v.adjustment[0], "by": v.adjustment[1]} if v.adjustment else None
                ),
            }
            for v in deck.values
        ],
        "arena_list": arena_list(deck),
    }
