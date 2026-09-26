"""宝箱を取ったかの記録 ― ⚠ ビットの並びは **MSB から**（RX3-0012 / 2026-09-07）。

## ⚠⚠ 1 年ぶんの宿題だったところ

★番地（`$608E`）と通し番号は 2026-08-25 に ROM のコードで確定していました。
⚠ ですが**セーブの配列が全部 0** で、裏取りができていませんでした
（★`docs/design/dq3-findings.md`「これは番地の裏取りにならない」）。

⚠ そして控えてあった「ビット = 番号 & 7」は**誤り**でした。

## ★この検査が守るもの

```text
① ROM のコード（ASL を (n&7)+1 回）と同じ並びであること
② ⚠ 総数 193 が `chests.read_tables` と一致していること
③ ★セーブの実データが、**MSB から読んだときだけ**辻褄が合うこと
```

⚠ ③は `LSB から` に変えると赤くなります（★破壊試験を同梱）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dq3_states                                            # noqa: E402
from savestate_dir import states_dir                         # noqa: E402

from dq3rom import chest_flags as CF                         # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


# ----------------------------------------------------------------------
# ★① ROM のコードと同じ並びか（⚠ セーブが無くても回る）
# ----------------------------------------------------------------------
def _like_6502(index: int) -> tuple[int, int]:
    """★bank12 `$9DCE`-`$9DE1` をそのまま真似る。

    ```text
    LSR A x3 → X      ; バイト番号
    AND #$07 → Y
    LDA $608E,X
    ASL A / DEY / BPL ; ★(Y + 1) 回
    → 桁上がりが答え
    ```
    """
    x = index >> 3
    y = index & 7
    # ★1 バイトを左へ (y + 1) 回。⚠ 最後に落ちたビットが答え
    probe = 0
    for bit in range(8):
        value = 1 << bit
        carry = 0
        acc = value
        for _ in range(y + 1):
            carry = (acc >> 7) & 1
            acc = (acc << 1) & 0xFF
        if carry:
            probe = value
            break
    return CF.BASE + x, probe


@pytest.mark.parametrize("index", [0, 1, 6, 7, 8, 15, 16, 17, 18, 23, 100, 192])
def test_ROMのシフト回数と同じビットを指す(index):
    assert CF.bit_of(index) == _like_6502(index), index


def test_全部の番号でROMと一致する():
    """⚠ 抜き取りだと「たまたま」が残る（★193 件ぜんぶ見る）。"""
    for n in range(CF.COUNT):
        assert CF.bit_of(n) == _like_6502(n), n


def test_MSBから並ぶ():
    """★通し番号 0 が bit7（⚠ ここが逆だと map の区切りがずれる）。"""
    assert CF.bit_of(0) == (CF.BASE, 0x80)
    assert CF.bit_of(7) == (CF.BASE, 0x01)
    assert CF.bit_of(8) == (CF.BASE + 1, 0x80)


def test_範囲の外は断る():
    for bad in (-1, CF.COUNT, 999):
        with pytest.raises(ValueError):
            CF.bit_of(bad)


def test_短いWRAMはNoneでFalseと混ぜない():
    assert CF.taken(b"") is None
    assert CF.is_taken(b"", 0) is None
    assert CF.raw(None) is None


def test_合成したバイト列を読み戻せる():
    buf = bytearray(CF.BASE + CF.NBYTES)
    want = [0, 5, 16, 17, 18, 192]
    for n in want:
        off, mask = CF.bit_of(n)
        buf[off] |= mask
    assert CF.taken(bytes(buf)) == want


# ----------------------------------------------------------------------
# ★② 総数
# ----------------------------------------------------------------------
@needs_rom
def test_総数が個数表と一致する():
    """⚠ 193 を 2 か所に書いているので、★ずれたら赤くする。"""
    from dq3rom import chests
    from dq3rom import profile as dq3

    pairs, _ = chests.read_tables(dq3.load_and_identify(ROM_PATH))
    assert sum(n for _m, n in pairs) == CF.COUNT


# ----------------------------------------------------------------------
# ★③ 実データ（⚠ セーブは**番号で名指ししない** / RX3-0028）
# ----------------------------------------------------------------------
def _owner():
    from dq3rom import chests
    from dq3rom import profile as dq3

    pairs, _ = chests.read_tables(dq3.load_and_identify(ROM_PATH))
    out, run = {}, 0
    for mid, n in pairs:
        for i in range(run, run + n):
            out[i] = mid
        run += n
    return out


def _states_with_chests():
    """★宝箱を 1 つ以上取っているセーブを、**中身で**選ぶ。"""
    from retroux.core.bgmap import savestate as ss

    every = sorted(p for p in pathlib.Path(states_dir()).glob("DQ3_J*.fc*")
                   if p.suffix != ".fcs")
    if not every:
        pytest.skip("★DQ3 のセーブステートがありません（⚠ 同梱していません）")
    got = []
    for p in every:
        wram = ss.load(p).chunks.get("WRAM")
        taken = CF.taken(wram)
        if taken:
            got.append((p, ss.load(p), taken))
    if not got:
        pytest.fail(
            "⚠⚠ 宝箱を 1 つも取っていないセーブしかありません（★%d 本）。"
            "★この検査は `RX3-0012` の裏取りそのものなので、⚠ 消さずに、"
            "宝箱を取ったセーブを 1 本固定し直してください: %s"
            % (len(every), ", ".join(p.name for p in every)))
    return got


@needs_rom
def test_取った宝箱は同じmapにまとまる():
    """★実データ: 取った宝箱が **1 つの map に収まる**（⚠ 序盤のセーブなので）。

    ⚠⚠ `LSB から` に変えると、同じバイトが**別の map**を指し、
    ★依頼者が行っていない場所の宝箱を「取った」ことになります。
    """
    owner = _owner()
    for path, _st, taken in _states_with_chests():
        maps = {owner[n] for n in taken}
        assert len(maps) == 1, "⚠ %s: 取った宝箱が %s に散っている" % (path.name, sorted(maps))


@needs_rom
def test_中に居るセーブは自分の居る場所の宝箱を取っている():
    """⚠⚠ **これが MSB / LSB を分ける検査**（★2026-09-07 の決め手）。

    ★「取りかけの地図の**中に居る**」セーブが 1 本でもあれば、それが決め手です。

    ⚠ 全部のセーブに求めてはいけません（★取ってから外へ出れば、居る場所は変わる）。
    ⚠⚠ `LSB から` に変えると、取った宝箱が map 48 / 52 になり、
      ★**そこに居るセーブは 1 本もありません** → この検査が赤くなります。
    """
    owner = _owner()
    local = 0
    hits = []
    for path, st, taken in _states_with_chests():
        kind = st.byte(0x2F)
        if kind in (None, 0):
            continue                      # ★世界地図（⚠ map_no は前の値の残り / RX3-0016）
        local += 1
        here = st.byte(0x8B)
        if here in {owner[n] for n in taken}:
            hits.append((path.name, here, taken))
    assert local, (
        "⚠⚠ 地図の中で保存されたセーブが 1 本もありません（★この検査は空回り）。"
        "⚠ 消さずに、洞窟や町の中で宝箱を取ったセーブを 1 本固定してください")
    assert hits, (
        "⚠⚠ 「いま居る地図の宝箱を取っている」セーブが 1 本もありません。"
        "★ビットの並び（MSB / LSB）が逆になっていないか、⚠ まず疑ってください"
        "（`RX3-0012` / `dq3rom/chest_flags.py` の註）")


@needs_rom
def test_取りかけの状態がそのmapの中に収まる():
    """★取った数が、その map の宝箱の数を超えないこと（⚠ 番号のずれの歯止め）。"""
    owner = _owner()
    total = {}
    for n, mid in owner.items():
        total[mid] = total.get(mid, 0) + 1
    for path, _st, taken in _states_with_chests():
        by_map: dict = {}
        for n in taken:
            by_map.setdefault(owner[n], []).append(n)
        for mid, got in by_map.items():
            assert len(got) <= total[mid], "⚠ %s: map %d は %d 個なのに %d 個取っている" % (
                path.name, mid, total[mid], len(got))


@needs_rom
def test_by_mapがまとめて返す():
    owner = _owner()
    from retroux.core.bgmap import savestate as ss

    path, _st, taken = _states_with_chests()[0]
    got = CF.by_map(ss.load(path).chunks["WRAM"], owner)
    assert got, path.name
    for mid, row in got.items():
        assert set(row["taken"]) <= set(row["all"])
        assert set(row["taken"]) == {n for n in taken if owner[n] == mid}
