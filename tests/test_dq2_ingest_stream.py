"""DQ2 の主 events の取り込み位置は論理 ID で持つ（RX-0163）。

★Portable のフォルダを動かしても（C:\\A\\Portable-DQ2 → D:\\B\\Portable-DQ2）、同じ流れの続きとして取り込む。
⚠ 「同じ ID だから続き」とは扱わない: 位置・先頭の署名・行の境目・取り込み済みの末尾の署名で確かめ、
  合わなければ取り込みを止める（★二重の記録・別の記録との混ざりを防ぐ）。
★実データ（C:\\Tools\\RetroUX）での移動の確認は docs/30-command-log.md。
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from retroux.core import dq2_paths
from retroux.core.db.database import Database
from retroux.core.recorder import MAIN_STREAM, Recorder, check_ingest_state, rotate_events
from retroux.migration import Options, migrate
from retroux.tools import ingest_state as T
from test_dq2_migration import EVENTS, HASH, make_legacy

MORE = [
    '{"type":"battle_start","frame":2000,"enemy_ids":[3],"is_first_encounter":true,"is_boss":false}',
    '{"type":"battle_end","frame":2600,"duration_frames":600,"speed_applied":1.0}',
]


def _quiet(*_a, **_k):
    return None


def portable(tmp_path: Path, name: str = "A") -> Path:
    """★旧版 → 移行を済ませた Portable 相当（A/Portable-DQ2）。"""
    legacy = make_legacy(tmp_path / f"old-{name}")
    dest = tmp_path / name / "Portable-DQ2"
    dest.mkdir(parents=True)
    migrate(legacy, dest, Options(), out=_quiet)
    return dest


def battles(root: Path) -> int:
    con = sqlite3.connect(root / "work" / "retroux.sqlite3")
    try:
        return con.execute("SELECT COUNT(*) FROM BattleLog").fetchone()[0]
    finally:
        con.close()


def launch(root: Path, monkeypatch) -> tuple[Database, Recorder]:
    """★起動と同じ道（write_root = フォルダ / dq2_paths.events() / MAIN_STREAM / rotate → Recorder）。"""
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(root))
    db = Database(root / "work" / "retroux.sqlite3")
    events = dq2_paths.events()
    assert events == root / "work" / "events.jsonl"
    rotate_events(db, events, stream=MAIN_STREAM)
    return db, Recorder(db, HASH, events, root / "work" / "command.json", stream=MAIN_STREAM)


def append(root: Path, lines) -> None:
    with (root / "work" / "events.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(line + "\n" for line in lines))


# --- フォルダを動かす（依頼 RX-0163 §8・§9）-------------------------------------

@pytest.mark.parametrize("how", ["move", "copy"])
def test_フォルダを動かしても取り込み直さず追記だけ取り込む(tmp_path, monkeypatch, how) -> None:
    a = portable(tmp_path)
    n = battles(a)
    assert n == 2
    b = tmp_path / "B" / "Portable-DQ2"
    b.parent.mkdir()
    (shutil.move if how == "move" else shutil.copytree)(str(a), str(b))

    db, rec = launch(b, monkeypatch)
    try:
        assert rec.hold is None, rec.hold
        assert rec.poll() == 0
        assert battles(b) == n, "⚠ 動かしたら過去の戦闘を取り込み直した"
        append(b, MORE)
        assert rec.poll() == 2
        assert battles(b) == n + 1, "追記した 1 戦闘だけ増える"
    finally:
        db.close()
    # ★再起動しても同じ（★位置を保存している）
    db, rec = launch(b, monkeypatch)
    try:
        assert rec.poll() == 0 and battles(b) == n + 1
        row = db.get_ingest_row(MAIN_STREAM)
        assert row["path"] == str((b / "work" / "events.jsonl").resolve())   # ★診断用は今の場所
    finally:
        db.close()


def test_IngestStateに絶対パスの鍵が増えない(tmp_path, monkeypatch) -> None:
    a = portable(tmp_path)
    db, rec = launch(a, monkeypatch)
    try:
        append(a, MORE)
        rec.poll()
        assert db.ingest_sources() == [MAIN_STREAM]
    finally:
        db.close()


# --- 別の events を続きと取り違えない（依頼 §10・§11）--------------------------

def _held(root: Path, monkeypatch, expect: str) -> None:
    before_rows = battles(root)
    db, rec = launch(root, monkeypatch)
    try:
        row_before = tuple(db.get_ingest_row(MAIN_STREAM))
        assert rec.hold is not None and expect in rec.hold, rec.hold
        assert any("取り込みを止めました" in w for w in rec.stats.warnings)
        append(root, MORE)
        assert rec.poll() == 0
        assert battles(root) == before_rows
        assert tuple(db.get_ingest_row(MAIN_STREAM)) == row_before, "⚠ 止めたのに位置を書き換えた"
    finally:
        db.close()


def test_eventsが短くなっていたら止める(tmp_path, monkeypatch) -> None:
    a = portable(tmp_path)
    ev = a / "work" / "events.jsonl"
    ev.write_bytes(ev.read_bytes()[: len(EVENTS[0]) + 1])
    _held(a, monkeypatch, "超えています")


def test_位置がeventsの大きさを超えていたら止める(tmp_path, monkeypatch) -> None:
    a = portable(tmp_path)
    con = sqlite3.connect(a / "work" / "retroux.sqlite3")
    con.execute("UPDATE IngestState SET offset = offset + 999 WHERE source = ?", (MAIN_STREAM,))
    con.commit()
    con.close()
    _held(a, monkeypatch, "超えています")


def test_eventsの先頭が別物なら止める(tmp_path, monkeypatch) -> None:
    a = portable(tmp_path)
    (a / "work" / "events.jsonl").write_bytes(("".join(line + "\n" for line in MORE) * 20).encode("utf-8"))
    _held(a, monkeypatch, "先頭")


def test_DQ3のeventsなら止める(tmp_path, monkeypatch) -> None:
    a = portable(tmp_path)
    (a / "work" / "events.jsonl").write_bytes(
        ('{"type":"dq3_session_start","product":"retroux-dq3"}\n' * 40).encode("utf-8"))
    _held(a, monkeypatch, "先頭")


def _diverged(tmp_path: Path) -> tuple[Path, Path]:
    """★同じ旧版から移した 2 つの Portable が、それぞれ別に遊んだ（★先頭は同じ・続きが違う）。"""
    a = portable(tmp_path)
    b = tmp_path / "C" / "Portable-DQ2"
    shutil.copytree(a, b)
    append(a, MORE)
    append(b, [MORE[0].replace("[3]", "[7]").replace("2000", "2100"), MORE[1]])
    for root in (a, b):
        db = Database(root / "work" / "retroux.sqlite3")
        Recorder(db, HASH, root / "work" / "events.jsonl", root / "work" / "command.json",
                 stream=MAIN_STREAM).poll()
        db.close()
    return a, b


def test_別の環境のeventsだけを写したら止める(tmp_path, monkeypatch) -> None:
    a, b = _diverged(tmp_path)
    shutil.copy2(b / "work" / "events.jsonl", a / "work" / "events.jsonl")
    _held(a, monkeypatch, "末尾")


def test_別の環境のDBだけを写したら止める(tmp_path, monkeypatch) -> None:
    a, b = _diverged(tmp_path)
    shutil.copy2(b / "work" / "retroux.sqlite3", a / "work" / "retroux.sqlite3")
    _held(a, monkeypatch, "末尾")


def test_別のDQ2データのDBなら止める(tmp_path, monkeypatch) -> None:
    """★別の旧版から移した（★先頭からして違う）DB を置いた。"""
    a = portable(tmp_path, "A")
    other_legacy = make_legacy(tmp_path / "old-other")
    (other_legacy / "work" / "events.jsonl").write_bytes(
        ("".join(line + "\n" for line in reversed(EVENTS))).encode("utf-8"))
    db = sqlite3.connect(other_legacy / "work" / "retroux.sqlite3")
    db.execute("UPDATE IngestState SET head_sig = NULL")      # ★別の旧版（署名なしで取り込み済み）
    db.commit()
    db.close()
    other = tmp_path / "X" / "Portable-DQ2"
    other.mkdir(parents=True)
    migrate(other_legacy, other, Options(), out=_quiet)
    shutil.copy2(other / "work" / "retroux.sqlite3", a / "work" / "retroux.sqlite3")
    _held(a, monkeypatch, "末尾")


def test_止めているときは世代交代もしない(tmp_path, monkeypatch) -> None:
    """⚠ 別の環境の位置で「追いついた」と見て回すと、取り込んでいない行を置き去りにする。"""
    a, b = _diverged(tmp_path)
    shutil.copy2(b / "work" / "retroux.sqlite3", a / "work" / "retroux.sqlite3")
    db = Database(a / "work" / "retroux.sqlite3")
    try:
        got = rotate_events(db, a / "work" / "events.jsonl", stream=MAIN_STREAM, max_bytes=1)
        assert got.rotated is False and "合わない" in got.reason
        assert (a / "work" / "events.jsonl").exists()
    finally:
        db.close()


# --- 旧い形式（鍵 = 絶対パス）---------------------------------------------------

def _legacy_key(root: Path, source: str) -> None:
    con = sqlite3.connect(root / "work" / "retroux.sqlite3")
    con.execute("UPDATE IngestState SET source = ?, tail_sig = NULL WHERE source = ?", (source, MAIN_STREAM))
    con.commit()
    con.close()


def test_その場の旧版の行は同じ場所なら論理IDへ移す(tmp_path, monkeypatch) -> None:
    """★開発 repo のように、旧版のデータをその場で今の版が読む（schema 0 のまま）。"""
    a = portable(tmp_path)
    _legacy_key(a, str((a / "work" / "events.jsonl").resolve()))
    n = battles(a)
    db, rec = launch(a, monkeypatch)
    try:
        assert rec.hold is None and rec.poll() == 0 and battles(a) == n
        assert db.ingest_sources() == [MAIN_STREAM]
    finally:
        db.close()


def test_別の場所の旧い行しか無ければ止める(tmp_path, monkeypatch) -> None:
    """⚠ 似た行を探して付け替えるのは正規の仕様にしない（★開発用の修理で明示して直す）。"""
    a = portable(tmp_path)
    _legacy_key(a, r"C:\somewhere\else\work\events.jsonl")
    db, rec = launch(a, monkeypatch)
    try:
        assert rec.hold and "旧い形式" in rec.hold
        assert rec.poll() == 0
    finally:
        db.close()


def test_開発用の修理は確かめてから付け替える(tmp_path, monkeypatch) -> None:
    a = portable(tmp_path)
    old = r"C:\moved\work\events.jsonl"
    _legacy_key(a, old)
    events = a / "work" / "events.jsonl"
    db = Database(a / "work" / "retroux.sqlite3")
    try:
        assert T.adopt(db, events, old, apply=False, out=_quiet) == 0
        assert db.ingest_sources() == [old], "⚠ --apply 無しで変えた"
        assert T.adopt(db, events, old, apply=True, out=_quiet) == 0
        assert db.ingest_sources() == [MAIN_STREAM]
        assert T.status(db, events, out=_quiet) == 0
    finally:
        db.close()


def test_開発用の修理は別のeventsなら付け替えない(tmp_path) -> None:
    a = portable(tmp_path)
    old = r"C:\moved\work\events.jsonl"
    _legacy_key(a, old)
    events = a / "work" / "events.jsonl"
    events.write_bytes(("".join(line + "\n" for line in MORE) * 20).encode("utf-8"))
    db = Database(a / "work" / "retroux.sqlite3")
    try:
        assert T.adopt(db, events, old, apply=True, out=_quiet) == 2
        assert db.ingest_sources() == [old]
        assert T.status(db, events, out=_quiet) == 2
    finally:
        db.close()


def test_鍵を渡さない呼び手はこれまでどおり() -> None:
    """★検査・分析が別のファイルを読む道（鍵 = 絶対パス / 作り直されたら先頭から）は変えない。"""
    import inspect

    assert inspect.signature(Recorder).parameters["stream"].default is None
    assert inspect.signature(check_ingest_state).parameters.keys() >= {"db", "key", "events_path"}
