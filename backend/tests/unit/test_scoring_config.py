from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from arena_wizard.domain.scoring import load_scoring_config, parse_scoring_config
from arena_wizard.domain.sets import ConfigError, Format


def _raw() -> dict[str, Any]:
    from importlib import resources

    path = resources.files("arena_wizard").joinpath("config", "scoring", "default.bo1_sealed.yaml")
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document


def test_the_packaged_default_loads_with_its_file_hash() -> None:
    config = load_scoring_config(Format.BO1_SEALED, "SOS")
    assert config.version
    assert len(config.sha256) == 64
    assert config.targets.creatures_low == 13
    assert isinstance(config.targets.creatures_low, int)
    assert isinstance(config.weights.bomb, float)


def test_a_format_without_any_config_is_an_error() -> None:
    with pytest.raises(ConfigError, match="trad_sealed"):
        load_scoring_config(Format.TRAD_SEALED)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.pop("version"), "version"),
        (lambda r: r.pop("weights"), "section 'weights'"),
        (lambda r: r["weights"].pop("bomb"), "weights.bomb"),
        (lambda r: r["targets"].update(extra=1), "unknown fields"),
        (lambda r: r["shrinkage"].update(prior_games="many"), "shrinkage.prior_games"),
        (lambda r: r["bombs"].update(min_cards=True), "bombs.min_cards"),
    ],
)
def test_each_problem_names_its_section_and_field(mutate: Any, message: str) -> None:
    raw = copy.deepcopy(_raw())
    mutate(raw)
    with pytest.raises(ConfigError, match=message):
        parse_scoring_config(raw)


def test_a_document_that_is_not_a_mapping_is_rejected() -> None:
    with pytest.raises(ConfigError, match="version"):
        parse_scoring_config(["not", "a", "mapping"])


def test_the_event_section_loads_with_its_types() -> None:
    event = load_scoring_config(Format.BO1_SEALED).event
    assert event.sigma > 0 and event.proxy_sigma > 0
    assert isinstance(event.max_decks, int) and event.max_decks >= 1
    assert 0 < event.min_grade_coverage <= 1


@pytest.mark.parametrize(
    ("field", "bad", "message"),
    [
        ("sigma", 0, "event.sigma"),
        ("proxy_sigma", -1.0, "event.proxy_sigma"),
        ("min_grade_coverage", 0, "coverage"),
        ("min_grade_coverage", 1.5, "coverage"),
        ("max_decks", 0, "max_decks"),
        ("play_floor", 0.5, "play_floor"),
        ("play_ceiling", -0.5, "play_floor"),
    ],
)
def test_event_error_terms_and_limits_must_be_usable(field: str, bad: float, message: str) -> None:
    raw = copy.deepcopy(_raw())
    raw["event"][field] = bad
    with pytest.raises(ConfigError, match=message):
        parse_scoring_config(raw)


def test_a_missing_event_section_is_an_error() -> None:
    raw = copy.deepcopy(_raw())
    raw.pop("event")
    with pytest.raises(ConfigError, match="section 'event'"):
        parse_scoring_config(raw)
