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


#: ★仲間の名前の 1 バイト → 字形表の索引（RX3-0518 / 2026-10-05）
#:
#:   ★RAM の名前（`state.json` の `party[].name_tiles`）は、字形表の**下位 1 バイト**です。
#:   ★実測（依頼者の本物の `state.json`）: 4 人とも `+ 0x100` で読めた
#:     `[11, 16, 50, 0]` → 「あかり」/ エルシト / ハンソロ / ロミオ（★`party_panel.JOBS` の実測名と同じ 4 人）。
#:   ⚠ 同じ state の `job_tile`（★画面の「つよさ」窓から拾った職業の頭文字）も `+ 0x100` で
#:     ゆ / せ / け / ふ と読め、`class_gender` の 勇者 / 戦士 / 賢者 / 武闘家 と 4 人とも一致した。
NAME_TILE_BASE = 0x100

#: ★名前の空き（★字形表の 0x100 は空白 / ⚠ 4 文字に満たない名前の後ろが埋まる）
_BLANKS = ("␣", " ", "　")

_table: dict | None = None


def _name_table() -> dict:
    """★字形表（索引 → 字）。⚠ 読めなければ空。"""
    global _table
    if _table is None:
        try:
            from retroux.core.text import Charset

            spec = json.loads(PROFILE.read_text(encoding="utf-8")).get("text")
            cs = Charset(spec) if spec else None
            _table = dict(cs.table) if cs is not None else {}
        except Exception:                                # noqa: BLE001 ★読めないだけ
            _table = {}
    return _table


def party_name(tiles) -> str | None:
    """★仲間の名前（`name_tiles`）→ 字。⚠ 1 文字でも読めなければ None（★推測で埋めない）。

    ★濁点・半濁点の字が来たら、前の字に合わせます（NFC）。
    """
    import unicodedata

    if not isinstance(tiles, (list, tuple)) or not tiles:
        return None
    table = _name_table()
    if not table:
        return None
    out = ""
    for raw in tiles:
        if not isinstance(raw, int) or isinstance(raw, bool) or not 0 <= raw <= 0xFF:
            return None
        ch = table.get(NAME_TILE_BASE + raw)
        if ch is None:
            return None
        if ch in ("゛", "゜") and out:
            out = unicodedata.normalize("NFC", out + {"゛": "゙", "゜": "゚"}[ch])
            continue
        out += ch
    for blank in _BLANKS:
        out = out.replace(blank, " ")
    out = out.strip()
    return out or None


def reset() -> None:
    """⚠ 検査用（★文字表を読み直す）。"""
    global _known, _tried, _table
    _known, _tried, _table = None, False, None
