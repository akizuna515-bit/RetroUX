"""呪文がかき消される場所では唱えない（RX3-0320 / 2026-09-20）。

⚠⚠ 依頼者「save9 呪文をかきけすダンジョンでは、呪文をつかわないようにしたい（ROM、RAM解析要）」
★依頼者「おそらくピラミッド地下も出てくると思う」→ ⚠ **そのとおり**（`$CF` / `$D0`）。

## ★ゲームの持ち方は「表」ではなく「比較の並び」

⚠ 場所ごとの属性の表はありません。★bank 0 `$A12C` の 1 本の関数にこう書いてあるだけです。

```text
LDA $2F / AND #$01 / BEQ → ★世界地図なら使える
LDA $8B
CMP #$38 / BEQ → ⚠ 消される
CMP #$C3 / BCC → ★使える
CMP #$C6 / BCC → ⚠ 消される（= $C3〜$C5）
CMP #$CF / BEQ → ⚠ 消される
CMP #$D0 / BNE → ★使える
```

→ ★番号を**書き写さず**、⚠ この命令列から**読み出します**（`dq3rom/no_magic.py`）。

## ⚠⚠ MP は判定より先に引かれます

★実機は「唱える → MP が減る → しかし じゅもんは かきけされた！」。
⚠ つまり**唱えるだけ損**なので、★最初から選ばないようにします。

## ⚠ 戦闘のフラグ（`$0568` bit4）は使いません

★あれは戦闘の初めに写されるもので、⚠ フィールドでは前の戦闘の残りです
（★save9 は `in_battle=false` なのに立っている）。⚠ パルプンテでも立ちます。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from dq3rom import no_magic as NMG

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"
LUA = ROOT / "dq3" / "phase0"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が無い")

#: ★ROM から読めるはずの値（⚠ 検査の側は**答えを書いて**、読み手と突き合わせる）
WANT_MAPS = (0x38, 0xC3, 0xC4, 0xC5, 0xCF, 0xD0)
SAVE9_MAP, SAVE9_KIND = 0xC5, 7


@pytest.fixture(scope="module")
def prg():
    if not ROM.exists():
        pytest.skip("⚠ ROM が無い")
    from dq3rom import profile as P

    return P.load_and_identify(ROM).rom.prg


# --- ★ROM から読む -----------------------------------------------------------

@needs_rom
def test_判定はROMに1か所だけ(prg):
    """⚠⚠ 2 か所あれば骨格が甘い（★別の関数を拾っている）。"""
    got = NMG.read_rule(prg)
    assert got is not None
    assert got["at"] == 0x00212C, hex(got["at"])


@needs_rom
def test_2か所あったら信じない(prg):
    """⚠⚠ 壊す実験で分かった穴: ★「1 か所だけ」の歯止めを**1 度も発火させて**いなかった。

    ★同じ命令列を 2 つ並べた偽の ROM で、⚠ `None`（= 信じない）になることを見ます。
    """
    got = NMG.read_rule(prg)
    chunk = prg[got["at"]:got["at"] + 32]
    assert NMG.read_rule(chunk) is not None, "⚠ 前提: 1 つなら読める"
    assert NMG.read_rule(chunk + chunk) is None, "⚠⚠ 2 か所あるのに信じた"


@needs_rom
def test_範囲が逆なら信じない(prg):
    """⚠ `CMP #$C3 / CMP #$C6` の大小が逆 = 読み違い（★推測で並べない）。"""
    got = NMG.read_rule(prg)
    chunk = bytearray(prg[got["at"]:got["at"] + 32])
    chunk[13], chunk[17] = chunk[17], chunk[13]        # ★$C3 と $C6 を入れ替える
    assert NMG.read_rule(bytes(chunk)) is None


@needs_rom
def test_消される場所を読み出せる(prg):
    assert NMG.no_magic_maps(prg) == WANT_MAPS


@needs_rom
def test_ピラミッドも入っている(prg):
    """★依頼者「おそらくピラミッド地下も出てくると思う」。"""
    got = NMG.no_magic_maps(prg)
    assert 0xCF in got and 0xD0 in got


@needs_rom
def test_範囲の3枚がそろっている(prg):
    """⚠ `CMP #$C3 / CMP #$C6` は**範囲**（★$C3・$C4・$C5 の 3 枚）。"""
    got = NMG.no_magic_maps(prg)
    assert {0xC3, 0xC4, 0xC5} <= set(got)


@needs_rom
def test_地図の中のときだけ見る(prg):
    """★`AND #$01`（⚠ 世界地図・アレフガルド広域では使える）。"""
    assert NMG.read_rule(prg)["kind_mask"] == 1


# --- ★判定 -------------------------------------------------------------------

@needs_rom
def test_save9の場所では消される(prg):
    """★★ これが直したかったこと（⚠ save9 = kind 7 / map $C5）。"""
    assert NMG.blocks_magic(prg, SAVE9_KIND, SAVE9_MAP) is True


@needs_rom
def test_隣の洞窟では消されない(prg):
    """⚠⚠ 「kind が 7 だから」ではない（★map 番号で決まる）。"""
    assert NMG.blocks_magic(prg, SAVE9_KIND, 0x39) is False


@needs_rom
def test_世界地図では消されない(prg):
    for kind in (0, 2):
        assert NMG.blocks_magic(prg, kind, SAVE9_MAP) is False, kind


@needs_rom
@pytest.mark.parametrize("map_id", WANT_MAPS)
def test_6枚すべてで消される(prg, map_id):
    assert NMG.blocks_magic(prg, 1, map_id) is True


@needs_rom
def test_材料が無ければ今までどおり(prg):
    """⚠ 読めない・届いていないときは **False**（★黙って呪文を止めない）。"""
    assert NMG.blocks_magic(prg, None, SAVE9_MAP) is False
    assert NMG.blocks_magic(prg, SAVE9_KIND, None) is False
    assert NMG.blocks_magic(b"", SAVE9_KIND, SAVE9_MAP) is False
    assert NMG.no_magic_maps(b"") == ()


@needs_rom
def test_実機のセーブと合う(prg):
    """★セーブから `$2F` と `$8B` を読み、⚠ **1 本では決めない**。"""
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from retroux.core.bgmap import savestate as ss

    from savestate_dir import states_dir

    hits, seen = [], 0
    for path in sorted(states_dir().glob("DQ3_J*")):
        try:
            ram = bytes(ss.load(path).chunks["RAM"])
        except Exception:                                  # noqa: BLE001
            continue
        seen += 1
        if NMG.blocks_magic(prg, ram[0x2F], ram[0x8B]):
            hits.append((path.name, ram[0x2F], ram[0x8B]))
    if seen < 5:
        pytest.skip("⚠ セーブが足りない（%d 本）" % seen)
    # ⚠ 陽性は「消される map」に限る（★陽性が 0 でも、⚠ 陰性が全部正しければよい）
    for name, kind, mid in hits:
        assert mid in WANT_MAPS and (kind & 1), (name, kind, mid)


# --- ★Lua へ渡す -------------------------------------------------------------

@needs_rom
def test_生成物の設定に載る():
    """⚠⚠ 壊す実験で分かった穴: ★`_no_magic()` を直に呼ぶ検査しか無く、

    **CFG に載せ忘れても気づけません**でした（★Lua は `CFG.no_magic` しか見ない）。
    """
    from dq3.phase0 import generate_lua as G

    cfg = G.build()
    assert "no_magic" in cfg, "⚠⚠ CFG に載せていない（★Lua からは見えない）"
    assert sorted(cfg["no_magic"]["maps"]) == list(WANT_MAPS)


@needs_rom
def test_生成物に番号が載る():
    from dq3.phase0 import generate_lua as G

    got = G._no_magic({})
    assert got["kind_mask"] == 1
    assert sorted(got["maps"]) == list(WANT_MAPS)
    assert all(v is True for v in got["maps"].values())


def test_番号を書き写していない():
    """⚠⚠ ROM から読む形になっていること（★書き写すと、別の ROM で黙って嘘をつく）。"""
    src = (ROOT / "dq3" / "phase0" / "generate_lua.py").read_text(encoding="utf-8")
    head = src[src.index("def _no_magic"):]
    head = head[:head.index("def _battle_state")]
    body = chr(10).join(ln for ln in head.splitlines() if not ln.lstrip().startswith("#"))
    assert "no_magic" in body and "read_rule" in body
    for lit in ("0x38", "0xC3", "0xC5", "0xCF", "0xD0", "197"):
        assert lit not in body, "⚠⚠ 番号を書き写した: %s" % lit


# --- ★Lua の判定（⚠ 実機で走るのはこちら）-----------------------------------

def _lua_code(name: str) -> str:
    path = LUA / name
    if not path.exists():
        pytest.skip("⚠ %s がありません" % name)
    src = path.read_text(encoding="utf-8")
    return chr(10).join(ln for ln in src.splitlines() if not ln.lstrip().startswith("--"))


def test_判定するLuaは1か所():
    """⚠ 2 か所に書かない（★片方だけ直す型を繰り返さない）。"""
    assert re.search(r"function M\.no_magic_here", _lua_code("core.lua"))


def test_戦闘AIが見ている():
    code = _lua_code("auto_v0.lua")
    assert "Core.no_magic_here(CFG.no_magic)" in code
    assert 'mp_policy = no_magic and "forbid" or nil' in code


def test_まんたんが見ている():
    assert "Core.no_magic_here(CFG.no_magic)" in _lua_code("mantan_v0.lua")


def test_呪文の候補を作る所で止める():
    """★キアリク・キアリー・HP の回復は**すべて** `casts` を通る（⚠ 1 か所で足りる）。"""
    code = _lua_code("mantan_items.lua")
    assert "if no_magic then return {} end" in code
    assert "not opts.no_magic)" in code, "⚠ v0 の道が残っている"


def test_戦闘のフラグは使わない():
    """⚠⚠ `$0568` はフィールドでは前の戦闘の残り（★パルプンテでも立つ）。"""
    for name in ("core.lua", "auto_v0.lua", "mantan_v0.lua", "mantan_items.lua"):
        code = _lua_code(name)
        assert "0x0568" not in code and "0x568" not in code, name
