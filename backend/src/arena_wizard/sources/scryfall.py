"""Scryfall: the card database behind the committed card tables.

Production never calls Scryfall. A developer runs `arena-wizard sync-cards`, which uses
the paginated search API (a handful of requests per set, which Scryfall's bulk-data page
says is fine for data refreshed around set releases) and commits the resulting tables.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena_wizard.domain.cards import Card, CardFace, Color, Rarity, sort_colors
from arena_wizard.sources.http import SourceContext, SourceError, get

SEARCH_URL = "https://api.scryfall.com/cards/search"
NAMED_URL = "https://api.scryfall.com/cards/named"


def fetch_search(ctx: SourceContext, query: str) -> list[dict[str, Any]]:
    """Return every Arena printing matching a Scryfall query, following pagination.

    Args:
        ctx: The injected context.
        query: A Scryfall query such as "set:sos"; " game:arena" is appended.

    Returns:
        The raw card objects in Scryfall's order. Empty when nothing matches, which
        Scryfall reports as a 404.

    Raises:
        SourceError: Any other non-200 status, or a response without the expected shape.
    """
    params = {"q": f"{query} game:arena", "unique": "prints", "order": "set"}
    response = get(ctx, SEARCH_URL, key="scryfall_search", params=params)
    if response.status_code == 404:
        return []
    cards: list[dict[str, Any]] = []
    while True:
        if response.status_code != 200:
            raise SourceError(f"Scryfall search {query!r} returned {response.status_code}")
        body = response.json()
        try:
            cards.extend(body["data"])
            if not body["has_more"]:
                return cards
            next_page = body["next_page"]
        except KeyError as exc:
            raise SourceError(f"Scryfall search {query!r} response lacks {exc}") from exc
        response = get(ctx, next_page, key="scryfall_search")


def fetch_oracle_id(ctx: SourceContext, name: str) -> str | None:
    """Look up a card by exact name (full or face name) and return its oracle id.

    Args:
        ctx: The injected context.
        name: The name as 17Lands writes it, usually a front-face name.

    Returns:
        The oracle id, or None when Scryfall knows no card by that name.

    Raises:
        SourceError: Any status other than 200 or 404.
    """
    response = get(ctx, NAMED_URL, key="scryfall", params={"exact": name})
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise SourceError(f"Scryfall named lookup {name!r} returned {response.status_code}")
    oracle_id = response.json().get("oracle_id")
    if not isinstance(oracle_id, str):
        raise SourceError(f"Scryfall named lookup {name!r} has no oracle_id")
    return oracle_id


def _colors(values: list[str]) -> tuple[Color, ...]:
    """Convert Scryfall color letters to WUBRG-ordered Colors."""
    return sort_colors([Color(value) for value in values])


def _face(raw: Mapping[str, Any]) -> CardFace:
    """Convert one Scryfall card face."""
    return CardFace(
        name=raw["name"],
        mana_cost=raw.get("mana_cost", ""),
        type_line=raw.get("type_line", ""),
        oracle_text=raw.get("oracle_text", ""),
        power=raw.get("power"),
        toughness=raw.get("toughness"),
    )


def compute_card(raw: Mapping[str, Any]) -> Card:
    """Trim a raw Scryfall card object to a Card. Pure.

    Multi-face cards (adventure, prepare, transform) keep their faces; top-level fields
    Scryfall omits for some layouts are rebuilt from the faces.

    Args:
        raw: A Scryfall card object.

    Returns:
        The trimmed card.
    """
    faces = tuple(_face(face) for face in raw.get("card_faces", []))
    raw_faces: list[Mapping[str, Any]] = raw.get("card_faces", [])
    front: Mapping[str, Any] = raw_faces[0] if raw_faces else raw
    colors = raw.get("colors")
    if colors is None:
        colors = sorted({c for face in raw_faces for c in face.get("colors", [])})
    image_uris: Mapping[str, str] = raw.get("image_uris") or front.get("image_uris") or {}
    arena_id = raw.get("arena_id")
    return Card(
        scryfall_id=raw["id"],
        oracle_id=raw["oracle_id"],
        arena_id=int(arena_id) if arena_id is not None else None,
        name=raw["name"],
        front_name=front["name"],
        layout=raw["layout"],
        set_code=raw["set"].upper(),
        collector_number=raw["collector_number"],
        rarity=Rarity(raw["rarity"]),
        mana_cost=raw.get("mana_cost") or " // ".join(face.mana_cost for face in faces),
        mana_value=float(raw.get("cmc", 0.0)),
        type_line=raw.get("type_line") or " // ".join(face.type_line for face in faces),
        oracle_text=raw.get("oracle_text") or "\n//\n".join(face.oracle_text for face in faces),
        power=raw.get("power", front.get("power")),
        toughness=raw.get("toughness", front.get("toughness")),
        colors=_colors(colors),
        color_identity=_colors(raw.get("color_identity", [])),
        produced_mana=tuple(raw.get("produced_mana", [])),
        faces=faces,
        image_uri=image_uris.get("normal"),
        artist=raw.get("artist") or front.get("artist"),
        released_at=raw["released_at"],
    )
