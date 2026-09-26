"""窓が開いた瞬間に撮った画面を読む（RX3-0124 ① / 2026-09-19）。

★`research/probes/active/dq3_choice_probe.lua` が 1 枚 1 行で書きます:

```text
{"f":1234,"id":29,"delay":20,"screen":"00 …（960 升の 16 進）"}
```

## ⚠⚠ ここが確かめたいこと

```text
窓 $1D   「はい」「いいえ」   ★選択肢
窓 $16   「かいにきた」       ★店
窓 $17   「どくのちりょう」   ★教会
```

★窓の番号（RAM `$0077`）と、⚠ **画面に実際に写った語**が一致したら、
`RX3-0121` の INFERRED を CONFIRMED へ上げられます。

## ⚠ 原作テキストは持ちません

★探す語は `dq3rom/profiles/*.json` の**既にある語**だけを使います
（⚠ 新しく台詞を書き写さない / `docs/00-project-policy.md`）。
"""
from __future__ import annotations

import io
import json
import pathlib

#: ★窓の番号 → その窓に出るはずの語（⚠ profile に**既にある**語だけ）
#:   ★「はい」「いいえ」は `tests/test_dq3_choice.py` が窓の定義から読んでいるもの。
EXPECT = {
    0x1D: ("はい", "いいえ"),
    0x16: ("かいにきた",),
    0x17: ("どくのちりょう",),
}

#: ★確かめたい窓（★Acceptance の 3 つ）
WANTED = tuple(sorted(EXPECT))


def load(path) -> list:
    """★1 行 1 枚を読む。⚠ 壊れた行は飛ばす（★全部を失わない）。"""
    out, bad = [], 0
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict) and row.get("screen"):
            row["broken"] = bad
            out.append(row)
    return out


def screen_of(row) -> bytes:
    """★16 進の並び → 升の値。⚠ 読めなければ空。"""
    # ⚠ probe は画面が取れないと `?no-host` / `?nil` / `?err:…` と書きます。
    #   ★ここで別に弾く必要はありません（`bytes.fromhex` が例外にする）。
    #   ⚠⚠ 以前は先に `startswith("?")` で弾いていましたが、★壊す実験で
    #     **外しても赤にならない**＝死にコードだと分かったので外しました。
    try:
        return bytes.fromhex(str(row.get("screen") or ""))
    except ValueError:
        return b""


def text_of(row, charset) -> str:
    """★その画面の文（⚠ 空の行は落とす）。"""
    from dq3rom import screen as SC

    raw = screen_of(row)
    if len(raw) < SC.COLUMNS * SC.ROWS:
        return ""
    return " / ".join(ln.stripped for ln in SC.read_screen(raw, charset) if ln.stripped)


def matched(row, charset) -> tuple:
    """★その 1 枚が、窓の番号どおりの語を写しているか。

    戻り値: `(窓の番号, 見つかった語, 全部そろったか)`
    """
    wid = int(row.get("id") or -1)
    want = EXPECT.get(wid)
    if want is None:
        return wid, (), False
    body = text_of(row, charset)
    hit = tuple(w for w in want if w in body)
    return wid, hit, len(hit) == len(want)


def summarise(rows, charset) -> dict:
    """★窓の番号ごとのまとめ（⚠ 「0 枚」も残す）。"""
    out: dict = {}
    for row in rows:
        wid, hit, full = matched(row, charset)
        got = out.setdefault(wid, {"shots": 0, "matched": 0, "words": set(),
                                   "first_frame": None})
        got["shots"] += 1
        got["words"].update(hit)
        if full:
            got["matched"] += 1
            if got["first_frame"] is None:
                got["first_frame"] = row.get("f")
    for wid, got in out.items():
        got["words"] = sorted(got["words"])
        got["expected"] = list(EXPECT.get(wid, ()))
    return out


def verdict(rows, charset) -> dict:
    """★Acceptance の 3 つに答える（⚠ 足りないものを黙らせない）。"""
    got = summarise(rows, charset)
    done = {wid: bool(got.get(wid, {}).get("matched")) for wid in WANTED}
    return {
        "shots": len(rows),
        "windows": got,
        "confirmed": sorted(w for w, ok in done.items() if ok),
        "missing": sorted(w for w, ok in done.items() if not ok),
        "ok": all(done.values()),
    }


def report(rows, charset) -> str:
    """★人が読む 1 枚（⚠ 原作の文は出さない / 語の有無だけ）。"""
    got = verdict(rows, charset)
    lines = ["撮った枚数: %d" % got["shots"]]
    for wid in sorted(got["windows"]):
        w = got["windows"][wid]
        lines.append("  窓 $%02X  %d 枚 / 一致 %d 枚  見つかった語: %s"
                     % (wid, w["shots"], w["matched"],
                        "・".join(w["words"]) or "（無し）"))
    lines.append("★確かめられた窓: %s"
                 % ("・".join("$%02X" % w for w in got["confirmed"]) or "（無し）"))
    lines.append("⚠ まだの窓: %s"
                 % ("・".join("$%02X" % w for w in got["missing"]) or "（無し）"))
    return chr(10).join(lines)


def charset():
    """★画面の文字表（⚠ profile が正本）。"""
    from retroux.core.text import Charset

    root = pathlib.Path(__file__).resolve().parents[2]
    got = json.loads((root / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                     .read_text(encoding="utf-8"))["text"]
    return Charset(got)


__all__ = ["EXPECT", "WANTED", "load", "screen_of", "text_of", "matched",
           "summarise", "verdict", "report", "charset"]
