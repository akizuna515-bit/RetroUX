"""マップ地形を作るコードを**探す**道具（2026-08-02 / 指示書 Phase 1）。

★★ **狙い** ★★

  日本版DQ2が ROM から地形を作る処理を特定します。
  ⚠ Python へ手で写す前に、**まずどこにあるかを突き止めます**。

## ⚠ なぜ「探す道具」から作るのか

2026-08-02、私は地形データの位置を**4回続けて外しました**:

  1. ポインタA が地形だと思った          → 違った
  2. ポインタB が地形だと思った          → 各行1バイトで偶然合っただけ
  3. 手で写した処理を間違えたと思った    → 写しは正しかった
  4. `$E03C` が見た目を返すと思った      → ルーチンそのものが違った

★毎回「数字が合った」で判断していました。
  **コードを辿れば、そもそも当てずっぽうが要りません。**

## ⚠ データをコードとして読まない

`85 23`（`STA $23`）に**見える**バイト列は、データの中にいくらでもあります。
実際 2026-08-02 に bank3 のデータを命令として読んで外しました。
★このツールは「入口から辿って届いた所」だけを命令として扱います。

## 使い方

    python -m retroux.tools.dq2_map_code refs --targets 0x23,0x24
    python -m retroux.tools.dq2_map_code call-graph --entry 7:E03C
    python -m retroux.tools.dq2_map_code rank
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
DEFAULT_OUT = PROJECT_ROOT / "work" / "map-code-analysis"

#: ★追いたいゼロページ（指示書 6章・7.1）
WATCHED = {
    0x0C: "タイルセット番号",
    0x0D: "$E03C の戻り値",
    0x0E: "累積（$E03C 内）",
    0x0F: "マスク（$E03C 内）",
    0x10: "汎用ポインタ下位",
    0x11: "汎用ポインタ上位",
    0x12: "調べる座標X",
    0x13: "調べる座標Y",
    0x16: "プレイヤーX",
    0x17: "プレイヤーY",
    0x1D: "前回の $0D",
    0x1F: "マップ種別",
    0x20: "境界タイルID",
    0x21: "幅の元",
    0x22: "高さの元",
    0x23: "ポインタA 下位",
    0x24: "ポインタA 上位",
    0x25: "ポインタB 下位",
    0x26: "ポインタB 上位",
    0x27: "パレット索引",
    0x31: "map_id",
}

#: ★既知の入口 `(CPU番地, バンク)` → 役割。
#:
#: ⚠⚠ **バンクを間違えると何も辿れません**（2026-08-02 に踏んだ）。
#:   `$8000`-`$BFFF` は**切り替えバンク**なので、どのバンクかを
#:   一緒に持たないと PRG のどこか分かりません。
#:   `$C000`-`$FFFF` は固定バンク（最後の16KB）です。
KNOWN_ENTRIES = {
    (0xE03C, 7): "座標→区分らしい値（ポインタB を読む）",
    (0xE20C, 7): "map_id からマップ種別を決める",
    (0x8015, 0): "タイルセットを載せる（$0C が引数）",
    (0x807B, 0): "ダンジョンのタイルセットを重ねる",
    (0x80E5, 0): "CHR 索引表を引く",
}


def _out(text: str = "") -> None:
    print(text)


def _note(address: int) -> str:
    """★分かっている役割があれば添える。"""
    for (addr, _bank), text in KNOWN_ENTRIES.items():
        if addr == address:
            return text
    return ""


@dataclasses.dataclass
class Reference:
    """ゼロページを触っている命令1つ。"""

    target: int
    offset: int
    address: int
    bank: int
    text: str
    kind: str
    """read / write / indirect / rmw"""
    routine: int
    """どの入口から辿って見つかったか（CPU 番地）。"""


def _kind_of(insn) -> str:
    if insn.mode in ("izx", "izy"):
        return "indirect"
    if insn.mnemonic in ("STA", "STX", "STY"):
        return "write"
    if insn.mnemonic in ("INC", "DEC", "ASL", "LSR", "ROL", "ROR"):
        return "rmw"
    return "read"


def collect(prg, layout, entries, targets):
    """入口の集まりから辿って、`targets` を触る命令を集める。

    ⚠ 「ROM を頭から舐める」のではありません。★届いた所だけ。
    """
    from ..core.bgmap.disasm import walk

    found: list[Reference] = []
    calls: dict[int, set] = collections.defaultdict(set)
    visited_routines: set[tuple[int, int]] = set()
    todo = list(entries)
    while todo:
        address, bank = todo.pop()
        if (address, bank) in visited_routines:
            continue
        visited_routines.add((address, bank))
        for insn in walk(prg, layout, address, bank):
            if insn.mnemonic == "JSR":
                calls[address].add(insn.target)
                # ⚠ `$8000` 台は**いま載っているバンク**のまま辿る。
                #   ★バンク切替を跨ぐ呼び出しは、ここでは追えません
                #     （追えたつもりになるほうが危ない）。
                target_bank = layout.fixed if insn.target >= 0xC000 else bank
                if (insn.target, target_bank) not in visited_routines:
                    todo.append((insn.target, target_bank))
            zp = insn.zero_page
            if zp is not None and zp in targets:
                found.append(Reference(
                    target=zp, offset=insn.offset, address=insn.address,
                    bank=insn.offset // layout.BANK_SIZE,
                    text=insn.text(), kind=_kind_of(insn), routine=address))
    return found, calls, visited_routines


def _load(rom_path):
    from ..core.bgmap.disasm import Layout
    from ..core.bgmap.rom_tiles import load_prg

    prg = load_prg(rom_path)
    return prg, Layout(prg)


def _parse_entry(text: str) -> tuple[int, int]:
    """`7:E03C` を `(番地, バンク)` にする。"""
    bank_text, _, addr_text = text.partition(":")
    if not addr_text:
        raise ValueError(f"★`バンク:番地` の形で指定してください: {text}")
    return int(addr_text, 16), int(bank_text, 0)


def cmd_refs(rom_path, targets, entries, out_dir) -> int:
    """ゼロページの参照箇所を集める（指示書 7.1）。"""
    prg, layout = _load(rom_path)
    found, _calls, routines = collect(prg, layout, entries, set(targets))
    _out(f"★入口 {len(entries)} 個から辿り、{len(routines)} ルーチンを見ました")
    _out(f"★{len(found)} 件の参照が見つかりました\n")

    by_target = collections.defaultdict(list)
    for ref in found:
        by_target[ref.target].append(ref)
    for target in sorted(by_target):
        name = WATCHED.get(target, "")
        refs = by_target[target]
        kinds = collections.Counter(r.kind for r in refs)
        _out(f"  ${target:02X} {name}: {len(refs)} 件 "
             + " / ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
        for ref in refs[:6]:
            _out(f"      ${ref.address:04X} (PRG {ref.offset:05X} bank{ref.bank})"
                 f"  {ref.text}   ← ${ref.routine:04X} から")
        if len(refs) > 6:
            _out(f"      … ほか {len(refs) - 6} 件")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "zero-page-refs.csv"
    lines = ["target,prg_offset,cpu_address,bank,instruction,access_type,from_routine"]
    for ref in sorted(found, key=lambda r: (r.target, r.offset)):
        lines.append(f"0x{ref.target:02X},0x{ref.offset:05X},0x{ref.address:04X},"
                     f"{ref.bank},\"{ref.text}\",{ref.kind},0x{ref.routine:04X}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _out(f"\n★書き出しました: {path}")
    return 0


def cmd_call_graph(rom_path, entries, out_dir) -> int:
    """入口から辿れる呼出関係を出す（指示書 7.3）。"""
    prg, layout = _load(rom_path)
    _found, calls, routines = collect(prg, layout, entries, set())
    _out(f"★{len(routines)} ルーチン / {sum(len(v) for v in calls.values())} 本の呼び出し\n")
    for caller in sorted(calls):
        note = _note(caller)
        _out(f"  ${caller:04X}{'  ' + note if note else ''}")
        for callee in sorted(calls[caller]):
            note2 = _note(callee)
            _out(f"      -> ${callee:04X}{'  ' + note2 if note2 else ''}")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "call-graph.md"
    lines = ["# 呼出グラフ（自動生成）", "",
             "⚠ 入口から辿って届いた所だけです。",
             "★データをコードとして読まないため、頭から舐めていません。", ""]
    for caller in sorted(calls):
        lines.append(f"- `${caller:04X}`")
        for callee in sorted(calls[caller]):
            lines.append(f"  - `${callee:04X}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _out(f"\n★書き出しました: {path}")
    return 0


def cmd_rank(rom_path, entries, out_dir) -> int:
    """地形を作っていそうなルーチンを点数づけする（指示書 7.4）。

    ⚠⚠ **点数は手がかりであって、答えではありません。**
      ★上位に来たものを、次の段階で実際に動かして確かめます。
    """
    prg, layout = _load(rom_path)
    found, calls, routines = collect(prg, layout, entries, set(WATCHED))

    #: 加点の理由（指示書 7.4）。★何点かではなく**なぜ**を残す
    reasons: dict[int, list[str]] = collections.defaultdict(list)
    by_routine: dict[int, list[Reference]] = collections.defaultdict(list)
    for ref in found:
        by_routine[ref.routine].append(ref)

    for routine, refs in by_routine.items():
        targets = {r.target for r in refs}
        if {0x23, 0x24} & targets:
            reasons[routine].append("ポインタA を触る")
        if {0x25, 0x26} & targets:
            reasons[routine].append("ポインタB を触る")
        if 0x20 in targets:
            reasons[routine].append("境界タイルID を触る")
        if {0x21, 0x22} & targets:
            reasons[routine].append("幅・高さ を触る")
        if 0x0C in targets:
            reasons[routine].append("タイルセット番号 を触る")
        if {0x12, 0x13} & targets:
            reasons[routine].append("調べる座標 を触る")
        if any(r.kind == "indirect" for r in refs):
            reasons[routine].append("間接読み出しがある")
        if len(calls.get(routine, ())) >= 3:
            reasons[routine].append("いくつも呼び出す（まとめ役らしい）")

    ranked = sorted(reasons.items(), key=lambda kv: -len(kv[1]))
    _out("★地形を作っていそうなルーチン（点数は手がかりであって答えではない）\n")
    for routine, why in ranked[:15]:
        note = _note(routine)
        _out(f"  ${routine:04X} [{len(why)}点]{'  ' + note if note else ''}")
        for w in why:
            _out(f"      ・{w}")
    if not ranked:
        _out("  ⚠ 1つも見つかりませんでした（入口が足りない？）")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "candidates.md"
    lines = ["# 地形を作っていそうなルーチン（自動生成）", "",
             "⚠⚠ **点数は手がかりであって、答えではありません。**",
             "★上位を、次の段階で実際に動かして確かめます。", ""]
    for routine, why in ranked:
        lines.append(f"## `${routine:04X}` — {len(why)}点")
        lines.extend(f"- {w}" for w in why)
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _out(f"\n★書き出しました: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(
        description="マップ地形を作るコードを探す（指示書 Phase 1）")
    parser.add_argument("command", choices=("refs", "call-graph", "rank"))
    parser.add_argument("--rom", default=None)
    parser.add_argument("--targets", default=None,
                        help="追うゼロページ（例 0x23,0x24）。既定は全部")
    parser.add_argument("--entry", action="append", default=None,
                        help="入口（例 7:E03C）。何度でも指定できる")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    rom = pathlib.Path(args.rom) if args.rom else DEFAULT_ROM
    out_dir = pathlib.Path(args.output) if args.output else DEFAULT_OUT
    if not rom.exists():
        _out(f"✗ ROM がありません: {rom}")
        return 1

    entries = ([_parse_entry(e) for e in args.entry] if args.entry
               else list(KNOWN_ENTRIES))
    targets = ([int(t, 0) for t in args.targets.split(",")] if args.targets
               else list(WATCHED))

    if args.command == "refs":
        return cmd_refs(rom, targets, entries, out_dir)
    if args.command == "call-graph":
        return cmd_call_graph(rom, entries, out_dir)
    return cmd_rank(rom, entries, out_dir)


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
