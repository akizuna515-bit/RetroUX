"""窓の色（`$06E0`）の決まりを見張る（RX3-0225 / 2026-09-12）。

★Auto を人へ返す合図は、ゲーム自身が決めた窓の色です（`$27` オレンジ / `$2A` 緑 /
`dq3/phase0/battle_speed.lua` の `on_window`・`may_auto_start`）。⚠ RetroUX は色を計算しません（★1 バイト読むだけ）。

ここで見るのは、ROM の決まり（JP bank 13 `$959B-$961C`）を HP と状態から計算し直すと、
セーブの `$06E0` と一致するかです。⚠ 外れたら番地か決まりのどちらかが違っています
（★Auto が危ないときに人へ返らない / 返りすぎる）。

```text
順  条件（4 枠のうち 1 人でも）                                        値
1   死んでいる（$073C+2i bit7 XOR $073D+2i bit7）                       $27 オレンジ
2   生きている（両方の bit7）人の HP < floor(最大 HP / 4)（16 bit）       $2A 緑
3   夜（$06DF >= $78）かつ $60B7 bit5（戦闘の本体の旗）が立っていない   $21 薄い青
4   それ以外                                                            $30 白
⚠   最後に $6A58 == 0 なら $30（★ROM: LDX $6A58 / BNE / LDA #$30 / ⚠ 意味は未確認）
```

⚠ 毒（`$073D` bit5）では変わらない。⚠ 赤は無い。
"""
from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
#: ⚠ 意味は未確認（★ROM の分岐だけ: 0 なら白に倒す / bank 13 $9610）
GATE = 0x6A58


def _hex(value) -> int:
    """★`"0x06E0"` でも `1760` でも受ける（⚠ 10 進を 16 進で読む事故を起こさない）。"""
    return value if isinstance(value, int) else int(str(value), 16)


def _runtime() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))["runtime"]


#: ⚠⚠ **決まりの本体は `dq3/knowledge/window_color.py` に移しました**（RX3-0412 / 2026-09-23）。
#:   ★`scripts/dq3_make_fixture.py` も同じものを使います（⚠ HP を書き換えたら色も直す）。
#:   ⚠ ここに写し直すと、★片方だけ直って気づけません（この repo が何度も踏んだ形）。
from dq3.knowledge.window_color import window_color                    # noqa: E402


def _reader(ram: bytes, wram: bytes):
    def read(addr: int) -> int:
        if 0 <= addr < len(ram):
            return ram[addr]
        if 0x6000 <= addr < 0x6000 + len(wram):
            return wram[addr - 0x6000]
        raise AssertionError("⚠ セーブに無い番地 $%04X（★0 と見なすと白に化ける）" % addr)
    return read


# --- ★決まりそのもの（⚠ 検出器にも検査を書く）-------------------------------------

def _scene(members, *, time=0x10, battle=False, gate=1):
    """★members: (hp, hp_max, 状態の下位, 状態の上位)。⚠ 空き枠は (0, 0, 0, 0)。"""
    rt = _runtime()
    party = rt["party"]
    ram, wram = bytearray(0x800), bytearray(0x2000)
    for i, (h, m, lo, hi) in enumerate(members):
        for base, v in ((_hex(party["hp_current"]), h), (_hex(party["hp_max"]), m)):
            ram[base + i * 2], ram[base + i * 2 + 1] = v % 256, v // 256
        ram[_hex(party["status"]) + i * 2], ram[_hex(party["status"]) + i * 2 + 1] = lo, hi
    ram[_hex(rt["window_color"]["time"])] = time
    wram[_hex(rt["in_battle"]["flags"]) - 0x6000] = 0x20 if battle else 0
    wram[GATE - 0x6000] = gate
    return window_color(_reader(bytes(ram), bytes(wram)), rt)


ALIVE = (0x80, 0x80)
EMPTY = (0, 0, 0, 0)


@pytest.mark.parametrize(("name", "members", "kw", "want"), [
    ("元気", [(30, 30, *ALIVE), (20, 25, *ALIVE)], {}, 0x30),
    ("死者（下位だけ bit7）", [(30, 30, *ALIVE), (0, 25, 0x80, 0x00)], {}, 0x27),
    ("死者は緑より先", [(1, 30, *ALIVE), (0, 25, 0x00, 0x80)], {}, 0x27),
    ("6/28 は緑", [(6, 28, *ALIVE)], {}, 0x2A),
    ("7/28 は白（28//4 = 7 / ⚠ 未満）", [(7, 28, *ALIVE)], {}, 0x30),
    ("8/28 = 28.6% は白（⚠ 以前の 30% の決まりでは危険）", [(8, 28, *ALIVE)], {}, 0x30),
    ("16 bit: 256/1100 は緑（1100//4 = 275）", [(256, 1100, *ALIVE)], {}, 0x2A),
    ("16 bit: 300/1100 は白", [(300, 1100, *ALIVE)], {}, 0x30),
    ("空き枠は数えない", [(30, 30, *ALIVE), EMPTY, EMPTY, EMPTY], {}, 0x30),
    ("毒では変わらない", [(30, 30, 0x80, 0xA0)], {}, 0x30),
    ("夜は薄い青", [(30, 30, *ALIVE)], {"time": 0x78}, 0x21),
    ("夜の手前は白", [(30, 30, *ALIVE)], {"time": 0x77}, 0x30),
    ("戦闘の本体では夜でも白（$60B7 bit5）", [(30, 30, *ALIVE)], {"time": 0x90, "battle": True}, 0x30),
    ("戦闘中でも緑は緑", [(6, 28, *ALIVE)], {"time": 0x90, "battle": True}, 0x2A),
    ("$6A58 == 0 なら死者がいても白", [(0, 25, 0x80, 0x00)], {"gate": 0}, 0x30),
])
def test_決まりの表(name, members, kw, want):
    assert _scene(members, **kw) == want, name


# --- ★セーブの `$06E0` と一致する（★ROM の決まり・番地が変わっていない）-----------------

def _savestates() -> list[pathlib.Path]:
    from dq3.testing import fixtures as FX

    return [fx.path for fx in FX.all_fixtures() if fx.path.exists()]


#: ⚠ `$03E8` だけ `$06E0` と違うセーブ（★計算 = `$06E0` は一致 / 製品が読むのは `$06E0` だけ）。
#:   battle_hasami_sukult（依頼者の save2 / 2026-09-13）: 戦闘中・`$03E8` = 10。★読み込むとすぐスクルトが効いたので、
#:   演出で画面の色を変えている途中と推測（⚠ 未確認）。⚠ 増やすときは理由を書く（★黙って外さない）。
MIRROR_EXCEPTIONS = {"battle_hasami_sukult.fcs"}


def test_セーブの窓の色は決まりどおり():
    """★repo の fixture のセーブすべてで、計算した色 = `$06E0` = `$03E8`（★ROM は両方へ書く）。"""
    from retroux.core.bgmap import savestate as ss

    paths = _savestates()
    if not paths:
        pytest.skip("⚠ fixture のセーブが無い環境（work/test-fixtures/dq3/states）")
    rt = _runtime()
    addr = _hex(rt["window_color"]["address"])
    bad, seen = [], {}
    for path in paths:
        state = ss.load(path)
        ram, wram = state.chunks["RAM"], state.chunks.get("WRAM", b"")
        want = window_color(_reader(ram, wram), rt)
        got = ram[addr]
        seen[path.name] = "%02X" % got
        if got != want or (ram[0x03E8] != got and path.name not in MIRROR_EXCEPTIONS):
            bad.append("%s: 計算 %02X / $06E0 %02X / $03E8 %02X" % (path.name, want, got, ram[0x03E8]))
    assert not bad, "⚠⚠ 窓の色が決まりと合わない:\n" + "\n".join(bad)
    assert len(seen) >= 1, seen


def test_生成物に窓の色の番地と人へ返す色が載る():
    """⚠ profile に書いた値を誰も読まない、にしない（★Lua は `CFG.window_color` を battle_speed へ渡す）。

    ★Lua が渡された番地・色を使うことは `dq3_battle_speed_test.lua`（窓の色の節）が見ています。
    """
    from dq3.phase0.generate_lua import build

    cfg = build()
    assert cfg["window_color"] == {"address": 0x06E0, "dead": 0x27, "low_hp": 0x2A}
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert "window = CFG.window_color" in lua, "⚠ auto_v0 が生成物の窓の色を battle_speed へ渡していない"
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "memory.readbyte(CFG.window_color.address)" in dev, "⚠ state.json の window_color が生成物の番地でない"
