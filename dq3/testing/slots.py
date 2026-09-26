"""セーブスロットの決めごと（RX3-0031 / 2026-08-31）。

## ⚠⚠ 依頼者の決めごと（PoC② §2）

```text
slot 0〜4  人間用。⚠⚠ **AI は書き込み禁止**
slot 5〜9  AI が自由に load / save / 上書き / 作り直し
```

★読み込みは 0〜9 すべて許します（⚠ 禁じられているのは書き込みだけ）。

## ⚠ ここと Lua の両方に同じ数字がある

★`dq3/phase0/ai_state.lua` にも `AI_MIN` / `AI_MAX` があります。
⚠ 2 か所に**書いてしまっている**ので、`tests/test_dq3_ai_slots.py` が
**同じ数字であること**を見張ります（★片方だけ動くのを防ぐ）。

⚠⚠ Lua は FCEUX の中で動くので、Python から呼べません。
  ★だから写しは避けられません。→ **検査で縛る**のがこの計画のやり方です。
"""

from __future__ import annotations

import os
import pathlib

#: ★AI が書いてよい範囲
AI_MIN, AI_MAX = 5, 9
#: ⚠ 人のもの（★読むのは自由、書くのは禁止）
HUMAN_MIN, HUMAN_MAX = 0, 4

ROOT = pathlib.Path(__file__).resolve().parents[2]
#: ★セーブステートの置き場（⚠ Git 管理外）
FCS = ROOT / "tools" / "fceux" / "fcs"


class SlotDenied(PermissionError):
    """⚠⚠ 人のスロットへ書こうとした。★黙って書かない。"""


def valid(slot) -> bool:
    """★スロット番号として正しいか。"""
    return isinstance(slot, int) and not isinstance(slot, bool) and 0 <= slot <= 9


def can_write(slot) -> bool:
    """★★ AI が**書いて**よいスロットか。

    ⚠⚠ ここが唯一の判定。★呼ぶ側で `if slot >= 5` と書かないこと。

    ★★ 隔離して動いているときは **0〜9 すべて**書けます（RX3-0128 / 2026-09-08）。
      ⚠ そこにあるのは本番の**コピー**で、人のセーブではありません。
      ★物理隔離が本体、この番号の保護は**二重の歯止め**として残します。
    """
    if not valid(slot):
        return False
    if in_sandbox():
        return True
    return AI_MIN <= slot <= AI_MAX


def in_sandbox() -> bool:
    """★隔離された置き場で動いているか（⚠ `dq3/testing/sandbox.py` が立てる）。"""
    return os.environ.get("RETROUX_SANDBOX") == "1"


def can_read(slot) -> bool:
    """★AI が読んでよいスロットか（⚠ 読むのは全部よい）。"""
    return valid(slot)


def check_write(slot) -> int:
    """⚠ 書けなければ例外。★書けるならその番号を返す。"""
    if not can_write(slot):
        raise SlotDenied(
            "⚠⚠ AI はスロット %r へ書けません（★書けるのは %d〜%d。"
            "スロット %d〜%d は人のものです。★隔離して動かせば全部書けます）"
            % (slot, AI_MIN, AI_MAX, HUMAN_MIN, HUMAN_MAX))
    return slot


def path_of(slot, *, rom: str = "DQ3_J") -> pathlib.Path:
    """★そのスロットのファイル。⚠ 存在は確かめません。"""
    if not valid(slot):
        raise ValueError("⚠ スロット番号が範囲外: %r" % (slot,))
    return FCS / ("%s.fc%d" % (rom, slot))
