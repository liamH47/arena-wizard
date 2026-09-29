"""The merge gate: absolute checks on the new report, then a ratchet against the base.

Decided by the milestone-1 panel (decision 0006): outcome measures gate, imitation only
ratchets. The base is always the target branch's committed report, never a file the pull
request can rewrite, and comparisons are in whole basis points.

Absolute, on every set:
- every pool gets a deck, and every deck is legal;
- the engine's score of players' decks predicts wins better than raw win rates in hand
  (AUC margin above zero);
- agreement with players is no more than 300 bp below the raw-win-rate baseline;
- the engine splashes no more than 1,000 bp more often than players (the measured
  miscalibration was over-splashing; a splash costs about 4 win-rate points, so splashing
  less than players is allowed);
- automatic bombs average between 0.5 and 1.5 per pool.

Against the base, per set: the evaluation data is unchanged, no metric the base had is
missing, and agreement at 1 and at 3 does not lose a net 300 bp of pools (paired flips).

An exception needs an entry in `eval/accepted.json` naming the set, the check, its
decision record, and the base report's decision digest, so it expires as soon as the
base report changes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

RATCHET_BP = 300
SPLASH_TOLERANCE_BP = 1_000
BOMBS_PER_POOL = (0.5, 1.5)
DATA_PINS = ("sha256", "sample_sha256", "switch_sha256", "presplit_sha256", "split_day")


@dataclass(frozen=True, slots=True)
class GateFailure:
    """One reason the report may not merge."""

    set_code: str
    check: str
    message: str


def basis_points(value: float) -> int:
    """A rate as whole basis points: 0.5512 is 5512."""
    return round(value * 10_000)


def _value(metrics: Mapping[str, Any], key: str) -> float | None:
    metric = metrics.get(key)
    if isinstance(metric, Mapping):
        value = metric.get("value")
        return value if isinstance(value, int | float) else None
    return metric if isinstance(metric, int | float) else None


def _absolute(code: str, metrics: Mapping[str, Any]) -> list[GateFailure]:
    """Checks that hold for any report, with or without a base."""
    failures: list[GateFailure] = []
    legality = _value(metrics, "legality")
    if legality is None or basis_points(legality) != 10_000:
        failures.append(GateFailure(code, "legality", f"legality is {legality}, not 1.0"))
    if metrics.get("pools_without_deck") != 0:
        failures.append(
            GateFailure(code, "pools_without_deck", f"{metrics.get('pools_without_deck')} pools")
        )
    margin = _value(metrics.get("deck_score", {}), "auc_margin_over_raw_gih")
    if margin is None or margin <= 0:
        failures.append(
            GateFailure(
                code,
                "deck_score",
                f"the engine's AUC margin over raw win rates is {margin}, not above zero",
            )
        )
    engine, raw = _value(metrics, "pair_agreement_at_1"), _value(metrics, "naive_raw_gih_at_1")
    if engine is None or raw is None:
        failures.append(GateFailure(code, "raw_gih", "agreement or the raw baseline is missing"))
    elif basis_points(engine) - basis_points(raw) < -RATCHET_BP:
        failures.append(
            GateFailure(
                code,
                "raw_gih",
                f"agreement is {basis_points(raw) - basis_points(engine)} bp below raw win rates",
            )
        )
    engine_splash = _value(metrics, "engine_splash_share")
    player_splash = _value(metrics, "player_splash_share")
    if engine_splash is None or player_splash is None:
        failures.append(GateFailure(code, "splash", "splash shares are missing"))
    elif basis_points(engine_splash) - basis_points(player_splash) > SPLASH_TOLERANCE_BP:
        failures.append(
            GateFailure(
                code,
                "splash",
                f"engine splashes {engine_splash:.1%}, players {player_splash:.1%}",
            )
        )
    bombs = _value(metrics, "bombs_per_pool")
    low, high = BOMBS_PER_POOL
    if bombs is None or not low <= bombs <= high:
        failures.append(
            GateFailure(code, "bombs", f"{bombs} automatic bombs per pool, not {low} to {high}")
        )
    return failures


def _hits(picks: Mapping[str, Any], draft_id: str, depth: int) -> bool:
    pick = picks[draft_id]
    return bool(pick["player"] in pick["engine"][:depth])


def _ratchet(code: str, head: Mapping[str, Any], base: Mapping[str, Any]) -> list[GateFailure]:
    """Checks against the base report's section for the same set."""
    failures: list[GateFailure] = []
    head_pins, base_pins = head.get("provenance", {}), base.get("provenance", {})
    changed = [pin for pin in DATA_PINS if head_pins.get(pin) != base_pins.get(pin)]
    if changed:
        failures.append(GateFailure(code, "data", f"evaluation data changed: {changed}"))
        return failures
    for key in base.get("metrics", {}):
        if key not in head.get("metrics", {}):
            failures.append(GateFailure(code, key, "missing from the new report"))
        elif _value(base["metrics"], key) is not None and _value(head["metrics"], key) is None:
            failures.append(GateFailure(code, key, "had a value and now has none"))
    head_picks, base_picks = head.get("pool_picks", {}), base.get("pool_picks", {})
    two_color = [d for d, p in base_picks.items() if len(p["player"]) == 2 and d in head_picks]
    for depth, name in ((1, "pair_agreement_at_1"), (3, "pair_agreement_at_3")):
        worse = sum(
            _hits(base_picks, d, depth) and not _hits(head_picks, d, depth) for d in two_color
        )
        better = sum(
            _hits(head_picks, d, depth) and not _hits(base_picks, d, depth) for d in two_color
        )
        loss = (worse - better) * 10_000 // max(len(two_color), 1)
        if loss >= RATCHET_BP:
            failures.append(
                GateFailure(
                    code, name, f"{worse} pools worse, {better} better: a net loss of {loss} bp"
                )
            )
    return failures


def gate(
    head: Mapping[str, Any],
    base: Mapping[str, Any] | None,
    accepted: Sequence[Mapping[str, str]] = (),
) -> tuple[GateFailure, ...]:
    """Every reason the head report may not merge. Pure.

    Args:
        head: The freshly generated report.
        base: The base branch's report, or None when the base predates the report.
        accepted: Exceptions as {"set", "check", "decision", "base_digest"}; an entry only
            counts while `base_digest` equals the base report's decision digest.

    Returns:
        The failures that no current exception covers; empty when the report may merge.
    """
    failures: list[GateFailure] = []
    for code, section in head["sets"].items():
        failures += _absolute(code, section["metrics"])
    if base is not None:
        for code, section in base["sets"].items():
            if code not in head["sets"]:
                failures.append(GateFailure(code, "set", "missing from the new report"))
            else:
                failures += _ratchet(code, head["sets"][code], section)
    digest = None if base is None else base.get("decision_digest")
    current = {
        (a.get("set"), a.get("check"))
        for a in accepted
        if digest is not None and a.get("base_digest") == digest and a.get("decision")
    }
    return tuple(f for f in failures if (f.set_code, f.check) not in current)
