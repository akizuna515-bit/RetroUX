"""ずれたタイルIDを捨てる道具のテスト（2026-08-01 / 課題 #65）。

★ここで守りたいこと:
  1. **既定では消さない**（`--apply` が要る）
  2. **訪問記録は1行も消えない**（消すのは `tile` 列と絵だけ）
  3. **控えを取ってから消す**
  4. ⚠ **遊んでいる最中は断る**（`tile_art.txt` は Lua が追記中）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from retroux.tools import tile_reset


def _make_db(path: Path) -> None:
    """訪問記録を4マス作る（うち3マスにタイルIDが入っている）。"""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE VisitedTile ("
                 "rom_hash TEXT, map_id INTEGER, map_ptr INTEGER,"
                 " x INTEGER, y INTEGER, tile INTEGER)")
    conn.executemany(
        "INSERT INTO VisitedTile VALUES (?,?,?,?,?,?)",
        [("h", 1, 0x8000, 0, 0, 0x5F),
         ("h", 1, 0x8000, 1, 0, 0xB0),
         ("h", 1, 0x8000, 2, 0, 0xA3),
         ("h", 1, 0x8000, 3, 0, None)])
    conn.commit()
    conn.close()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """DB と絵のファイルを差し替えた状態を作る。"""
    db = tmp_path / "retroux.sqlite3"
    _make_db(db)
    art = tmp_path / "tile_art.txt"
    art.write_text("01:5F\tAABBCC\n01:B0\tDDEEFF\n", encoding="utf-8")
    monkeypatch.setattr(tile_reset, "ART_PATH", art)
    # ⚠⚠ **控え先も必ず差し替える**（2026-08-01 に実際に汚した）。
    #   差し替え忘れたテストが `--apply` を呼び、**本物の work/backups/ へ
    #   テスト用DBの控えを書いた**。テストは実プロジェクトを触ってはいけない。
    monkeypatch.setattr(tile_reset, "BACKUP_DIR", tmp_path / "backups")

    class _Cfg:
        def path(self, _key):
            return db

    import retroux.core.config.user_config as uc
    monkeypatch.setattr(uc, "load", lambda _p=None: (_Cfg(), []))
    # ★遊んでいない状態を既定にする（本物のプロセス一覧は見に行かせない）
    monkeypatch.setattr(tile_reset, "_someone_is_playing", lambda: None)
    return db, art


def _rows(db: Path):
    conn = sqlite3.connect(db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM VisitedTile").fetchone()[0]
        with_tile = conn.execute(
            "SELECT COUNT(*) FROM VisitedTile WHERE tile IS NOT NULL"
        ).fetchone()[0]
        return total, with_tile
    finally:
        conn.close()


def test_既定では消さない(env, capsys):
    db, art = env
    assert tile_reset.main([]) == 0
    assert _rows(db) == (4, 3)          # ★1つも消えていない
    assert art.exists()
    assert "--apply" in capsys.readouterr().out


def test_applyでタイルIDだけ消える(env):
    db, art = env
    assert tile_reset.main(["--apply"]) == 0
    total, with_tile = _rows(db)
    assert with_tile == 0               # ★タイルIDは消えた
    assert total == 4                   # ★★訪問記録は1行も消えていない
    assert not art.exists()             # ★絵も消えた


def test_控えを取ってから消す(env, tmp_path):
    db, art = env
    tile_reset.main(["--apply"])
    backups = list((tmp_path / "backups").glob("*-before-tile-reset"))
    names = {p.name.split(".")[0] for p in backups}
    assert names == {"retroux", "tile_art"}, backups
    # ★控えの DB にはタイルIDが**残っている**（戻せる）
    kept = [p for p in backups if p.name.startswith("retroux")][0]
    conn = sqlite3.connect(kept)
    try:
        n = conn.execute("SELECT COUNT(*) FROM VisitedTile "
                         "WHERE tile IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    assert n == 3


def test_遊んでいる最中は断る(env, monkeypatch, capsys):
    db, art = env
    monkeypatch.setattr(tile_reset, "_someone_is_playing",
                        lambda: "⚠⚠ RetroUX が 4 個動いています。")
    assert tile_reset.main(["--apply"]) == 1
    assert _rows(db) == (4, 3)          # ★何も消えていない
    assert art.exists()
    assert "動いています" in capsys.readouterr().out


def test_forceを付ければ動作中でも通る(env, monkeypatch):
    db, art = env
    called = []
    monkeypatch.setattr(tile_reset, "_someone_is_playing",
                        lambda: called.append(1) or "動いています")
    assert tile_reset.main(["--apply", "--force"]) == 0
    assert called == []                 # ★そもそも確認しない
    assert _rows(db) == (4, 0)


def test_数えるだけなら動作中でも通る(env, monkeypatch):
    """★読むだけなので、遊んでいても害がない。"""
    db, _art = env
    monkeypatch.setattr(tile_reset, "_someone_is_playing",
                        lambda: "動いています")
    assert tile_reset.main([]) == 0
    assert _rows(db) == (4, 3)


def test_テストが本物のwork配下へ書かない(env):
    """⚠⚠ **2026-08-01 に実際に汚した。**

    控え先を差し替え忘れたテストが `--apply` を呼び、**本物の
    `work/backups/` へテスト用DBの控えを書いた**（8KB のゴミが残った）。
    ★fixture が必ず差し替えるようにした。ここでそれを確かめる。
    """
    real = tile_reset.PROJECT_ROOT / "work" / "backups"
    before = set(real.glob("*")) if real.exists() else set()
    tile_reset.main(["--apply"])
    after = set(real.glob("*")) if real.exists() else set()
    assert after == before, f"★本物の work/backups を汚した: {after - before}"


def test_控えは相談用ZIPに入る場所へ置かない():
    """⚠⚠ **2026-08-01 に実際に配ってしまった。**

    控えを `work/generated/` へ置いたところ、`export-for-review.ps1` が
    そこを**丸ごと** ZIP に入れるため、**直す前の間違ったデータ 535KB**が
    相談用の配布物に混ざった。相談相手がそれを解析しかねない。

    ★控えは `work/backups/`（書き出しの対象外）へ置く。
    """
    rel = tile_reset.BACKUP_DIR.relative_to(tile_reset.PROJECT_ROOT).as_posix()
    assert rel == "work/backups", rel
    assert "generated" not in rel


def test_名前にretrouxを含むだけのプロセスを数えない():
    """⚠⚠ **2026-08-01 に実際にやらかした。**

    判定を `*retroux*` にしたら、`python -m retroux.tools.tile_reset` である
    **自分自身**を数えて「2個動いています」と言い、永久に実行できなかった。

    ★★ **差分で測る。** ★★
      「動いている／いない」で見ると、本当に RetroUX が起動している間は
      skip になって**素通り**する。★余計なプロセスを1つ足して、
      数が増えないことを確かめれば、起動中でも判定できる。
    """
    import subprocess
    import sys
    import time

    before = tile_reset._count_playing()
    if before is None:
        pytest.skip("プロセス一覧を数えられない環境です")

    # ★コマンドラインに "retroux" を含む python を1つ立てる。
    #   ⚠ ただし "retroux.gui" ではない＝遊んでいる印ではない。
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import time  # retroux.tools のふりをする\ntime.sleep(20)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        time.sleep(1.0)                     # プロセス一覧に載るのを待つ
        during = tile_reset._count_playing()
        assert during == before, (
            f"★余計なプロセスを数えている（{before} -> {during}）。"
            "判定が広すぎる（`*retroux*` になっていないか）")
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_DBが無ければ止まる(tmp_path, monkeypatch, capsys):
    class _Cfg:
        def path(self, _key):
            return tmp_path / "ない.sqlite3"

    import retroux.core.config.user_config as uc
    monkeypatch.setattr(uc, "load", lambda _p=None: (_Cfg(), []))
    monkeypatch.setattr(tile_reset, "_someone_is_playing", lambda: None)
    assert tile_reset.main(["--apply"]) == 1
    assert "DB がありません" in capsys.readouterr().out
