"""Every committed bomb list is the group's own or cites a recorded permission (0007)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml

from arena_wizard.engine.bombs import load_curated

DECISIONS = Path(__file__).resolve().parents[3] / "docs" / "decisions"


def _packaged() -> list[str]:
    folder = resources.files("arena_wizard").joinpath("config", "bombs")
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".yaml"))


def test_every_committed_bomb_list_loads_and_its_permission_is_recorded() -> None:
    folder = resources.files("arena_wizard").joinpath("config", "bombs")
    for name in _packaged():
        load_curated(name.removesuffix(".yaml"))
        raw = yaml.safe_load(folder.joinpath(name).read_text(encoding="utf-8"))
        provenance = raw["provenance"]
        if provenance != "own":
            number = provenance.removeprefix("permission ")
            assert list(DECISIONS.glob(f"{number}-*.md")), f"{name}: no decision {number}"


def test_the_decisions_folder_is_where_this_test_looks() -> None:
    assert (DECISIONS / "0007-fra-event-mode.md").is_file()
