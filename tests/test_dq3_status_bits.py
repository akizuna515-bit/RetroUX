"""状態の旗と呪文の対応を ROM で固定する（RX3-0337 §7 / 依頼者の §13-K）。

## ⚠⚠ なぜこの検査が要るのか

★2026-09-21 に**マヌーサとメダパニを取り違えました**（RX3-0338）。
⚠ 付与ルーチンが 100 バイト離れた**双子**で、どちらも `ORA #$10`、
★違うのは**書き先のバイトだけ**でした。

```text
$0530,X bit4  ★マヌーサ（surround）  → 物理に追加のミス判定（5/8）
$0531,X bit4  ★メダパニ（chaos）     → 行動／対象の変更（★敵同士の攻撃はこちら）
$0531,X bit5  ★ラリホー（sleep）     → 行動を止める
```

⚠ 名前や近さで見分けようとすると、また同じ間違いをします。
→ ★**ROM のバイト列**で固定します（⚠ 文書だけに書いても守られない）。
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "input" / "Dragon Quest 3 (J).nes"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が読めない環境")

#: ★bank 4 は $8000〜$BFFF に見える
BANK = 4


@pytest.fixture(scope="module")
def prg() -> bytes:
    if not ROM.exists():
        pytest.skip("⚠ ROM が読めない環境")
    return ROM.read_bytes()[16:]


def at(addr: int) -> int:
    """★bank 4 の CPU 番地 → ファイルの位置。"""
    return BANK * 0x4000 + (addr - 0x8000)


def code(prg: bytes, addr: int, n: int) -> bytes:
    return prg[at(addr) : at(addr) + n]


# ======================================================================
# ★1. 付与ルーチン（★どの呪文がどのバイトのどの bit を立てるか）
# ======================================================================
@needs_rom
def test_マヌーサは状態0のbit4を立てる(prg: bytes) -> None:
    """★JP bank4 `$9F04`: `LDA $0530,X / ORA #$10 / STA $0530,X`。"""
    assert code(prg, 0x9F04, 8) == bytes.fromhex("bd 30 05 09 10 9d 30 05".replace(" ", ""))


@needs_rom
def test_メダパニは状態1のbit4を立てる(prg: bytes) -> None:
    """★JP bank4 `$9F68`: `LDA $0531,X / ORA #$10 / STA $0531,X`。

    ⚠⚠ マヌーサと**同じ `ORA #$10`**。★違うのは `$0530` か `$0531` かだけ。
    """
    assert code(prg, 0x9F68, 8) == bytes.fromhex("bd 31 05 09 10 9d 31 05".replace(" ", ""))


@needs_rom
def test_ラリホーは状態1のbit5を立ててカウンタを3にする(prg: bytes) -> None:
    """★JP bank4 `$9DC3`: 旗（bit5）＋ `$0530` の下位 2bit を 3 に。"""
    got = code(prg, 0x9DC3, 16)
    # ★LDA $0531,X / ORA #$20 / STA $0531,X   ← 眠りの旗（bit5）
    assert got[:8] == bytes.fromhex("bd 31 05 09 20 9d 31 05".replace(" ", ""))
    # ★LDA $0530,X / ORA #$03 / STA $0530,X   ← 目覚めのカウンタ（下位 2bit）
    assert got[8:16] == bytes.fromhex("bd 30 05 09 03 9d 30 05".replace(" ", ""))


@needs_rom
def test_ラリホーのカウンタは3から始まる(prg: bytes) -> None:
    got = code(prg, 0x9DCB, 8)
    assert got == bytes.fromhex("bd 30 05 09 03 9d 30 05".replace(" ", ""))


# ======================================================================
# ★2. 効き方（★マヌーサ = 物理の追加ミス 5/8）
# ======================================================================
@needs_rom
def test_マヌーサは物理攻撃に5対8のミスを足す(prg: bytes) -> None:
    """★JP bank4 `$8C24` から: 状態 0 の bit4 → 乱数 → `CMP #$A0` で外す。

    ```text
    BD 30 05  LDA $0530,X
    29 10     AND #$10
    F0 1C     BEQ  命中へ
    20 63 AD  JSR  乱数
    C9 A0     CMP  #$A0      ← ★160 / 256 = 5/8 で外す
    B0 15     BCS  命中へ
    ```
    """
    got = code(prg, 0x8C24, 12)
    assert got == bytes.fromhex("bd 30 05 29 10 f0 1c 20 63 ad c9 a0".replace(" ", ""))
    # ★命中率は (256 - 160) / 256
    assert (256 - 0xA0) / 256 == 0.375


@needs_rom
def test_マヌーサのミス判定に敵の数を見る分岐は無い(prg: bytes) -> None:
    """⚠⚠ 前回「敵 1 体では無効」と書いた誤りの再発防止（RX3-0338）。

    ★`$8C24`〜`$8C32` の 15 バイトに、⚠ 生存敵数（`$4D`）を読む命令が無いこと。
    """
    got = code(prg, 0x8C24, 15)
    assert b"\xa6\x4d" not in got, "⚠ LDX $4D（生存敵数）がミス判定に入っている"
    assert b"\xa5\x4d" not in got, "⚠ LDA $4D（生存敵数）がミス判定に入っている"


@needs_rom
def test_敵の幻には自然解除が無い(prg: bytes) -> None:
    """★`$0530,X` へ書き戻す命令のうち、⚠ bit4 を落とすもの（`AND #$EF`）が無いこと。

    ⚠ 落とすのは戦闘の初期化（`LDA #$00 / STA $0530,X`）だけ。
    """
    import re

    # ⚠ AND #imm のあと $0530,X へ書き戻す形を全部見る
    for m in re.finditer(rb"\x29(.)\x9d\x30\x05", prg, re.S):
        mask = m.group(1)[0]
        assert mask != 0xEF, (
            "⚠⚠ 敵の幻を落とす命令が見つかった（★仕様が変わったか、読み違い）: "
            "offset=%#x" % m.start()
        )


@needs_rom
def test_敵の眠りだけが毎ターン解除される(prg: bytes) -> None:
    """★`$0531,X` の bit5 を落とす（`AND #$DF`）のは 1 か所だけ。"""
    import re

    hits = [m.start() for m in re.finditer(rb"\x29\xdf\x9d\x31\x05", prg)]
    assert len(hits) == 1, "⚠ 眠りの解除が %d か所ある（★1 か所のはず）" % len(hits)


@needs_rom
def test_眠りの閾値表(prg: bytes) -> None:
    """★JP bank4 `$B4F3` = `FF C0 80 40`（⚠ カウンタ 0,1,2,3 の順）。

    ★目覚めの確率 = (閾値 + 1) / 256 → 1.000 / 0.754 / 0.504 / 0.254。
    """
    assert code(prg, 0xB4F3, 4) == bytes.fromhex("ffc08040")


# ======================================================================
# ★3. 戦闘 AI 側の値
# ======================================================================
#
# ⚠ ここには**字面の検査を置きません**（★`.lua` を grep しても「動いた」証拠にならない）。
#   ★AI が使う値は Lua の足場が**実際に読んで**見ています:
#
#   ```text
#   SVF  Actions.ILLUSION_HIT_RATE == 0.375     research/probes/active/dq3_ai_test.lua
#   SVC  Actions.SLEEP_EXPECTED_TURNS == 2.207  同上
#   ```
#
#   ★このファイルの役目は「**ROM 側の根拠**が動いていないこと」です。
#   ⚠ 2 つがずれたら、上の足場が赤になります（★壊す実験 ④ で確認済み）。


def test_耐性の名前が呪文と対応している() -> None:
    """★`surround` = 9 / `chaos` = 11 / `sleep` = 6（⚠ 取り違えの元）。"""
    from dq3rom.enemy_detail import RESISTANCES

    by_index = {row[0]: row[3] for row in RESISTANCES}
    assert by_index[6] == "sleep"
    assert by_index[9] == "surround"
    assert by_index[11] == "chaos"
