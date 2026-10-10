"""実ログの絶対パスの監査（RX3-0530 / RX-0043）。

```text
python -m retroux.tools.audit_log_paths [ログ] [--all]
```

★通常の pytest は、この部品を**隔離した一時ログ**に当てて仕様（相対で書く）を見る。
  利用者の過去の起動ログは、検査の結果を左右しない（⚠ 編集・削除・退避もしない）。
★この道具は、実運用のログを**読むだけ**で監査する。違反の日時・内容と、
  ⚠ 修正の前か後かを分けて出す（修正より前の行は「直す前の記録」で、次の起動で消える）。

終了コード: 0 = 修正後の行に違反なし / 1 = 修正後の行に違反あり / 2 = ログが無い・読めない
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_LOG = ("work", "runtime", "dq2-log", "retroux.log")

#: ★起動の 1 行目（`launcher-common.ps1` が必ず出す）。ここから先が「最後の起動」
START_MARK = "launcher 設定を変換しています"
ABS_PATH = re.compile(r"[A-Za-z]:[/\\][A-Za-z0-9_.\-]+(?:[/\\][A-Za-z0-9_.\-]+)+")
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
#: ★絶対パスを出さないように直した版が入った印（`dq2_paths._for_log`）
FIX_MARKER = "_for_log"
FIX_FILE = "retroux/core/dq2_paths.py"


def last_launch(lines: list[str]) -> list[str]:
    """最後の起動の行。起動の目印が無ければ空（⚠ 「0 件」と「見ていない」を混ぜないため、呼び手が長さを見る）。"""
    starts = [i for i, line in enumerate(lines) if START_MARK in line]
    return lines[starts[-1]:] if starts else []


def find_violations(lines: list[str], root_name: str) -> list[dict]:
    """行ごとの絶対パス（この製品の置き場を含むもの）。{line_no, stamp, path, text}。"""
    out = []
    for no, line in enumerate(lines, 1):
        for m in ABS_PATH.finditer(line):
            if root_name in m.group(0):
                st = STAMP.match(line)
                out.append({"line_no": no, "stamp": st.group(1) if st else "", "path": m.group(0),
                            "text": line.strip()})
    return out


def fix_time(root: pathlib.Path = PROJECT_ROOT) -> dt.datetime | None:
    """修正が入った日時（git の履歴で `_for_log` を足した最初の commit）。取れなければ None。"""
    try:
        got = subprocess.run(
            ["git", "-C", str(root), "log", "-S" + FIX_MARKER, "--format=%cI", "--", FIX_FILE],
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    if not got:
        return None
    return dt.datetime.fromisoformat(got[-1]).astimezone().replace(tzinfo=None)   # ★最初の commit = 一番古い


def split_by_fix(found: list[dict], fixed_at: dt.datetime | None) -> tuple[list[dict], list[dict]]:
    """(修正前の行, 修正後の行)。⚠ 日時が読めない行・修正の日時が分からないときは「修正後」に入れる（見逃さない側）。"""
    before, after = [], []
    for v in found:
        try:
            at = dt.datetime.strptime(v["stamp"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            at = None
        (before if (fixed_at is not None and at is not None and at < fixed_at) else after).append(v)
    return before, after


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="audit_log_paths")
    ap.add_argument("log", nargs="?")
    ap.add_argument("--all", action="store_true", help="最後の起動だけでなくログ全体を見る")
    args = ap.parse_args(argv)
    path = pathlib.Path(args.log) if args.log else PROJECT_ROOT.joinpath(*DEFAULT_LOG)
    if not path.is_file():
        print("ログが無い: %s" % path)
        return 2
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    scope = lines if args.all else last_launch(lines)
    if not scope:
        print("起動の目印（%s）が見つからない: %s" % (START_MARK, path))
        return 2
    fixed_at = fix_time()
    before, after = split_by_fix(find_violations(scope, PROJECT_ROOT.name), fixed_at)
    print("対象 %d 行 / 修正の日時 %s" % (len(scope), fixed_at.isoformat(sep=" ") if fixed_at else "不明"))
    for label, rows in (("修正前の記録", before), ("修正後の行", after)):
        print("%s: %d 件" % (label, len(rows)))
        for v in rows:
            print("  %s  %s  （ログの %d 行目）" % (v["stamp"] or "日時なし", v["path"], v["line_no"]))
    return 1 if after else 0


if __name__ == "__main__":
    sys.exit(main())
