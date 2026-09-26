"""BRK far-call を辿る（RX3-0013 ① / 2026-08-31）。

## ★★ 仕組み（⚠ ROM で裏を取った）

`$FFFE`（IRQ/BRK ベクタ）＝ `$EF11`。そのハンドラの実測:

```text
$EF19  TSX
$EF1A  LDA $0102,X  / SBC #$01 -> $21     ★戻り先 -1 ＝「BRK の次のバイト」
$EF22  LDA $0103,X  / SBC #$00 -> $22
$EF2B  LDA ($21),Y  (Y=0)  -> X           ★1 バイト目 = arg
$EF2F  LDA ($21),Y  (Y=1)                 ★2 バイト目 = sel
$EF32  AND #$0F / CMP #$0F                ⚠ 下位ニブルが $F か（★C に残す）
$EF37  AND #$F0 / ROR / LSR / LSR -> Y    ⚠⚠ **ROR がその C を bit7 に入れる**
$EF3D  LDA $EE6E,Y / LDA $EE6F,Y -> $21/$22
$EF47  TXA / TAY                          ★arg を Y へ
$EF4E  JMP ($0021)
```

★式にすると:

```text
Y = ((sel & 0xF0) >> 3) + (32 if (sel & 0x0F) == 0x0F else 0)
entry = Y // 2
```

## ⚠⚠ 文書の訂正

`docs/design/dq3-findings.md` には
「⚠ 下位ニブルが $F のときだけ索引 **0x80**（→ `$388A`）」とありましたが、
★実測では **+32** です。⚠ `$388A` は表の中に**1 つもありません**。

## ★表は 20 本（⚠ これも実測）

`$EE6E` から 20 ワード（40 バイト）。★直後の `$EE96` は素直なコードです
（`CLD / LDA #$FF / STA $1B / LDA $2002 / BPL`）。

```text
entry 0..15   ふつうの sel（★下位ニブル ≠ $F）
entry 16..19  ⚠ 下位ニブルが $F のとき。★hi は 0〜3 しか使えない
```

⚠ つまり `sel & 0x0F == 0x0F` かつ `sel >> 4 >= 4` は**表の外**へ飛びます。
★実コードには出てこないはずで、それが「データの偶然」を弾く手がかりになります。

## ★entry → バンク

⚠ 行き先が `LDX #$nn` で始まっていれば、その `nn` が**バンク番号**です。

```text
$FEE3  LDX #$00 / BEQ $FF0C     ★bank 0
$FEE7  LDX #$01 / BNE $FF0C     ★bank 1
   …
$FF0C  TYA / BRK 04 07 / RTS    ⚠⚠ **入れ子の BRK**（→ entry 0 = $C48C）
$C48C  STA $36 / STX $34 / LDA $06D5 / PHA …   ★バンクを切り替えて呼ぶ本体
```

## ⚠ ここまでで**分からない**こと

```text
⚠ 行き先が $8000-$BFFF（切替窓）の entry は、★そのときのバンク次第
⚠ arg（Y）は「そのバンクの何番目の処理か」の索引。
  ★本当の番地を出すには、バンクごとの表の頭が要る（→ 次の段）
```
"""

from __future__ import annotations

import dataclasses

from . import profile as P

#: ★ワード表の先頭（⚠ 固定バンク）
TABLE_CPU = 0xEE6E
#: ★本数（⚠ 実測。★直後 `$EE96` はコード）
ENTRIES = 20
#: ⚠ この下位ニブルのときだけ、索引が +32 される
SPECIAL_LOW = 0x0F
#: ⚠ ハンドラが足す量（★`ROR` が C を bit7 に入れるため）
SPECIAL_STEP = 32

#: ★切替窓（⚠ ここへ飛ぶ entry は、そのときのバンク次第）
SWITCH_LO, SWITCH_HI = 0x8000, 0xBFFF
#: ★`LDX #$nn`
LDX_IMM = 0xA2


def y_of(sel: int) -> int:
    """★ハンドラと**同じ計算**で、表のバイト位置を出す。

    ⚠ ここが唯一の実装。★呼ぶ側で `sel >> 4` と書かないこと。
    """
    if not 0 <= sel <= 0xFF:
        raise ValueError("⚠ sel が 1 バイトではありません: %r" % (sel,))
    y = (sel & 0xF0) >> 3
    if (sel & 0x0F) == SPECIAL_LOW:
        y += SPECIAL_STEP
    return y


def entry_of(sel: int) -> int:
    """★何番目の入口か（⚠ 表の外なら `ENTRIES` 以上）。"""
    return y_of(sel) // 2


def in_table(sel: int) -> bool:
    """★表の中を指しているか。⚠ 外なら実コードではありえない。"""
    return entry_of(sel) < ENTRIES


def targets(ident: P.Identified) -> list[int]:
    """★20 本の行き先（CPU 番地）。"""
    win = ident.window(ident.rom.fixed_bank)
    base = TABLE_CPU - 0xC000
    return [win[base + i * 2] | (win[base + i * 2 + 1] << 8)
            for i in range(ENTRIES)]


def bank_of(ident: P.Identified, target: int):
    """⚠ その行き先が `LDX #$nn` で始まっていれば、その `nn`。★無ければ None。

    ⚠⚠ **推測しません。** `LDX #` 以外なら「分からない」を返します。
    """
    if not 0xC000 <= target <= 0xFFFF:
        return None                      # ⚠ 切替窓はそのときのバンク次第
    win = ident.window(ident.rom.fixed_bank)
    off = target - 0xC000
    if off + 1 >= len(win) or win[off] != LDX_IMM:
        return None
    got = win[off + 1]
    return got if 0 <= got < ident.rom.prg_banks else None


@dataclasses.dataclass(frozen=True)
class Call:
    """★1 か所の `BRK arg sel`。"""

    bank: int
    cpu: int          #: ★`BRK` そのものの番地
    arg: int          #: ★Y に入る（⚠ そのバンクでの索引）
    sel: int
    entry: int
    target: int | None      #: ★飛び先（⚠ 表の外なら None）
    to_bank: int | None     #: ★切り替わる先（⚠ 分からなければ None）

    @property
    def arg_is_routine(self) -> bool:
        """★`arg` を routine 番号として読んでよいか。

        ⚠⚠ **entry 0 のときだけ**です。

          ★entry 0（`$C48C`）は `Y`（＝arg）をそのまま `$C501` へ渡す。
          ⚠ ほかの入口は踏み台で、★**`Y` を自分の値に差し替えます**。

          ```text
          $FF07  TYA           ★元の arg を A へ退避
                 BRK $A0 $07   ⚠⚠ Y は $A0 に**入れ替わる**
                 RTS
          ```

          → ⚠ entry 18 の `BRK $82 $2F` は「routine $82」ではなく、
            ★「routine $A0 を A=$82 で呼ぶ」です。

        ⚠ 2026-09-16（`RX3-0081`）: **entry 1 も `arg` をそのまま渡します**が、
        ★指すのは `256 + arg` です。→ 番号が要るときは `routine_number` を使ってください
        （⚠ ここは「`arg` **そのもの**が番号か」を返すので、entry 0 だけのままです）。
        """
        return self.entry == 0

    @property
    def routine_number(self) -> int | None:
        """★この呼び出しが指す routine の通し番号。⚠ 踏み台の入口なら `None`。

        ```text
        entry 0（sel = $0x）… arg          ★通し番号 0..255
        entry 1（sel = $1x）… arg + 256    ★通し番号 256..410
        ```

        ⚠ `sel` の下位ニブルが `$F` のものは別の入口（+32）なので、ここには来ません。
        """
        base = ROUTINE_BASE.get(self.entry)
        return None if base is None else base + self.arg

    @property
    def switched(self) -> bool:
        """⚠ 行き先が切替窓か（★そのときのバンク次第で決まらない）。"""
        return self.target is not None and SWITCH_LO <= self.target <= SWITCH_HI

    def describe(self) -> str:
        who = ("bank %d" % self.to_bank) if self.to_bank is not None else (
            "⚠ 切替窓（そのときのバンク次第）" if self.switched else "⚠ 不明")
        tgt = "$%04X" % self.target if self.target is not None else "⚠ 表の外"
        return ("bank%d:$%04X  BRK arg=$%02X sel=$%02X → entry %d → %s / %s"
                % (self.bank, self.cpu, self.arg, self.sel,
                   self.entry, tgt, who))


def read_call(ident: P.Identified, bank: int, cpu: int) -> Call | None:
    """★その番地の `BRK arg sel` を読む。⚠ `BRK` でなければ None。"""
    win = ident.window(bank)
    base = 0xC000 if bank == ident.rom.fixed_bank else 0x8000
    off = cpu - base
    if off < 0 or off + 2 >= len(win) or win[off] != 0x00:
        return None
    arg, sel = win[off + 1], win[off + 2]
    entry = entry_of(sel)
    if entry >= ENTRIES:
        return Call(bank, cpu, arg, sel, entry, None, None)
    tgt = targets(ident)[entry]
    return Call(bank, cpu, arg, sel, entry, tgt, bank_of(ident, tgt))


def scan(ident: P.Identified, bank: int, *, only_valid: bool = True):
    """⚠⚠ そのバンクの `BRK` **候補**を全部返す。

    ★`only_valid` なら「表の中を指すもの」だけ。

    ⚠⚠ **これは「呼び出しである」ことの証明ではありません。**
      ROM 全体で `00 xx yy` は 1 万件以上あり、★大半はデータの中の偶然です
      （`docs/design/dq3-findings.md`）。⚠ 到達可能性は見ていません。
    """
    win = ident.window(bank)
    base = 0xC000 if bank == ident.rom.fixed_bank else 0x8000
    got = []
    for off in range(len(win) - 2):
        if win[off] != 0x00:
            continue
        call = read_call(ident, bank, base + off)
        if call is None:
            continue
        if only_valid and call.target is None:
            continue
        got.append(call)
    return got


# ---------------------------------------------------------------------
# ★★ arg → (bank, 番地)（RX3-0013 ① / 2026-08-31）
# ---------------------------------------------------------------------
#
#   ⚠ `$C48C`（バンク切替の本体）が `$C501` を呼び、そこで組み立てる。
#
#   ```text
#   $C501  LDA $FD3E,Y        ★そのバンクでの**通し番号**
#          TYA / AND #$01     ⚠ 奇偶でニブルを選ぶ
#          LDA $FC70,Y>>1     ★**バンク番号**（⚠ 1 バイトに 2 件）
#          JSR $FFBD          ★バンクを切り替える
#          PLA / ASL / TAY
#          LDA $8000,Y        ★切り替えた先の $8000 の表を引く
#   ```

#: ★通し番号の表（⚠ 固定バンク）
INDEX_CPU = 0xFD3E
#: ★バンク番号の表（⚠ 1 バイトに 2 件。★偶数が上位ニブル）
BANK_CPU = 0xFC70
#: ★本数（⚠ 次に来る `$FED9`（entry 13 の入口）まで）
ROUTINES = 0xFED9 - INDEX_CPU
#: ★切り替えた先の、routine の表
PER_BANK_TABLE = 0x8000

# ---------------------------------------------------------------------
# ★★ 256 以降へ届く入口（RX3-0081 ② / 2026-09-16）
# ---------------------------------------------------------------------
#
#   ⚠ ここには長いあいだ「arg は 1 バイトなのに表は 411 本。256 以降へ届く
#     別の入口があるはず（★まだ確かめていない）」と書いてありました。
#   ★**ありました。** 飛び先表の **entry 1**（`$C454`）です。
#
#   ```text
#   entry 0  $C48C → $C501  LDA $FD3E,Y / LDA $FC70,(Y>>1)   ★通し番号 0..255
#   entry 1  $C454 → $C4E0  LDA $FE3E,Y / LDA $FCF0,(Y>>1)   ★通し番号 256 + arg
#   ```
#
#   ⚠⚠ **2 つのルーチンは、表の番地 2 か所を除いて 1 バイトも違いません**
#   （★`verify_routine_entries` がそれを見張ります）。
#
#   ```text
#   $FE3E = $FD3E + 256    ★通し番号の表の 256 本目から
#   $FCF0 = $FC70 + 128    ★バンク表は 1 バイトに 2 件 → +128 バイト = +256 件
#   ```

#: ★通し番号を引くルーチン（⚠ 固定バンク）
LOOKUP_LO_CPU = 0xC501
LOOKUP_HI_CPU = 0xC4E0

#: ★entry → `arg` に足す下駄（⚠ ここに無い entry は踏み台）
ROUTINE_BASE: dict[int, int] = {0: 0, 1: 256}

#: ★`arg` をそのまま渡す入口（⚠ 表の位置ではなく、飛び先の番地で持つ）
ROUTINE_ENTRY_CPU = {0: 0xC48C, 1: 0xC454}


@dataclasses.dataclass(frozen=True)
class Routine:
    """★`arg` 1 つが指す処理。"""

    arg: int
    index: int            #: ★そのバンクでの通し番号
    bank: int
    address: int | None   #: ★`$8000` の表から引いた番地（⚠ 読めなければ None）
    fixed: bool = False   #: ⚠ 固定バンク（★窓が $C000-$FFFF）

    @property
    def sane(self) -> bool:
        """★番地が、そのバンクの窓に収まっているか。"""
        if self.address is None:
            return False
        if self.fixed:
            return 0xC000 <= self.address <= 0xFFFF
        return 0x8000 <= self.address <= 0xBFFF

    def describe(self) -> str:
        a = "$%04X" % self.address if self.address is not None else "⚠ 読めない"
        tail = "" if self.sane else "  ⚠ 窓の外"
        return ("arg=$%02X (#%d) → bank %d %s%s"
                % (self.arg, self.index, self.bank, a, tail))


def routine(ident: P.Identified, arg: int):
    """★`arg` から `(bank, 番地)` を出す。⚠ 表の外なら None。

    ⚠⚠ **これは「その arg が実際に呼ばれる」証明ではありません。**
      ★表を引いただけです。

    ⚠⚠ **`Call.arg` を渡してよいのは `arg_is_routine` が真のときだけ。**
      ★ほかの入口は踏み台で `Y` を差し替えます（★`$FF07` を見ること）。
    """
    if not 0 <= arg < ROUTINES:
        return None
    fixed_win = ident.window(ident.rom.fixed_bank)
    idx = fixed_win[INDEX_CPU - 0xC000 + arg]
    packed = fixed_win[BANK_CPU - 0xC000 + (arg >> 1)]
    # ⚠ 偶数は上位ニブル、奇数は下位ニブル（★`$C506 AND #$01` で分岐）
    bank = (packed & 0x0F) if (arg & 1) else (packed >> 4)
    if not 0 <= bank < ident.rom.prg_banks:
        return Routine(arg, idx, bank, None, False)
    win = ident.window(bank)
    off = idx * 2
    addr = None
    if off + 1 < len(win):
        addr = win[off] | (win[off + 1] << 8)
    return Routine(arg, idx, bank, addr, bank == ident.rom.fixed_bank)


def routines(ident: P.Identified):
    """★全部（⚠ `ROUTINES` 本）。"""
    return [routine(ident, a) for a in range(ROUTINES)]


def verify_routine_entries(ident: P.Identified) -> list[str]:
    """★「entry 1 は 256 の下駄」を ROM で確かめる。空なら一致（RX3-0081 ②）。

    ⚠ 「そういう値がある」ではなく、★**2 つのルーチンが表の番地だけ違う**
    ことを見ます（⚠ 片方が書き換わったら鳴る）。
    """
    problems: list[str] = []
    win = ident.window(ident.rom.fixed_bank)

    def code(cpu: int, n: int) -> bytes:
        off = cpu - 0xC000
        return bytes(win[off:off + n])

    n = 0x16
    lo, hi = code(LOOKUP_LO_CPU, n), code(LOOKUP_HI_CPU, n)
    want = (lo.replace(bytes((INDEX_CPU & 0xFF, INDEX_CPU >> 8)),
                       bytes(((INDEX_CPU + 256) & 0xFF, (INDEX_CPU + 256) >> 8)))
              .replace(bytes((BANK_CPU & 0xFF, BANK_CPU >> 8)),
                       bytes(((BANK_CPU + 128) & 0xFF, (BANK_CPU + 128) >> 8))))
    if hi != want:
        problems.append("$%04X が $%04X の「表だけ差し替え」になっていない: %s ≠ %s"
                        % (LOOKUP_HI_CPU, LOOKUP_LO_CPU, hi.hex(), want.hex()))
    if want == lo:
        problems.append("⚠ 差し替えが起きていない（★表の番地が読めていない）")

    tgt = targets(ident)
    for entry, cpu in ROUTINE_ENTRY_CPU.items():
        if tgt[entry] != cpu:
            problems.append("entry %d の行き先が $%04X ではなく $%04X"
                            % (entry, cpu, tgt[entry]))
    # ★entry 1 が「上の表」を引くルーチンを呼んでいること（`JSR $C4E0`）
    call = bytes((0x20, LOOKUP_HI_CPU & 0xFF, LOOKUP_HI_CPU >> 8))
    if call not in code(ROUTINE_ENTRY_CPU[1], 0x14):
        problems.append("entry 1（$%04X）が JSR $%04X を含まない"
                        % (ROUTINE_ENTRY_CPU[1], LOOKUP_HI_CPU))
    if max(ROUTINE_BASE.values()) + 0xFF < ROUTINES - 1:
        problems.append("⚠ 下駄を足しても %d 本に届かない" % ROUTINES)
    return problems
