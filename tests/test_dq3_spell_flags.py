"""覚えた呪文の記録 ― ⚠ ビットは **LSB から**、⚠⚠ 中身は「枠」（RX3-0071 / 2026-09-07）。

## ★この検査が守るもの

```text
① ROM のコード（$998A の ROR を (枠 & 7) + 1 回）と同じ向きであること
② ⚠ 「ビット = 呪文 ID」と思い込まないこと（★表を 1 段引く）
③ ★実データが「減らない」こと（⚠ 覚えたものは消えない）
```

⚠ `dq3rom/chest_flags.py`（宝箱）は **MSB から**です。★同じ ROM で 2 通りあるので、
⚠⚠ **片方を見て他方を決めないこと**。この検査は両方の向きを名指しで比べます。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir                         # noqa: E402

from dq3rom import spell_flags as SF                         # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


# ----------------------------------------------------------------------
# ★① ROM と同じ向きか
# ----------------------------------------------------------------------
def _like_6502(frame: int) -> int:
    """★`$998A`-`$9994` を真似る。

    ```text
    LDY $0E / INY / ROR $0F / DEY / BNE   ; ★(枠 & 7) + 1 回 右シフト
    ```
    ★桁上がりに出るビットのマスクを返す。
    """
    y = frame & 7
    for bit in range(8):
        acc, carry = 1 << bit, 0
        for _ in range(y + 1):
            carry = acc & 1
            acc >>= 1
        if carry:
            return 1 << bit
    raise AssertionError("⚠ ありえない")


@pytest.mark.parametrize("frame", list(range(SF.FRAMES)))
def test_ROMのシフト回数と同じビットを指す(frame):
    assert SF.bit_of(0, frame)[1] == _like_6502(frame), frame


def test_LSBから並ぶ():
    """⚠⚠ 宝箱（MSB）と**逆**（★取り違えないように名指しで書く）。"""
    from dq3rom import chest_flags as CF

    assert SF.bit_of(0, 0)[1] == 0x01
    assert SF.bit_of(0, 7)[1] == 0x80
    assert CF.bit_of(0)[1] == 0x80, "⚠ 宝箱は MSB から（★逆になっていないか）"


def test_人ごとに8バイト():
    assert SF.bit_of(0, 0)[0] == SF.BASE
    assert SF.bit_of(1, 0)[0] == SF.BASE + SF.STRIDE
    assert SF.bit_of(3, 63)[0] == SF.BASE + 3 * SF.STRIDE + 7


def test_範囲の外は断る():
    for slot, frame in ((-1, 0), (SF.SLOTS, 0), (0, -1), (0, SF.FRAMES)):
        with pytest.raises(ValueError):
            SF.bit_of(slot, frame)


def test_短いRAMはNone():
    assert SF.learned(b"", 0) is None
    assert SF.raw(None, 0) is None


def test_合成したバイト列を読み戻せる():
    buf = bytearray(SF.BASE + SF.SLOTS * SF.STRIDE)
    want = [0, 1, 7, 8, 24, 63]
    for n in want:
        off, mask = SF.bit_of(2, n)
        buf[off] |= mask
    assert SF.learned(bytes(buf), 2) == want
    assert SF.learned(bytes(buf), 0) == []


# ----------------------------------------------------------------------
# ★② 表（⚠ 「ビット = 呪文 ID」ではない）
# ----------------------------------------------------------------------
@needs_rom
def test_呪文の表が12ブロックある():
    prg = ROM_PATH.read_bytes()[16:]
    got = SF.blocks(prg)
    assert len(got) == SF.BLOCK_COUNT
    assert all(len(b) == SF.BLOCK_SIZE for b in got)


@needs_rom
def test_勇者専用の呪文が最初の4ブロックに入る():
    """★ブロックが職業ごとに束ねられている根拠（⚠ ライデイン / ギガデインは勇者だけ）。"""
    from dq3rom import names

    prg = ROM_PATH.read_bytes()[16:]
    table = names.load_cached(ROM_PATH)["names"]["spell"]
    got = SF.blocks(prg)

    def named(block):
        return {table.get(v, table.get(str(v))) for v in block if v != SF.NO_SPELL}

    hero = set().union(*(named(got[b]) for b in range(4)))
    assert {"ライデイン", "ギガデイン"} <= hero, sorted(hero)
    others = set().union(*(named(got[b]) for b in range(4, SF.BLOCK_COUNT)))
    assert not ({"ライデイン", "ギガデイン"} & others), sorted(others)


@needs_rom
def test_未使用のブロックがある():
    """⚠ 12 ブロックすべてが埋まっているわけではない（★$FF は潰さない）。"""
    got = SF.blocks(ROM_PATH.read_bytes()[16:])
    empty = [i for i, b in enumerate(got) if all(v == SF.NO_SPELL for v in b)]
    assert empty, "⚠ 空のブロックが 1 つも無い（★$FF の扱いを確かめる検査が空回り）"


# ----------------------------------------------------------------------
# ★③ 実データ（⚠ セーブは**中身で**選ぶ / RX3-0028）
# ----------------------------------------------------------------------
def _states():
    """★いま遊んでいるセーブ 10 本だけ（⚠ `-bak` は**別のとき**のもの）。

    ## ⚠⚠ 2026-09-07 に踏んだ

      ★`DQ3_J*.fc*` で拾うと `-bak` / `.bak` まで入り、⚠ **別の周回**が混ざります。
      「覚えた呪文は減らない」は**同じ周回の中でしか成り立たない**ので、
      ⚠ 混ぜると赤くなります（★番地は合っているのに）。
    """
    from retroux.core.bgmap import savestate as ss

    every = sorted(pathlib.Path(states_dir()).glob("DQ3_J.fc[0-9]"))
    if not every:
        pytest.skip("★DQ3 のセーブステートがありません（⚠ 同梱していません）")
    return [(p, ss.load(p).ram) for p in every]


def test_呪文を覚えているセーブがある():
    """⚠ 「0 件」は通っていないだけ（★材料があることを先に見る）。"""
    got = [p.name for p, ram in _states() if any(SF.learned(ram, c) for c in range(SF.SLOTS))]
    assert got, (
        "⚠⚠ 呪文を 1 つも覚えていないセーブしかありません。"
        "★この検査は `RX3-0071` の裏取りそのものなので、⚠ 消さずに固定し直してください")


def test_覚えた呪文は減らない():
    """★同じ人の枠が、セーブをまたいで**包含の鎖**になること。

    ⚠⚠ 「覚えたものが消えない」は当たり前ですが、★番地や stride がずれていると
    **鎖になりません**（⚠ 別の人のバイトを読んでしまうため）。
    """
    rows = _states()
    for c in range(SF.SLOTS):
        sets = sorted((set(SF.learned(ram, c)) for _p, ram in rows), key=len)
        for small, big in zip(sets, sets[1:]):
            assert small <= big, (
                "⚠⚠ 人%d の枠が鎖になっていません: %s ⊄ %s（★stride か番地を疑う）"
                % (c, sorted(small), sorted(big)))


def test_呪文を覚えない人がいる():
    """★どのセーブでも空の人が居ること（⚠ 全員に立つなら読み違い）。"""
    rows = _states()
    empty = [c for c in range(SF.SLOTS)
             if all(not SF.learned(ram, c) for _p, ram in rows)]
    assert empty, "⚠ 全員が呪文を持っている（★別のものを読んでいないか）"


def test_人の境目をまたいでいない():
    """⚠ stride が 8 でなければ、★別の人のビットを拾って鎖が崩れる。

    ★`STRIDE` を 1 ずらして読むと、⚠ どこかの人で鎖が崩れることを見ます
    （= この検査が**効いている**ことの確認）。
    """
    rows = _states()

    def chain_ok(stride):
        for c in range(SF.SLOTS):
            sets = []
            for _p, ram in rows:
                off = SF.BASE + c * stride
                if off + SF.STRIDE > len(ram):
                    return True                      # ⚠ 読めないなら判定しない
                sets.append({n for n in range(SF.FRAMES)
                             if ram[off + (n >> 3)] & (1 << (n & 7))})
            sets.sort(key=len)
            for small, big in zip(sets, sets[1:]):
                if not small <= big:
                    return False
        return True

    assert chain_ok(SF.STRIDE), "⚠ いまの stride で鎖が崩れている"
    assert not chain_ok(SF.STRIDE + 1), (
        "⚠⚠ stride をずらしても鎖が崩れません（★この検査は空回り）")
