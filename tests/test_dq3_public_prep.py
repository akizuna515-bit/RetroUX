"""公開準備の道具を見張る（RX3-0414 / RX3-0421 / RX3-0422 / 2026-09-24）。

⚠⚠ **`save_id` が一意であること**が要（★依頼者 §5）。

```text
⚠ 2026-09-23 に踏んだ形:
   tools/fceux/fcs/DQ3_J.fc3 と work/tests/savestates/DQ3_J.fc3 は**別物**なのに
   `path.name` だけを ID にしたので**同じ ID** になり、★片方が黙って消えた。
```
"""
from __future__ import annotations

import csv
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREP = ROOT / "work" / "release" / "public-prep"
MANUAL = ROOT / "dq3" / "testing" / "map_kind_manual.json"


def _rows(name: str):
    path = PREP / name
    if not path.exists():
        pytest.skip("⚠ %s がまだありません（★先に棚卸しを回す）" % name)
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


# --- ★★ save_id は一意（⚠ ここが今回の本体）--------------------------------

def test_save_idは一意():
    """⚠⚠ 同じ名前のファイルが別の置き場にあっても、★別の ID になること。"""
    rows = _rows("dq3-savestate-inventory.csv")
    ids = [r["save_id"] for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, "⚠⚠ save_id が重なっています（★片方が消えます）: %s" % dup[:5]
    assert len(ids) >= 1


def test_save_idに置き場が入っている():
    """★`slot:` / `backup:` / `fixture:` などの接頭辞で、⚠ 出どころが読めること。"""
    rows = _rows("dq3-savestate-inventory.csv")
    bad = [r["save_id"] for r in rows if ":" not in r["save_id"]]
    assert not bad, "⚠ 置き場の接頭辞が無い: %s" % bad[:5]


def test_source_pathも一意():
    """⚠ `save_id` が一意でも、★元のファイルが重なっていたら数え間違いです。"""
    rows = _rows("dq3-savestate-inventory.csv")
    paths = [r["source_path"] for r in rows]
    dup = sorted({p for p in paths if paths.count(p) > 1})
    assert not dup, "⚠⚠ 同じファイルを 2 回数えています: %s" % dup[:5]


# --- ⚠ 「分からない」を 0 や空で塗りつぶしていないか ------------------------

def test_数えられないものを0と書かない():
    """⚠⚠ `record_count` は**数えられなければ -1**（★0 は「空」の意味）。"""
    rows = _rows("dq3-knowledge-inventory.csv")
    for r in rows:
        n = int(r["record_count"])
        assert n == -1 or n >= 0, "⚠ 変な件数: %s=%s" % (r["knowledge_type"], n)
    # ★1 つは必ず数えられているはず（⚠ 全部 -1 なら読み方が壊れている）
    assert any(int(r["record_count"]) > 0 for r in rows), "⚠⚠ 1 件も数えられていない"


def test_地名の状態が3つのどれか():
    rows = _rows("dq3-savestate-inventory-located.csv")
    ok = {"confirmed", "provisional", "unknown"}
    bad = {r["location_status"] for r in rows} - ok
    assert not bad, "⚠ 知らない location_status: %s" % bad


# --- ★手で付けた地図の種類（⚠ 汎用の分類器ではない）------------------------

def test_手で付けた種類は決めた語だけ():
    if not MANUAL.exists():
        pytest.skip("⚠ 手で付けた表がありません")
    data = json.loads(MANUAL.read_text(encoding="utf-8"))
    ok = {"dungeon", "tower", "cave", "castle", "other"}
    for mid, row in (data.get("maps") or {}).items():
        assert row.get("kind") in ok, "⚠ 知らない kind: map %s = %s" % (mid, row.get("kind"))
        assert row.get("why"), "⚠⚠ 根拠が書いていない: map %s" % mid
        assert row.get("name"), "⚠ 地名が書いていない: map %s" % mid


def test_手で付けた表は小さいまま():
    """⚠⚠ **Location 分類システムにしない**（★依頼者 §2）。

    ⚠ 増え始めたら、★「撮影候補を選ぶため」という目的から逸れています。
    """
    if not MANUAL.exists():
        pytest.skip("⚠ 手で付けた表がありません")
    data = json.loads(MANUAL.read_text(encoding="utf-8"))
    n = len(data.get("maps") or {})
    assert n <= 30, ("⚠⚠ 手で付けた地図が %d 件に増えています。"
                     "★分類システムを作り始めていないか見直してください" % n)


# --- ⚠ fixture と通常プレイのセーブを混同しない（★依頼者 §1）---------------

# --- ⚠⚠ 撮影の初期化範囲（★依頼者 RX3-0424 §2）--------------------------

def test_撮影の初期化はprogressと地名を消さない():
    """⚠⚠ **`--reset talk` を使ってはいけない**ことを固定する。

    ```text
    ⚠ `topics` は topic-state.json **＋ progress.json ＋ location-book.json** を消す
    ★撮影で消してよいのは 勇者メモ と 聞き込み履歴 だけ（依頼者 §2）
    ```
    """
    from dq3.knowledge.playdata import PlayDataService

    svc = PlayDataService()
    keep = {"progress.json", "location-book.json", "seen.json", "enemy-names.json",
            "chests.json", "explored.json", "hidden-items.json"}

    # ★撮影で使う範囲（memos + hearing）は、⚠ 残すべきファイルに触らないこと
    touched = {p.name for k in ("memos", "hearing") for p in svc.files_of(k)}
    bad = touched & keep
    assert not bad, "⚠⚠ 撮影の初期化が残すべきものを消します: %s" % sorted(bad)

    # ⚠ `topics` を足すと壊れることも示す（★なぜ使わないかが読める）
    with_topics = {p.name for k in ("memos", "hearing", "topics") for p in svc.files_of(k)}
    assert with_topics & keep, (
        "⚠ topics が progress / location-book を消さなくなったなら、"
        "★ランブックの注意書きを見直してください")


def test_fixtureはカタログで区別できる():
    path = PREP / "dq3-public-shooting-catalog.json"
    if not path.exists():
        pytest.skip("⚠ カタログがまだありません")
    rows = json.loads(path.read_text(encoding="utf-8"))
    fx = [r for r in rows if r["save_id"].startswith(("fixture:", "derived:"))]
    if not fx:
        pytest.skip("⚠ fixture が候補に入っていません")
    for r in fx:
        assert "fixture" in r["note"], (
            "⚠⚠ fixture なのに注意書きが無い（★通常プレイと誤認する）: %s" % r["save_id"])
