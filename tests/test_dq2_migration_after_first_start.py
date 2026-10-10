"""先に 1 回起動した Portable へも移行できる（RX-0164 / 依頼者 2026-10-03「推奨案で」）。

★利用者は「ZIP を展開 → 試しに起動 → 旧版から移行」をやりがち。起動しただけで印（created）・DB（Rom の行）・
  events の先頭・設定が書かれるので、以前は「既に今の版」で**何もしなかった**（⚠ エラーにもならない）。
★遊んだ跡が無ければ新規と同じく移し、起動で作られたファイルは `work/dq2-migration/replaced/<run>/` へ退避する。
⚠ 1 つでも遊んだ跡があれば止める（★混ぜない）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from retroux.core import dq2_data as D
from retroux.core.db.database import Database
from retroux.core.recorder import MAIN_STREAM, Recorder
from retroux.migration import MigrationStop, Options, migrate
from retroux.migration import runner as R
from test_dq2_migration import EVENTS, HASH, make_legacy

SESSION = '{"type":"session_start","frame":1}'


def _quiet(*_a, **_k):
    return None


def run(src, dst, **kw):
    return migrate(src, dst, Options(**kw), out=_quiet)


def first_start(dest: Path) -> None:
    """★ZIP を展開して 1 回起動した形（起動の判定 → GUI が DB と ROM の行 → Lua が events の先頭 → 取り込み）。"""
    assert D.gate(R.dest_places(dest), out=_quiet) == 0          # ★印（created）
    work = dest / "work"
    (work / "events.jsonl").write_bytes((SESSION + "\n").encode("utf-8"))
    db = Database(work / "retroux.sqlite3")
    db.register_rom(HASH, "ドラゴンクエストII 悪霊の神々", "JP", 2)
    Recorder(db, HASH, work / "events.jsonl", work / "command.json", stream=MAIN_STREAM).poll()
    db.close()
    (work / "window-state.json").write_bytes(b'{"fresh": 1}')
    (work / "generated").mkdir(exist_ok=True)
    (work / "generated" / "config.lua").write_bytes(b"-- fresh")
    (work / "dq2-settings").mkdir(exist_ok=True)
    (work / "dq2-settings" / "keybindings.yaml").write_bytes(b"schema_version: 1\n")


@pytest.fixture
def legacy(tmp_path) -> Path:
    return make_legacy(tmp_path / "old")


@pytest.fixture
def dest(tmp_path) -> Path:
    d = tmp_path / "RetroUX-DQ2"
    d.mkdir()
    first_start(d)
    return d


def battles(root: Path) -> int:
    con = sqlite3.connect(root / "work" / "retroux.sqlite3")
    try:
        return con.execute("SELECT COUNT(*) FROM BattleLog").fetchone()[0]
    finally:
        con.close()


def test_起動しただけなら遊んだ跡は無い(dest) -> None:
    assert D.detect(R.dest_places(dest)).kind == D.CURRENT
    assert D.used_reason(R.dest_places(dest)) is None


def test_先に起動していても移せて起動のファイルは退避する(legacy, dest) -> None:
    got = run(legacy, dest)
    assert got.status == "migrated"
    assert battles(dest) == 2
    assert (dest / "work" / "events.jsonl").read_bytes() == (legacy / "work" / "events.jsonl").read_bytes()
    assert (dest / "work" / "window-state.json").read_bytes() == (legacy / "work" / "window-state.json").read_bytes()
    keep = dest / D.MIGRATION_DIR_REL / "replaced" / got.run / "work"
    assert (keep / "events.jsonl").read_bytes() == (SESSION + "\n").encode("utf-8")
    assert (keep / "window-state.json").read_bytes() == b'{"fresh": 1}'
    assert (keep / "retroux.sqlite3").exists()
    assert "work/events.jsonl" in got.report["replaced"]
    # ★起動で作った設定は旧から来ないので残る（★退避もしない）
    assert (dest / "work" / "dq2-settings" / "keybindings.yaml").read_bytes() == b"schema_version: 1\n"
    marker = D.read_marker(dest)
    assert [h["event"] for h in marker["history"]] == ["created", "migrated"]
    assert D.detect(R.dest_places(dest)).kind == D.CURRENT


def test_移したあと取り込み直さない(legacy, dest) -> None:
    run(legacy, dest)
    db = Database(dest / "work" / "retroux.sqlite3")
    try:
        rec = Recorder(db, HASH, dest / "work" / "events.jsonl", dest / "work" / "command.json", stream=MAIN_STREAM)
        assert rec.hold is None and rec.poll() == 0
    finally:
        db.close()
    assert battles(dest) == 2


def test_2回目は何もしない(legacy, dest) -> None:
    run(legacy, dest)
    assert run(legacy, dest).status == "noop"
    assert battles(dest) == 2


def _played_battle(dest: Path) -> None:
    db = Database(dest / "work" / "retroux.sqlite3")
    with (dest / "work" / "events.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(EVENTS[0] + "\n" + EVENTS[1] + "\n")
    Recorder(db, HASH, dest / "work" / "events.jsonl", dest / "work" / "command.json", stream=MAIN_STREAM).poll()
    db.close()


def _unread_events(dest: Path) -> None:
    with (dest / "work" / "events.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(EVENTS[0] + "\n")


def _savestate(dest: Path) -> None:
    (dest / "tools" / "fceux" / "fcs").mkdir(parents=True)
    (dest / "tools" / "fceux" / "fcs" / "DQ2_J.fc1").write_bytes(b"x")


@pytest.mark.parametrize("play, why", [(_played_battle, "BattleLog"), (_unread_events, "取り込んでいない"),
                                       (_savestate, "セーブステート")],
                         ids=["戦闘の記録", "取り込んでいないevents", "セーブ"])
def test_遊んだ跡があれば止めて何も変えない(legacy, dest, play, why) -> None:
    play(dest)
    before = sorted((p.relative_to(dest).as_posix(), p.stat().st_size) for p in (dest / "work").rglob("*")
                    if p.is_file() and "dq2-migration" not in p.parts)
    with pytest.raises(MigrationStop, match=why):
        run(legacy, dest)
    after = sorted((p.relative_to(dest).as_posix(), p.stat().st_size) for p in (dest / "work").rglob("*")
                   if p.is_file() and "dq2-migration" not in p.parts)
    assert after == before
    assert [h["event"] for h in D.read_marker(dest)["history"]] == ["created"]


def test_本番へ入れる途中で落ちても続きから終え退避も残る(legacy, dest, monkeypatch) -> None:
    real = R._commit

    def crash(staging, dst, files, replaced=(), run=""):
        keep = dst / D.MIGRATION_DIR_REL / "replaced" / run
        for rel in replaced[:1]:
            (keep / rel).parent.mkdir(parents=True, exist_ok=True)
            (dst / rel).replace(keep / rel)
        raise KeyboardInterrupt("電源が落ちた")

    monkeypatch.setattr(R, "_commit", crash)
    with pytest.raises(KeyboardInterrupt):
        run(legacy, dest)
    monkeypatch.setattr(R, "_commit", real)
    assert D.detect(R.dest_places(dest)).kind == D.INCOMPLETE
    got = run(legacy, dest, resume=True)
    assert got.status == "migrated" and battles(dest) == 2
    keep = dest / D.MIGRATION_DIR_REL / "replaced" / got.run
    assert (keep / "work" / "events.jsonl").read_bytes() == (SESSION + "\n").encode("utf-8")
    # ★続きからでも、起動のファイルは全部退避されている（⚠ 落ちる前に退避した 1 件だけではない）
    assert got.report["replaced"] and all((keep / rel).exists() for rel in got.report["replaced"])
    assert (keep / "work" / "window-state.json").read_bytes() == b'{"fresh": 1}'
