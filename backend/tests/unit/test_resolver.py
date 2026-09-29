from __future__ import annotations

from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.domain.pool import WarningKind
from arena_wizard.domain.sets import load_set_config
from arena_wizard.engine.export_parser import parse_export
from arena_wizard.engine.resolver import build_index, resolve_pool

SOS = load_packaged_card_table("SOS")
HOB = load_packaged_card_table("HOB")
HOME = build_index([SOS], "SOS")
OTHERS = build_index([HOB])


def _pool(text: str):  # type: ignore[no-untyped-def]
    return resolve_pool(parse_export(text), load_set_config("SOS"), HOME, OTHERS)


def _printing(set_code: str) -> tuple[str, str, str]:
    card = next(c for c in SOS.cards if c.set_code == set_code and not c.is_basic)
    return card.front_name, card.set_code, card.collector_number


def test_exact_printings_resolve_without_warnings_including_bonus_sheets() -> None:
    lines = [
        f"1 {n} ({s}) {c}" for n, s, c in (_printing("SOS"), _printing("SOA"), _printing("SPG"))
    ]
    pool = _pool("\n".join(lines))
    assert [w.kind for w in pool.warnings] == [WarningKind.POOL_SIZE]
    assert pool.nonbasic_count == 3


def test_copies_across_lines_and_printings_merge_into_one_entry() -> None:
    name, set_code, number = _printing("SOS")
    pool = _pool(f"1 {name} ({set_code}) {number}\n2 {name} (SOS) 9999\n")
    (entry,) = pool.entries
    assert entry.count == 3
    kinds = [w.kind for w in pool.warnings]
    assert WarningKind.ALTERNATE_PRINTING in kinds


def test_a_card_from_another_set_is_kept_and_flagged() -> None:
    card = next(c for c in HOB.cards if not c.is_basic)
    pool = _pool(f"1 {card.front_name} (HOB) {card.collector_number}\n")
    assert pool.entries[0].card == card
    assert pool.warnings[0].kind is WarningKind.WRONG_SET


def test_an_unknown_name_is_left_out_with_suggestions() -> None:
    name, _, _ = _printing("SOS")
    typo = name[:-1] + ("x" if name[-1] != "x" else "y")
    pool = _pool(f"1 {typo} (SOS) 99999\n")
    assert pool.entries == ()
    warning = pool.warnings[0]
    assert warning.kind is WarningKind.UNKNOWN_NAME
    assert name in warning.suggestions


def test_basics_are_kept_apart_from_the_pool() -> None:
    plains = next(c for c in SOS.cards if c.front_name == "Plains")
    name, s, n = _printing("SOS")
    pool = _pool(f"17 Plains (SOS) {plains.collector_number}\n1 {name} ({s}) {n}\n")
    assert [e.card.front_name for e in pool.basics] == ["Plains"]
    assert pool.nonbasic_count == 1


def test_a_pool_of_normal_size_has_no_size_warning() -> None:
    spells = [c for c in SOS.cards if c.set_code == "SOS" and not c.is_basic][:83]
    pool = _pool("\n".join(f"1 {c.front_name} (SOS) {c.collector_number}" for c in spells))
    assert all(w.kind is not WarningKind.POOL_SIZE for w in pool.warnings)


def test_parse_warnings_pass_through_to_the_pool() -> None:
    pool = _pool("this is not a card line\n")
    assert pool.warnings[0].kind is WarningKind.UNPARSED


def test_names_prefer_the_home_set_printing() -> None:
    both = build_index([HOB, SOS], "SOS")
    for name, card in both.by_name.items():
        if any(c.set_code == "SOS" and name in (c.front_name, c.name) for c in SOS.cards):
            assert card.set_code == "SOS" or not any(
                c.set_code == "SOS" and c.front_name == card.front_name for c in SOS.cards
            )
