"""地図の一括変換が全件を扱えていること（チェックリスト §7）。

## ★ 実測（2026-08-19）

    PYTHONUTF8=1 python -m retroux.tools.dq2_map_batch
    → ★描けた 108 / ▲一部 0 / ⚠ 失敗 1

⚠ 「失敗 1」は **`$01`（世界地図）**。★これは**設計どおり**:

    ⚠ map $01 は種別0です。★いまの手順は街・ダンジョン（種別1以上）
      だけに使えます。世界地図は行ポインタ＋ランレングスで別経路です

★世界地図は `dq2_world_map.py` / `core/bgmap/world_map.py` が扱い、
**65536/65536** を展開できています（README「現在の状態」）。

## ⚠⚠ なぜ検査するか

★「108 / 1」という数字を**記録に残さない**と、
⚠ あとで 105/4 になっても「前からそうだった」と読まれる。

⚠ 一括変換そのものは1分以上かかるので、ここでは**回さない**。
★代わりに「どの map_id がどちらの経路か」を固定する
（⚠ 経路の割り当てが変われば、変換の結果も変わる）。
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ROM_PATH = pathlib.Path(
    os.environ.get("DQ2_ROM_PATH") or "work/rom/DQ2_J.nes")
needs_rom = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"ROM がありません（{ROM_PATH}）")

#: ★実測（2026-08-19 / `python -m retroux.tools.dq2_map_batch`）
DREW = 108
FAILED = 1
#: ★map_id の範囲。⚠ `$6D` は**ヘッダ表の外**（実測で判明）
FIRST_MAP = 0x00        # ⚠ $00 も有効（実測）
LAST_MAP = 0x6C


@needs_rom
def test_世界地図だけが別経路である():
    """★★ ⚠⚠ **「失敗 1」の中身を固定する** ★★

    ⚠ 数を書くだけでは足りない。★**どの map_id か**まで押さえる。
    """
    from retroux.core.bgmap.map_master import map_kind
    from retroux.core.bgmap.world_art import WORLD_MAP_ID

    other = [mid for mid in range(FIRST_MAP, LAST_MAP + 1)
             if map_kind(mid) == 0]
    assert other == [WORLD_MAP_ID], (
        f"⚠ 種別0（別経路）が {[hex(m) for m in other]}"
        f"（★世界地図 {hex(WORLD_MAP_ID)} だけであるべき）")


@needs_rom
def test_街とダンジョンは全部同じ経路で読める():
    """⚠ 1つでも読めなくなったら気づくこと。"""
    from dq2rom import ines
    from retroux.core.bgmap import adapter
    from retroux.core.bgmap.map_master import map_kind
    from retroux.core.bgmap.world_art import WORLD_MAP_ID

    prg = ines.load(str(ROM_PATH)).prg
    ok, bad = 0, []
    for mid in range(FIRST_MAP, LAST_MAP + 1):
        if mid == WORLD_MAP_ID or map_kind(mid) == 0:
            continue
        got = adapter.resolve_map_master(prg, mid, None)
        if got:
            ok += 1
        else:
            bad.append(f"{mid:02X}: {got.detail}")
    assert not bad, bad
    assert ok == DREW, (
        f"★読めたのは {ok} 件（⚠ 実測は {DREW} 件）")


@needs_rom
def test_世界地図はそちらの経路で読める():
    """★「別経路だから失敗でよい」で終わらせない（⚠ 動くことを見る）。

    ⚠ 世界地図は1マスずつ `terrain_at()` で引く（★行ポインタ＋RLE）。
    """
    from dq2rom import ines
    from retroux.core.bgmap import world_map

    prg = ines.load(str(ROM_PATH)).prg
    # ★四隅と中央を引く（⚠ 65536 マス全部は `test_world_map.py` が見る）
    for x, y in ((0, 0), (255, 0), (0, 255), (255, 255), (128, 128)):
        got = world_map.terrain_at(prg, x, y)
        assert got is not None, f"⚠ ({x},{y}) が読めない"


def test_一括変換の結果が文書に残っている():
    """⚠ 数字を記録に残さないと、あとで劣化しても気づけない。"""
    body = (PROJECT_ROOT / "docs" / "project"
            / "RELEASE_CHECKLIST_V1.md").read_text(encoding="utf-8")
    assert f"{DREW}" in body, "★描けた件数が書かれていない"
    assert "世界地図" in body, "★世界地図が別経路であることが書かれていない"
