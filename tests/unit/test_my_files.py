"""my_files: list and read the user's own folder, nothing outside it."""
import asyncio

import pytest

from harness.tools.builtin import my_files as mf


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "SESSIONS", tmp_path)
    (tmp_path / "u1").mkdir()
    (tmp_path / "u2").mkdir()
    (tmp_path / "u1" / "notes.txt").write_text("buy milk\ncall Priya")
    (tmp_path / "u1" / "rent.csv").write_text("month,amount\nJan,15000\n")
    (tmp_path / "u1" / "photo.png").write_bytes(b"\x89PNG")
    (tmp_path / "u2" / "secret.txt").write_text("other user's file")
    return tmp_path


def run(user_id, **kw):
    return asyncio.run(mf.make_my_files_tool(user_id).handler(**kw))


def test_list_shows_only_the_users_files(folder):
    out = run("u1", action="list")
    assert "notes.txt" in out and "rent.csv" in out and "photo.png" in out
    assert "secret.txt" not in out


def test_read_returns_the_text(folder):
    assert "call Priya" in run("u1", action="read", name="notes.txt")
    assert "month: Jan" in run("u1", action="read", name="rent.csv") or "Jan" in run("u1", action="read", name="rent.csv")


@pytest.mark.parametrize("name", ["../u2/secret.txt", "/etc/passwd", "u2/secret.txt"])
def test_only_the_basename_is_honoured(folder, name):
    out = run("u1", action="read", name=name)
    assert "other user's file" not in out and "root:" not in out


def test_images_point_to_view_image_and_missing_files_say_so(folder):
    assert "view_image" in run("u1", action="read", name="photo.png")
    assert "No file named" in run("u1", action="read", name="nope.txt")


def test_long_files_are_truncated(folder):
    (folder / "u1" / "big.txt").write_text("x" * (mf.MAX_CHARS + 500))
    out = run("u1", action="read", name="big.txt")
    assert "truncated" in out and len(out) < mf.MAX_CHARS + 300


def test_empty_or_missing_folder(folder):
    assert "empty" in run("nobody", action="list")
