"""Grade lists combined into one standardized score per card (decision 0007)."""

from __future__ import annotations

import statistics

import pytest

from arena_wizard.domain.cards import Rarity
from arena_wizard.engine.grades import GradeSource, grade_scores
from arena_wizard.pastes.parsers import LETTER_GRADES

C, U, R = Rarity.COMMON, Rarity.UNCOMMON, Rarity.RARE
RARITY = {"Ace": R, "Bee": U, "Cee": C, "Dee": C, "Eff": C}
LETTERS = {"Ace": "A+", "Bee": "B", "Cee": "C", "Dee": "C-", "Eff": "F"}


def _source(label: str, raw: dict[str, str], values: dict[str, float]) -> GradeSource:
    return GradeSource(label, values, raw)


def _letters(label: str = "LLU") -> GradeSource:
    return _source(label, LETTERS, {n: float(LETTER_GRADES.index(g)) for n, g in LETTERS.items()})


def test_nothing_pasted_gives_no_scores() -> None:
    assert grade_scores((), RARITY) is None


def test_an_a_plus_card_scores_above_an_f_card() -> None:
    scores = grade_scores((_letters(),), RARITY)
    assert scores is not None
    assert scores.z["Ace"] > scores.z["Bee"] > scores.z["Cee"] > scores.z["Eff"]
    assert scores.raw["Ace"] == (("LLU", "A+"),)
    assert scores.labels == ("LLU",)


def test_a_single_source_is_already_on_unit_spread() -> None:
    scores = grade_scores((_letters(),), RARITY)
    assert scores is not None
    assert statistics.fmean(scores.z.values()) == pytest.approx(0.0)
    assert statistics.pstdev(scores.z.values()) == pytest.approx(1.0)


def test_letters_ordinals_and_rescaled_numbers_give_identical_scores() -> None:
    ordinal = {n: float(LETTER_GRADES.index(g)) for n, g in LETTERS.items()}
    five = {n: v * 5 / 12 for n, v in ordinal.items()}
    ten = {n: v * 10 / 12 + 0 for n, v in ordinal.items()}
    results = [
        grade_scores((_source("x", LETTERS, values),), RARITY) for values in (ordinal, five, ten)
    ]
    first = results[0]
    assert first is not None
    for other in results[1:]:
        assert other is not None
        assert other.z == pytest.approx(first.z)


def test_names_outside_the_set_are_ignored_before_scoring() -> None:
    values = {n: float(LETTER_GRADES.index(g)) for n, g in LETTERS.items()}
    raw = dict(LETTERS)
    with_typo = _source("x", {**raw, "Typo Card": "A+"}, {**values, "Typo Card": 12.0})
    plain, typo = (
        grade_scores((_source("x", raw, values),), RARITY),
        grade_scores((with_typo,), RARITY),
    )
    assert plain is not None and typo is not None
    assert typo.z == pytest.approx(plain.z)
    assert "Typo Card" not in typo.z


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"Ace": 3.0}, "at least two"),
        ({"Ace": 3.0, "Bee": 3.0, "Cee": 3.0}, "the same"),
    ],
)
def test_a_source_that_cannot_rank_cards_is_an_error(
    values: dict[str, float], message: str
) -> None:
    raw = {n: str(v) for n, v in values.items()}
    with pytest.raises(ValueError, match=message):
        grade_scores((_source("x", raw, values),), RARITY)


def test_two_sources_are_averaged_and_re_standardized_to_unit_spread() -> None:
    second_values = {"Ace": 4.0, "Bee": 1.0, "Cee": 3.5, "Dee": 2.0}
    second = _source("LSV", {n: str(v) for n, v in second_values.items()}, second_values)
    scores = grade_scores((_letters(), second), RARITY)
    assert scores is not None
    assert statistics.fmean(scores.z.values()) == pytest.approx(0.0)
    assert statistics.pstdev(scores.z.values()) == pytest.approx(1.0)
    assert scores.raw["Ace"] == (("LLU", "A+"), ("LSV", "4.0"))
    assert scores.raw["Eff"] == (("LLU", "F"),)
    assert scores.labels == ("LLU", "LSV")


def test_each_rarity_records_the_mean_score_of_its_graded_cards() -> None:
    scores = grade_scores((_letters(),), RARITY)
    assert scores is not None
    commons = [scores.z[n] for n in ("Cee", "Dee", "Eff")]
    assert scores.rarity_z[C] == pytest.approx(statistics.fmean(commons))
    assert scores.rarity_z[R] == pytest.approx(scores.z["Ace"])
    assert Rarity.MYTHIC not in scores.rarity_z
