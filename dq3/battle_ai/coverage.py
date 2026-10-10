"""実機 run の理由ログを集計する（RX3-0139 / 2026-09-09）— 指示書 v1.1 §14。

```text
⚠ これまで  「実機で動いた」→ ★何の分岐を通ったのかは、報告を読み直すしかない
★これから  戦況 / 役割 / 実コマンド / 作戦 / MP 制約 / fixture を数える
```

## ⚠⚠ 100% を目標にしません

★目的は「**まだ 1 度も発火していない重要な分岐が見える**」ことだけです。
⚠ 未発火を自動で失敗にしません（指示書 §14）。★report に警告として出します。

## ★読むもの

```text
work/runtime/dq3-probe/battle_ai_run/<日時>/report.md   ★AI の理由ログが入っている
work/runtime/dq3-probe/battle_ai_run/<日時>/fixture.json ★使った fixture（id / sha256）
```

## 使い方

```bash
PYTHONUTF8=1 python -m dq3.battle_ai.coverage             # ★全部の run を集計
PYTHONUTF8=1 python -m dq3.battle_ai.coverage --runs 3    # ★新しい 3 本だけ
PYTHONUTF8=1 python -m dq3.battle_ai.coverage --markdown  # ★report へ貼る形
```
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

from . import settings as S
from .. import paths as P3

RUN_DIR = P3.work("runtime", "dq3-probe", "battle_ai_run")

#: ★見たい分岐（⚠ ここに無いものは「その他」に入る）
SITUATIONS = ("消化戦", "優勢", "均衡", "劣勢")
ROLES = ("物理", "魔法", "支援", "ヒール", "防御")
COMMANDS = ("attack", "defend", "回復呪文", "攻撃呪文", "支援呪文", "蘇生呪文", "どうぐ")
#: ★作戦の名前は settings が正本（★RX3-0198: 「レベル上げ」→「速攻」/ ⚠ ここへ写さない）
STRATEGIES = tuple(S.STRATEGY_LABELS[k] for k in S.STRATEGIES)
#: ⚠⚠ 昔の記録の読み替え（★同じ作戦としてまとめて数える）。
#:
#:   ```text
#:   〜2026-09-12  作戦=レベル上げ
#:   〜2026-09-20  作戦=速攻
#:   いま          作戦=最短撃破
#:   ```
#:
#:   ⚠ **消さないこと**。★消すと過去の実機 run が全部「その他」に落ちます。
STRATEGY_ALIASES = {"レベル上げ": S.STRATEGY_LABELS[S.LEVELING],
                    "速攻": S.STRATEGY_LABELS[S.LEVELING]}
#: ★MP 制約の名前は settings が正本（⚠ ここへ写さない / 作戦と同じ作法）
MP_POLICIES = tuple(S.MP_LABELS[k] for k in S.MP_POLICIES)
#: ⚠⚠ 昔の記録の読み替え（RX3-0333 / 2026-09-21）。
#:
#:   ```text
#:   〜2026-09-21  MP=温存        ⚠ `pipeline.lua` が画面と違う字を書いていた
#:   いま          MP=半分程度残す
#:   ```
#:
#:   ⚠ **消さないこと**。★消すと過去の実機 run の「温存」が全部「その他」に落ちます。
#:   ⚠ 過去のログは**書き換えません**（★読むときに寄せます）。
MP_ALIASES = {"温存": S.MP_LABELS[S.MP_SAVE]}

#: ★★ 「これが 0 なら知らせる」分岐（⚠ 失敗にはしない / 指示書 §14）
WATCH = {
    "戦況": ("劣勢",),
    "役割": ("支援",),
    "実コマンド": ("支援呪文", "蘇生呪文", "どうぐ"),
    "MP 制約": (S.MP_LABELS[S.MP_SAVE],),
}

_TURN = re.compile(r"AI turn=\d+ 戦況=(\S+).*?作戦=(\S+) MP=(\S+)")
_ACT = re.compile(r"AI (p\d) 役割=(\S+?)\([^)]*\) do=(\S+)")
#: ★攻撃呪文の判断（RX3-0198 の `AI tune pN … magic_candidate=… decision=… reason=…`）
_TUNE = re.compile(r"AI tune p\d .*?magic_candidate=\S+ .*?decision=(\S+) reason=(\S+)")


def _command_class(do: str, spells: dict) -> str:
    """★`do=` の中身 → 数える名前（⚠ 呪文は種別で分ける）。"""
    if do.startswith("attack"):
        return "attack"
    if do.startswith("defend"):
        return "defend"
    if do.startswith("item"):
        return "どうぐ"
    if do.startswith("spell:"):
        name = do[len("spell:"):].split("→")[0]
        return spells.get(name, "攻撃呪文")
    return "その他"


def _spell_kinds() -> dict:
    """★呪文の名前 → 種別（⚠ ROM から。★手で並べない）。"""
    out: dict[str, str] = {}
    try:
        from ..knowledge import spell_info as SI

        for row in SI.all_spells():
            kind = getattr(row, "kind", "")
            label = {"heal": "回復呪文", "revive": "蘇生呪文", "attack": "攻撃呪文"}.get(kind)
            if label is None and kind in ("buff", "debuff", "instant"):
                label = "支援呪文"
            if label and getattr(row, "name", None):
                out[row.name] = label
    except Exception:                                      # noqa: BLE001 - ★ROM 無しでも動く
        return {}
    return out


def scan_run(path: pathlib.Path) -> dict:
    """★1 つの run から数える（⚠ 読めない run は空で返す。★落とさない）。"""
    got = {"run": path.name, "situation": collections.Counter(),
           "role": collections.Counter(), "command": collections.Counter(),
           "strategy": collections.Counter(), "mp": collections.Counter(),
           "magic": collections.Counter(),
           "fixture": None, "fixture_sha256": None, "test": None, "actions": 0}
    report = path / "report.md"
    if not report.exists():
        return got
    spells = _spell_kinds()
    text = report.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = _TURN.search(line)
        if m:
            got["actions"] += 1
            got["situation"][m.group(1)] += 1
            got["strategy"][STRATEGY_ALIASES.get(m.group(2), m.group(2))] += 1
            got["mp"][MP_ALIASES.get(m.group(3), m.group(3))] += 1
            continue
        m = _TUNE.search(line)
        if m:
            got["magic"]["%s:%s" % (m.group(1), m.group(2))] += 1
            continue
        m = _ACT.search(line)
        if m:
            got["role"][m.group(2)] += 1
            got["command"][_command_class(m.group(3), spells)] += 1
    head = path / "fixture.json"
    if head.exists():
        try:
            body = json.loads(head.read_text(encoding="utf-8"))
            got["fixture"] = body.get("fixture")
            got["fixture_sha256"] = body.get("fixture_sha256")
            got["test"] = body.get("test")
        except (OSError, ValueError):
            pass
    return got


def collect(runs: int | None = None, root: pathlib.Path | None = None) -> dict:
    """★新しい順に run を読み、⚠ 合計する。"""
    base = root or RUN_DIR
    dirs = sorted((p for p in base.glob("*") if p.is_dir()), reverse=True)
    if runs:
        dirs = dirs[:runs]
    out = {"runs": [], "situation": collections.Counter(), "role": collections.Counter(),
           "command": collections.Counter(), "strategy": collections.Counter(),
           "mp": collections.Counter(), "magic": collections.Counter(),
           "fixtures": collections.Counter(), "tests": collections.Counter(), "actions": 0}
    for path in reversed(dirs):
        got = scan_run(path)
        if got["actions"] == 0 and not got["fixture"]:
            continue
        out["runs"].append(got["run"])
        out["actions"] += got["actions"]
        for key in ("situation", "role", "command", "strategy", "mp", "magic"):
            out[key].update(got[key])
        if got["fixture"]:
            out["fixtures"][got["fixture"]] += 1
        if got["test"]:
            out["tests"][got["test"]] += 1
    return out


def gaps(data: dict) -> list[str]:
    """⚠ まだ 1 度も発火していない**重要な**分岐（★失敗にはしない）。"""
    field = {"戦況": "situation", "役割": "role", "実コマンド": "command", "MP 制約": "mp"}
    out = []
    for label, names in WATCH.items():
        counter = data.get(field[label]) or {}
        for name in names:
            if not counter.get(name):
                out.append("%s: %s" % (label, name))
    return out


def _table(title: str, counter, want) -> list[str]:
    lines = ["### %s" % title, "", "```text"]
    seen = set()
    for name in want:
        n = counter.get(name, 0)
        mark = "   ⚠ まだ 0" if n == 0 else ""
        lines.append("  %-14s %6d%s" % (name, n, mark))
        seen.add(name)
    for name, n in sorted(counter.items(), key=lambda kv: -kv[1]):
        if name not in seen:
            lines.append("  %-14s %6d" % (name, n))
    lines += ["```", ""]
    return lines


def as_markdown(data: dict) -> str:
    lines = ["## 実機カバレッジ（RX3-0139）", "",
             "★run %d 本 / 行動 %d（⚠ 100%% を目標にしません。"
             "**まだ通っていない分岐が見える**ことが目的です）"
             % (len(data["runs"]), data["actions"]), ""]
    lines += _table("戦況", data["situation"], SITUATIONS)
    lines += _table("役割", data["role"], ROLES)
    lines += _table("実コマンド", data["command"], COMMANDS)
    lines += _table("作戦", data["strategy"], STRATEGIES)
    lines += _table("MP 制約", data["mp"], MP_POLICIES)
    if data.get("magic"):
        # ★RX3-0198: 攻撃呪文を撃った / 撃たなかった理由（★「なぜ魔術師が撃たないか」を run から読む）
        lines += _table("攻撃呪文の判断（decision:reason）", data["magic"], ())
    if data["fixtures"]:
        lines += ["### 使った fixture", "", "```text"]
        for name, n in data["fixtures"].most_common():
            lines.append("  %-28s %d 回" % (name, n))
        lines += ["```", ""]
    missing = gaps(data)
    if missing:
        lines += ["### ⚠ まだ 1 度も通っていない分岐", "", "```text"]
        for line in missing:
            lines.append("  " + line)
        lines += ["```", "",
                  "⚠ これは**失敗ではありません**。★その場面の fixture が要ります"
                  "（`python -m dq3.testing.fixtures needed`）。", ""]
    else:
        lines += ["★見張っている分岐は、すべて 1 度は通っています。", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="戦闘 AI の実機カバレッジ")
    ap.add_argument("--runs", type=int, default=None, help="★新しい N 本だけ")
    ap.add_argument("--markdown", action="store_true", help="★report へ貼る形で出す")
    args = ap.parse_args(argv)
    data = collect(args.runs)
    if not data["runs"]:
        print("（実機 run の記録がありません）")
        return 0
    print(as_markdown(data) if args.markdown else as_markdown(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
