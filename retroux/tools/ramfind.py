"""RAM とROMから「候補のアドレス」を絞る（MVP2 Phase 5 / 指示書 5.4 F）。

★これは今日までの解析を**道具にしたもの**。手でやっていたのは:

  1. 観測した値から**条件**を作る（例: 敵の戦闘開始時HPは 最大HP×0.75〜1.0）
  2. その条件に合うアドレス／ROMの位置を**総当たり**する
  3. 残った候補を**別経路のデータ**で確かめる
  4. memory_map へ貼れる形にする

  ★3 が要。探索に使っていないデータで裏が取れて初めて「見つけた」と言える
    （敵ステータス表は「以前に実測した スライム1体=2G」と一致して確定した）。

使い方:

    # 値がこの範囲にあるアドレスを探す（全セーブで成立するものだけ）
    python -m retroux.tools.ramfind value --min 20 --max 30

    # 2つのセーブの違いを見る
    python -m retroux.tools.ramfind diff --a DQ2_J.fc0 --b DQ2_J.fc1

    # すべてのセーブで同じ値のアドレス（名前・設定などを探すとき）
    python -m retroux.tools.ramfind stable --min-run 3

    # ROM から「N バイト刻みの表」を探す（敵ステータス表を見つけた方法）
    python -m retroux.tools.ramfind table --stride 15 --count 83 \\
        --at 0x33=60:64 --at 0x16=32:42

    --csv out.csv   … 表計算で見る
    --yaml          … memory_map.yaml へ貼れる形で出す

⚠ **候補は候補**。`confidence: candidate` を付けて出す。
  実測で裏を取ってから `confirmed` に上げること。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from . import ram as ram_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FCS = PROJECT_ROOT / "tools" / "fceux" / "fcs"
DEFAULT_ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"


def _snapshots(args) -> list[ram_mod.Snapshot]:
    snaps = ram_mod.load_all(args.fcs, args.pattern)
    if not snaps:
        print(f"セーブステートが見つかりません: {args.fcs}/{args.pattern}",
              file=sys.stderr)
    return snaps


def _emit(rows: list[dict], args, headers: list[str]) -> None:
    """結果を出す。CSV / YAML / 画面のどれか。"""
    if args.csv:
        # ★CSV には**持っている列を全部**出す。画面用に絞った headers だけだと
        #   DictWriter が余分なキーで例外になるうえ（実際に落ちた）、
        #   後から見たときに元データが足りない。保存は広く、画面は狭く。
        fields = list(headers)
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} 件を書きました: {args.csv}")
        return

    if args.yaml:
        # ★memory_map.yaml へ**そのまま貼れる**形。確度は candidate で出す。
        #   「見つけた」と「確かめた」を混ぜないため。
        print("# ramfind の候補。★実測で裏を取ってから confirmed に上げること。")
        for r in rows[:args.limit]:
            name = f"candidate_{r['addr']:04x}"
            print(f"  {name}:")
            print(f"    addr: 0x{r['addr']:04X}")
            print("    size: 1")
            print("    confidence: candidate")
            print(f"    description: |")
            print(f"      ramfind で絞った候補。{r.get('note', '')}")
        return

    for r in rows[:args.limit]:
        print("  " + "  ".join(f"{h}={r[h]}" for h in headers if h in r))
    if len(rows) > args.limit:
        print(f"  …ほか {len(rows) - args.limit} 件（--limit で増やせます）")


def cmd_value(args) -> int:
    """値が範囲に入るアドレスを探す。**全スナップショットで成立**するものだけ。"""
    snaps = _snapshots(args)
    if not snaps:
        return 1
    lo, hi = args.min, args.max
    rows = []
    for addr in range(args.start, args.end + 1):
        values = [s.data[addr] for s in snaps]
        if all(lo <= v <= hi for v in values):
            rows.append({"addr": addr, "addr_hex": f"${addr:04X}",
                         "values": ",".join(str(v) for v in values),
                         "note": f"{len(snaps)}件すべてで {lo}〜{hi}"})
    print(f"{len(snaps)} 件のセーブで {lo}〜{hi} に入るアドレス: {len(rows)} 件")
    _emit(rows, args, ["addr_hex", "values", "note"])
    return 0


def cmd_diff(args) -> int:
    """2つのセーブの違い。"""
    a = ram_mod.Snapshot(args.a, ram_mod.read_savestate(Path(args.fcs) / args.a))
    b = ram_mod.Snapshot(args.b, ram_mod.read_savestate(Path(args.fcs) / args.b))
    d = ram_mod.diff(a, b, args.start, args.end)
    rows = [{"addr": k, "addr_hex": f"${k:04X}", "before": v[0], "after": v[1],
             "delta": v[1] - v[0]} for k, v in sorted(d.items())]
    print(f"{args.a} と {args.b} の違い: {len(rows)} 件")
    _emit(rows, args, ["addr_hex", "before", "after", "delta"])
    return 0


def cmd_stable(args) -> int:
    """すべてのセーブで同じ値のアドレス（連続した区間で出す）。"""
    snaps = _snapshots(args)
    if not snaps:
        return 1
    addrs = [a for a in ram_mod.stable(snaps, args.start, args.end)
             if snaps[0].data[a] not in (0x00, 0xFF)]
    runs, cur = [], []
    for a in addrs:
        if cur and a == cur[-1] + 1:
            cur.append(a)
        else:
            if len(cur) >= args.min_run:
                runs.append(cur)
            cur = [a]
    if len(cur) >= args.min_run:
        runs.append(cur)

    rows = [{"addr": r[0], "addr_hex": f"${r[0]:04X}-${r[-1]:04X}",
             "length": len(r),
             "values": " ".join(f"{snaps[0].data[a]:02X}" for a in r[:16]),
             "note": f"{len(snaps)}件すべてで同値"} for r in runs]
    print(f"{len(snaps)} 件すべてで同値の区間（{args.min_run}バイト以上）: {len(rows)} 件")
    _emit(rows, args, ["addr_hex", "length", "values"])
    return 0


def _parse_at(text: str) -> tuple[int, int, int]:
    """`0x33=60:64` を (index, lo, hi) に。"""
    key, _, rng = text.partition("=")
    lo, _, hi = rng.partition(":")
    return int(key, 0), int(lo), int(hi if hi else lo)


def cmd_table(args) -> int:
    """ROM から「N バイト刻みの表」を探す。

    ★敵ステータス表を見つけた方法そのもの。
      「ID 0x33 の1バイト目が 60〜64」のような条件をいくつか与えると、
      条件をすべて満たす位置だけが残る。
    """
    prg = Path(args.rom).read_bytes()[16:]      # iNES ヘッダを除く
    conds = [_parse_at(x) for x in args.at]
    if not conds:
        print("--at を1つ以上ください（例: --at 0x33=60:64）", file=sys.stderr)
        return 1

    rows = []
    span = args.stride * args.count
    for base in range(0, max(0, len(prg) - span)):
        ok = True
        for index, lo, hi in conds:
            v = prg[base + (index - args.first_index) * args.stride + args.field]
            if not (lo <= v <= hi):
                ok = False
                break
        if not ok:
            continue
        # ★0 が並ぶ位置は表ではない（全要素が値を持つはず）
        if args.no_zero and any(
                prg[base + i * args.stride + args.field] == 0
                for i in range(args.count)):
            continue
        rows.append({"addr": base, "addr_hex": f"PRG 0x{base:05X}",
                     "note": f"{args.stride}バイト刻み × {args.count}"})

    print(f"条件 {len(conds)} 件すべてを満たす位置: {len(rows)} 件")
    _emit(rows, args, ["addr_hex", "note"])
    if len(rows) > 1:
        print("★複数残りました。**探索に使っていないデータ**で確かめてください"
              "（既知の実測値と突き合わせるのがいちばん強い）。")
    return 0


def main(argv: list[str] | None = None) -> int:
    # ★共通のオプションは**サブコマンドの後ろにも書ける**ようにする。
    #   argparse の既定では前にしか置けず、
    #   `ramfind stable --start 0x100` が「知らない引数」で落ちる。
    #   道具は、自然に書いた形で動いてほしい。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--fcs", default=str(DEFAULT_FCS),
                        help="セーブステートのフォルダ")
    # ★どのファイルを見たかで結果が変わる。既定は「いま遊んでいる10枠」。
    #   バックアップ（別の冒険の書）を混ぜると、同じはずの値が動いて見える。
    common.add_argument("--pattern", default="DQ2_J.fc[0-9]",
                        help="読むファイルの形（既定: いま遊んでいるスロット）")
    common.add_argument("--rom", default=str(DEFAULT_ROM))
    common.add_argument("--start", type=lambda x: int(x, 0), default=0)
    common.add_argument("--end", type=lambda x: int(x, 0),
                        default=ram_mod.RAM_SIZE - 1)
    common.add_argument("--limit", type=int, default=30, help="画面に出す件数")
    common.add_argument("--csv", default=None, help="CSV に書き出す")
    common.add_argument("--yaml", action="store_true",
                        help="memory_map.yaml へ貼れる形で出す（confidence: candidate）")

    ap = argparse.ArgumentParser(description="RAM/ROM の候補を絞る（Phase 5）",
                                 parents=[common])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("value", help="値が範囲に入るアドレス", parents=[common])
    p.add_argument("--min", type=lambda x: int(x, 0), required=True)
    p.add_argument("--max", type=lambda x: int(x, 0), required=True)
    p.set_defaults(func=cmd_value)

    p = sub.add_parser("diff", help="2つのセーブの違い", parents=[common])
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("stable", help="すべてのセーブで同値の区間", parents=[common])
    p.add_argument("--min-run", type=int, default=3)
    p.set_defaults(func=cmd_stable)

    p = sub.add_parser("table", help="ROM の N バイト刻みの表を探す", parents=[common])
    p.add_argument("--stride", type=int, required=True)
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--field", type=int, default=0, help="レコード内のバイト位置")
    p.add_argument("--first-index", type=int, default=1,
                   help="表の先頭が表す ID（既定 1）")
    p.add_argument("--at", action="append", default=[],
                   help="条件（例: 0x33=60:64）。複数指定できます")
    p.add_argument("--no-zero", action="store_true", default=True)
    p.set_defaults(func=cmd_table)

    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
