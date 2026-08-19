"""遊んだ記録の退避とクリア（2026-08-03 / 依頼者の要望）。

★★★ **利用者のデータを消す道具なので、厚く試験します。** ★★★

⚠⚠ ここで見張るいちばん大事なこと:

  1. `--apply` を付けなければ**何も変わらない**
  2. `clear` は**必ず先に退避する**（退避できなければ消さない）
  3. ⚠⚠ **ROM・セーブステート・採取データに触らない**
"""

from __future__ import annotations

import json
import pathlib
import sqlite3

import pytest

from retroux.tools import playdata


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """★本物の `work/` を触らないように、仮の場所へ差し替えます。"""
    work = tmp_path / "work"
    work.mkdir()
    db = work / "retroux.sqlite3"
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("CREATE TABLE VisitedTile (id INTEGER PRIMARY KEY, x INT)")
        conn.execute("CREATE TABLE BattleEvent (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE Rom (hash TEXT)")
        conn.execute("CREATE TABLE MapOverride (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO VisitedTile (x) VALUES (?)",
                         [(i,) for i in range(20)])
        conn.executemany("INSERT INTO BattleEvent DEFAULT VALUES", [()] * 5)
        conn.execute("INSERT INTO Rom VALUES ('deadbeef')")
        conn.execute("INSERT INTO MapOverride DEFAULT VALUES")
    conn.close()

    (work / "events.jsonl").write_text("記録\n", encoding="utf-8")
    (work / "retroux.log").write_text("ログ\n", encoding="utf-8")
    (work / "map-assets").mkdir()
    (work / "map-assets" / "a.png").write_bytes(b"png")

    # ⚠⚠ **消してはいけないもの**
    (work / "rom").mkdir()
    (work / "rom" / "DQ2_J.nes").write_bytes(b"ROM")
    (work / "savestate-backup").mkdir()
    (work / "savestate-backup" / "DQ2_J-bak.fc0").write_bytes(b"SAVE")
    (work / "map-capture").mkdir()
    (work / "map-capture" / "capture.txt").write_text("採取", encoding="utf-8")
    (work / "evidence").mkdir()
    (work / "evidence" / "e.txt").write_text("証拠", encoding="utf-8")

    monkeypatch.setattr(playdata, "WORK", work)
    monkeypatch.setattr(playdata, "DB_PATH", db)
    monkeypatch.setattr(playdata, "VAULT", work / "playdata-archive")
    return work


def _rows(db: pathlib.Path, table: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    finally:
        conn.close()


# --- ★★ 触ってはいけないものを、消す対象に入れない -----------------------

def test_触らないものと消すものが重ならない():
    """⚠⚠ **ここが崩れると取り返しがつきません。**"""
    doomed = set(playdata.PLAY_FILES) | set(playdata.DERIVED_DIRS)
    assert not (doomed & set(playdata.NEVER_TOUCH))


def test_セーブステートは消す対象に入っていない():
    """⚠⚠ **ゲームのセーブは絶対に消しません。**

    ★セーブステートは **2 か所**あります:

    | どれ | 場所 |
    | --- | --- |
    | ★本物 | `tools/fceux/fcs/`（`DQ2_J-bak.fc0` 〜 `.fc9`） |
    | ★控え | `work/savestate-backup/`（10 世代） |

    ⚠ ここが消すのは `work/` の中だけなので、**本物には手が届きません**。
      ★それでも「消す一覧」に紛れ込まないよう見張ります。
    """
    for name in playdata.DERIVED_DIRS + playdata.PLAY_FILES:
        assert "save" not in name.lower(), f"⚠ {name}"
        assert "fcs" not in name.lower(), f"⚠ {name}"
    assert "savestate-backup" in playdata.NEVER_TOUCH
    assert "savestate_backup" in playdata.NEVER_TOUCH


def test_消すのはworkの中だけ():
    """★★ `tools/fceux/fcs`（セーブの本物）へ手が届かないこと。

    ⚠ 消す対象は `WORK` からの相対名だけで組み立てます。
      `..` や絶対パスが混ざっていたら、外へ出てしまいます。
    """
    for name in playdata.PLAY_FILES + playdata.DERIVED_DIRS:
        assert ".." not in name, f"⚠ {name} が親をたどっています"
        assert not pathlib.Path(name).is_absolute(), f"⚠ {name}"
        assert "/" not in name and "\\" not in name, f"⚠ {name}"


def test_セーブステートの本物の場所を取り違えていない():
    """★`savestate_backup.py` が見張っている場所と合っていること。

    ⚠ ここがずれると、説明と実物が食い違います。
    """
    from retroux.tools import savestate_backup

    assert savestate_backup.DEFAULT_SRC.name == "fcs"
    assert savestate_backup.DEFAULT_SRC.parent.name == "fceux"
    # ★控えは work の中（★だから NEVER_TOUCH で守る必要がある）
    assert savestate_backup.DEFAULT_DST.name == "savestate-backup"
    assert savestate_backup.DEFAULT_DST.name in playdata.NEVER_TOUCH


def test_ROMは消す対象に入っていない():
    assert "rom" in playdata.NEVER_TOUCH
    assert "rom" not in playdata.DERIVED_DIRS


def test_採取と解析のデータは消さない():
    for name in ("map-capture", "evidence", "dq2-disasm"):
        assert name in playdata.NEVER_TOUCH


def test_ROMの登録は残す():
    """★`Rom` テーブルを消すと、遊んだ記録が結びつかなくなります。"""
    assert "Rom" in playdata.KEEP_TABLES
    assert "Rom" not in playdata.PLAY_TABLES


# --- ★ 数えるだけ（`--apply` なし）----------------------------------------

def test_statusは何も変えない(workspace):
    before = sorted(p.name for p in workspace.rglob("*"))
    assert playdata.cmd_status() == 0
    assert sorted(p.name for p in workspace.rglob("*")) == before


def test_applyなしのbackupは退避しない(workspace):
    assert playdata.cmd_backup(apply=False) == 0
    assert not (workspace / "playdata-archive").exists()


def test_applyなしのclearは消さない(workspace):
    """⚠⚠ **これがいちばん大事**。"""
    assert playdata.cmd_clear(apply=False) == 0
    assert _rows(playdata.DB_PATH, "VisitedTile") == 20
    assert (workspace / "events.jsonl").exists()
    assert (workspace / "map-assets").exists()
    assert not (workspace / "playdata-archive").exists()


# --- ★ 退避 ---------------------------------------------------------------

def test_退避すると中身が写る(workspace):
    assert playdata.cmd_backup(apply=True, label="てすと") == 0
    saved = list((workspace / "playdata-archive").iterdir())
    assert len(saved) == 1
    target = saved[0]
    assert "てすと" in target.name
    assert (target / "retroux.sqlite3").exists()
    assert (target / "events.jsonl").exists()
    assert (target / "map-assets" / "a.png").exists()
    # ★元は消えていない
    assert _rows(playdata.DB_PATH, "VisitedTile") == 20


def test_退避にROMやセーブは入らない(workspace):
    """⚠ 退避が大きくなりすぎないように。★元がある物は写しません。"""
    playdata.cmd_backup(apply=True)
    target = next((workspace / "playdata-archive").iterdir())
    names = {p.name for p in target.rglob("*")}
    assert "DQ2_J.nes" not in names
    assert "DQ2_J-bak.fc0" not in names
    assert "capture.txt" not in names


def test_退避に説明書きが付く(workspace):
    playdata.cmd_backup(apply=True)
    target = next((workspace / "playdata-archive").iterdir())
    data = json.loads((target / "manifest.json").read_bytes().decode("utf-8"))
    assert data["rows"]["VisitedTile"] == 20
    assert "ROM" in data["note"]


# --- ★★ 消す -------------------------------------------------------------

def test_clearは先に退避してから消す(workspace):
    """★★★ **これが肝**。⚠ 消す前に必ず残します。"""
    assert playdata.cmd_clear(apply=True) == 0
    saved = list((workspace / "playdata-archive").iterdir())
    assert len(saved) == 1
    # ★退避には元の 20 行が入っている
    assert _rows(saved[0] / "retroux.sqlite3", "VisitedTile") == 20
    # ★本体は空になった
    assert _rows(playdata.DB_PATH, "VisitedTile") == 0
    assert _rows(playdata.DB_PATH, "BattleEvent") == 0


def test_clearでもROMの登録は残る(workspace):
    playdata.cmd_clear(apply=True)
    assert _rows(playdata.DB_PATH, "Rom") == 1
    assert _rows(playdata.DB_PATH, "MapOverride") == 1


def test_clearでもROMとセーブは残る(workspace):
    """⚠⚠ **ここが崩れたら取り返しがつきません。**"""
    playdata.cmd_clear(apply=True)
    assert (workspace / "rom" / "DQ2_J.nes").read_bytes() == b"ROM"
    assert (workspace / "savestate-backup" / "DQ2_J-bak.fc0").read_bytes() == b"SAVE"
    assert (workspace / "map-capture" / "capture.txt").exists()
    assert (workspace / "evidence" / "e.txt").exists()


def test_clearで遊んだファイルが消える(workspace):
    playdata.cmd_clear(apply=True)
    assert not (workspace / "events.jsonl").exists()
    assert not (workspace / "retroux.log").exists()
    assert not (workspace / "map-assets").exists()


def test_DBが無くても落ちない(workspace):
    playdata.DB_PATH.unlink()
    assert playdata.cmd_status() == 0
    assert playdata.cmd_clear(apply=True) == 0


# --- ★ 一覧・戻す ---------------------------------------------------------

def test_一覧が出る(workspace):
    assert playdata.cmd_list() == 0          # ★まだ無くても落ちない
    playdata.cmd_backup(apply=True, label="いち")
    assert playdata.cmd_list() == 0


def test_戻すと記録が復活する(workspace):
    playdata.cmd_backup(apply=True, label="もと")
    name = next(p.name for p in (workspace / "playdata-archive").iterdir())
    playdata.cmd_clear(apply=True)
    assert _rows(playdata.DB_PATH, "VisitedTile") == 0

    assert playdata.cmd_restore(name, apply=True) == 0
    assert _rows(playdata.DB_PATH, "VisitedTile") == 20
    assert (workspace / "events.jsonl").exists()
    assert (workspace / "map-assets" / "a.png").exists()


def test_戻す前にもいまの状態を退避する(workspace):
    """⚠ 戻したあとで「やっぱり元がよかった」と言えるように。"""
    playdata.cmd_backup(apply=True, label="A")
    name = next(p.name for p in (workspace / "playdata-archive").iterdir())
    before = len(list((workspace / "playdata-archive").iterdir()))
    playdata.cmd_restore(name, apply=True)
    after = len(list((workspace / "playdata-archive").iterdir()))
    assert after == before + 1, "★戻す前の状態も残るはず"


def test_applyなしの戻すは何もしない(workspace):
    playdata.cmd_backup(apply=True)
    name = next(p.name for p in (workspace / "playdata-archive").iterdir())
    playdata.cmd_clear(apply=True)
    assert playdata.cmd_restore(name, apply=False) == 0
    assert _rows(playdata.DB_PATH, "VisitedTile") == 0, "★戻っていないこと"


def test_無い退避を指定したら教えてくれる(workspace):
    assert playdata.cmd_restore("そんなものはない", apply=True) == 1


# --- ★ CLI ---------------------------------------------------------------

def test_CLIがapplyなしで動く(workspace):
    assert playdata.main(["status"]) == 0
    assert playdata.main(["list"]) == 0
    assert playdata.main(["clear"]) == 0
    assert _rows(playdata.DB_PATH, "VisitedTile") == 20, "★消えていないこと"


def test_restoreに名前が無ければ断る(workspace):
    assert playdata.main(["restore"]) == 1
