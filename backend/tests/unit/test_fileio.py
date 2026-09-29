from __future__ import annotations

from pathlib import Path

import pytest

from arena_wizard.fileio import atomic_write_bytes, atomic_write_text


def test_a_write_creates_the_directory_and_rewriting_replaces_the_file(tmp_path: Path) -> None:
    target = tmp_path / "new" / "dir" / "file.bin"
    atomic_write_bytes(target, b"first")
    atomic_write_bytes(target, b"second")
    assert target.read_bytes() == b"second"
    assert [p.name for p in target.parent.iterdir()] == ["file.bin"]


def test_text_is_written_as_utf8_keeping_its_own_line_endings(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    atomic_write_text(target, "Dáin\r\nÉowyn\n")
    assert target.read_bytes() == "Dáin\r\nÉowyn\n".encode()


def test_a_failed_replace_raises_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "inside").write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"data")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["occupied"]
    assert (target / "inside").read_text(encoding="utf-8") == "x"
