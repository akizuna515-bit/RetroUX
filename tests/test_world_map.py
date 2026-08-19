"""世界地図の最小デコーダ（2026-08-02 / Phase 7 の試作）。

⚠⚠ **試作です。** ここで固定するのは「読めた」ことと、
★**街・ダンジョンへ混ざっていないこと**です。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import world_map as W
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")


# --- ★★ 経路を混ぜない ---------------------------------------------------

def _imported_names(module) -> set:
    """★そのモジュールが**実際に取り込んでいる**名前。

    ⚠ 本文の注意書き（docstring）は見ません。
      「使うな」と書いてあること自体を違反と読んでしまうためです。
    """
    import ast

    tree = ast.parse(pathlib.Path(module.__file__).read_bytes().decode("utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_世界地図の処理が街ダンジョンへ混ざっていない():
    """★★★ 依頼者の指示: 「世界地図用処理を街・ダンジョンへ流用しない」。

    ⚠ 2026-08-02、`wall_shape` をダンジョンに当てて誤った絵を出しました。
    ★ここで**取り込み自体**を禁じます。
    """
    import retroux.core.bgmap.dungeon_map as dungeon

    names = _imported_names(dungeon)
    for banned in ("wall_shape", "world_map"):
        assert not any(banned in n for n in names), (
            f"⚠ ダンジョン側が {banned} を取り込んでいます: {sorted(names)}")


def test_世界地図モジュールがダンジョンを呼ばない():
    """⚠ 逆向きも見ます。★別々に保ちます。"""
    assert not any("dungeon_map" in n for n in _imported_names(W))


def test_MapMasterは世界地図を受けつけない():
    """★種別0 は別経路。⚠ 黙って壊れた地図を返しません。"""
    from retroux.core.bgmap import map_master

    assert 0 not in map_master.SUPPORTED_KINDS


# --- ★ 行ポインタ表 -------------------------------------------------------

@needs_rom
def test_行ポインタ表はbank3で単調増加():
    """★★ どのバンクかは**中身で決めました**。

    `$9CC0` は差し替えバンクの範囲なので、アドレスだけでは決まりません。
    ★bank3 だけが単調増加します。
    """
    prg = load_prg(ROM)
    assert W.ROW_POINTER_BANK == 3
    ptrs = [W.row_pointer(prg, y) for y in range(W.WORLD_SIZE)]
    assert all(ptrs[i] < ptrs[i + 1] for i in range(len(ptrs) - 1))


@needs_rom
def test_行ポインタ表の直後からデータが始まる():
    """★256 行 × 2 バイト = 512。`$9CC0 + $200 = $9EC0`。

    ⚠ 最初の行データが `$9EC2` で、**ぴったり続いています**。
      これが「bank3 で正しい」ことの2つ目の裏づけです。
    """
    prg = load_prg(ROM)
    assert W.ROW_POINTER_TABLE + W.WORLD_SIZE * 2 == 0x9EC0
    assert W.row_pointer(prg, 0) == 0x9EC2


@needs_rom
def test_行の長さが正で妥当な幅に収まる():
    prg = load_prg(ROM)
    lengths = [W.row_length(prg, y) for y in range(W.WORLD_SIZE - 1)]
    assert all(n > 0 for n in lengths)
    # ★1 行 256 マスをランレングスで持つので、生バイトより短いはず
    assert max(lengths) < W.WORLD_SIZE


@needs_rom
def test_最後の行はポインタの差では測れない():
    """⚠ 次の行が無いので、並びからは測れません。"""
    prg = load_prg(ROM)
    assert W.row_length(prg, W.WORLD_SIZE - 1) is None


@needs_rom
def test_最後の行は展開して長さが分かる():
    """★★★ 2026-08-03 / Phase 8。**100% になりました。**

    ⚠⚠ これは推測ではありません。幅が 256 とヘッダで分かっているので、
      そこに達したところが行の終わりです。

    ★`y=255` は `$B81A` から `9F` が 8 個。
      `($9F & $1F) + 1 = 32` マス × 8 = **ちょうど 256**。
      次（`$B822`）からは別のデータ（`09 00 0B 00 …`）が始まります。
    """
    prg = load_prg(ROM)
    assert W.measured_row_length(prg, W.WORLD_SIZE - 1) == 8
    assert W.effective_row_length(prg, W.WORLD_SIZE - 1) == 8
    assert W.terrain_at(prg, 0, W.WORLD_SIZE - 1) is not None


@needs_rom
def test_数えた長さは並びから測った長さと一致する():
    """★★ 裏取り。⚠ 最後以外は両方で測れるので、合うはずです。"""
    prg = load_prg(ROM)
    for y in range(0, W.WORLD_SIZE - 1, 17):
        assert W.measured_row_length(prg, y) == W.row_length(prg, y), (
            f"⚠ y={y} で食い違います")


# --- ★ 展開 ---------------------------------------------------------------

@needs_rom
def test_全部のマスが読める():
    """★★★ 2026-08-03 / Phase 8。**65536/65536 = 100%**。

    ⚠ 2026-08-02 は 99.6% で、最後の 1 行（256 マス）が読めませんでした。
    """
    grid = W.decode_grid(load_prg(ROM))
    cov = W.coverage(grid)
    assert cov["read"] == 65536
    assert cov["unread"] == 0
    assert all(v is not None for v in grid[W.WORLD_SIZE - 1])


@needs_rom
def test_地形IDの散らばりが地図らしい():
    """★一番多い地形が 6 割ほど（海）。⚠ 名前は付けません。

    ⚠⚠ 「$04 は海」と決めつけません。★数が多いことだけを見ます。
    """
    cov = W.coverage(W.decode_grid(load_prg(ROM)))
    tally = cov["terrain_ids"]
    assert len(tally) >= 10, "★1 種類しか出ないなら展開が壊れています"
    top = max(tally.values())
    assert 0.4 < top / cov["read"] < 0.8


@needs_rom
def test_範囲外はNone():
    prg = load_prg(ROM)
    assert W.terrain_at(prg, -1, 0) is None
    assert W.terrain_at(prg, W.WORLD_SIZE, 0) is None
    assert W.terrain_at(prg, 0, -1) is None


@needs_rom
def test_行ポインタは範囲外で例外():
    """⚠ 黙って 0 を返しません。"""
    prg = load_prg(ROM)
    with pytest.raises(W.WorldMapError):
        W.row_pointer(prg, W.WORLD_SIZE)


# --- ★ 左右反転 -----------------------------------------------------------

@needs_rom
def test_左右反転の境目で読み方が変わる():
    """★`$DEF6: CMP #$80 / EOR #$FF`。⚠ 実装が両側を扱えること。"""
    prg = load_prg(ROM)
    left = [W.terrain_at(prg, x, 100) for x in range(0, W.MIRROR_FROM, 8)]
    right = [W.terrain_at(prg, x, 100)
             for x in range(W.MIRROR_FROM, W.WORLD_SIZE, 8)]
    assert all(v is not None for v in left)
    assert all(v is not None for v in right)
    # ⚠ 反転しているだけなら中身がそっくり同じになるはず**ではない**
    #   （★ランレングスの数え方が違うので、確かめるのは「読めること」まで）
    assert len(set(left)) > 1 and len(set(right)) > 1


# --- ⚠ 特別扱い -----------------------------------------------------------

def test_特別扱いは判定だけで置き換えない():
    """⚠ `$05F8` が何か分かっていないので、★置き換えません。"""
    assert W.special_region(0xB5, 0xA5, 0x13) is True
    assert W.special_region(0xB5, 0xA5, 0x12) is False
    assert W.special_region(0x00, 0x00, 0x13) is False
    assert W.special_region(0xB5, 0xA5, None) is False


# --- ★ ROM の値を固定 -----------------------------------------------------

@needs_rom
def test_行ポインタ表の番地はROMの実データ():
    """★`$DD9B`/`$DD9C` に `C0 9C` が入っています。"""
    prg = load_prg(ROM)
    off = 7 * 0x4000 + 0xDD9B - 0xC000
    assert prg[off] | (prg[off + 1] << 8) == W.ROW_POINTER_TABLE


@needs_rom
def test_世界地図のヘッダ():
    """★256×256、区画データなし。"""
    from retroux.core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

    prg = load_prg(ROM)
    off = MAP_HEADER + W.WORLD_MAP_ID * MAP_HEADER_SIZE
    header = prg[off:off + 8]
    assert header[1] + 1 == W.WORLD_SIZE
    assert header[2] + 1 == W.WORLD_SIZE
    assert (header[5] | (header[6] << 8)) == 0, "⚠ 世界地図に区画データは無い"
