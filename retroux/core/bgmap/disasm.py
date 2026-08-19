"""6502 の逆アセンブル（2026-08-02 / 指示書 Phase 1）。

★★ **静的解析のための土台です。** ★★

  ⚠ 命令の**長さ**が分からないと、バイト列を命令として辿れません。
    「たまたま `85 23` に見えるデータ」を `STA $23` と読み違えます。
    ★実際、2026-08-02 に一度それで外しました（bank3 のデータを
      コードだと思って読んだ）。

## ⚠ 逆アセンブルは「入口から辿る」

  ★ROM を頭から舐めると、データをコードとして読んでしまいます。
    `walk()` は **入口から分岐をたどって**、届いた所だけを命令とみなします。
"""

from __future__ import annotations

import dataclasses

#: アドレッシングモード → 命令の長さ（オペコードを含む）
MODE_SIZE = {
    "imp": 1, "acc": 1,
    "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "izx": 2, "izy": 2, "rel": 2,
    "abs": 3, "abx": 3, "aby": 3, "ind": 3,
}

#: オペコード → (ニーモニック, モード)。⚠ 未定義命令は入れない
OPCODES: dict[int, tuple[str, str]] = {
    0x00: ("BRK", "imp"), 0x01: ("ORA", "izx"), 0x05: ("ORA", "zp"),
    0x06: ("ASL", "zp"), 0x08: ("PHP", "imp"), 0x09: ("ORA", "imm"),
    0x0A: ("ASL", "acc"), 0x0D: ("ORA", "abs"), 0x0E: ("ASL", "abs"),
    0x10: ("BPL", "rel"), 0x11: ("ORA", "izy"), 0x15: ("ORA", "zpx"),
    0x16: ("ASL", "zpx"), 0x18: ("CLC", "imp"), 0x19: ("ORA", "aby"),
    0x1D: ("ORA", "abx"), 0x1E: ("ASL", "abx"),
    0x20: ("JSR", "abs"), 0x21: ("AND", "izx"), 0x24: ("BIT", "zp"),
    0x25: ("AND", "zp"), 0x26: ("ROL", "zp"), 0x28: ("PLP", "imp"),
    0x29: ("AND", "imm"), 0x2A: ("ROL", "acc"), 0x2C: ("BIT", "abs"),
    0x2D: ("AND", "abs"), 0x2E: ("ROL", "abs"),
    0x30: ("BMI", "rel"), 0x31: ("AND", "izy"), 0x35: ("AND", "zpx"),
    0x36: ("ROL", "zpx"), 0x38: ("SEC", "imp"), 0x39: ("AND", "aby"),
    0x3D: ("AND", "abx"), 0x3E: ("ROL", "abx"),
    0x40: ("RTI", "imp"), 0x41: ("EOR", "izx"), 0x45: ("EOR", "zp"),
    0x46: ("LSR", "zp"), 0x48: ("PHA", "imp"), 0x49: ("EOR", "imm"),
    0x4A: ("LSR", "acc"), 0x4C: ("JMP", "abs"), 0x4D: ("EOR", "abs"),
    0x4E: ("LSR", "abs"),
    0x50: ("BVC", "rel"), 0x51: ("EOR", "izy"), 0x55: ("EOR", "zpx"),
    0x56: ("LSR", "zpx"), 0x58: ("CLI", "imp"), 0x59: ("EOR", "aby"),
    0x5D: ("EOR", "abx"), 0x5E: ("LSR", "abx"),
    0x60: ("RTS", "imp"), 0x61: ("ADC", "izx"), 0x65: ("ADC", "zp"),
    0x66: ("ROR", "zp"), 0x68: ("PLA", "imp"), 0x69: ("ADC", "imm"),
    0x6A: ("ROR", "acc"), 0x6C: ("JMP", "ind"), 0x6D: ("ADC", "abs"),
    0x6E: ("ROR", "abs"),
    0x70: ("BVS", "rel"), 0x71: ("ADC", "izy"), 0x75: ("ADC", "zpx"),
    0x76: ("ROR", "zpx"), 0x78: ("SEI", "imp"), 0x79: ("ADC", "aby"),
    0x7D: ("ADC", "abx"), 0x7E: ("ROR", "abx"),
    0x81: ("STA", "izx"), 0x84: ("STY", "zp"), 0x85: ("STA", "zp"),
    0x86: ("STX", "zp"), 0x88: ("DEY", "imp"), 0x8A: ("TXA", "imp"),
    0x8C: ("STY", "abs"), 0x8D: ("STA", "abs"), 0x8E: ("STX", "abs"),
    0x90: ("BCC", "rel"), 0x91: ("STA", "izy"), 0x94: ("STY", "zpx"),
    0x95: ("STA", "zpx"), 0x96: ("STX", "zpy"), 0x98: ("TYA", "imp"),
    0x99: ("STA", "aby"), 0x9A: ("TXS", "imp"), 0x9D: ("STA", "abx"),
    0xA0: ("LDY", "imm"), 0xA1: ("LDA", "izx"), 0xA2: ("LDX", "imm"),
    0xA4: ("LDY", "zp"), 0xA5: ("LDA", "zp"), 0xA6: ("LDX", "zp"),
    0xA8: ("TAY", "imp"), 0xA9: ("LDA", "imm"), 0xAA: ("TAX", "imp"),
    0xAC: ("LDY", "abs"), 0xAD: ("LDA", "abs"), 0xAE: ("LDX", "abs"),
    0xB0: ("BCS", "rel"), 0xB1: ("LDA", "izy"), 0xB4: ("LDY", "zpx"),
    0xB5: ("LDA", "zpx"), 0xB6: ("LDX", "zpy"), 0xB8: ("CLV", "imp"),
    0xB9: ("LDA", "aby"), 0xBA: ("TSX", "imp"), 0xBC: ("LDY", "abx"),
    0xBD: ("LDA", "abx"), 0xBE: ("LDX", "aby"),
    0xC0: ("CPY", "imm"), 0xC1: ("CMP", "izx"), 0xC4: ("CPY", "zp"),
    0xC5: ("CMP", "zp"), 0xC6: ("DEC", "zp"), 0xC8: ("INY", "imp"),
    0xC9: ("CMP", "imm"), 0xCA: ("DEX", "imp"), 0xCC: ("CPY", "abs"),
    0xCD: ("CMP", "abs"), 0xCE: ("DEC", "abs"),
    0xD0: ("BNE", "rel"), 0xD1: ("CMP", "izy"), 0xD5: ("CMP", "zpx"),
    0xD6: ("DEC", "zpx"), 0xD8: ("CLD", "imp"), 0xD9: ("CMP", "aby"),
    0xDD: ("CMP", "abx"), 0xDE: ("DEC", "abx"),
    0xE0: ("CPX", "imm"), 0xE1: ("SBC", "izx"), 0xE4: ("CPX", "zp"),
    0xE5: ("SBC", "zp"), 0xE6: ("INC", "zp"), 0xE8: ("INX", "imp"),
    0xE9: ("SBC", "imm"), 0xEA: ("NOP", "imp"), 0xEC: ("CPX", "abs"),
    0xED: ("SBC", "abs"), 0xEE: ("INC", "abs"),
    0xF0: ("BEQ", "rel"), 0xF1: ("SBC", "izy"), 0xF5: ("SBC", "zpx"),
    0xF6: ("SBC", "zpx"), 0xF8: ("SED", "imp"), 0xF9: ("SBC", "aby"),
    0xFD: ("SBC", "abx"), 0xFE: ("INC", "abx"),
}

#: 流れがそこで終わる命令（次の命令へ落ちない）
TERMINATORS = frozenset({"RTS", "RTI", "JMP", "BRK"})
#: 分岐命令（条件つき。★次へも落ちる）
BRANCHES = frozenset({"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"})
#: ゼロページを直接触るモード
ZP_MODES = frozenset({"zp", "zpx", "zpy"})
#: ゼロページのペアを間接で使うモード
INDIRECT_MODES = frozenset({"izx", "izy"})


@dataclasses.dataclass(frozen=True)
class Insn:
    """命令1つ。"""

    offset: int
    """PRG の中の位置。"""
    address: int
    """CPU から見た番地。"""
    opcode: int
    mnemonic: str
    mode: str
    operand: int
    """オペランドの値（`imp`/`acc` は 0）。"""
    size: int

    @property
    def target(self) -> int | None:
        """飛び先。⚠ 分からなければ None。"""
        if self.mode == "rel":
            off = self.operand
            return self.address + self.size + (off - 256 if off & 0x80 else off)
        if self.mode == "abs" and self.mnemonic in ("JMP", "JSR"):
            return self.operand
        return None

    @property
    def zero_page(self) -> int | None:
        """触っているゼロページ番地。⚠ 違えば None。"""
        if self.mode in ZP_MODES or self.mode in INDIRECT_MODES:
            return self.operand
        return None

    def text(self) -> str:
        m, o = self.mnemonic, self.operand
        if self.mode in ("imp", "acc"):
            return m
        if self.mode == "imm":
            return f"{m} #${o:02X}"
        if self.mode == "rel":
            return f"{m} ${self.target:04X}"
        if self.mode in ("zp", "zpx", "zpy"):
            suffix = {"zp": "", "zpx": ",X", "zpy": ",Y"}[self.mode]
            return f"{m} ${o:02X}{suffix}"
        if self.mode == "izx":
            return f"{m} (${o:02X},X)"
        if self.mode == "izy":
            return f"{m} (${o:02X}),Y"
        if self.mode == "ind":
            return f"{m} (${o:04X})"
        suffix = {"abs": "", "abx": ",X", "aby": ",Y"}[self.mode]
        return f"{m} ${o:04X}{suffix}"


def decode(prg: bytes, offset: int, address: int) -> Insn | None:
    """1命令を読む。⚠ 未定義のオペコードなら None。"""
    if offset >= len(prg):
        return None
    op = prg[offset]
    known = OPCODES.get(op)
    if known is None:
        return None
    mnemonic, mode = known
    size = MODE_SIZE[mode]
    if offset + size > len(prg):
        return None
    if size == 1:
        operand = 0
    elif size == 2:
        operand = prg[offset + 1]
    else:
        operand = prg[offset + 1] | (prg[offset + 2] << 8)
    return Insn(offset=offset, address=address, opcode=op, mnemonic=mnemonic,
                mode=mode, operand=operand, size=size)


class Layout:
    """PRG の中の位置と、CPU から見た番地の対応（UNROM）。

    ⚠ 切り替えバンクは `$8000`、固定バンク（最後の16KB）は `$C000`。
    """

    BANK_SIZE = 0x4000

    def __init__(self, prg: bytes) -> None:
        self.prg = prg
        self.banks = len(prg) // self.BANK_SIZE
        self.fixed = self.banks - 1

    def address_of(self, offset: int) -> int:
        bank = offset // self.BANK_SIZE
        base = 0xC000 if bank == self.fixed else 0x8000
        return base + (offset % self.BANK_SIZE)

    def offset_of(self, address: int, bank: int) -> int | None:
        """CPU 番地 → PRG の位置。⚠ 窓の外なら None。"""
        if 0xC000 <= address <= 0xFFFF:
            return self.fixed * self.BANK_SIZE + (address - 0xC000)
        if 0x8000 <= address < 0xC000:
            if not 0 <= bank < self.banks:
                return None
            return bank * self.BANK_SIZE + (address - 0x8000)
        return None


def walk(prg: bytes, layout: Layout, entry: int, bank: int,
         limit: int = 4000) -> list[Insn]:
    """入口から**分岐をたどって**命令を集める。

    ★ROM を頭から舐めません。データをコードとして読まないためです。

    ⚠ 同じ所を2度は辿りません。`JSR` の先は**辿りません**
      （呼出グラフ側で別に扱います）。
    """
    start = layout.offset_of(entry, bank)
    if start is None:
        return []
    out: list[Insn] = []
    seen: set[int] = set()
    todo = [start]
    while todo and len(out) < limit:
        offset = todo.pop()
        while offset not in seen and len(out) < limit:
            seen.add(offset)
            insn = decode(prg, offset, layout.address_of(offset))
            if insn is None:
                break
            out.append(insn)
            if insn.mnemonic in BRANCHES:
                target = layout.offset_of(insn.target, bank)
                if target is not None and target not in seen:
                    todo.append(target)
            elif insn.mnemonic == "JMP" and insn.mode == "abs":
                target = layout.offset_of(insn.target, bank)
                if target is not None and target not in seen:
                    todo.append(target)
                break
            elif insn.mnemonic in TERMINATORS:
                break
            offset += insn.size
    out.sort(key=lambda i: i.offset)
    return out
