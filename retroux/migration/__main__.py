"""`python -m retroux.migration --source <旧フォルダ> --dest <新しいフォルダ>`（RX-0157 / RX-0158 / RX-0165）。

★終了コード: 0 = 移した / 何もしなかった、2 = 安全に止めた（★本番は変えていないか、journal から続きが分かる）。

★`--interactive` は ZIP の `migrate-dq2.cmd` から使う（★人が読む形で出し、最後に Enter を待つ）:
  旧フォルダを聞く（★ドラッグ＆ドロップの引用符は外す）→ RetroUX が動いていれば止める → ROM を写すか聞く（既定 いいえ）→
  移す → 何を移したか / なぜ止めたかを日本語で出す。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core import path_depth
from . import m0001_legacy_to_portable as M
from . import regenerate
from .runner import MigrationStop, Options, Result, migrate


def running_product() -> str | None:
    """★RetroUX（DQ2 / DQ3）が動いていれば、その名前（⚠ 動いている最中に移すと記録が混ざる）。"""
    from ..core import product_lock as PL

    api = PL.Win32Mutex()
    if not api.available():
        return None
    prefix = PL.current_prefix()
    for product in PL.PRODUCTS:
        if api.exists(PL.identity_name(product, prefix)):
            return PL.LABELS[product]
    return None


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _unquote(text: str) -> str:
    return text.strip().strip('"').strip()


def summary_lines(got: Result) -> list[str]:
    """★移した結果を人が読む形に（★数は report から）。"""
    if got.status == "noop":
        return ["何もしませんでした（このフォルダは既に移行済みです）。"]
    rep = got.report or {}
    rows = (rep.get("db") or {}).get("rows") or {}
    lines = ["移しました。"]
    if rows:
        lines.append(f"  戦闘の記録 {rows.get('BattleLog', 0)} 件 / 歩いたマス {rows.get('VisitedTile', 0)} /"
                     f" 出会った敵 {rows.get('EncounteredMonster', 0)} 種 / メモ {rows.get('MapNote', 0)} 件")
    lines.append(f"  セーブ {rep.get('savestates', 0)} 件 / セーブの控え {rep.get('backup_generations', 0)} 世代"
                 + (f" / ROM {rep['rom']['name']}" if rep.get("rom") else ""))
    if rep.get("fceux_files"):
        lines.append(f"  FCEUX {rep['fceux_files']} ファイル（tools\\fceux\\ / ★セーブと fceux.cfg は除く）")
    elif not rep.get("fceux_kept"):
        lines.append("  ⚠ FCEUX は写していません（★旧いフォルダの tools\\fceux\\ に無い）→ PLACE-FCEUX-HERE.txt")
    lines += [f"  ★{note}" for note in got.notes]
    lines.append("DQ2.cmd で起動してください。")
    return lines


def main(argv: list[str] | None = None) -> int:
    keys = M.optional_keys()
    ap = argparse.ArgumentParser(description="旧 DQ2 フォルダのデータを新しいフォルダへ移す（★旧は変えない）")
    ap.add_argument("--source", help="旧 DQ2 のフォルダ（★読むだけ / --interactive なら聞く）")
    ap.add_argument("--dest", required=True, help="新しいフォルダ（★新しい版のプログラムを置いたところ）")
    ap.add_argument("--with", dest="include", action="append", default=[], choices=sorted(keys),
                    help="選んで写すもの（既定 ON: " + ", ".join(k for k, on in keys.items() if on) + "）")
    ap.add_argument("--without", dest="exclude", action="append", default=[], choices=sorted(keys),
                    help="既定 ON のものを写さない")
    ap.add_argument("--no-regenerate", action="store_true", help="作り直しをしない（★印にそう書く）")
    ap.add_argument("--resume", action="store_true", help="本番へ入れる途中で止まった移行の続き")
    ap.add_argument("--discard-staging", action="store_true", help="staging の途中で止まった移行を消してやり直す")
    ap.add_argument("--interactive", action="store_true", help="人が使う形（migrate-dq2.cmd から）")
    ap.add_argument("--no-wait", action="store_true", help="--interactive の最後に Enter を待たない")
    args = ap.parse_args(argv)

    def finish(code: int) -> int:
        if args.interactive and not args.no_wait:
            _ask("\nEnter で閉じます。")
        return code

    source = args.source
    include = set(args.include)
    if args.interactive:
        print("RetroUX DQ2 — 旧い DQ2 のフォルダからデータを移します（★旧いフォルダは変えません）。\n")
        # ★移す前に、展開先が深すぎないかを見る（RX-0166 / ⚠ 移しても起動で黙って止まる）
        depth = path_depth.measure(args.dest)
        if not depth["ok"]:
            print("止めました: RetroUX を置いたフォルダが深すぎます"
                  f"（中のいちばん長いパスが {depth['total']} 文字 / Windows の上限 {path_depth.LIMIT} 文字）。\n"
                  "  C:\\Tools など浅い場所へ ZIP を展開し直してから、もう一度実行してください"
                  f"（展開先のフォルダの文字数の目安: {depth['allowed']} 文字以下）。\n"
                  "★旧いフォルダは変えていません。")
            return finish(2)
        if not source:
            source = _unquote(_ask("旧い DQ2 のフォルダ（RetroUX.cmd や RetroUX.vbs があるところ）を\n"
                                   "この画面へドラッグして Enter: "))
        if not source:
            print("止めました: フォルダが指定されていません。")
            return finish(2)
        busy = running_product()
        if busy:
            print(f"止めました: {busy} が起動中です。閉じてからもう一度実行してください。")
            return finish(2)
        if "rom" not in include and "rom" not in args.exclude:
            if _ask("旧いフォルダの ROM（DQ2_J.nes）も写しますか？ [y/N]: ").strip().lower() in ("y", "yes"):
                include.add("rom")
    elif not source:
        ap.error("--source が要ります（★人が使うなら --interactive）")

    options = Options(include=frozenset(include), exclude=frozenset(args.exclude),
                      regenerate=None if args.no_regenerate else regenerate.run,
                      resume=args.resume, discard_staging=args.discard_staging)
    try:
        got = migrate(Path(_unquote(source)), Path(args.dest), options)
    except MigrationStop as exc:
        print(f"止めました: {exc}", file=sys.stdout if args.interactive else sys.stderr)
        if args.interactive:
            print("★旧いフォルダは変えていません。")
        return finish(2)
    if args.interactive:
        print("\n".join(summary_lines(got)))
        return finish(0)
    print(json.dumps({"status": got.status, "run": got.run, "report": got.report,
                      "notes": list(got.notes)}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
