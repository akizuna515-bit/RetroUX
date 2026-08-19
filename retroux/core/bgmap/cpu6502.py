"""ROM のルーチンを**そのまま動かす**ための小さな 6502（2026-08-02）。

★★ **なぜ書いたか** ★★

  ⚠⚠ マップ展開ルーチン `$E03C` を手で Python へ写したところ、
    **2回続けて誤りました**（どのポインタが地形か / 行の区切り）。
    手で写す限り、また間違えます。

  ★ならば**写さずに動かす**。実機の RAM（セーブステート）を初期状態に
    すれば、私の解釈は一切入りません。**測定は推論に勝る。**

## ⚠ これは汎用の 6502 ではありません

`$E03C` が使う命令だけ実装しています。知らない命令に当たったら
**その場で止めます**（黙って進めて嘘の答えを出さない）。

## メモリの配置（UNROM）

```
$0000-$07FF  RAM（セーブステートから）
$8000-$BFFF  切り替えバンク（既定で bank2。`JSR $FE95` が選ぶもの）
$C000-$FFFF  固定バンク（bank7）
```
"""

from __future__ import annotations

#: bank の大きさ（UNROM は 16KB）
BANK_SIZE = 0x4000
#: 固定バンク（最後の 16KB）が写る位置
FIXED_WINDOW = 0xC000
#: 切り替えバンクが写る位置
SWAP_WINDOW = 0x8000


class UnknownOpcode(RuntimeError):
    """⚠ 知らない命令。★推測で飛ばさず、ここで止める。"""


class Cpu:
    """`$E03C` を動かすのに足りるだけの 6502。"""

    def __init__(self, prg: bytes, ram: bytes, bank: int = 2) -> None:
        self.prg = prg
        self.ram = bytearray(ram)
        self.bank = bank
        self.a = self.x = self.y = 0
        self.sp = 0xFD
        self.carry = self.zero = self.negative = False
        self.pc = 0
        self.stack: list[int] = []

    # --- メモリ ---------------------------------------------------------

    def read(self, addr: int) -> int:
        addr &= 0xFFFF
        if addr < 0x2000:
            return self.ram[addr & 0x7FF]
        if addr >= FIXED_WINDOW:
            base = len(self.prg) - BANK_SIZE
            return self.prg[base + (addr - FIXED_WINDOW)]
        if addr >= SWAP_WINDOW:
            return self.prg[self.bank * BANK_SIZE + (addr - SWAP_WINDOW)]
        return 0                      # ⚠ 読めない所は 0（PPU など）

    def write(self, addr: int, value: int) -> None:
        addr &= 0xFFFF
        if addr < 0x2000:
            self.ram[addr & 0x7FF] = value & 0xFF
        # ⚠ ROM への書き込みは無視（バンク切替は `JSR` 側で扱う）

    def word(self, addr: int) -> int:
        return self.read(addr) | (self.read(addr + 1) << 8)

    # --- フラグ ---------------------------------------------------------

    def _nz(self, value: int) -> int:
        value &= 0xFF
        self.zero = value == 0
        self.negative = bool(value & 0x80)
        return value

    # --- 実行 -----------------------------------------------------------

    def run(self, start: int, limit: int = 200000) -> None:
        """`start` から `RTS` で戻るまで動かす。

        ⚠ 回りすぎたら止める（無限ループを残さない）。
        """
        self.pc = start
        depth = 0
        for _ in range(limit):
            op = self.read(self.pc)
            self.pc += 1
            done = self._step(op)
            if done == "jsr":
                depth += 1
            elif done == "rts":
                if depth == 0:
                    return
                depth -= 1
        raise RuntimeError("★回りすぎました（無限ループの疑い）")

    def _imm(self) -> int:
        v = self.read(self.pc)
        self.pc += 1
        return v

    def _abs(self) -> int:
        v = self.word(self.pc)
        self.pc += 2
        return v

    def _branch(self, take: bool) -> None:
        off = self._imm()
        if take:
            self.pc += off - 256 if off & 0x80 else off

    def _cmp(self, left: int, right: int) -> None:
        self.carry = left >= right
        self._nz((left - right) & 0xFF)

    def _step(self, op: int):                       # noqa: C901, PLR0912
        r, w = self.read, self.write
        if op == 0xA9:   self.a = self._nz(self._imm())                # LDA #
        elif op == 0xA5: self.a = self._nz(r(self._imm()))             # LDA zp
        elif op == 0xAD: self.a = self._nz(r(self._abs()))             # LDA abs
        elif op == 0xB1:                                               # LDA (zp),Y
            base = self.word(self._imm())
            self.a = self._nz(r(base + self.y))
        elif op == 0xBD:                                               # LDA abs,X
            self.a = self._nz(r(self._abs() + self.x))
        elif op == 0xA2: self.x = self._nz(self._imm())                # LDX #
        elif op == 0xA6: self.x = self._nz(r(self._imm()))             # LDX zp
        elif op == 0xA0: self.y = self._nz(self._imm())                # LDY #
        elif op == 0xA4: self.y = self._nz(r(self._imm()))             # LDY zp
        elif op == 0x85: w(self._imm(), self.a)                        # STA zp
        elif op == 0x8D: w(self._abs(), self.a)                        # STA abs
        elif op == 0x86: w(self._imm(), self.x)                        # STX zp
        elif op == 0x84: w(self._imm(), self.y)                        # STY zp
        elif op == 0x29: self.a = self._nz(self.a & self._imm())       # AND #
        elif op == 0x25: self.a = self._nz(self.a & r(self._imm()))    # AND zp
        elif op == 0x09: self.a = self._nz(self.a | self._imm())       # ORA #
        elif op == 0x05: self.a = self._nz(self.a | r(self._imm()))    # ORA zp
        elif op == 0x11:                                               # ORA (zp),Y
            base = self.word(self._imm())
            self.a = self._nz(self.a | r(base + self.y))
        elif op == 0x4A:                                               # LSR A
            self.carry = bool(self.a & 1)
            self.a = self._nz(self.a >> 1)
        elif op == 0x46:                                               # LSR zp
            addr = self._imm()
            v = r(addr)
            self.carry = bool(v & 1)
            w(addr, self._nz(v >> 1))
        elif op == 0x0A:                                               # ASL A
            self.carry = bool(self.a & 0x80)
            self.a = self._nz((self.a << 1) & 0xFF)
        elif op == 0x06:                                               # ASL zp
            addr = self._imm()
            v = r(addr)
            self.carry = bool(v & 0x80)
            w(addr, self._nz((v << 1) & 0xFF))
        elif op == 0x66:                                               # ROR zp
            addr = self._imm()
            v = r(addr) | (0x100 if self.carry else 0)
            self.carry = bool(v & 1)
            w(addr, self._nz(v >> 1))
        elif op == 0x6A:                                               # ROR A
            v = self.a | (0x100 if self.carry else 0)
            self.carry = bool(v & 1)
            self.a = self._nz(v >> 1)
        elif op == 0x2A:                                               # ROL A
            v = (self.a << 1) | (1 if self.carry else 0)
            self.carry = bool(v & 0x100)
            self.a = self._nz(v & 0xFF)
        elif op == 0x24:                                               # BIT zp
            v = r(self._imm())
            self.zero = (self.a & v) == 0
            self.negative = bool(v & 0x80)
        elif op == 0x49: self.a = self._nz(self.a ^ self._imm())       # EOR #
        elif op == 0x45: self.a = self._nz(self.a ^ r(self._imm()))    # EOR zp
        elif op == 0x9D: w(self._abs() + self.x, self.a)               # STA abs,X
        elif op == 0x99: w(self._abs() + self.y, self.a)               # STA abs,Y
        elif op == 0xB9: self.a = self._nz(r(self._abs() + self.y))    # LDA abs,Y
        elif op == 0xBC: self.y = self._nz(r(self._abs() + self.x))    # LDY abs,X
        elif op == 0xBE: self.x = self._nz(r(self._abs() + self.y))    # LDX abs,Y
        elif op == 0xB5: self.a = self._nz(r((self._imm() + self.x) & 0xFF))
        elif op == 0x95: w((self._imm() + self.x) & 0xFF, self.a)      # STA zp,X
        elif op == 0xB4: self.y = self._nz(r((self._imm() + self.x) & 0xFF))
        elif op == 0xD5: self._cmp(self.a, r((self._imm() + self.x) & 0xFF))
        elif op == 0xDD: self._cmp(self.a, r(self._abs() + self.x))    # CMP abs,X
        elif op == 0xD9: self._cmp(self.a, r(self._abs() + self.y))    # CMP abs,Y
        elif op == 0xCD: self._cmp(self.a, r(self._abs()))             # CMP abs
        elif op == 0xEC: self._cmp(self.x, r(self._abs()))             # CPX abs
        elif op == 0x2C:                                               # BIT abs
            v = r(self._abs())
            self.zero = (self.a & v) == 0
            self.negative = bool(v & 0x80)
        elif op == 0x26:                                               # ROL zp
            addr = self._imm()
            v = (r(addr) << 1) | (1 if self.carry else 0)
            self.carry = bool(v & 0x100)
            w(addr, self._nz(v & 0xFF))
        elif op == 0x65:                                               # ADC zp
            v = r(self._imm()) + (1 if self.carry else 0)
            total = self.a + v
            self.carry = total > 0xFF
            self.a = self._nz(total & 0xFF)
        elif op == 0x6D:                                               # ADC abs
            v = r(self._abs()) + (1 if self.carry else 0)
            total = self.a + v
            self.carry = total > 0xFF
            self.a = self._nz(total & 0xFF)
        elif op == 0x7D:                                               # ADC abs,X
            v = r(self._abs() + self.x) + (1 if self.carry else 0)
            total = self.a + v
            self.carry = total > 0xFF
            self.a = self._nz(total & 0xFF)
        elif op == 0x79:                                               # ADC abs,Y
            v = r(self._abs() + self.y) + (1 if self.carry else 0)
            total = self.a + v
            self.carry = total > 0xFF
            self.a = self._nz(total & 0xFF)
        elif op == 0xED:                                               # SBC abs
            v = r(self._abs())
            total = self.a - v - (0 if self.carry else 1)
            self.carry = total >= 0
            self.a = self._nz(total & 0xFF)
        elif op == 0x0D: self.a = self._nz(self.a | r(self._abs()))    # ORA abs
        elif op == 0x2D: self.a = self._nz(self.a & r(self._abs()))    # AND abs
        elif op == 0x4D: self.a = self._nz(self.a ^ r(self._abs()))    # EOR abs
        elif op == 0xEE:                                               # INC abs
            addr = self._abs()
            w(addr, self._nz(r(addr) + 1))
        elif op == 0xCE:                                               # DEC abs
            addr = self._abs()
            w(addr, self._nz(r(addr) - 1))
        elif op == 0x0E:                                               # ASL abs
            addr = self._abs()
            v = r(addr)
            self.carry = bool(v & 0x80)
            w(addr, self._nz((v << 1) & 0xFF))
        elif op == 0x4E:                                               # LSR abs
            addr = self._abs()
            v = r(addr)
            self.carry = bool(v & 1)
            w(addr, self._nz(v >> 1))
        elif op == 0x69:                                               # ADC #
            v = self._imm() + (1 if self.carry else 0)
            total = self.a + v
            self.carry = total > 0xFF
            self.a = self._nz(total & 0xFF)
        elif op == 0xE5:                                               # SBC zp
            v = r(self._imm())
            total = self.a - v - (0 if self.carry else 1)
            self.carry = total >= 0
            self.a = self._nz(total & 0xFF)
        elif op == 0xE9:                                               # SBC #
            v = self._imm()
            total = self.a - v - (0 if self.carry else 1)
            self.carry = total >= 0
            self.a = self._nz(total & 0xFF)
        elif op == 0xC9: self._cmp(self.a, self._imm())                # CMP #
        elif op == 0xC5: self._cmp(self.a, r(self._imm()))             # CMP zp
        elif op == 0xE0: self._cmp(self.x, self._imm())                # CPX #
        elif op == 0xE4: self._cmp(self.x, r(self._imm()))             # CPX zp
        elif op == 0xC0: self._cmp(self.y, self._imm())                # CPY #
        elif op == 0xC4: self._cmp(self.y, r(self._imm()))             # CPY zp
        elif op == 0x38: self.carry = True                             # SEC
        elif op == 0x18: self.carry = False                            # CLC
        elif op == 0xE8: self.x = self._nz(self.x + 1)                 # INX
        elif op == 0xC8: self.y = self._nz(self.y + 1)                 # INY
        elif op == 0xCA: self.x = self._nz(self.x - 1)                 # DEX
        elif op == 0x88: self.y = self._nz(self.y - 1)                 # DEY
        elif op == 0xE6:                                               # INC zp
            addr = self._imm()
            w(addr, self._nz(r(addr) + 1))
        elif op == 0xC6:                                               # DEC zp
            addr = self._imm()
            w(addr, self._nz(r(addr) - 1))
        elif op == 0xAA: self.x = self._nz(self.a)                     # TAX
        elif op == 0xA8: self.y = self._nz(self.a)                     # TAY
        elif op == 0x8A: self.a = self._nz(self.x)                     # TXA
        elif op == 0x98: self.a = self._nz(self.y)                     # TYA
        elif op == 0x48: self.stack.append(self.a)                     # PHA
        elif op == 0x68: self.a = self._nz(self.stack.pop())           # PLA
        elif op == 0x90: self._branch(not self.carry)                  # BCC
        elif op == 0xB0: self._branch(self.carry)                      # BCS
        elif op == 0xF0: self._branch(self.zero)                       # BEQ
        elif op == 0xD0: self._branch(not self.zero)                   # BNE
        elif op == 0x30: self._branch(self.negative)                   # BMI
        elif op == 0x10: self._branch(not self.negative)               # BPL
        elif op == 0x4C: self.pc = self._abs()                         # JMP
        elif op == 0x20:                                               # JSR
            target = self._abs()
            hooked = self.on_jsr(target)
            if hooked:
                return None
            self.stack.append(self.pc)
            self.pc = target
            return "jsr"
        elif op == 0x60:                                               # RTS
            if self.stack:
                self.pc = self.stack.pop()
            return "rts"
        elif op == 0xEA: pass                                          # NOP
        else:
            raise UnknownOpcode(
                f"★知らない命令 ${op:02X} at ${self.pc - 1:04X}")
        return None

    # --- 外から差し替える ------------------------------------------------

    def on_jsr(self, target: int) -> bool:
        """`JSR` を横取りする。True を返すと**呼ばずに飛ばす**。

        ★バンク切替（`$FE95` など）は、ここで `self.bank` を変えて
          飛ばすのが素直です。⚠ 本物を走らせると PPU まで要ります。
        """
        return False
