"""The paste path imports no HTTP code, so a pasted link can never be fetched (decision 0007).

Checked in a fresh interpreter, because the test process has already imported httpx.
"""

from __future__ import annotations

import subprocess
import sys

PACKAGE = (
    "arena_wizard.pastes.parsers",
    "arena_wizard.pastes.check",
    "arena_wizard.pastes.names",
    "arena_wizard.pastes.sources",
    "arena_wizard.pastes.store",
)


def _network_modules_after_importing(modules: tuple[str, ...]) -> str:
    probe = (
        "import sys\n"
        f"for name in {modules!r}:\n"
        "    __import__(name)\n"
        "bad = sorted(m for m in sys.modules if m == 'httpx' or m.startswith('httpx.')\n"
        "             or m.startswith('arena_wizard.sources'))\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_the_pastes_package_loads_no_http_client_or_source_adapter() -> None:
    assert _network_modules_after_importing(PACKAGE) == ""


def test_the_paste_command_loads_no_http_client_or_source_adapter() -> None:
    assert _network_modules_after_importing(("arena_wizard.paste_commands",)) == ""
