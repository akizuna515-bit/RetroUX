"""貯めた raw タイルを、あとから文字にする（RX3-0016 / 2026-08-25）。

## ★★ raw と文字を分ける（指示書 §7）

    取得 → raw 保存 → 表示用文字列生成

⚠ 文字列だけ保存して raw を捨てる実装は禁止、という指示。
★文字コード表を直したら、**過去に貯めたものを全部読み直せる**ようにするため。

実際、DQ3 の文字コード表は目で読んだもの（`high-confidence`）で、
⚠ 直る見込みがある。★raw を持っていれば、直したときに全部やり直せる。

## 使い方

```bash
python -m dq3rom text-log --log work/runtime/dq3-probe/text_events.jsonl
```
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

from .screen import (DAKUTEN, HANDAKUTEN, PATTERN_BASE, _SEMI_VOICED, _VOICED,
                     is_mark_tile)
from .window import DIVIDER


@dataclasses.dataclass(frozen=True)
class TextEvent:
    """1 回ぶんの表示。⚠ `raw_tiles` が一次情報。"""

    frame: int
    map_id: int
    loc_type: int
    battle: int
    window_id: str
    window: dict
    digest: str
    raw_tiles: tuple[tuple[int, ...], ...]

    @classmethod
    def from_json(cls, d: dict) -> "TextEvent":
        return cls(
            frame=int(d.get("frame", 0)),
            map_id=int(d.get("map_id", 0)),
            loc_type=int(d.get("loc_type", 0)),
            battle=int(d.get("battle", 0)),
            window_id=str(d.get("window_id", "")),
            window=d.get("window") or {},
            digest=str(d.get("digest", "")),
            raw_tiles=tuple(tuple(int(t) for t in row)
                            for row in (d.get("raw_tiles") or [])),
        )


def decode(event: TextEvent, charset) -> tuple[str, list[int]]:
    """raw タイル → 文字。

    ⚠ DQ3 の濁点は**1 行上のマス**にある。★窓の中だけを保存しているので、
    1 行目の濁点は取れない（窓の外にある）。**そこは諦めて記録に残す**。
    ⚠ 読めないタイルは `<XX>` で残す（★捨てない）。
    """
    lines: list[str] = []
    unknown: list[int] = []
    rows = event.raw_tiles
    for i, row in enumerate(rows):
        above = rows[i - 1] if i > 0 else ()
        chars: list[str] = []
        for j, b in enumerate(row):
            if b == DIVIDER:
                chars.append(" ")
                continue
            if is_mark_tile(PATTERN_BASE + b):
                chars.append(" ")        # ★印は下の行へ合成済み（RX3-0108）
                continue
            ch = charset.table.get(PATTERN_BASE + b)
            if ch is None:
                unknown.append(PATTERN_BASE + b)
                chars.append(f"<{b:02X}>")
                continue
            mark = PATTERN_BASE + above[j] if j < len(above) else 0
            if mark == DAKUTEN:
                ch = _VOICED.get(ch, ch)
            elif mark == HANDAKUTEN:
                ch = _SEMI_VOICED.get(ch, ch)
            chars.append(ch)
        lines.append("".join(chars).replace("␣", " ").rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines), unknown


def load(path: pathlib.Path) -> list[TextEvent]:
    """⚠ 壊れた行があっても止めない（★1 行の失敗で全部を捨てない）。"""
    out: list[TextEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(TextEvent.from_json(json.loads(line)))
        except (ValueError, TypeError):
            continue
    return out


def unique_texts(events: list[TextEvent], charset) -> dict[str, dict]:
    """一意な表示の辞書（指示書 §23 の `texts`）。

    ★同じ文字列でも**窓の形が違えば別**として持てるよう、指紋を鍵にする。
    """
    out: dict[str, dict] = {}
    for e in events:
        text, unknown = decode(e, charset)
        key = e.digest
        if key in out:
            out[key]["count"] += 1
            continue
        out[key] = {
            "window_id": e.window_id,
            "text": text,
            "unknown": sorted(set(unknown)),
            # ⚠ 全部読めたかどうかを残す（★あとで直したいものが分かる）
            "conversion_status": "complete" if not unknown else "partial",
            "count": 1,
            "first_frame": e.frame,
            "map_id": e.map_id,
        }
    return out
