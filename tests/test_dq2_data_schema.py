"""DQ2 のデータの版（RX-0157 / D-45 / 依頼 §5・§6）。

★印 `work/dq2-data.json` が正本。DB の `PRAGMA user_version` は補助（0 = 記録なし）。
⚠ 食い違い・知らない版・途中の移行では止める（★どちらにも合わせない / 勝手に最新版扱いしない）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from retroux.core import dq2_data as D
from retroux.core import dq2_ownership as O
from retroux.core.db.database import Database
from retroux.migration import m0001_legacy_to_portable as M
from retroux.migration import runner as R

ROOT = Path(__file__).resolve().parents[1]


def places(root: Path) -> D.Places:
    return R.dest_places(root)


def _db(root: Path, *, dq2: bool = True, user_version: int | None = None) -> Path:
    path = root / "work" / "retroux.sqlite3"
    db = Database(path)
    if dq2:
        db.register_rom(D.DQ2_PRG_SHA256, "ドラゴンクエストII 悪霊の神々", "JP", 2)
    if user_version is not None:
        db._conn.execute(f"PRAGMA user_version = {user_version}")
        db._conn.commit()
    db.close()
    return path


def _quiet(*_a, **_k):
    return None


def test_印の形(tmp_path) -> None:
    D.write_marker(tmp_path, D.new_marker(1, "RetroUX 9.9", "created"))
    data = json.loads((tmp_path / "work" / "dq2-data.json").read_bytes().decode("utf-8"))
    assert set(data) == {"product", "schema", "created_by", "history"}
    assert data["product"] == "retroux-dq2" and data["schema"] == 1 and data["created_by"] == "RetroUX 9.9"
    assert data["history"][0]["event"] == "created"


def test_新規は印を書いて始める(tmp_path) -> None:
    assert D.detect(places(tmp_path)).kind == D.NEW
    assert D.gate(places(tmp_path), out=_quiet) == 0
    assert D.read_marker(tmp_path)["schema"] == D.CURRENT_SCHEMA
    assert D.detect(places(tmp_path)).kind == D.CURRENT


@pytest.mark.parametrize("what", ["db", "events", "savestate"])
def test_印が無く遊んだデータがあればschema0で何も書かない(tmp_path, what) -> None:
    if what == "db":
        _db(tmp_path, user_version=0)
    elif what == "events":
        (tmp_path / "work").mkdir()
        (tmp_path / "work" / "events.jsonl").write_bytes(b'{"type":"session_start"}\n')
    else:
        (tmp_path / "tools" / "fceux" / "fcs").mkdir(parents=True)
        (tmp_path / "tools" / "fceux" / "fcs" / "DQ2_J.fc1").write_bytes(b"x")
    got = D.detect(places(tmp_path))
    assert got.kind == D.SCHEMA0 and got.schema == 0 and got.evidence
    assert D.gate(places(tmp_path), out=_quiet) == 0
    assert D.read_marker(tmp_path) is None, "⚠ 旧版のデータに勝手に印を書いた"


def test_DQ3だけのデータは遊んだデータに数えない(tmp_path) -> None:
    (tmp_path / "tools" / "fceux" / "fcs").mkdir(parents=True)
    (tmp_path / "tools" / "fceux" / "fcs" / "DQ3_J.fc1").write_bytes(b"x")
    _db(tmp_path, dq2=False)
    assert D.detect(places(tmp_path)).kind == D.NEW


def test_知らない版は止める(tmp_path) -> None:
    D.write_marker(tmp_path, {"product": "retroux-dq2", "schema": 2, "created_by": "未来", "history": []})
    got = D.detect(places(tmp_path))
    assert got.kind == D.UNKNOWN and got.stop
    assert D.gate(places(tmp_path), out=_quiet) == 2


@pytest.mark.parametrize("body", [b"{", b"[]", json.dumps({"product": "retroux-dq3", "schema": 1}).encode(),
                                  json.dumps({"product": "retroux-dq2", "schema": "1"}).encode()],
                         ids=["壊れたJSON", "配列", "別の製品", "文字列の版"])
def test_読めない印は止める(tmp_path, body) -> None:
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "dq2-data.json").write_bytes(body)
    assert D.detect(places(tmp_path)).kind == D.BROKEN
    assert D.gate(places(tmp_path), out=_quiet) == 2


def test_印とDBの版が食い違えば止めてどちらも変えない(tmp_path) -> None:
    D.write_marker(tmp_path, D.new_marker(1, "x", "created"))
    db = _db(tmp_path, user_version=0)       # ★旧版の DB を置いた
    before = (tmp_path / "work" / "dq2-data.json").read_bytes(), db.read_bytes()
    got = D.detect(places(tmp_path))
    assert got.kind == D.MISMATCH and "user_version" in got.describe()
    assert D.gate(places(tmp_path), out=_quiet) == 2
    assert ((tmp_path / "work" / "dq2-data.json").read_bytes(), db.read_bytes()) == before


def test_印が無いのにDBが新しすぎれば止める(tmp_path) -> None:
    _db(tmp_path, user_version=D.CURRENT_SCHEMA + 1)
    assert D.detect(places(tmp_path)).kind == D.UNKNOWN


def test_新しいDBは今の版を記録し旧いDBは上げない(tmp_path) -> None:
    fresh = _db(tmp_path / "a")
    assert D.db_user_version(fresh) == Database.DATA_SCHEMA == D.CURRENT_SCHEMA
    old = _db(tmp_path / "b", user_version=0)
    Database(old).close()
    assert D.db_user_version(old) == 0


def test_判定は旧のDBに何も作らない(tmp_path) -> None:
    """⚠ WAL の DB は mode=ro でも -wal / -shm を作る（★実測）。"""
    db = _db(tmp_path, user_version=0)
    for f in ("-wal", "-shm"):
        Path(str(db) + f).unlink(missing_ok=True)
    D.detect(places(tmp_path))
    assert not Path(str(db) + "-wal").exists() and not Path(str(db) + "-shm").exists()


def test_起動前の判定をファイルで受け取れる(tmp_path, monkeypatch) -> None:
    D.write_marker(tmp_path, {"product": "retroux-dq2", "schema": 7, "created_by": "x", "history": []})
    monkeypatch.setattr(D, "current_places", lambda cfg=None: places(tmp_path))
    out = tmp_path / "gate.txt"
    assert D.main(["--gate", "--out", str(out)]) == 2
    lines = out.read_bytes().decode("utf-8").splitlines()
    assert lines[0] == "STOP" and any("schema 7" in line for line in lines)


def test_起動スクリプトは判定に通らなければFCEUXもGUIも起こさない() -> None:
    text = (ROOT / "scripts" / "start-dq2.ps1").read_bytes().decode("utf-8-sig")
    gate = text.index("retroux.core.dq2_data")
    for later in ("retroux.core.config.generate_lua", '"retroux.gui"', "Start-Dq2Emulator @startArgs",
                  '"retroux.tools.dq2_savestate_backup",'):
        assert gate < text.index(later), later
    block = text[gate:text.index("# --- 2. YAML -> Lua")]
    assert 'Trim() -ne "OK"' in block and "Stop-Launcher" in block


def test_DQ2のROMの値はmemory_mapと同じ() -> None:
    mm = yaml.safe_load((ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml").read_bytes().decode("utf-8"))
    assert mm["rom"]["prg_sha256"].upper() == D.DQ2_PRG_SHA256
    assert D.DQ2_TITLE_WORD in mm["rom"]["title"]


# --- ownership との連携（依頼 §8）---------------------------------------------

def test_移行の方針はownershipから決まる() -> None:
    assert O.policy_of("work/generated/tile_art.txt") == O.MIGRATE
    assert O.policy_of("work/generated/config.lua") == O.REGENERATE
    assert O.policy_of("work/rom/DQ2_J.nes") == O.OPTIONAL
    assert O.policy_of("config/mantan.yaml", "program") == O.CONVERT
    assert O.policy_of("work/retroux.log") == O.DO_NOT_MIGRATE
    assert O.policy_of("work/dq3-knowledge/a.json") == O.DO_NOT_MIGRATE
    assert O.policy_of("work/runtime/dq2-backup/savestate-backup/DQ2_J.fc1/g.bak") == O.MIGRATE
    assert set(O.POLICY_OF_CARRY) == set(O.CARRIES)


def test_変換が要る行には専用処理がある() -> None:
    patterns = {e.pattern for e in O.TABLE}
    for e in O.entries(carry="convert"):
        assert e.pattern in M.HANDLERS, e.pattern
    stale = [p for p in M.HANDLERS if p not in patterns]
    assert not stale, f"⚠ 表に無い行の専用処理（表を変えたのに追いついていない）: {stale}"


def test_選べるものはownershipのoptionalから() -> None:
    keys = M.optional_keys()
    assert keys == {M.optional_key(e): e.default_on for e in O.entries(carry="optional")}
    assert keys["map-assets"] is True and keys["rom"] is False
    assert {"monster-art", "playdata-archive", "backups", "events-archive"} <= set(keys)


def test_stepは番号順に鎖になる() -> None:
    chain = R.plan(0, D.CURRENT_SCHEMA)
    assert [s.id for s in chain] == ["0001_legacy_to_portable"]
    for s in chain:
        assert callable(s.precheck) and callable(s.apply) and callable(s.postcheck)
    with pytest.raises(R.MigrationStop):
        R.plan(0, 5)
