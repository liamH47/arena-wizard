from __future__ import annotations

import copy
from typing import Any

import pytest

from arena_wizard.eval.gate import GateFailure, basis_points, gate


def _metrics(**changes: Any) -> dict[str, Any]:
    """Metrics that pass every absolute check, with `changes` applied."""
    metrics: dict[str, Any] = {
        "legality": {"value": 1.0},
        "pools_without_deck": 0,
        "deck_score": {"auc_margin_over_raw_gih": {"value": 0.02}},
        "pair_agreement_at_1": {"value": 0.5},
        "naive_raw_gih_at_1": {"value": 0.5},
        "engine_splash_share": {"value": 0.1},
        "player_splash_share": {"value": 0.2},
        "bombs_per_pool": 1.0,
    }
    metrics.update(changes)
    return metrics


PINS = {
    "sha256": "a",
    "sample_sha256": "b",
    "switch_sha256": "c",
    "presplit_sha256": "d",
    "split_day": "2026-05-01",
}


def _section(
    metrics: dict[str, Any] | None = None, picks: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "provenance": dict(PINS),
        "metrics": _metrics() if metrics is None else metrics,
        "pool_picks": picks or {},
    }


def _report(digest: str = "base-digest", **sections: dict[str, Any]) -> dict[str, Any]:
    return {"decision_digest": digest, "sets": sections or {"SOS": _section()}}


def _checks(failures: tuple[GateFailure, ...]) -> list[tuple[str, str]]:
    return [(f.set_code, f.check) for f in failures]


def test_basis_points_round_to_whole_units() -> None:
    assert basis_points(0.5512) == 5512
    assert basis_points(0.47) - basis_points(0.5) == -300


def test_a_healthy_report_without_a_base_passes() -> None:
    assert gate(_report(), None) == ()


def test_an_illegal_deck_or_a_pool_without_one_fails() -> None:
    head = _report(SOS=_section(_metrics(legality={"value": 0.9999}, pools_without_deck=1)))
    assert _checks(gate(head, None)) == [("SOS", "legality"), ("SOS", "pools_without_deck")]


def test_missing_absolute_metrics_fail_rather_than_pass() -> None:
    head = _report(SOS=_section({}))
    assert _checks(gate(head, None)) == [
        ("SOS", "legality"),
        ("SOS", "pools_without_deck"),
        ("SOS", "deck_score"),
        ("SOS", "raw_gih"),
        ("SOS", "splash"),
        ("SOS", "bombs"),
    ]


def test_a_value_that_is_not_a_number_counts_as_missing() -> None:
    head = _report(SOS=_section(_metrics(legality={"value": "1.0"}, bombs_per_pool=None)))
    assert _checks(gate(head, None)) == [("SOS", "legality"), ("SOS", "bombs")]


@pytest.mark.parametrize(("margin", "passes"), [(0.0001, True), (0.0, False), (-0.01, False)])
def test_the_deck_score_margin_must_be_above_zero(margin: float, passes: bool) -> None:
    head = _report(
        SOS=_section(_metrics(deck_score={"auc_margin_over_raw_gih": {"value": margin}}))
    )
    assert (gate(head, None) == ()) is passes


@pytest.mark.parametrize(("engine", "passes"), [(0.47, True), (0.4699, False)])
def test_agreement_may_trail_raw_win_rates_by_exactly_300_bp(engine: float, passes: bool) -> None:
    head = _report(SOS=_section(_metrics(pair_agreement_at_1={"value": engine})))
    failures = gate(head, None)
    assert (failures == ()) is passes
    if not passes:
        assert failures[0].message == "agreement is 301 bp below raw win rates"


def test_agreement_without_its_raw_baseline_fails() -> None:
    head = _report(SOS=_section(_metrics(naive_raw_gih_at_1={"value": None})))
    assert _checks(gate(head, None)) == [("SOS", "raw_gih")]


@pytest.mark.parametrize(("engine", "passes"), [(0.3, True), (0.3001, False), (0.0, True)])
def test_the_engine_may_splash_at_most_1000_bp_more_than_players(
    engine: float, passes: bool
) -> None:
    head = _report(
        SOS=_section(
            _metrics(engine_splash_share={"value": engine}, player_splash_share={"value": 0.2})
        )
    )
    assert (gate(head, None) == ()) is passes


def test_missing_splash_shares_fail() -> None:
    head = _report(SOS=_section(_metrics(player_splash_share=None)))
    assert _checks(gate(head, None)) == [("SOS", "splash")]


@pytest.mark.parametrize(
    ("bombs", "passes"), [(0.5, True), (1.5, True), (0.49, False), (1.51, False)]
)
def test_bombs_per_pool_are_bounded_inclusively(bombs: float, passes: bool) -> None:
    assert (gate(_report(SOS=_section(_metrics(bombs_per_pool=bombs))), None) == ()) is passes


def test_an_unchanged_report_passes_its_own_ratchet() -> None:
    report = _report(SOS=_section(picks={"d1": {"player": "WB", "engine": ["WB"]}}))
    assert gate(report, copy.deepcopy(report)) == ()


def test_changed_evaluation_data_fails_once_and_skips_the_other_ratchet_checks() -> None:
    base = _report(SOS=_section(_metrics(extra=1.0)))
    head = _report(SOS=_section())
    head["sets"]["SOS"]["provenance"]["split_day"] = "2026-05-02"
    failures = gate(head, base)
    assert _checks(failures) == [("SOS", "data")]
    assert "split_day" in failures[0].message


def test_a_metric_the_base_had_may_not_disappear_or_lose_its_value() -> None:
    base = _report(SOS=_section(_metrics(lift={"value": 0.1}, other={"value": 0.2}, gone=None)))
    head = _report(SOS=_section(_metrics(lift={"value": None}, gone=None)))
    failures = gate(head, base)
    assert _checks(failures) == [("SOS", "lift"), ("SOS", "other")]
    assert [f.message for f in failures] == [
        "had a value and now has none",
        "missing from the new report",
    ]


def test_a_set_the_base_had_may_not_disappear() -> None:
    base = _report(SOS=_section(), HOB=_section())
    assert _checks(gate(_report(SOS=_section()), base)) == [("HOB", "set")]


def _picks(n: int, wrong: set[int], player: str = "WB") -> dict[str, Any]:
    """n pools; the top pick matches the player except in `wrong`, where it is second."""
    return {
        f"d{i:04}": {"player": player, "engine": ["UR", player] if i in wrong else [player, "BG"]}
        for i in range(n)
    }


def test_a_net_loss_of_299_bp_passes_and_300_bp_fails() -> None:
    base = _report(SOS=_section(picks=_picks(434, set())))
    head = _report(SOS=_section(picks=_picks(434, set(range(13)))))
    assert gate(head, base) == ()  # 13 of 434 pools is 299 bp

    base = _report(SOS=_section(picks=_picks(100, set())))
    head = _report(SOS=_section(picks=_picks(100, {0, 1, 2})))
    failures = gate(head, base)
    assert _checks(failures) == [("SOS", "pair_agreement_at_1")]
    assert failures[0].message == "3 pools worse, 0 better: a net loss of 300 bp"


def test_pools_that_improve_offset_pools_that_regress() -> None:
    base = _report(SOS=_section(picks=_picks(100, {50})))
    head = _report(SOS=_section(picks=_picks(100, {0, 1, 2})))
    assert gate(head, base) == ()  # 3 worse, 1 better: a net 200 bp


def test_agreement_at_three_is_ratcheted_separately() -> None:
    base = _report(SOS=_section(picks=_picks(100, set())))
    head_picks = _picks(100, set())
    for i in range(3):
        head_picks[f"d{i:04}"]["engine"] = ["UR", "BG", "GW"]
    failures = gate(_report(SOS=_section(picks=head_picks)), base)
    assert _checks(failures) == [("SOS", "pair_agreement_at_1"), ("SOS", "pair_agreement_at_3")]


def test_three_color_players_and_pools_missing_from_the_head_are_not_counted() -> None:
    base_picks = _picks(10, set())
    base_picks["gone"] = {"player": "WB", "engine": ["WB"]}
    base_picks.update({f"t{i}": {"player": "WUB", "engine": ["WU"]} for i in range(5)})
    head_picks = copy.deepcopy({k: v for k, v in base_picks.items() if k != "gone"})
    for i in range(5):
        head_picks[f"t{i}"]["engine"] = ["BG"]
    base = _report(SOS=_section(picks=base_picks))
    assert gate(_report(SOS=_section(picks=head_picks)), base) == ()


def test_a_base_section_without_provenance_or_picks_compares_only_what_it_has() -> None:
    base = {"decision_digest": "x", "sets": {"SOS": {"metrics": {}}}}
    head = _report(SOS={"metrics": _metrics()})
    assert gate(head, base) == ()


def test_an_accepted_failure_counts_only_while_the_base_digest_matches() -> None:
    head = _report(SOS=_section(_metrics(bombs_per_pool=2.0)))
    base = _report("digest-1", SOS=_section(_metrics(bombs_per_pool=2.0)))
    entry = {"set": "SOS", "check": "bombs", "decision": "docs/decisions/0009-x.md"}
    assert gate(head, base, [entry | {"base_digest": "digest-1"}]) == ()
    stale = [entry | {"base_digest": "digest-0"}]
    assert _checks(gate(head, base, stale)) == [("SOS", "bombs")]


def test_an_accepted_entry_without_a_decision_or_a_base_digest_does_not_count() -> None:
    head = _report(SOS=_section(_metrics(bombs_per_pool=2.0)))
    base = _report("digest-1", SOS=_section(_metrics(bombs_per_pool=2.0)))
    unsigned = {"set": "SOS", "check": "bombs", "decision": "", "base_digest": "digest-1"}
    assert _checks(gate(head, base, [unsigned])) == [("SOS", "bombs")]
    signed = unsigned | {"decision": "docs/decisions/0009-x.md"}
    assert _checks(gate(head, None, [signed])) == [("SOS", "bombs")]
    assert _checks(gate(head, {"sets": {}}, [signed])) == [("SOS", "bombs")]


def _versioned(digest: str, engine: str = "2", config: str = "c1") -> dict[str, Any]:
    return _report(digest) | {"engine_version": engine, "scoring_config": {"sha256": config}}


def test_decisions_may_not_change_without_an_engine_or_config_change() -> None:
    failures = gate(_versioned("new"), _versioned("old"))
    assert _checks(failures) == [("all", "decisions")]
    assert "without an engine or config change" in failures[0].message


@pytest.mark.parametrize(
    "head",
    [
        _versioned("new", engine="3"),
        _versioned("new", config="c2"),
        _versioned("old"),
    ],
)
def test_changed_decisions_pass_with_a_new_engine_or_config_or_when_unchanged(
    head: dict[str, Any],
) -> None:
    assert gate(head, _versioned("old")) == ()


def test_reports_that_do_not_record_engine_and_config_are_not_held_to_it() -> None:
    base = _versioned("old")
    del base["scoring_config"]
    assert gate(_versioned("new"), base) == ()
    assert gate(_report("new") | {"engine_version": "2"}, _versioned("old")) == ()


def test_a_decisions_failure_can_be_accepted_while_the_base_digest_matches() -> None:
    entry = {"set": "all", "check": "decisions", "decision": "docs/decisions/0009-x.md"}
    assert gate(_versioned("new"), _versioned("old"), [entry | {"base_digest": "old"}]) == ()
