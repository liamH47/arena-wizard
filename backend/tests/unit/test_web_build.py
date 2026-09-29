"""Web builds: pool resolution, hashing, the inputs key, and deck payloads."""

from __future__ import annotations

import dataclasses
import datetime as dt
import random
from importlib import resources
from pathlib import Path

import pytest

from arena_wizard import web_build
from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.cli import decode_text
from arena_wizard.domain.cards import Color
from arena_wizard.domain.pool import Pool
from arena_wizard.domain.sets import EventType, Format, load_set_config
from arena_wizard.engine.values import spell_rarities
from arena_wizard.paste_commands import PasteRequest, plan_paste
from arena_wizard.pastes.parsers import PARSER_VERSION, CardDataRow
from arena_wizard.pastes.store import PasteKey, StoredPaste
from arena_wizard.web_build import (
    body_hash,
    covered,
    deck_payload,
    inputs_key,
    package_digest,
    pool_hash,
    resolve_export,
    run_build,
    tree_digest,
)
from tests.api.app_fixture import fra_pool
from tests.unit.test_paste_commands import grades_csv

FRA = load_set_config("FRA")
DAY = dt.date(2026, 10, 3)


def _grades(seed: int = 1, source: str = "llu-marc") -> StoredPaste:
    request = PasteRequest("FRA", "grades", source, None, None, None, None, False)
    return plan_paste(request, grades_csv(seed=seed), FRA, DAY, frozenset(), (), decode_text).new


def test_an_export_resolves_against_the_set_s_cards() -> None:
    pool = resolve_export(FRA, Format.BO1_SEALED, fra_pool())
    assert pool.set_code == "FRA" and pool.nonbasic_count == 83 and pool.warnings == ()


def _one_printing_each(size: int = 83) -> list[str]:
    seen: set[str] = set()
    lines = []
    for card in load_packaged_card_table("FRA").cards:
        if card.is_basic or card.oracle_id in seen:
            continue
        seen.add(card.oracle_id)
        lines.append(f"1 {card.name} ({card.set_code.upper()}) {card.collector_number}")
    return lines[:size]


def test_the_pool_hash_ignores_line_order_and_follows_the_counts() -> None:
    lines = _one_printing_each()
    forward = resolve_export(FRA, Format.BO1_SEALED, "\n".join(lines))
    backward = resolve_export(FRA, Format.BO1_SEALED, "\n".join(reversed(lines)))
    assert pool_hash(forward) == pool_hash(backward)
    doubled = resolve_export(FRA, Format.BO1_SEALED, "\n".join([*lines, lines[0]]))
    assert pool_hash(doubled) != pool_hash(forward)


def test_two_printings_of_one_card_hash_the_same_in_either_order() -> None:
    first = "1 Emrakul, the Exigent Doom (FRA) 1"
    second = "1 Emrakul, the Exigent Doom (FRA) 403"
    forward = resolve_export(FRA, Format.BO1_SEALED, "\n".join([first, second]))
    backward = resolve_export(FRA, Format.BO1_SEALED, "\n".join([second, first]))
    assert pool_hash(forward) == pool_hash(backward)


def test_a_body_hash_is_stable_across_key_order() -> None:
    assert body_hash({"a": 1, "b": [2]}) == body_hash({"b": [2], "a": 1})
    assert body_hash({"a": 1}) != body_hash({"a": 2})


def test_the_inputs_key_follows_every_paste_detail_but_not_paste_order() -> None:
    pool = resolve_export(FRA, Format.BO1_SEALED, fra_pool())
    one, two = _grades(1), _grades(2, "llu-alex")
    base = inputs_key(pool, [one, two], DAY)
    assert inputs_key(pool, [two, one], DAY) == base
    assert inputs_key(pool, [one], DAY) != base
    for change in (
        {"text_sha256": "0" * 64},
        {"copied_on": DAY - dt.timedelta(days=1)},
        {"published_on": DAY},
        {"parser_version": 99},
    ):
        assert inputs_key(pool, [one, dataclasses.replace(two, **change)], DAY) != base


def test_the_inputs_key_follows_the_deployed_package(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = resolve_export(FRA, Format.BO1_SEALED, fra_pool())
    base = inputs_key(pool, [], DAY)
    monkeypatch.setattr(web_build, "package_digest", lambda: "another deploy")
    assert inputs_key(pool, [], DAY) != base


def test_the_inputs_key_changes_when_the_embargo_passes() -> None:
    pool = resolve_export(FRA, Format.BO1_SEALED, fra_pool())
    before = FRA.embargo_until - dt.timedelta(days=1)
    assert inputs_key(pool, [], before) == inputs_key(pool, [], before - dt.timedelta(days=1))
    assert inputs_key(pool, [], FRA.embargo_until) != inputs_key(pool, [], before)


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def test_the_package_digest_is_the_installed_package_s_tree_digest() -> None:
    assert package_digest() == tree_digest(resources.files("arena_wizard"))
    assert len(package_digest()) == 64


def test_bytecode_never_changes_the_tree_digest(tmp_path: Path) -> None:
    root = _tree(tmp_path / "pkg", {"a.py": b"x = 1", "sub/b.yaml": b"k: v"})
    before = tree_digest(root)
    _tree(root, {"__pycache__/a.cpython-313.pyc": b"\x00\x01", "sub/c.pyc": b"\x02"})
    assert tree_digest(root) == before


def test_one_changed_byte_anywhere_changes_the_tree_digest(tmp_path: Path) -> None:
    root = _tree(tmp_path / "pkg", {"a.py": b"x = 1", "sub/deep/b.yaml": b"k: v"})
    before = tree_digest(root)
    (root / "sub/deep/b.yaml").write_bytes(b"k: w")
    assert tree_digest(root) != before
    (root / "sub/deep/b.yaml").write_bytes(b"k: v")
    assert tree_digest(root) == before


def test_renaming_a_file_changes_the_tree_digest(tmp_path: Path) -> None:
    root = _tree(tmp_path / "pkg", {"a.py": b"x = 1"})
    before = tree_digest(root)
    (root / "a.py").rename(root / "b.py")
    assert tree_digest(root) != before


def test_moving_bytes_between_a_name_and_its_contents_changes_the_tree_digest(
    tmp_path: Path,
) -> None:
    one = _tree(tmp_path / "one", {"a": b"bc"})
    two = _tree(tmp_path / "two", {"ab": b"c"})
    assert tree_digest(one) != tree_digest(two)


def test_published_public_files_are_covered_only_after_the_embargo() -> None:
    sos = load_set_config("SOS")
    assert covered(sos, sos.embargo_until - dt.timedelta(days=1)) == frozenset()
    assert covered(sos, sos.embargo_until) == {EventType.SEALED, EventType.PREMIER_DRAFT}
    assert covered(FRA, FRA.embargo_until) == frozenset()


def test_a_web_build_names_stale_pastes_and_directs_to_the_pastes_page() -> None:
    pool = resolve_export(FRA, Format.BO1_SEALED, fra_pool())
    _, result, _ = run_build(
        pool, [_grades()], DAY, ["LSV from 2026-10-01 was stored by an old one"]
    )
    text = "\n".join(result.data_lines)
    assert "  Not used     LSV from 2026-10-01 was stored by an old one." in text
    assert "arena-wizard paste" not in text and "Pastes page" in text


def test_a_web_build_is_an_event_build_with_deck_payloads() -> None:
    pool = resolve_export(FRA, Format.BO1_SEALED, fra_pool())
    mode, result, version = run_build(pool, [_grades()], DAY)
    assert mode == "event" and version and result.refusal is None and result.decks
    payload = deck_payload(result.decks[0])
    assert payload["label"] == result.decks[0].label
    assert payload["colors"] == result.decks[0].colors
    assert (
        sum(s["count"] for s in payload["spells"]) + sum(land["count"] for land in payload["lands"])
        == 40
    )
    value = payload["values"][0]
    assert value["basis"] in ("grades", "rarity average of grades")
    assert {"q", "se", "layers", "grades", "source"} <= set(value)
    assert payload["arena_list"].count("\n") >= 10
    assert all(t.keys() == {"name", "contribution", "detail"} for t in payload["terms"])


def test_a_splashed_deck_names_its_splash_color() -> None:
    pool = resolve_export(FRA, Format.BO1_SEALED, fra_pool())
    _, result, _ = run_build(pool, [_grades()], DAY)
    deck = result.decks[0]
    assert deck_payload(dataclasses.replace(deck, splash=None))["splash"] is None
    assert deck_payload(dataclasses.replace(deck, splash=Color.RED))["splash"] == "R"


def _sos_draft_paste(day: dt.date) -> StoredPaste:
    """Made-up SOS Premier Draft card data, as if pasted on `day`."""
    spells = sorted(spell_rarities(load_packaged_card_table("SOS").cards))
    rows = tuple(
        CardDataRow(name, "", None, 400 + 7 * i, 0.50 + (i % 9) / 100, 300, 0.5)
        for i, name in enumerate(spells)
    )
    return StoredPaste(
        key=PasteKey("SOS", "card-data", EventType.PREMIER_DRAFT, "17lands-card-data", day),
        label="17Lands card data",
        url=None,
        copied_on=day,
        published_on=None,
        columns=("Name", "# GIH", "GIH WR", "# GNS", "GNS WR"),
        text_sha256="e" * 64,
        parser_version=PARSER_VERSION,
        card_rows=rows,
    )


def _sos_pool() -> Pool:
    cards = [c for c in load_packaged_card_table("SOS").cards if not c.is_basic]
    picks = random.Random(5).sample(cards, 83)
    text = "\n".join(f"1 {c.name} ({c.set_code.upper()}) {c.collector_number}" for c in picks)
    return resolve_export(load_set_config("SOS"), Format.BO1_SEALED, text)


def test_a_web_build_ignores_pastes_a_published_public_file_covers() -> None:
    sos = load_set_config("SOS")
    before = sos.embargo_until - dt.timedelta(days=1)
    paste = _sos_draft_paste(before)
    _, early, _ = run_build(_sos_pool(), [paste], before)
    assert any(line.startswith("  Draft data   used") for line in early.data_lines)
    _, late, _ = run_build(_sos_pool(), [paste], sos.embargo_until)
    text = "\n".join(late.data_lines)
    assert "  Draft data   missing" in text
    assert "the public file replaces it" in text
