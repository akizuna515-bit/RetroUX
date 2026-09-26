"""アレフガルド（下の世界）の地図も絵で描く（RX3-0316 / 2026-09-20）。

⚠⚠ 依頼者「アレフガルドでの緑の丸が誤って表示される。…CHR も表示されない
（ストーリー的にたしか夜の世界から昼の世界に変わるのでそれもある）」。

## ★測って分かったこと（⚠ 古い前提は誤りだった）

`map_art.lua` には長らく「⚠ まだ対応していない（★世界タイルの対応表が要る）」と
書いてありましたが、**ROM と実機セーブで測ったら誤りでした**。

```text
$9A tileset    ★アレフガルドでも 0（= 上の世界と同じ道）
$7200 / $7300  ★上の世界と**全バイト一致**
画面 vs ROM    ★world_alefgard と 181/181 一致（world_main は 118/181 の偶然一致）
```

→ ★**新しい対応表は要りません**。⚠ 違うのは **CHR の絵柄とパレット**だけです。

## ⚠ もう 1 つの穴: 同じ世界に居ると材料を取り直せない

★`map_key()` は `$2F/$8B/$88/$89` だけで作っていました。
⚠ 世界地図では `$8B`（map 番号）も `$88/$89`（広さ）も**前の地図の残り**なので、
⚠⚠ 世界地図に居るあいだ鍵はずっと同じ → **CHR や色が変わっても書き直しません**。

→ ★世界地図のときだけ、⚠ **動かないパレットの組**を鍵に足しました。
  （⚠ 組 0・1 は海のアニメーションで毎回変わる → 足すと毎 tick 書き直しになる）
"""
from __future__ import annotations

import pathlib
import re

import pytest

from dq3.knowledge import tile_art as TA

ROOT = pathlib.Path(__file__).resolve().parents[1]
LUA = ROOT / "dq3" / "phase0" / "map_art.lua"
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"

UPPER, ALEF = 0, 2
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が無い")


def _lua() -> str:
    if not LUA.exists():
        pytest.skip("⚠ map_art.lua がありません")
    return LUA.read_text(encoding="utf-8")


def _code(src: str) -> str:
    """⚠ 註は数えない（★字面の検査が註で通ってしまわないように）。"""
    return chr(10).join(ln for ln in src.splitlines() if not ln.lstrip().startswith("--"))


# --- ★Lua が材料を書き出す門 -------------------------------------------------

def test_世界地図かを決める1か所がある():
    """⚠⚠ もとは `kind == KIND_WORLD` を**2 か所に別々に**書いていた。"""
    assert re.search(r"function\s+is_world", _code(_lua()))


def test_アレフガルドを弾く門が無い():
    """★2 つあった門（`tick` と `write_now`）の両方。"""
    code = _code(_lua())
    assert "kind_now ~= KIND_WORLD" not in code, "⚠⚠ tick の門が残っている"
    assert re.search(r"if\s+is_world\(kind\)\s+then", code), "⚠ write_now が is_world を見ていない"
    # ⚠ 「まだ対応していない」の黙って落ちる道が消えていること
    assert "if not is_local(kind) then" not in code


def test_アレフガルドの広さを書く():
    """⚠ 256x256 べた書きだと、★記録が嘘をつく（158x138）。"""
    code = _code(_lua())
    assert "158" in code and "138" in code


# --- ★色が変わったら取り直す -------------------------------------------------

def test_世界地図の鍵に色が入る():
    """⚠⚠ これが無いと、★同じ世界に居るあいだ材料を 1 度も書き直さない。"""
    code = _code(_lua())
    head = code[code.index("local function map_key"):]
    head = head[:head.index("end")]
    assert "is_world" in head and "read_pram" in head, head


def test_動くパレットの組は鍵に入れない():
    """⚠⚠ 組 0・1 は海のアニメーションで毎回変わる（★入れると毎回書き直す）。

    ★`$3F08`〜`$3F0F`（組 2・3 / 陸・林・山）だけを見る = 1 始まりで 9..16。
    """
    code = _code(_lua())
    assert re.search(r"PRAM_STABLE_FROM,\s*PRAM_STABLE_TO\s*=\s*9,\s*16", code), (
        "⚠⚠ パレットの見る範囲が 組 2・3 になっていない")
    assert "PRAM_STABLE_FROM, PRAM_STABLE_TO)" in code, "⚠ 範囲を使っていない"


# --- ★Python が受け取る -----------------------------------------------------

def test_2つの世界の名前を持つ():
    assert TA.WORLD_NAMES == {0: "world_main", 2: "world_alefgard"}
    assert TA.KIND_ALEFGARD == ALEF


def test_terrainと同じ表を使う():
    """⚠ 2 か所で別の表を持たない（★片方だけ直すと食い違う）。"""
    from dq3.knowledge import terrain as T

    assert T.WORLD_TABLE == TA.WORLD_NAMES


@needs_rom
def test_アレフガルドの升はROMから引ける():
    got = TA.world_cells("world_alefgard")
    assert got is not None
    cells, width, height = got
    assert (width, height) == (158, 138)
    assert len(cells) == width * height


@needs_rom
def test_上の世界とは別の升():
    """⚠⚠ 同じ升を返していたら、★世界を分けた意味がない。"""
    alef = TA.world_cells("world_alefgard")
    main = TA.world_cells("world_main")
    assert alef is not None and main is not None
    assert (alef[1], alef[2]) != (main[1], main[2])
    assert alef[0] != main[0][:len(alef[0])]


@needs_rom
def test_対応表はアレフガルドの升を全部知っている():
    """★新しい表が要らないことの裏取り（⚠ 未知の id が 1 つも無い）。"""
    table = TA.world_metatiles()
    cells, _w, _h = TA.world_cells("world_alefgard")
    unknown = sorted({v for v in cells} - set(table))
    assert unknown == [], "⚠⚠ 対応表に無い升: %s" % unknown


# --- ★橋渡し（⚠ 材料 → RuntimeArt）------------------------------------------

def _body(kind, pram_hex):
    return {"kind": kind, "map_id": 0, "width": 0, "height": 0,
            "chr_checksum": 1, "tileset": "", "palette_group": "",
            "pram": pram_hex, "map": ""}


#: ★色のある材料（⚠ 暗転・白黒だと作らない決まりがある）
PRAM = ("0f27212" + "1") + "0f132919" + "0f000f19" + "0f190917" + "0f0f0f0f" * 4


@needs_rom
def test_アレフガルドの材料からも絵ができる():
    """★★ これが直したかったこと。"""
    chr_data = bytes(TA.CHR_LEN) if hasattr(TA, "CHR_LEN") else bytes(8192)
    got = TA._world_runtime(_body(ALEF, PRAM), chr_data)
    # ⚠⚠ ここで skip にしてはいけません（★壊しても「通っていないだけ」になる）。
    #   ★壊す実験で実際に skip へ化けました（RX3-0316）。
    assert got is not None, "⚠⚠ 材料から絵ができない"
    assert got.kind == ALEF, "⚠⚠ 上の世界として返した（★画面が弾く）"
    assert (got.width, got.height) == (158, 138)


@needs_rom
def test_上の世界は今までどおり():
    chr_data = bytes(8192)
    got = TA._world_runtime(_body(UPPER, PRAM), chr_data)
    # ⚠⚠ ここで skip にしてはいけません（★壊しても「通っていないだけ」になる）。
    #   ★壊す実験で実際に skip へ化けました（RX3-0316）。
    assert got is not None, "⚠⚠ 材料から絵ができない"
    assert got.kind == UPPER and (got.width, got.height) == (256, 256)


def test_知らない世界の材料は作らない():
    """⚠ 推測で作らない（★9 のような種別）。"""
    assert TA._world_runtime(_body(9, PRAM), bytes(8192)) is None


# --- ⚠ 触ってはいけない所 ---------------------------------------------------

def test_氷の差し替えは上の世界だけ():
    """⚠⚠ ROM も `$2F & 2` では氷に替えない（★アレフガルドへ広げない）。"""
    assert TA._game_swap("world_alefgard", 0, TA.WORLD_ICE_FROM) == TA.WORLD_ICE_FROM
    assert TA._game_swap("world_main", 0, TA.WORLD_ICE_FROM) == TA.WORLD_ICE_TO


# --- ⚠ 壊す実験で見つかった、通っていなかった道 -------------------------------


def _write_material(tmp_path, kind):
    """★実機が書いたつもりの材料を、⚠ **隔離先**に置く（★本物の work/ に書かない）。"""
    import json

    (tmp_path / TA.RUNTIME_JSON).write_text(
        json.dumps(_body(kind, PRAM), ensure_ascii=False), encoding="utf-8")
    (tmp_path / TA.RUNTIME_BIN).write_bytes(bytes(8192))
    return tmp_path


@needs_rom
def test_材料の読み込みもアレフガルドを通す(tmp_path):
    """⚠⚠ 壊す実験で分かった穴: ★`_world_runtime` を直に呼ぶ検査しか無く、

    **材料を読む入口（`from_runtime`）の分岐を 1 度も通していません**でした。
    """
    got = TA.from_runtime(_write_material(tmp_path, ALEF))
    # ⚠⚠ ここで skip にしてはいけません（★壊しても「通っていないだけ」になる）。
    #   ★壊す実験で実際に skip へ化けました（RX3-0316）。
    assert got is not None, "⚠⚠ 材料から絵ができない"
    assert got.kind == ALEF
    assert (got.width, got.height) == (158, 138)


@needs_rom
def test_材料の読み込みは上の世界も今までどおり(tmp_path):
    got = TA.from_runtime(_write_material(tmp_path, UPPER))
    # ⚠⚠ ここで skip にしてはいけません（★壊しても「通っていないだけ」になる）。
    #   ★壊す実験で実際に skip へ化けました（RX3-0316）。
    assert got is not None, "⚠⚠ 材料から絵ができない"
    assert got.kind == UPPER and (got.width, got.height) == (256, 256)


def test_材料が無ければ黙って色ブロックへ(tmp_path):
    """⚠ 落ちない（★指示書 §1）。"""
    assert TA.from_runtime(tmp_path) is None
