"""FCEUX のセーブステートを読む（2026-08-02 / Stop 1'）。

★★ **これがあると、FCEUX を起こさずに実機の値を確かめられます。**
  ⚠ 遊んでいる最中でも測れるので、調査が止まりません。

⚠ セーブステートは `tools/fceux/fcs/` にある**利用者のもの**を読みます。
  ★テストデータとして同梱しません（指示書 §18.7）。無ければ飛ばします。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.savestate import NotASaveState, load

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATES = PROJECT_ROOT / "tools" / "fceux" / "fcs"
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"

_found = sorted(STATES.glob("DQ2_J*.fc[0-9]")) if STATES.exists() else []


def _readable(paths):
    """★**読めたものだけ**返す。⚠ 「ファイルがある」と「読める」は別。

    2026-08-22（RX-0100）: 利用者の環境には非圧縮のセーブステートしか無く、
    ⚠ 見張りは「1本でもあれば走らせる」だったので、**0件のまま本文へ進んで**
    「★0 件しか確かめていない」で落ちていた。★材料の数で止める。
    """
    got = []
    for p in paths:
        try:
            load(p)
        except Exception:                 # noqa: BLE001  ★読めないものは数えない
            continue
        got.append(p)
    return got


_any = _readable(_found)
needs_state = pytest.mark.skipif(not _any, reason="読めるセーブステートが無い")
#: ⚠ 突き合わせ物は**3本以上**ないと意味が無い（1本だと偶然と区別できない）
needs_states3 = pytest.mark.skipif(
    len(_any) < 3, reason=f"読めるセーブステートが {len(_any)} 本（3本必要）")
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")


def _on_a_map(paths, allow=(0x00, 0x01)):
    """★**中身まで見て**、突き合わせに使える物だけ返す（RX-0100）。

    ⚠ 読めるセーブステートでも、世界地図（$00/$01）や未読込だと
      ヘッダの突き合わせができない。★「何本あるか」ではなく
      **「何本使えるか」**で見張らないと、本文で 0〜2 件になって落ちる。
    """
    got = []
    for p in paths:
        map_id = load(p).byte(0x31)
        if map_id is not None and map_id not in allow:
            got.append(p)
    return got


#: 突き合わせに使える物（マップ上のもの）
_ON_MAP = _on_a_map(_any)
#: 種別の突き合わせは世界地図でも効く（$00 だけ除く）
_HAS_KIND = _on_a_map(_any, allow=(0x00,))
#: ⚠ 3本未満だと偶然と区別できないので走らせない
needs_maps3 = pytest.mark.skipif(
    len(_ON_MAP) < 3,
    reason=f"マップ上のセーブステートが {len(_ON_MAP)} 本（3本必要）")
needs_kind3 = pytest.mark.skipif(
    len(_HAS_KIND) < 3,
    reason=f"種別を確かめられるセーブステートが {len(_HAS_KIND)} 本（3本必要）")


@needs_state
def test_チャンクを読める():
    st = load(_any[0])
    assert len(st.ram) == 2048          # ★CPU の RAM
    assert len(st.nametable) == 2048    # ★ネームテーブル 2 枚
    assert len(st.chr_data) == 8192     # ★CHR-RAM
    assert len(st.palette) == 32
    assert len(st.oam) == 256


@needs_state
def test_バイトとワードを読める():
    st = load(_any[0])
    assert st.byte(0x31) is not None            # map_id
    ptr = st.word(0x25)
    assert ptr == (st.byte(0x26) << 8) | st.byte(0x25)


@needs_state
def test_読めない番地はNone():
    """⚠ 0 と 不明を混ぜない。"""
    st = load(_any[0])
    assert st.byte(0x10000) is None
    assert st.word(0x10000) is None


def test_ちがう形式なら断る(tmp_path):
    bad = tmp_path / "x.fc0"
    bad.write_bytes(b"XXXX" + bytes(100))
    with pytest.raises(NotASaveState):
        load(bad)


def test_展開できなければ断る(tmp_path):
    bad = tmp_path / "y.fc0"
    bad.write_bytes(b"FCSX" + bytes(12) + b"not zlib")
    with pytest.raises(NotASaveState):
        load(bad)


def _fake_state(chunks: dict) -> bytes:
    """チャンクを並べて中身だけ作る（頭は付けない）。"""
    body = b""
    for name, data in chunks.items():
        body += (name.encode().ljust(4, bytes(1))      # ★名前は4バイト（後ろは 0 埋め）
                 + len(data).to_bytes(4, "little") + data)
    return body


def test_圧縮していないセーブステートも読める(tmp_path):
    """★★ **FCEUX は縮まないとき「そのまま」書きます**（RX-0100 / 2026-08-22）★★

    ⚠ 12 バイト目の「圧縮後の大きさ」に `0xFFFFFFFF`（-1）が入り、
      後ろは zlib ではなく**生のチャンク列**になります。
    ★ここに気づくまで、利用者の `.fc1` が丸ごと読めていませんでした
      （「展開できません」で 3 本中 2 本が捨てられ、突き合わせが 0 件に）。
    """
    body = _fake_state({"RAM": bytes(range(256)) * 8, "PRAM": bytes(32)})
    head = (b"FCSX" + len(body).to_bytes(4, "little")
            + (20606).to_bytes(4, "little")
            + bytes([0xFF] * 4))          # ⚠ -1 = 圧縮していない
    path = tmp_path / "raw.fc1"
    path.write_bytes(head + body)

    st = load(path)
    assert len(st.ram) == 2048
    assert st.byte(0x31) == 0x31            # ★中身がそのまま取れている


def test_圧縮の長さぶんだけ展開する(tmp_path):
    """⚠ 圧縮の後ろにゴミが付いていても読めること。

    ★`comprlen` で切ってから展開するようにした（RX-0100）。
      切らずに末尾まで渡していると、FCEUX が足す物で落ちる余地が残る。
    """
    import zlib
    body = _fake_state({"RAM": bytes(2048)})
    comp = zlib.compress(body)
    head = (b"FCSX" + len(body).to_bytes(4, "little")
            + (20606).to_bytes(4, "little")
            + len(comp).to_bytes(4, "little"))
    path = tmp_path / "z.fc0"
    path.write_bytes(head + comp + b"\x00\x01\x02")   # ★末尾にゴミ

    assert len(load(path).ram) == 2048


# --- ★★ ここが Stop 1' の収穫 ★★ ------------------------------------

@needs_maps3
@needs_rom
def test_RAMの20から27はマップヘッダそのもの():
    """★★ **これで「仮定」が消えました**（2026-08-02）。

    ⚠ それまでは「ヘッダ byte1/2 が幅・高さ、byte5/6 がデータ位置」は
      照合から**推し量った**ものでした。
    ★セーブステートの RAM を見たら、`$20`-`$27` に
      **ヘッダ 8 バイトがそのまま**入っていました:

        map $3F のヘッダ = 24 13 17 B3 A0 26 B4 5B
        RAM $20-$27     = 24 13 17 B3 A0 26 B4 5B   ★完全一致

      つまり `$21`=幅 / `$22`=高さ / `$25$26`=地形データ の位置。
    """
    from retroux.core.bgmap.rom_map import read_header
    from retroux.core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE, load_prg

    prg = load_prg(ROM)
    checked = 0
    for path in _ON_MAP:                 # ★使える物は先に数えてある
        st = load(path)
        map_id = st.byte(0x31)
        off = MAP_HEADER + map_id * MAP_HEADER_SIZE
        assert bytes(st.ram[0x20:0x28]) == prg[off:off + 8], (
            f"{path.name}: map ${map_id:02X}")
        # ★私たちの読み方と一致すること
        h = read_header(prg, map_id)
        assert (h.width, h.height) == (st.byte(0x21), st.byte(0x22))
        assert h.pointer == st.word(0x25)
        checked += 1
    assert checked == len(_ON_MAP), f"★{checked} 件しか確かめていない"


@needs_kind3
@needs_rom
def test_マップ種別もRAMと一致する():
    """★`map_kind()`（`$E20A` の写し）が `$1F` と合うか。"""
    from retroux.core.bgmap.rom_map import map_kind

    checked = 0
    for path in _HAS_KIND:
        st = load(path)
        map_id, kind = st.byte(0x31), st.byte(0x1F)
        assert map_kind(map_id) == kind, f"{path.name}: map ${map_id:02X}"
        checked += 1
    assert checked == len(_HAS_KIND)


@needs_state
def test_主人公の画面位置は見た目で決めない():
    """⚠⚠ **ここで一度外しました**（2026-08-02）。

    OAM の主人公は画面 (128,107) にあり、素直に 16 で割ると (8, 6)。
    ★ですが7件のセーブステートで地形と突き合わせると
      **(8,7) のほうが合いました**（矛盾なし 4件 vs 2件）。
    ★キャラの絵は背景のマスより少し上に描かれます。

    ⚠ ここでは「見た目のマスは (8,6) 側に出る」ことだけ固定します。
      ★地形の照合に使うのは **(8,7)**。
    """
    for path in _any:
        try:
            st = load(path)
        except NotASaveState:
            continue
        cell = st.hero_screen_cell()
        if cell is None:
            continue
        assert cell[0] == 8, f"{path.name}: 横は画面中央のはず"
        assert cell[1] in (6, 7), f"{path.name}: {cell}"
        return
    pytest.skip("主人公のスプライトが見つからない")
