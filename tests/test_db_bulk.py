"""まとめ書きのテスト（MVP2 Phase 1）。

★なぜ必要になったか（実測 / 2026-07-26）:
  1イベント = 1コミット = 1回の fsync で **127ms** かかっていた。
  溜まっていた 4820 件の取り込みに10分近くを要し、
  GUI は起動時にこれを同期で呼ぶため**固まったように見えていた**
  （実際に「ウィンドウが出ない」として現れた）。
  まとめて1コミットにしたら 0.13 秒になった。

守りたい契約:
  1. bulk() を抜けたときに**確かに保存されている**（遅延したまま消えない）
  2. 途中で失敗したら**まとめて捨てる**（半端に残さない）
  3. 入れ子にしても、いちばん外側で1回だけコミットする
"""

from __future__ import annotations

import sqlite3

import pytest

from retroux.core.db.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.sqlite3")
    yield d
    d.close()


def _rom_count(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM Rom").fetchone()[0]
    finally:
        conn.close()


def test_bulk_commits_at_exit(db, tmp_path):
    with db.bulk():
        db.register_rom("A", "ROM A", "JP")
        db.register_rom("B", "ROM B", "JP")

    # ★別の接続から見えることを確かめる（コミットされた証拠になる）
    assert _rom_count(tmp_path / "t.sqlite3") == 2


def test_bulk_is_not_visible_before_exit(db, tmp_path):
    with db.bulk():
        db.register_rom("A", "ROM A", "JP")
        # まだコミットしていないので、外からは見えない
        assert _rom_count(tmp_path / "t.sqlite3") == 0
    assert _rom_count(tmp_path / "t.sqlite3") == 1


def test_bulk_rolls_back_on_error(db, tmp_path):
    """途中で失敗したら**まとめて捨てる**。

    半端に取り込むと「取り込み位置だけ進んで戦闘が欠ける」という
    直しにくい壊れ方になる。
    """
    with pytest.raises(RuntimeError):
        with db.bulk():
            db.register_rom("A", "ROM A", "JP")
            raise RuntimeError("途中で失敗")

    assert _rom_count(tmp_path / "t.sqlite3") == 0


def test_nested_bulk_commits_once(db, tmp_path):
    with db.bulk():
        db.register_rom("A", "ROM A", "JP")
        with db.bulk():
            db.register_rom("B", "ROM B", "JP")
        # 内側を抜けただけではコミットしない
        assert _rom_count(tmp_path / "t.sqlite3") == 0
    assert _rom_count(tmp_path / "t.sqlite3") == 2


def test_normal_write_still_commits(db, tmp_path):
    """bulk を使わない書き込みは今までどおり即コミットする。"""
    db.register_rom("A", "ROM A", "JP")
    assert _rom_count(tmp_path / "t.sqlite3") == 1
