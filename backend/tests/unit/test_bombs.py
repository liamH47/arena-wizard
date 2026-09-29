from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from arena_wizard.domain.cards import Rarity
from arena_wizard.domain.scoring import BombRules
from arena_wizard.domain.sets import ConfigError
from arena_wizard.domain.stats import CardCounts
from arena_wizard.engine.bombs import CuratedBomb, bomb_scores, bombs, load_curated, parse_curated
from arena_wizard.engine.values import FormatMeans

C, RARE = Rarity.COMMON, Rarity.RARE
MEANS = FormatMeans(gih=0.5, gih_by_rarity={C: 0.5}, gns_by_rarity={C: 0.5}, iwd=0.0, pair=None)
RULES = BombRules(min_games=100, min_cards=3, threshold=1.0)


def _counts(gih_wins: int, gns_wins: int) -> CardCounts:
    return CardCounts(games_gih=100, wins_gih=gih_wins, games_gns=100, wins_gns=gns_wins)


THREE = {"Strong": _counts(60, 40), "Middle": _counts(50, 50), "Weak": _counts(40, 60)}
RARITIES = {"Strong": C, "Middle": C, "Weak": RARE, "Thin": C}


def test_the_bomb_score_is_the_restandardized_sum_of_two_z_scores() -> None:
    # With no prior, GIH is 0.6, 0.5, 0.4 and IWD 0.2, 0, -0.2: both z-scores are
    # +-sqrt(1.5) and 0, their sum is +-2 sqrt(1.5), and re-standardizing gives sqrt(1.5).
    scores = bomb_scores(THREE, RARITIES, MEANS, RULES, 0, 0)
    assert scores == pytest.approx(
        {"Strong": math.sqrt(1.5), "Middle": 0.0, "Weak": -math.sqrt(1.5)}
    )


def test_cards_under_the_game_floor_or_without_a_rarity_are_not_scored() -> None:
    counts = {
        **THREE,
        "Thin": CardCounts(games_gih=99, wins_gih=99),
        "Unknown": _counts(90, 10),
    }
    assert bomb_scores(counts, RARITIES, MEANS, RULES, 0, 0).keys() == THREE.keys()


def test_too_few_qualifying_cards_give_no_scores() -> None:
    two = {name: THREE[name] for name in ("Strong", "Weak")}
    assert bomb_scores(two, RARITIES, MEANS, RULES, 0, 0) == {}


def test_no_means_give_no_scores() -> None:
    assert bomb_scores(THREE, RARITIES, None, RULES, 0, 0) == {}


def test_identical_cards_all_score_zero() -> None:
    same = {name: _counts(50, 50) for name in THREE}
    assert bomb_scores(same, RARITIES, MEANS, RULES, 100, 100) == dict.fromkeys(THREE, 0.0)


def test_shrinkage_pulls_scores_but_keeps_the_order() -> None:
    scores = bomb_scores(THREE, RARITIES, MEANS, RULES, 180, 350)
    assert scores["Strong"] > scores["Middle"] > scores["Weak"]


def test_the_curated_list_parses_with_an_optional_note() -> None:
    raw = {
        "curated": [
            {"name": "A", "action": "add", "source": "LSV review", "note": "wins alone"},
            {"name": "B", "action": "remove", "source": "Lords of Limited"},
            {"name": "C", "action": "annotate", "source": "Limited Resources", "note": 3},
        ]
    }
    assert parse_curated(raw) == (
        CuratedBomb("A", "add", "wins alone", "LSV review"),
        CuratedBomb("B", "remove", "", "Lords of Limited"),
        CuratedBomb("C", "annotate", "3", "Limited Resources"),
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (None, "needs a 'curated' list"),
        ({"curated": {"name": "A"}}, "needs a 'curated' list"),
        ({"curated": ["A"]}, "needs a name and a cited source"),
        ({"curated": [{"name": "A", "action": "add"}]}, "needs a name and a cited source"),
        ({"curated": [{"action": "add", "source": "x"}]}, "needs a name and a cited source"),
        ({"curated": [{"name": "A", "source": "x"}]}, "must be add, remove, or annotate"),
        (
            {"curated": [{"name": "A", "action": "promote", "source": "x"}]},
            "must be add, remove, or annotate",
        ),
    ],
)
def test_a_malformed_curated_list_is_refused(raw: Any, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_curated(raw)


def test_a_set_without_a_curated_file_has_an_empty_list() -> None:
    assert load_curated("ZZZ") == ()


def test_a_curated_list_is_read_from_its_directory_by_upper_case_set_code(tmp_path: Path) -> None:
    (tmp_path / "SOS.yaml").write_text(
        "curated:\n  - name: Made-up Dragon\n    action: add\n    note: wins alone\n"
        "    source: a set review\n",
        encoding="utf-8",
    )
    assert load_curated("sos", tmp_path) == (
        CuratedBomb("Made-up Dragon", "add", "wins alone", "a set review"),
    )
    assert load_curated("HOB", tmp_path) == ()


def test_automatic_bombs_are_the_scores_at_or_above_the_threshold() -> None:
    assert bombs({"A": 2.0, "B": 1.99, "C": 3.1}, 2.0, ()) == {"A": 2.0, "C": 3.1}


def test_curated_entries_add_remove_and_annotate() -> None:
    scores = {"Auto": 2.5, "Removed": 3.0, "Weak": 0.4, "Strong": 2.8, "Noted": 2.2}
    curated = (
        CuratedBomb("Removed", "remove", "", "x"),
        CuratedBomb("Weak", "add", "", "x"),
        CuratedBomb("Strong", "add", "", "x"),
        CuratedBomb("Unscored", "add", "", "x"),
        CuratedBomb("Noted", "annotate", "", "x"),
        CuratedBomb("Never", "remove", "", "x"),
    )
    assert bombs(scores, 2.0, curated) == {
        "Auto": 2.5,
        "Weak": 2.0,
        "Strong": 2.8,
        "Unscored": 2.0,
        "Noted": 2.2,
    }
