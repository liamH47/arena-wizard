"""The registry of sources a paste may name (decision 0007)."""

from __future__ import annotations

import pytest

from arena_wizard.pastes.sources import (
    CARD_DATA,
    GRADES,
    REFUSED,
    REGISTRY,
    UnknownSource,
    source_for,
)


def test_registered_ids_return_their_label_and_dataset() -> None:
    assert source_for("17lands-card-data").dataset == CARD_DATA
    lsv = source_for("tcgplayer-lsv")
    assert (lsv.label, lsv.dataset) == ("LSV, TCGplayer set review", GRADES)
    assert all(source_for(sid) is REGISTRY[sid] for sid in REGISTRY)


@pytest.mark.parametrize("source_id", ["own-liam", "own-friday-night-2"])
def test_the_groups_own_lists_are_grades_named_after_their_author(source_id: str) -> None:
    source = source_for(source_id)
    assert source.dataset == GRADES
    assert source.label == f"the group's own grades ({source_id.removeprefix('own-')})"


@pytest.mark.parametrize(
    "source_id",
    ["own-", "own-Liam", "own-../x", "own--x", "own-x-", "own-" + "a" * 41, "own-con sole"],
)
def test_own_ids_with_bad_characters_or_too_long_are_unknown(source_id: str) -> None:
    with pytest.raises(UnknownSource, match="unknown source"):
        source_for(source_id)


def test_the_longest_own_id_is_accepted() -> None:
    assert source_for("own-" + "a" * 40).dataset == GRADES


@pytest.mark.parametrize("source_id", sorted(REFUSED))
def test_refused_sources_say_why(source_id: str) -> None:
    with pytest.raises(UnknownSource, match=f"{source_id} is not accepted"):
        source_for(source_id)


def test_an_unknown_id_lists_the_registered_ones() -> None:
    with pytest.raises(UnknownSource, match="llu-marc") as error:
        source_for("LSV")
    assert "own-<name>" in str(error.value)
