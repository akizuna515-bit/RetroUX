"""画面や会話から取った「名前」を、出す形にそろえる（RX3-0100 / 2026-09-07）。

★★ 入口はここ 1 つ ★★

⚠⚠ DQ3 は り と リ に**同じ絵を 1 つしか持っていません**（`RX3-0093`）。
★そのため、画面から読んだ名前も、会話から取った地名も「アりアハン」になります。

```text
ROM の名前     dq3rom/names.py        ★復号のあとに通す
画面の敵の名前  enemies_seen._tidy     ★ここを通す
会話の地名     locations.greeting_place ★ここを通す
```

⚠ ずらすと突き合わせが割れます（★`RX3-0093` の教訓）。→ **同じ関数を通す**。

⚠ 文字表が読めなければ、★何もしないでそのまま返します（黙って落ちない）。
"""
from __future__ import annotations

import json
import pathlib

#: ★プロファイル（⚠ 文字表はここから。★ここに文字を書かない）
PROFILE = (pathlib.Path(__file__).resolve().parents[2]
           / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")

_known: set | None = None
_tried = False


def known_chars() -> set:
    """★文字表が出せる字（⚠ 読めなければ空）。"""
    global _known, _tried
    if _tried:
        return _known or set()
    _tried = True
    try:
        from retroux.core.text import Charset

        spec = json.loads(PROFILE.read_text(encoding="utf-8")).get("text")
        cs = Charset(spec) if spec else None
        _known = set(cs.table.values()) if (cs is not None and cs.usable) else None
    except Exception:                                    # noqa: BLE001 ★直さないだけ
        _known = None
    return _known or set()


def to_display(name: str) -> str:
    """★名前を出す形に（⚠ 同じ絵を使い回している かな を直す）。"""
    if not name:
        return name
    known = known_chars()
    if not known:
        return name
    from dq3rom.kana import katakana_word

    return katakana_word(name, known)


def reset() -> None:
    """⚠ 検査用（★文字表を読み直す）。"""
    global _known, _tried
    _known, _tried = None, False
