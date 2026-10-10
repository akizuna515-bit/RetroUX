"""DQ2 のデータの持ち主と分類（RX-0156 / D-44）。

★表（`retroux/core/dq2_ownership.py`）が**コードの書き先を全部**覆っていることを、コードから採って確かめる。
⚠ 表だけ見て「全部ある」と言うと、足し忘れた書き先が素通りする（★見張る対象の足し忘れ / RX3-0280 の型）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from retroux.core import dq2_ownership as O

ROOT = Path(__file__).resolve().parents[1]

_Q = r"""["']"""
_LITERAL = re.compile(_Q + r"/?(work/[A-Za-z0-9_\-./]+)" + _Q)
_JOIN = re.compile(r"""/\s*["']work["']((?:\s*/\s*["'][A-Za-z0-9_\-.]+["'])+)""")
_CALL = re.compile(r"""\b(work|program_work|generated|setting)\(((?:\s*["'][A-Za-z0-9_\-.]+["']\s*,?)+)\)""")
_PART = re.compile(r"""["']([A-Za-z0-9_\-.]+)["']""")
_CALL_PREFIX = {"work": "work/", "program_work": "work/", "generated": "work/generated/",
                "setting": "work/dq2-settings/"}


def code_work_paths() -> dict[str, list[str]]:
    """★`retroux/` の .py / .lua / .yaml から `work/...` の場所を採る（★コメント行は除く）。"""
    found: dict[str, list[str]] = {}
    for path in sorted((ROOT / "retroux").rglob("*")):
        if path.suffix not in (".py", ".lua", ".yaml"):
            continue
        text = path.read_bytes().decode("utf-8")
        for no, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith(("#", "--")):
                continue
            hits = [m.group(1) for m in _LITERAL.finditer(line)]
            hits += ["work/" + "/".join(_PART.findall(m.group(1))) for m in _JOIN.finditer(line)]
            hits += [_CALL_PREFIX[m.group(1)] + "/".join(_PART.findall(m.group(2)))
                     for m in _CALL.finditer(line)]
            for hit in hits:
                found.setdefault(hit.rstrip("/"), []).append(
                    f"{path.relative_to(ROOT).as_posix()}:{no}")
    return found


def test_採る仕組みが既知の書き先を拾えている() -> None:
    """⚠ 採る側が壊れて 0 件になると、下の検査は何も見ずに緑になる。"""
    got = code_work_paths()
    for must in ("work/caution.txt", "work/generated/tile_art.txt", "work/events.jsonl",
                 "work/dq2-settings/mantan.yaml", "work/tactics/profiles",
                 "work/runtime/dq2-log/retroux.log"):
        assert must in got, must
    assert len(got) >= 30


def test_コードの書き先はすべて表に載っている() -> None:
    missing = {p: sites for p, sites in code_work_paths().items()
               if p != "work/..." and not O.is_dq3(p) and O.classify(p) is None}
    assert not missing, ("★dq2_ownership.TABLE に行を足してください: "
                         + "; ".join(f"{p} ({s[0]})" for p, s in sorted(missing.items())))


def test_間接に決まる書き先も表に載っている() -> None:
    """★名前を組み立てて書く所（★上の正規表現では採れない）。"""
    from retroux.core import backup_status, enemy_tables
    from retroux.tools import dq2_savestate_backup as B
    from retroux.tools import playdata

    paths = ["work/" + name for name in playdata.PLAY_FILES]
    paths += ["work/" + name for name in playdata.DERIVED_DIRS]
    # ⚠ NEVER_TOUCH は名前の前方一致（`savestate_backup` は .lock / .status.json の頭）なので、置き場の名前だけ
    paths += ["work/" + name for name in playdata.NEVER_TOUCH
              if name not in ("evidence", "dq2-disasm", "savestate_backup")]
    paths += ["work/savestate_backup.lock", "work/savestate_backup.status.json",
              "work/tactics/active.txt", "work/tactics/profiles/balanced.yaml"]
    paths += ["work/generated/" + enemy_tables.CACHE_NAME,
              "work/" + backup_status.STATUS_NAME,
              "work/" + "/".join(B.HOME_PARTS) + "/savestate_backup.lock",
              "work/" + "/".join(B.HOME_PARTS) + "/savestate-backup/DQ2_J.fc0"]
    missing = [p for p in paths if O.classify(p) is None]
    assert not missing, missing


@pytest.mark.parametrize("path, kind", [
    ("work/generated/tile_art.txt", O.OBSERVED_DATA),    # ⚠⚠ generated の名前を信じない
    ("work/generated/config.lua", O.DERIVED_DATA),
    ("work/generated/enemy_tables.json", O.DERIVED_DATA),
    ("work/retroux.sqlite3", O.OBSERVED_DATA),           # ⚠ DQ3 の ownership は derived と数える（RX3-0506）
    ("work/retroux.sqlite3-wal", O.OBSERVED_DATA),
    ("work/encountered.txt", O.OBSERVED_DATA),
    ("work/dq2-settings/keybindings.yaml", O.USER_DATA),
    ("config/mantan.yaml", O.USER_DATA),
    ("work/runtime/dq2-backup/savestate-backup/DQ2_J.fc0/x", O.USER_DATA),
    ("work/runtime/dq2-backup/savestate_backup.lock", O.RUNTIME),
    ("work/state.json", O.RUNTIME),
    ("work/runtime/dq2-log/retroux.log", O.RUNTIME),
    ("work/map-capture/a.png", O.DEVELOPMENT_ONLY),
])
def test_紛らわしいものの分類(path: str, kind: str) -> None:
    got = O.classify(path)
    assert got is not None and got.kind == kind, (path, got)


def test_移行の既定は依頼どおり() -> None:
    """★依頼 §13: ROM は既定 OFF / map-assets は既定 ON / 旧ログは写さない / FCEUX の cfg は写さない。"""
    rom = O.classify("work/rom/DQ2_J.nes")
    assert rom.carry == "optional" and rom.default_on is False
    assets = O.classify("work/map-assets/a.png")
    assert assets.carry == "optional" and assets.default_on is True
    assert O.classify("work/retroux.log").carry == "skip"
    assert O.classify("work/runtime/dq2-log/retroux.log").carry == "skip"
    assert O.classify("fceux.cfg", root="fceux").carry == "skip"
    assert O.classify("fcs/DQ2_J.fc0", root="fceux").carry == "migrate"


def test_表の値は決めた語彙だけ() -> None:
    for e in O.TABLE:
        assert e.kind in O.KINDS, e
        assert e.carry in O.CARRIES, e
        assert e.root in O.ROOTS, e
        assert e.note, e
        assert not (e.default_on and e.carry != "optional"), e


def test_作り直せないものは写す() -> None:
    """⚠ 人のデータと遊んだ記録を「作り直す」「写さない」に入れると、移行で黙って失われる。"""
    for e in O.entries(kind=O.USER_DATA) + O.entries(kind=O.OBSERVED_DATA):
        assert e.carry in ("migrate", "convert", "optional"), e


def test_DQ3のものは表の外() -> None:
    assert O.is_dq3("work/generated/dq3_memory_map.lua")
    assert O.is_dq3("work/runtime/dq3-log/x.log")
    assert not O.is_dq3("work/generated/config.lua")
