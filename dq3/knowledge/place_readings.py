"""場所の名前の**読み**（RX3-0292 / 2026-09-18）。

依頼者 2026-09-18:

    オリビアの岬の情報を得たら、オリビアの岬を表示させたい。
    ここ仕様甘い気がするので、いまの仕様をレポートしてほしい
    → ★レポートのあと「まずは A（名簿に読みを足して、かな同士で照合）を対応しよう」

## ⚠⚠ なぜ要るか — 名簿は漢字、会話はかな

```text
名簿（Guide Master）  岬の洞窟 / ナジミの塔 / 幽霊船 …      ★人が書いた漢字まじり
会話（ゲームの本文）  ＊「みさきのどうくつには …      ★全部かな（⚠ 文は架空）
                        ナジミのとうに のぼると。
照合                  `concepts.fold` は**カタカナ → ひらがな**だけ
                      ⚠⚠ 漢字はそのまま = **永久に当たらない**
```

★だから「行ってみる？」に `BY_TALK`（会話で聞いた場所）が **1 件も出ていませんでした**
（⚠ 実データで確認 / 出ていた 8 件は全部 `BY_TOPIC`）。

## ★置き場（⚠ コードは 1 バイトも書きません）

```text
input/dq3_place_readings.csv          ★正本（⚠ 人が置く / `input/` は読むだけ）
work/dq3-knowledge/place-readings.csv ★下書き（⚠ Git の外 / 正本が無ければこちらを読む）
```

列は `name,reading` の 2 つだけです（⚠ 余分な列は素通し）。

## ⚠ 守ること

```text
⚠ 読みは**かな**だけ           ★漢字が混じっていたら読まない（= 直す手がかりを残す）
⚠ 分からない読みは**空**        ★推測で埋めない（⚠ 間違った読みは「別の場所」に当たりうる）
⚠ 表が無くても落ちない          ★今までどおり（名前そのままで照合）
```
"""
from __future__ import annotations

import csv
import io
import pathlib
import re

from .. import paths

#: ★正本（⚠ 人が置く）
MASTER_PATH = paths.repo("input", "dq3_place_readings.csv")
#: ★下書き（⚠ Git の外 / 正本が無ければこちら）
DRAFT_PATH = paths.lazy_work("dq3-knowledge", "place-readings.csv")

#: ★読みに使ってよい字（⚠ ひらがな・カタカナ・長音・中黒・空白だけ）
KANA = re.compile(r"^[ぁ-ゟ゠-ヿーー・\s]+$")

#: ⚠ 読めなかった行（★黙らず残す / 画面には出さない）
problems: list = []


def _rows(path: pathlib.Path) -> list[dict]:
    try:
        text = io.open(path, encoding="utf-8-sig", newline="").read()
    except OSError:
        return []
    return list(csv.DictReader(io.StringIO(text)))


def load(path=None) -> dict:
    """★`名前 → 読み`（⚠ 無ければ空の辞書。★落ちません）。

    ⚠ `path` を渡さなければ、正本 → 下書き の順に探します。
    """
    problems.clear()
    if path is not None:
        rows = _rows(pathlib.Path(path))
    else:
        rows = _rows(MASTER_PATH) or _rows(DRAFT_PATH)
    out = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        reading = (row.get("reading") or "").strip()
        if not name or not reading:
            continue                                   # ★読みが空 = まだ分からない（⚠ 推測しない）
        if not KANA.match(reading):
            # ⚠ 漢字まじりの「読み」は読まない（★当たらないだけでなく、直す手がかりを残す）
            problems.append("%s: 読みがかなではありません（%s）" % (name, reading))
            continue
        out[name] = reading
    return out


def reading_of(name: str, table: dict | None = None) -> str | None:
    """★その名前の読み（⚠ 無ければ None）。"""
    if not name:
        return None
    return (load() if table is None else table).get(str(name))
