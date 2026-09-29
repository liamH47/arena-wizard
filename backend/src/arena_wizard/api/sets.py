"""The sets the app knows, with their dates and the 17Lands embargo."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from arena_wizard.auth.routes import CurrentUser
from arena_wizard.domain.sets import load_set_config, packaged_set_codes

router = APIRouter(prefix="/api/sets")


@router.get("")
def list_sets(user: CurrentUser) -> list[dict[str, Any]]:
    """Every configured set, newest release first."""
    configs = [load_set_config(code) for code in packaged_set_codes()]
    return [
        {
            "code": c.code,
            "name": c.name,
            "arena_release_date": c.arena_release_date.isoformat(),
            "embargo_until": c.embargo_until.isoformat(),
            "formats": [f.value for f in c.formats],
            "usual_range": list(c.nonbasic_pool_range),
        }
        for c in sorted(configs, key=lambda c: (c.arena_release_date, c.code), reverse=True)
    ]
