"""The sources a paste may name (decision 0007, from the steward's research of 2026-09-29).

A paste names a source id from this registry rather than free text, so one source always
maps to one key: two spellings of a reviewer cannot become two sources and double that
reviewer's weight, and a label can never become a path. Labels name reviewer and outlet,
with no implied endorsement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CARD_DATA = "card-data"
GRADES = "grades"
DATASETS = (CARD_DATA, GRADES)


@dataclass(frozen=True, slots=True)
class PasteSource:
    """A source a person may paste from, and the dataset it provides."""

    id: str
    label: str
    dataset: str


REGISTRY: dict[str, PasteSource] = {
    s.id: s
    for s in (
        PasteSource("17lands-card-data", "17Lands card data", CARD_DATA),
        PasteSource("tcgplayer-lsv", "LSV, TCGplayer set review", GRADES),
        PasteSource("tcgplayer-juza", "Martin Jůza, TCGplayer set review", GRADES),
        PasteSource("llu-marc", "Marc Anderson, Limited Level-Ups", GRADES),
        PasteSource("llu-alex", "Alex Nikolic, Limited Level-Ups", GRADES),
        PasteSource("mtgazone", "MTG Arena Zone set review", GRADES),
    )
}

REFUSED = {
    "draftsim": "Draftsim's terms forbid use that competes with its own tools (decision 0007)",
    "chunk-science": "chunk.science republishes other reviewers; paste the original reviewer",
    "limitedgrades": "limitedgrades.com grades are built from 17Lands win rates; paste the "
    "17Lands card data itself",
}

_OWN = re.compile(r"own-([a-z0-9]+(?:-[a-z0-9]+)*)")


class UnknownSource(ValueError):
    """The source id is not in the registry, or it is refused."""


def source_for(source_id: str) -> PasteSource:
    """Look up a source id; `own-<name>` is the group's own grade list.

    Raises:
        UnknownSource: A refused source, or an id that is neither registered nor `own-...`.
    """
    if source_id in REFUSED:
        raise UnknownSource(f"{source_id} is not accepted: {REFUSED[source_id]}")
    if source_id in REGISTRY:
        return REGISTRY[source_id]
    own = _OWN.fullmatch(source_id)
    if own and len(source_id) <= 44:
        return PasteSource(source_id, f"the group's own grades ({own.group(1)})", GRADES)
    known = ", ".join(sorted(REGISTRY))
    raise UnknownSource(
        f"unknown source {source_id!r}. Use one of {known}, or own-<name> for the group's "
        "own grades (lower-case letters, digits, and hyphens)"
    )
