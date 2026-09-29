"""The scoring configuration: every weight, target, and prior the engine uses.

Weights live in `config/scoring/`, never in code, so a tuning change is a reviewed diff of
one YAML file with its measured eval delta beside it. A set can override the default with
`{SET}.{format}.yaml`.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml

from arena_wizard.domain.sets import ConfigError, Format


@dataclass(frozen=True, slots=True)
class Weights:
    """How much each score term counts. See `docs/plan.md` section 7 for the objective."""

    card_quality: float
    iwd: float
    pair_strength: float
    bomb: float
    creature_balance: float
    removal: float
    two_drop: float
    three_drop: float
    top_end: float
    consistency: float
    splash_card: float


@dataclass(frozen=True, slots=True)
class Targets:
    """Deck-shape targets; counts beyond a cap earn nothing more."""

    creatures_low: int
    creatures_high: int
    removal_cap: int
    two_drop_cap: int
    three_drop_cap: int
    max_five_plus: int
    splash_max_cards: int
    splash_min_sources: int


@dataclass(frozen=True, slots=True)
class Shrinkage:
    """Pseudo-games of prior added to each rate before it is used."""

    prior_games: float
    iwd_prior_games: float
    pair_prior_games: float


@dataclass(frozen=True, slots=True)
class BombRules:
    """When a card counts as an automatic bomb."""

    min_games: int
    min_cards: int
    threshold: float


@dataclass(frozen=True, slots=True)
class Castability:
    """The consistency term: castability shortfall against a baseline source count."""

    baseline_sources: int
    deck_size: int
    scale: float


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """A complete, validated scoring configuration and the hash of the file it came from."""

    version: str
    weights: Weights
    targets: Targets
    shrinkage: Shrinkage
    bombs: BombRules
    castability: Castability
    sha256: str


def _section[T](cls: type[T], raw: Any, name: str) -> T:
    """Build one config section, naming the section and field on any problem."""
    if not isinstance(raw, Mapping):
        raise ConfigError(f"scoring config section '{name}' must be a mapping")
    fields = {f.name: f for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    unknown = sorted(set(raw) - set(fields))
    if unknown:
        raise ConfigError(f"scoring config section '{name}' has unknown fields {unknown}")
    values: dict[str, float | int] = {}
    for field_name, field in fields.items():
        if field_name not in raw:
            raise ConfigError(f"scoring config is missing '{name}.{field_name}'")
        value = raw[field_name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"scoring config '{name}.{field_name}' must be a number")
        values[field_name] = int(value) if field.type == "int" else float(value)
    return cls(**values)


def parse_scoring_config(raw: Any, sha256: str = "") -> ScoringConfig:
    """Validate parsed YAML into a ScoringConfig.

    Args:
        raw: The parsed YAML document.
        sha256: The hash of the file it came from, recorded for provenance.

    Returns:
        The configuration.

    Raises:
        ConfigError: A section or field is missing, unknown, or not a number.
    """
    if not isinstance(raw, Mapping) or not isinstance(raw.get("version"), str):
        raise ConfigError("scoring config needs a string 'version'")
    return ScoringConfig(
        version=raw["version"],
        weights=_section(Weights, raw.get("weights"), "weights"),
        targets=_section(Targets, raw.get("targets"), "targets"),
        shrinkage=_section(Shrinkage, raw.get("shrinkage"), "shrinkage"),
        bombs=_section(BombRules, raw.get("bombs"), "bombs"),
        castability=_section(Castability, raw.get("castability"), "castability"),
        sha256=sha256,
    )


def load_scoring_config(fmt: Format, set_code: str | None = None) -> ScoringConfig:
    """Load the set's override if one exists, otherwise the format's default.

    Args:
        fmt: The format being scored.
        set_code: The set, for a set-specific override.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: No configuration exists for the format, or it is invalid.
    """
    folder = resources.files("arena_wizard").joinpath("config", "scoring")
    candidates = [f"{set_code.upper()}.{fmt.value}.yaml"] if set_code else []
    candidates.append(f"default.{fmt.value}.yaml")
    for name in candidates:
        path = folder.joinpath(name)
        if path.is_file():
            data = path.read_bytes()
            return parse_scoring_config(
                yaml.safe_load(data.decode("utf-8")), hashlib.sha256(data).hexdigest()
            )
    raise ConfigError(f"no scoring configuration for format '{fmt.value}'")
