"""BRK far-call を辿る（RX3-0013 ① / 2026-08-31）。

## ⚠⚠ ROM は同梱していません

  ★依頼者の ROM（`work/rom/DQ3_J.nes`）を使います。
  ⚠ 無い環境では skip しますが、★**計算そのものは ROM 無しで確かめます**
  （`y_of` / `entry_of` は表を引く前の話なので）。
"""

from __future__ import annotations

import pathlib

import pytest

from dq3rom import farcall as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"


# --- ★ROM が無くても確かめられること ------------------------------------

def test_索引の計算がハンドラと同じ():
    """★`$EF37 AND #$F0 / ROR / LSR / LSR` をそのまま写したか。

    ⚠⚠ `ROR` は `CMP #$0F` のキャリーを **bit7** に入れます。
      ★だから下位ニブルが `$F` のとき **+32**（⚠ `0x80` ではない）。
    """
    # ★ふつうの sel（下位ニブル ≠ $F）→ 上位ニブル × 2
    for hi in range(16):
        for low in range(15):            # ⚠ $F は除く
            sel = (hi << 4) | low
            assert F.y_of(sel) == hi * 2, hex(sel)
            assert F.entry_of(sel) == hi

    # ⚠ 下位ニブルが $F → +32
    for hi in range(16):
        sel = (hi << 4) | 0x0F
        assert F.y_of(sel) == 32 + hi * 2, hex(sel)
        assert F.entry_of(sel) == 16 + hi


def test_文書の0x80は誤りだった():
    """⚠⚠ `docs/design/dq3-findings.md` は「索引 0x80」と書いていた。

    ★実測は **+32**。⚠ 0x80 だと索引 64 になり、表（20 本）の遥か外です。
    """
    assert F.SPECIAL_STEP == 32
    assert F.entry_of(0x0F) == 16, "★$0F は 17 本目（index 16）"
    assert F.entry_of(0x0F) * 2 != 0x80


def test_表の外を指す組み合わせがある():
    """★下位ニブルが `$F` で上位が 4 以上なら、⚠ 表の**外**。

    ⚠⚠ 実コードには出てこないはず。★データの偶然を弾く手がかり。
    """
    for hi in range(4):
        assert F.in_table((hi << 4) | 0x0F), hex(hi)
    for hi in range(4, 16):
        assert not F.in_table((hi << 4) | 0x0F), hex(hi)


def test_1バイトでないselは弾く():
    for bad in (-1, 256, 0x100):
        with pytest.raises(ValueError):
            F.y_of(bad)


# --- ★ROM が要るもの -----------------------------------------------------

@pytest.fixture(scope="module")
def ident():
    if not ROM.exists():
        pytest.skip("⚠ ROM がありません（★同梱していません）")
    from dq2rom import ines
    from dq3rom import profile as P

    return P.identify(ines.load(ROM))


def test_ベクタが文書どおり(ident):
    """★`$FFFE`（IRQ/BRK）= `$EF11`。⚠ ここが違えば全部の前提が崩れる。"""
    win = ident.window(ident.rom.fixed_bank)
    got = win[0xFFFE - 0xC000] | (win[0xFFFF - 0xC000] << 8)
    assert got == 0xEF11, "⚠⚠ IRQ/BRK ベクタが違う: $%04X" % got


def test_表は20本で直後はコード(ident):
    """★本数の根拠は「直後が素直なコードであること」。

    ⚠ `$EE96` は `CLD / LDA #$FF / STA $1B / LDA $2002 / BPL`。
    """
    from retroux.core.bgmap import disasm

    win = ident.window(ident.rom.fixed_bank)
    assert F.ENTRIES == 20
    after = F.TABLE_CPU + F.ENTRIES * 2
    assert after == 0xEE96, hex(after)
    ins = disasm.decode(win, after - 0xC000, after)
    assert ins is not None and ins.mnemonic == "CLD", (
        "⚠⚠ 表の直後がコードでない（★本数が違うかも）")


def test_表の行き先がみな番地らしい(ident):
    """⚠ 1 本でもゴミなら、★本数の見立てが間違っている。"""
    for i, t in enumerate(F.targets(ident)):
        assert 0x8000 <= t <= 0xFFFF, "⚠⚠ entry %d が $%04X" % (i, t)


def test_バンクへ辿れる入口がある(ident):
    """★`LDX #$nn` で始まる入口は、その `nn` がバンク。"""
    got = {i: F.bank_of(ident, t) for i, t in enumerate(F.targets(ident))}
    known = {i: b for i, b in got.items() if b is not None}
    assert len(known) >= 7, "⚠ バンクへ辿れる入口が %d 本しかない" % len(known)
    for i, b in known.items():
        assert 0 <= b < ident.rom.prg_banks


def test_切替窓の行き先は分からないと言う(ident):
    """⚠⚠ **推測しないこと。** ★$8000-$BFFF はそのときのバンク次第。"""
    for t in F.targets(ident):
        if 0x8000 <= t <= 0xBFFF:
            assert F.bank_of(ident, t) is None, (
                "⚠⚠ 切替窓なのにバンクを決めつけている: $%04X" % t)


def test_呼び出しを1件読める(ident):
    """★固定バンクに実在する `BRK`（`$EEC9`）を読む。"""
    call = F.read_call(ident, ident.rom.fixed_bank, 0xEEC9)
    assert call is not None, "⚠ `$EEC9` が BRK でない"
    assert call.sel == 0x07 and call.entry == 0
    assert call.target == 0xC48C
    assert "entry 0" in call.describe()


def test_BRKでなければNoneを返す(ident):
    """⚠ 推測で読まない。"""
    assert F.read_call(ident, ident.rom.fixed_bank, 0xEF11) is None


def test_絞り込みが効いていないことを記録する(ident):
    """⚠⚠ **これは「効いた」検査ではありません。**

    ★`00` の 97% が「表の中」を指します。⚠ つまり
    「表の中を指すか」では**データの偶然をほとんど弾けません**。

    ★この事実が変わったら気づけるように、ここに固定します。
    """
    win = ident.window(0)
    raw = sum(1 for o in range(len(win) - 2) if win[o] == 0)
    got = len(F.scan(ident, 0))
    assert raw > 0
    assert got / raw > 0.8, (
        "⚠ 絞り込みが急に効くようになった（★%d/%d）。仕組みを見直すこと"
        % (got, raw))


# --- ★★ arg → (bank, 番地)（RX3-0013 ①）--------------------------------

def test_2つの表が隙間なく並んでいる():
    """★本数の根拠。⚠ バンク表は 1 バイトに 2 件なので、ちょうど半分。"""
    assert F.BANK_CPU + (F.ROUTINES + 1) // 2 == F.INDEX_CPU, (
        "⚠⚠ バンク表と索引表の間に隙間がある（★本数の見立てが違う）")
    assert F.INDEX_CPU + F.ROUTINES == 0xFED9, "⚠ 索引表の終わりが違う"


def test_argからbankと番地が出る(ident):
    got = F.routine(ident, 0)
    assert got is not None
    assert 0 <= got.bank < ident.rom.prg_banks
    assert got.address is not None and got.sane
    assert "bank" in got.describe()


def test_ほとんどのargがまともな番地を指す(ident):
    """⚠⚠ **ここが本数の見立ての裏づけ**。

    ★表の外を読んでいれば、番地はでたらめになるはずです。
    """
    got = F.routines(ident)
    assert len(got) == F.ROUTINES
    ok = sum(1 for r in got if r.sane)
    assert ok / len(got) > 0.95, (
        "⚠⚠ まともな番地が %d/%d しかない（★表の見立てを疑うこと）"
        % (ok, len(got)))


def test_バンク番号が範囲に収まる(ident):
    for r in F.routines(ident):
        assert 0 <= r.bank < ident.rom.prg_banks, r.describe()


def test_ニブルの取り出しが奇偶で分かれている(ident):
    """★`$C506 AND #$01` の分岐を写したか。

    ⚠ 同じバイトから、偶数は上位・奇数は下位を取る。
    """
    win = ident.window(ident.rom.fixed_bank)
    for arg in (0, 1, 10, 11, 200, 201):
        packed = win[F.BANK_CPU - 0xC000 + (arg >> 1)]
        want = (packed & 0x0F) if (arg & 1) else (packed >> 4)
        assert F.routine(ident, arg).bank == want, arg


def test_表の外のargはNone(ident):
    assert F.routine(ident, F.ROUTINES) is None
    assert F.routine(ident, -1) is None


def test_argは1バイトなのに表は256本より多い(ident):
    """⚠⚠ **`arg` は 1 バイト（0..255）なのに、表は 411 本**。

    ★256 以降も同じくらいまともな番地を指すので、⚠ 表そのものは本物。
    ★2026-09-16（`RX3-0081` ②）: **届く入口が見つかりました** = entry 1。
    → 下の「entry 1 は 256 の下駄」を見てください。
    """
    assert F.ROUTINES > 256
    tail = [r for r in F.routines(ident)[256:]]
    ok = sum(1 for r in tail if r.sane)
    assert ok / len(tail) > 0.95, (
        "⚠ 256 以降がでたらめ（★表は 256 本かもしれない）: %d/%d"
        % (ok, len(tail)))


def test_argをroutine番号として読めるのはentry0だけ(ident):
    """⚠⚠ **ここを間違えると、まるで違う処理を指します。**

    ★entry 0（`$C48C`）は `Y`（＝arg）をそのまま渡します。
    ⚠ ほかの入口は踏み台で、`$FF07 TYA / BRK $A0 $07` のように
    **`Y` を自分の値に差し替えます**。

    → ★`BRK $82 $2F`（entry 18）は「routine $82」ではなく、
      「routine $A0 を A=$82 で呼ぶ」。
    """
    #: ★entry 0 になる sel（⚠ 上位ニブル 0 かつ下位 ≠ $F）
    yes = F.read_call(ident, ident.rom.fixed_bank, 0xD276)
    assert yes is not None and yes.entry == 0
    assert yes.arg_is_routine, "⚠ entry 0 なのに読めないことになっている"

    #: ⚠ entry 18（sel=$2F → 下位 $F・上位 2）
    no = F.read_call(ident, ident.rom.fixed_bank, 0xD279)
    assert no is not None and no.entry == 18
    assert not no.arg_is_routine, (
        "⚠⚠ 踏み台の入口で arg を routine 番号として読んでいる")


def test_実コードのBRKが全部たどれる(ident):
    """★地図を移る処理（`$D276` 以降）の `BRK` が、みな解ける。

    ⚠ ここが通らなければ、仕組みの読みがどこか違います。
    """
    got = []
    for cpu in (0xD276, 0xD279, 0xD290, 0xD293, 0xD2AB):
        call = F.read_call(ident, ident.rom.fixed_bank, cpu)
        assert call is not None, "⚠ $%04X が BRK でない" % cpu
        assert call.target is not None, "⚠ 表の外: $%04X" % cpu
        got.append(call)
    #: ★entry 0 のものは routine まで解ける
    zero = [c for c in got if c.arg_is_routine]
    assert len(zero) >= 4, "⚠ entry 0 が %d 件しかない" % len(zero)
    for c in zero:
        r = F.routine(ident, c.arg)
        assert r is not None and r.sane, (
            "⚠ routine が解けない: %s" % c.describe())

# ----------------------------------------------------------------------
# ★★ entry 1 は「256 の下駄」（RX3-0081 ② / 2026-09-16）
#
#   ⚠ ここは長らく「256 以降へ届く入口があるはず（まだ確かめていない）」でした。
# ----------------------------------------------------------------------
def test_entry1が256の下駄であることをROMで確かめる(ident):
    """⚠ 「そういう値がある」ではなく、★**2 つのルーチンが表の番地だけ違う**ことを見る。"""
    assert F.verify_routine_entries(ident) == []
    assert F.ROUTINE_BASE == {0: 0, 1: 256}
    assert F.LOOKUP_HI_CPU != F.LOOKUP_LO_CPU


def test_上と下のルーチンは表の番地しか違わない(ident):
    """★ここが裏取りの本体（⚠ 1 バイトでも他が違ったら、読みが違う）。"""
    win = ident.window(ident.rom.fixed_bank)

    def code(cpu, n=0x16):
        off = cpu - 0xC000
        return bytes(win[off:off + n])

    lo, hi = code(F.LOOKUP_LO_CPU), code(F.LOOKUP_HI_CPU)
    diff = [i for i, (a, b) in enumerate(zip(lo, hi)) if a != b]
    assert len(diff) == 2, "⚠ 違うバイトが %d 個ある: %s" % (len(diff), diff)
    # ★通し番号の表が +256（上位バイトが 1 つ上）/ バンク表が +128
    assert hi[diff[0]] - lo[diff[0]] == 1, "★$FD3E → $FE3E（+256）"
    assert hi[diff[1]] - lo[diff[1]] == 0x80, "★$FC70 → $FCF0（+128 バイト = +256 件）"


def test_下駄を足すと表の本数にちょうど届く():
    """⚠ 2 本の入口で 0..511 まで届き、★表は 411 本（足りる）。"""
    assert max(F.ROUTINE_BASE.values()) + 0xFF >= F.ROUTINES - 1
    assert min(F.ROUTINE_BASE.values()) == 0


def test_台本番号はentryで決まる(ident):
    """★`BRK <arg> $07` は arg、`BRK <arg> $17` は **256 + arg**。"""
    #: ★entry 0（sel = $0x / 下位ニブル ≠ $F）
    zero = F.read_call(ident, ident.rom.fixed_bank, 0xD276)
    assert zero is not None and zero.entry == 0
    assert zero.routine_number == zero.arg

    #: ★entry 1（sel = $17）… map 98 のイベント（bank0 `$AE53`）
    one = F.read_call(ident, 0, 0xAE53)
    assert one is not None and (one.arg, one.sel) == (0x56, 0x17), one.describe()
    assert one.entry == 1
    assert one.routine_number == 0x56 + 256 == 342
    assert not one.arg_is_routine, "⚠ arg そのものは番号ではない（★256 の下駄が要る）"

    #: ⚠ 踏み台の入口は番号を出さない
    no = F.read_call(ident, ident.rom.fixed_bank, 0xD279)
    assert no is not None and no.entry == 18 and no.routine_number is None


def test_entry1の台本がまともな番地を指す(ident):
    """⚠ 番号が出るだけでは足りない。★引いた先が窓に収まること。"""
    one = F.read_call(ident, 0, 0xAE53)
    r = F.routine(ident, one.routine_number)
    assert r is not None and r.sane, r.describe() if r else None
    #: ⚠ 下駄を忘れると別の処理を指す（★同じ番地であってはならない）
    wrong = F.routine(ident, one.arg)
    assert (wrong.bank, wrong.address) != (r.bank, r.address), (
        "⚠⚠ 256 を足さなくても同じ所を指す（★検査が空回りしている）")


def test_sel17は実コードに沢山ある(ident):
    """★entry 1 は珍しい入口ではない（⚠ 数えているのは候補で、証明ではない）。"""
    got = [c for b in range(ident.rom.prg_banks) for c in F.scan(ident, b)]
    one = [c for c in got if c.entry == 1]
    zero = [c for c in got if c.entry == 0]
    assert len(one) > 500, "⚠ entry 1 の候補が %d 件しかない" % len(one)
    assert len(zero) > len(one), "★entry 0 のほうが多いはず"

class _Patched:
    """★固定バンクの 1 バイトだけ差し替えた写し（⚠ ファイルは触らない）。"""

    def __init__(self, ident, cpu: int, value: int) -> None:
        self._ident = ident
        self.rom = ident.rom
        win = bytearray(ident.window(ident.rom.fixed_bank))
        win[cpu - 0xC000] = value
        self._win = bytes(win)

    def window(self, bank: int):
        if bank == self.rom.fixed_bank:
            return self._win
        return self._ident.window(bank)


def test_ROMが1バイト違えば照合が鳴る(ident):
    """⚠⚠ 照合器そのものを試す。

    ★合っているものだけ渡すと、`verify_routine_entries` を**短くしても**
    **食い違いを捨てても**緑のままになります（2026-09-16 に実際そうなった）。
    """
    #: ★ルーチンの**終わりのほう**（$C4F3 = JMP の opcode）を変える
    win = ident.window(ident.rom.fixed_bank)
    at = F.LOOKUP_HI_CPU + 0x13
    assert win[at - 0xC000] == 0x4C, "★見本の位置がずれた（実装が変わった）"
    bad = F.verify_routine_entries(_Patched(ident, at, 0xEA))
    assert bad and "差し替え" in bad[0], bad

    #: ★飛び先表の entry 1 を変える（⚠ $EE6E + 1*2 の下位バイト）
    bad = F.verify_routine_entries(_Patched(ident, F.TABLE_CPU + 2, 0x00))
    assert bad and any("entry 1" in line for line in bad), bad
