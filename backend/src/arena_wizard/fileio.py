"""Atomic file writes shared by every writer in the package.

The data goes to a uniquely named temporary file beside the target, is flushed to disk,
then replaces the target in one step, so a crash or a concurrent run never leaves a
partial file and two runs never share a temporary name.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace `path` with `data` atomically, creating its directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Replace `path` with UTF-8 `text` atomically; the text's own line endings are kept."""
    atomic_write_bytes(path, text.encode("utf-8"))
