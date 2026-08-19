"""まんたん（やくそうで満タン回復）を実行中のエミュレータへ要求する。

使い方（run.lua を動かしたまま、別のシェルで実行する）:
    python -m retroux.mantan

FCEUX 側は work/command.json を30フレームごとに見ているため、
実行から最大 0.5 秒ほどで始まる。

★encountered（遭遇済みモンスターID）を保存したまま書き換える。
  これを消すと初遭遇の保護が外れ、ボスに敗北後の再戦で倍速＋自動たたかうが
  有効になってしまう（DEV-8）。

★request_id を毎回変える。command.json は消えずに残るため、
  同じ値だと Lua 側が無視し、逆に値が無いと30フレームごとに再実行して
  やくそうを使い切る。

実行しない条件（FCEUX 側が判定し、ボタンを1つも押さずに拒否する）:
  ・戦闘中
  ・フィールドにいない（メニューや会話中）
  ・全員HPが満タン
  ・やくそうを持っていない
判定の結果は work/retroux.log と work/events.jsonl に出る。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from .core.bridge.writer import write_command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = PROJECT_ROOT / "retroux" / "plugins" / "dq2"


def _command_path() -> Path:
    with (PLUGIN_DIR / "config.yaml").open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    rel = config.get("logging", {}).get("command_path", "work/command.json")
    return PROJECT_ROOT / rel


def _existing_encountered(path: Path) -> list[int]:
    """既存の遭遇済みIDを読む。読めなければ空を返す。

    ★消してしまうと初遭遇の保護が外れる（DEV-8）ため、必ず引き継ぐ。
    """
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    ids = payload.get("encountered")
    if not isinstance(ids, list):
        return []
    return [int(i) for i in ids if isinstance(i, int)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="まんたん（やくそうで満タン回復）を要求する")
    parser.add_argument("--action", default="mantan",
                        help="要求する操作名（既定: mantan）")
    parser.add_argument("--mode", default=None,
                        help="回復目標モード（full=満タン / ratio90=9割）。"
                             "省略時は config の mantan.mode に従う")
    args = parser.parse_args(argv)

    path = _command_path()
    if not path.exists():
        print(f"警告: {path} がありません。"
              "エミュレータ側（run.lua）が起動していない可能性があります。",
              file=sys.stderr)

    encountered = _existing_encountered(path)
    write_command(
        path,
        encountered=encountered,
        action=args.action,
        request_id=int(time.time() * 1000),
        mantan_mode=args.mode,
    )
    print(f"{args.action} を要求しました: {path}")
    if args.mode:
        print(f"  回復目標モード: {args.mode}")
    print(f"  遭遇済みID {len(encountered)}件を引き継ぎました")
    print("  最大0.5秒ほどで開始します。実行可否は work/retroux.log を参照。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
