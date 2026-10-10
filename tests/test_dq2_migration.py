"""DQ2 の移行（RX-0157 runner / RX-0158 `0001_legacy_to_portable`）。

★依頼 §15 の正常・再実行・異常を、旧版の形に作った一時フォルダで確かめる。
⚠ 旧フォルダ（source）は**1 バイトも変えない**ことを毎回見る。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from retroux.core import dq2_data as D
from retroux.core.db.database import Database
from retroux.core.recorder import Recorder
from retroux.migration import MigrationStop, Options, migrate
from retroux.migration import m0001_legacy_to_portable as M
from retroux.migration import runner as R

ROOT = Path(__file__).resolve().parents[1]
HASH = D.DQ2_PRG_SHA256
EVENTS = [
    '{"type":"battle_start","frame":10,"enemy_ids":[1,1],"is_first_encounter":true,"is_boss":false}',
    '{"type":"battle_end","frame":700,"duration_frames":690,"speed_applied":4.0}',
    '{"type":"battle_start","frame":900,"enemy_ids":[2],"is_first_encounter":true,"is_boss":false}',
    '{"type":"battle_end","frame":1500,"duration_frames":600,"speed_applied":1.0}',
]


def _w(path: Path, data: bytes | str = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def make_legacy(src: Path) -> Path:
    """★旧版（v1.x）の DQ2 フォルダの形。⚠ DQ3 のものも同居させる（旧版はそうだった）。"""
    _w(src / "retroux" / "core" / "db" / "database.py", "# 旧版")
    (src / "retroux" / "plugins" / "dq2").mkdir(parents=True)
    _w(src / "user_config.yaml",
       "paths:\n  fceux: C:/DQ3/fceux64.exe\n  dq3_rom: work/rom/DQ3_J.nes\n  log: work/retroux.log\n"
       "gui:\n  font_size: 13\n")
    _w(src / "config" / "mantan.yaml", "target_hp_percent: 70\n")
    _w(src / "config" / "dq3_phase0.yaml", "x: 1\n")
    work = src / "work"
    events = _w(work / "events.jsonl", "".join(line + "\n" for line in EVENTS))
    db = Database(work / "retroux.sqlite3")
    db.register_rom(HASH, "ドラゴンクエストII 悪霊の神々", "JP", 2)
    ticks = iter([1.0, 2.0, 3.0, 4.0])
    assert Recorder(db, HASH, events, work / "command.json", clock=lambda: next(ticks)).poll() == 4
    now = "2026-10-03T00:00:00"
    db._conn.execute("INSERT INTO MapNote VALUES (?,?,?,?,?,?,?,?)", (HASH, 1, 2, 3, 4, "宝箱", now, now))
    db._conn.execute("INSERT INTO MapLandmark(rom_hash,map_id,map_ptr,x,y,kind,label,created_at,updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?,?)", (HASH, 1, 2, 5, 6, "stairs", "下り", now, now))
    db._conn.execute("PRAGMA user_version = 0")       # ★旧版の DB は 0
    db._conn.commit()
    db.close()
    for f in ("-wal", "-shm"):
        (work / f"retroux.sqlite3{f}").unlink(missing_ok=True)
    _w(work / "encountered.txt", "1\n2\n")
    _w(work / "caution.txt", "2\n")
    _w(work / "generated" / "tile_art.txt", "観測\n")
    _w(work / "generated" / "config.lua", "-- 古い版")
    _w(work / "generated" / "dq3_ai.lua", "-- DQ3")
    _w(work / "tactics" / "profiles" / "mine.yaml", "name: mine\n")
    _w(work / "tactics" / "active.txt", "mine\n")
    _w(work / "window-state.json", "{}")
    _w(work / "map-assets" / "tiles" / "a.png")
    _w(work / "monster-art" / "slime.png")
    _w(work / "playdata-archive" / "20260820" / "events.jsonl")
    _w(work / "playdata-archive" / "20260820" / "seen-1.json")
    _w(work / "playdata-archive" / "20260820" / "dq3-progress.json")
    for name in ("state.json", "command.json", "gamepad_input.txt", "retroux.log",
                 "event_ingestor.lock", "savestate_backup.status.json", "dq3-window-state.json"):
        _w(work / name)
    _w(work / "dq3-knowledge" / "book.json")
    _w(work / "research" / "note.txt")
    _w(work / "unknown-thing.txt")
    _w(work / "savestate-backup" / "DQ2_J.fc1" / "gen1.bak")
    _w(work / "savestate-backup" / "DQ3_J.fc0" / "gen1.bak")
    _w(work / "savestate-backup" / "MOTHER.fc0" / "gen1.bak")     # ★DQ3 でもない別の ROM（stem で落とす）
    _w(work / "rom" / "DQ2_J.nes", b"NES\x1a" + b"\0" * 12 + b"fake")
    fceux = src / "tools" / "fceux"
    for name in ("fceux64.exe", "lua5.1.dll", "fceux.cfg", "fcs/DQ2_J.fc1", "fcs/DQ2_J-bak.fc1",
                 "fcs/DQ3_J.fc0", "fcs/MOTHER.fc0", "sav/DQ2_J.sav", "sav/DQ3_J.sav"):
        _w(fceux / name)
    return src


def snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns,
                                                    hashlib.sha256(p.read_bytes()).hexdigest())
    return out


@pytest.fixture
def legacy(tmp_path) -> Path:
    return make_legacy(tmp_path / "old RetroUX")


@pytest.fixture
def dest(tmp_path) -> Path:
    d = tmp_path / "新しい DQ2"
    d.mkdir()
    return d


def _quiet(*_a, **_k):
    return None


def run(src, dst, **kw) -> R.Result:
    return migrate(src, dst, Options(**kw), out=_quiet)


def tables(db: Path) -> dict:
    con = sqlite3.connect(db)
    try:
        return M._tables(con)
    finally:
        con.close()


# --- 正常 -------------------------------------------------------------------

def test_schema0から1へ(legacy, dest) -> None:
    assert D.detect(M.source_places(legacy)).kind == D.SCHEMA0
    got = run(legacy, dest)
    assert got.status == "migrated"
    marker = D.read_marker(dest)
    assert marker["product"] == "retroux-dq2" and marker["schema"] == 1
    assert marker["history"][0]["event"] == "migrated" and marker["history"][0]["from_schema"] == 0
    assert D.detect(R.dest_places(dest)).kind == D.CURRENT
    assert not (dest / "work" / "dq2-migration" / "staging").exists() or \
        not any((dest / "work" / "dq2-migration" / "staging").iterdir())


def test_旧フォルダは1バイトも変わらない(legacy, dest) -> None:
    before = snapshot(legacy)
    run(legacy, dest, include=frozenset({"monster-art", "playdata-archive", "backups", "events-archive"}))
    assert snapshot(legacy) == before


def test_DBの件数とメモが残る(legacy, dest) -> None:
    before = tables(legacy / "work" / "retroux.sqlite3")
    run(legacy, dest)
    after = tables(dest / "work" / "retroux.sqlite3")
    assert after == before
    assert after["BattleLog"] == 2 and after["MapNote"] == 1 and after["MapLandmark"] == 1
    con = sqlite3.connect(dest / "work" / "retroux.sqlite3")
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def test_eventsはそのまま(legacy, dest) -> None:
    run(legacy, dest)
    assert (dest / "work" / "events.jsonl").read_bytes() == (legacy / "work" / "events.jsonl").read_bytes()


def test_IngestStateが論理IDになり二重に取り込まない(legacy, dest) -> None:
    """★★ 依頼 §9-2 の必須 ★★ 移したあと Recorder を作っても、過去の戦闘を取り込み直さない。

    ★鍵は論理 ID `dq2:events:main`（RX-0163）。⚠ 移行先の絶対パスへ書き換えない（★動かすと取り込み直すので）。
    """
    from retroux.core.recorder import MAIN_STREAM

    run(legacy, dest)
    db = Database(dest / "work" / "retroux.sqlite3")
    try:
        events = dest / "work" / "events.jsonl"
        row = db._conn.execute("SELECT source, offset, tail_sig, path FROM IngestState").fetchall()
        assert [r[0] for r in row] == [MAIN_STREAM]
        assert row[0][1] == events.stat().st_size
        assert row[0][2], "取り込み済みの末尾の署名が無い"
        assert row[0][3] == str(events.resolve())          # ★診断用（鍵ではない）
        before = db._conn.execute("SELECT COUNT(*) FROM BattleLog").fetchone()[0]
        rec = Recorder(db, HASH, events, dest / "work" / "command.json", stream=MAIN_STREAM)
        assert rec.hold is None and rec.poll() == 0
        assert db._conn.execute("SELECT COUNT(*) FROM BattleLog").fetchone()[0] == before
        # ★移したあとに足された行だけは取り込む（★位置を進めすぎていない）
        with events.open("a", encoding="utf-8") as fh:
            fh.write(EVENTS[0] + "\n" + EVENTS[1] + "\n")
        assert Recorder(db, HASH, events, dest / "work" / "command.json", stream=MAIN_STREAM).poll() == 2
        assert db._conn.execute("SELECT COUNT(*) FROM BattleLog").fetchone()[0] == before + 1
    finally:
        db.close()


def test_設定はDQ2の置き場へ変換される(legacy, dest) -> None:
    run(legacy, dest)
    assert (dest / "work" / "dq2-settings" / "mantan.yaml").read_bytes() == \
        (legacy / "config" / "mantan.yaml").read_bytes()
    import yaml

    cfg = yaml.safe_load((dest / "dq2_user_config.yaml").read_bytes().decode("utf-8"))
    assert "fceux" not in cfg["paths"] and "dq3_rom" not in cfg["paths"] and "log" not in cfg["paths"]
    assert cfg["gui"]["font_size"] == 13
    assert not (dest / "user_config.yaml").exists()
    assert not (dest / "config").exists()


def test_DQ2のセーブだけ移る(legacy, dest) -> None:
    run(legacy, dest)
    fcs = sorted(p.name for p in (dest / "tools" / "fceux" / "fcs").iterdir())
    assert fcs == ["DQ2_J-bak.fc1", "DQ2_J.fc1"]
    assert sorted(p.name for p in (dest / "tools" / "fceux" / "sav").iterdir()) == ["DQ2_J.sav"]
    backup = dest / "work" / "runtime" / "dq2-backup" / "savestate-backup"
    assert (backup / "DQ2_J.fc1" / "gen1.bak").exists()
    assert not (backup / "DQ3_J.fc0").exists()
    assert not (backup / "MOTHER.fc0").exists()
    assert not (dest / "work" / "savestate-backup").exists()
    # ★FCEUX 本体は既定で写す（RX-0167）。⚠ fceux.cfg は環境依存なので写さない
    for name in ("fceux64.exe", "lua5.1.dll"):
        assert (dest / "tools" / "fceux" / name).exists(), name
    assert not (dest / "tools" / "fceux" / "fceux.cfg").exists()


def test_FCEUX本体は外せる(legacy, dest) -> None:
    got = run(legacy, dest, exclude=frozenset({"fceux"}))
    assert not (dest / "tools" / "fceux" / "fceux64.exe").exists()
    assert (dest / "tools" / "fceux" / "fcs" / "DQ2_J.fc1").exists(), "★セーブは別（外さない）"
    assert not got.report.get("fceux_files")


def test_移行先にFCEUXがあれば上書きしない(legacy, dest) -> None:
    _w(dest / "tools" / "fceux" / "fceux64.exe", b"MINE")
    got = run(legacy, dest)
    assert (dest / "tools" / "fceux" / "fceux64.exe").read_bytes() == b"MINE"
    assert not (dest / "tools" / "fceux" / "lua5.1.dll").exists()
    assert got.report["fceux_kept"] == "fceux64.exe"
    assert any("既にある" in n for n in got.notes)


def test_DQ3のものは移らない(legacy, dest) -> None:
    run(legacy, dest, include=frozenset({"playdata-archive"}))
    names = [p.relative_to(dest).as_posix() for p in dest.rglob("*")]
    assert not [n for n in names if "dq3" in n.lower() or "DQ3" in n], names
    assert not (dest / "work" / "playdata-archive" / "20260820" / "seen-1.json").exists()
    assert (dest / "work" / "playdata-archive" / "20260820" / "events.jsonl").exists()


def test_観測と人のデータは移り作り直すものと実行時のものは移らない(legacy, dest) -> None:
    got = run(legacy, dest)
    work = dest / "work"
    for rel in ("generated/tile_art.txt", "encountered.txt", "caution.txt", "tactics/profiles/mine.yaml",
                "tactics/active.txt", "window-state.json"):
        assert (work / rel).exists(), rel
    for rel in ("generated/config.lua", "state.json", "command.json", "gamepad_input.txt", "retroux.log",
                "event_ingestor.lock", "savestate_backup.status.json", "research/note.txt",
                "monster-art/slime.png", "unknown-thing.txt"):
        assert not (work / rel).exists(), rel
    assert "work/unknown-thing.txt" in got.report["unclassified"]


def test_ROMは既定で移らない(legacy, dest) -> None:
    run(legacy, dest)
    assert not (dest / "work" / "rom").exists()


def test_ROMを選んでも照合に通らなければ止まり本番は変わらない(legacy, dest) -> None:
    """★偽の ROM（PRG の SHA が DQ2 と違う）。"""
    with pytest.raises(MigrationStop, match="ROM の照合"):
        run(legacy, dest, include=frozenset({"rom"}))
    assert D.read_marker(dest) is None
    assert not (dest / "work" / "retroux.sqlite3").exists()
    assert D.detect(R.dest_places(dest)).kind == D.NEW


def _real_rom() -> Path | None:
    for base in (ROOT, Path(os.environ.get("RETROUX_ROOT", ROOT))):
        p = base / "work" / "rom" / "DQ2_J.nes"
        if p.exists():
            return p
    return None


def test_ROMを選ぶと同じ名前で移る(legacy, dest) -> None:
    real = _real_rom()
    if real is None:
        pytest.skip("★ROM がありません")
    (legacy / "work" / "rom" / "DQ2_J.nes").write_bytes(real.read_bytes())
    got = run(legacy, dest, include=frozenset({"rom"}))
    assert (dest / "work" / "rom" / "DQ2_J.nes").read_bytes() == real.read_bytes()
    assert got.report["rom"]["prg_sha256"] == HASH


def test_map_assetsは既定で移り外せる(legacy, dest, tmp_path) -> None:
    run(legacy, dest)
    assert (dest / "work" / "map-assets" / "tiles" / "a.png").exists()
    other = tmp_path / "外した"
    other.mkdir()
    run(legacy, other, exclude=frozenset({"map-assets"}))
    assert not (other / "work" / "map-assets").exists()


def test_WALにだけある記録も移る(legacy, dest, tmp_path) -> None:
    """★★ 単純コピーを禁止した理由（依頼 §9-1）★★ 本体のファイルだけ写すと、WAL の中の記録が消える。"""
    work_db = tmp_path / "live" / "retroux.sqlite3"
    work_db.parent.mkdir()
    (work_db).write_bytes((legacy / "work" / "retroux.sqlite3").read_bytes())
    con = sqlite3.connect(work_db)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA wal_autocheckpoint = 0")
    con.execute("INSERT INTO MapNote VALUES (?,?,?,?,?,?,?,?)",
                (HASH, 9, 9, 9, 9, "WAL にだけある", "t", "t"))
    con.commit()
    try:
        for suffix in ("", "-wal", "-shm"):      # ★落ちた直後の形（WAL に未反映の記録が残っている）
            src = Path(str(work_db) + suffix)
            (legacy / "work" / ("retroux.sqlite3" + suffix)).write_bytes(src.read_bytes())
    finally:
        con.close()
    assert (legacy / "work" / "retroux.sqlite3-wal").stat().st_size > 0
    before = snapshot(legacy)
    run(legacy, dest)
    assert snapshot(legacy) == before, "⚠ WAL のある旧の DB を直接開いた（-shm が変わる）"
    con = sqlite3.connect(dest / "work" / "retroux.sqlite3")
    try:
        bodies = [r[0] for r in con.execute("SELECT body FROM MapNote")]
    finally:
        con.close()
    assert "WAL にだけある" in bodies, bodies


def test_写したDBの行数が元と違えば止まる(legacy, dest, monkeypatch) -> None:
    real = M.handle_db

    def lossy(ctx, src_db):
        real(ctx, src_db)
        con = sqlite3.connect(ctx.staging / "work" / "retroux.sqlite3")
        con.execute("DELETE FROM MapNote")
        con.commit()
        con.close()

    monkeypatch.setattr(M, "handle_db", lossy)
    with pytest.raises(MigrationStop, match="MapNote の行数"):
        run(legacy, dest)
    _assert_untouched(dest)


def test_移行先に同じ名前のファイルがあれば入れる前に止まる(legacy, dest) -> None:
    _w(dest / "work" / "window-state.json", '{"mine": 1}')
    with pytest.raises(MigrationStop, match="同じ名前"):
        run(legacy, dest)
    assert (dest / "work" / "window-state.json").read_text(encoding="utf-8") == '{"mine": 1}'
    assert D.read_marker(dest) is None
    assert not (dest / "work" / "retroux.sqlite3").exists()


# --- 再実行 -----------------------------------------------------------------

def test_2回目は何もしない(legacy, dest) -> None:
    run(legacy, dest)
    before = snapshot(dest)
    got = run(legacy, dest)
    assert got.status == "noop"
    after = snapshot(dest)
    journal = "work/dq2-migration/journal.jsonl"
    assert {k: v for k, v in after.items() if k != journal} == {k: v for k, v in before.items() if k != journal}
    assert tables(dest / "work" / "retroux.sqlite3")["BattleLog"] == 2


# --- 異常 -------------------------------------------------------------------

def _assert_untouched(dest: Path) -> None:
    assert D.read_marker(dest) is None
    assert not (dest / "work" / "retroux.sqlite3").exists()
    assert not (dest / "work" / "events.jsonl").exists()
    assert D.detect(R.dest_places(dest)).kind == D.NEW, "⚠ 止めたのに本番が途中の状態"


def _break_whole(raw: bytearray) -> bytearray:
    return bytearray(b"garbage!" * (len(raw) // 8))


def _break_page(raw: bytearray) -> bytearray:
    """★途中のページの中身だけ壊す（★ヘッダは無事 = 開けるが integrity_check が落ちる）。"""
    page = int.from_bytes(raw[16:18], "big") or 65536
    for start in range(page * 2, len(raw), page):
        raw[start:start + page] = b"\xa5" * page
    return raw


@pytest.mark.parametrize("breaker", [_break_whole, _break_page], ids=["全体", "途中のページ"])
def test_DBが壊れていれば止まる(legacy, dest, breaker) -> None:
    db = legacy / "work" / "retroux.sqlite3"
    db.write_bytes(bytes(breaker(bytearray(db.read_bytes()))))
    with pytest.raises(MigrationStop, match="DB"):
        run(legacy, dest)
    _assert_untouched(dest)


def test_eventsが足りなければ止まる(legacy, dest) -> None:
    ev = legacy / "work" / "events.jsonl"
    ev.write_bytes(ev.read_bytes()[: len(EVENTS[0]) + 1])
    with pytest.raises(MigrationStop, match="events 不足"):
        run(legacy, dest)
    _assert_untouched(dest)


def test_取り込み位置が別のファイルなら止まる(legacy, dest) -> None:
    """★events.jsonl が作り直されていた（先頭の署名が違う）。"""
    ev = legacy / "work" / "events.jsonl"
    ev.write_bytes(('{"type":"session_start","frame":1}\n' * 30).encode("utf-8"))
    with pytest.raises(MigrationStop, match="署名"):
        run(legacy, dest)
    _assert_untouched(dest)


def test_知らないschemaは止まる(legacy, dest) -> None:
    D.write_marker(dest, {"product": "retroux-dq2", "schema": 99, "created_by": "未来", "history": []})
    assert D.detect(R.dest_places(dest)).kind == D.UNKNOWN
    with pytest.raises(MigrationStop):
        run(legacy, dest)
    assert D.gate(R.dest_places(dest), out=_quiet) == 2


def test_stagingの途中なら止まり明示すればやり直す(legacy, dest) -> None:
    j = R.Journal(dest)
    j.write("20261003-000000-000000", "staging", source=str(legacy))
    _w(dest / D.MIGRATION_DIR_REL / "staging" / "20261003-000000-000000" / "work" / "half.txt")
    assert D.detect(R.dest_places(dest)).kind == D.INCOMPLETE
    assert D.gate(R.dest_places(dest), out=_quiet) == 2
    with pytest.raises(MigrationStop, match="--discard-staging"):
        run(legacy, dest)
    got = run(legacy, dest, discard_staging=True)
    assert got.status == "migrated"
    assert not (dest / "work" / "half.txt").exists()


def test_本番へ入れる途中で落ちたら止まり続きから終える(legacy, dest, monkeypatch) -> None:
    real = R._commit

    def half(staging, dst, files, replaced=(), run=""):
        first = files[: len(files) // 2]
        for rel in first:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / rel, dst / rel)
        raise KeyboardInterrupt("電源が落ちた")

    monkeypatch.setattr(R, "_commit", half)
    with pytest.raises(KeyboardInterrupt):
        run(legacy, dest)
    monkeypatch.setattr(R, "_commit", real)
    assert D.detect(R.dest_places(dest)).kind == D.INCOMPLETE
    with pytest.raises(MigrationStop, match="--resume"):
        run(legacy, dest)
    got = run(legacy, dest, resume=True)
    assert got.status == "migrated"
    assert tables(dest / "work" / "retroux.sqlite3")["BattleLog"] == 2
    assert (dest / "tools" / "fceux" / "fcs" / "DQ2_J.fc1").exists()
    assert D.detect(R.dest_places(dest)).kind == D.CURRENT


def test_移行先に遊んだデータがあれば止まる(legacy, dest) -> None:
    _w(dest / "work" / "events.jsonl", EVENTS[0] + "\n")
    with pytest.raises(MigrationStop, match="上書きしません"):
        run(legacy, dest)
    assert (dest / "work" / "events.jsonl").read_text(encoding="utf-8") == EVENTS[0] + "\n"


def test_移行元がDQ3なら止まる(legacy, dest) -> None:
    _w(legacy / "build-info.json", json.dumps({"product": "retroux-dq3"}))
    with pytest.raises(MigrationStop, match="retroux-dq3"):
        run(legacy, dest)
    _assert_untouched(dest)


def test_DQ2のフォルダでなければ止まる(tmp_path, dest) -> None:
    other = tmp_path / "空"
    _w(other / "work" / "events.jsonl", EVENTS[0] + "\n")
    with pytest.raises(MigrationStop, match="DQ2 のフォルダに見えません"):
        run(other, dest)


def test_作り直しが失敗したら印を書かず起動もさせない(legacy, dest) -> None:
    with pytest.raises(MigrationStop, match="作り直し"):
        run(legacy, dest, regenerate=lambda d: ["generate_lua が終了コード 1"])
    assert D.read_marker(dest) is None
    assert D.detect(R.dest_places(dest)).kind == D.INCOMPLETE
    assert D.gate(R.dest_places(dest), out=_quiet) == 2
    got = run(legacy, dest, resume=True, regenerate=lambda d: [])
    assert got.status == "migrated" and D.read_marker(dest)["history"][0]["regenerated"] is True


def test_移行元と移行先が重なれば止まる(legacy) -> None:
    with pytest.raises(MigrationStop, match="重なって"):
        run(legacy, legacy / "work" / "new")
