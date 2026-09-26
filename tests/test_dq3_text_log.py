"""貯めた raw タイルを、あとから文字にする（RX3-0016 / 2026-08-25）。

★★ raw と文字を分ける（指示書 §7）★★

    取得 → raw 保存 → 表示用文字列生成

⚠ 文字列だけ保存して raw を捨てる実装は禁止、という指示。
★DQ3 の文字コード表は**目で読んだもの**（high-confidence）で、直る見込みがある。
raw を持っていれば、直したときに**過去に貯めたものを全部やり直せる**。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from dq3rom import text_log
from retroux.core.text import Charset

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"


@pytest.fixture(scope="module")
def charset() -> Charset:
    return Charset(json.loads(PROFILE.read_text(encoding="utf-8"))["text"])


def _event(rows, **kw):
    d = {"frame": 1, "map_id": 0, "loc_type": 0, "battle": 0,
         "window_id": "00_00_04_04", "window": {}, "digest": "d",
         "raw_tiles": rows}
    d.update(kw)
    return text_log.TextEvent.from_json(d)


def test_文字にできる(charset):
    # あ い う（0x10B..0x10D → 生バイト 0B 0C 0D）
    text, unknown = text_log.decode(_event([[0x0B, 0x0C, 0x0D]]), charset)
    assert text == "あいう"
    assert unknown == []


def test_読めないタイルはrawが分かる形で残す(charset):
    """★指示書 §6。⚠ 捨てない。"""
    text, unknown = text_log.decode(_event([[0x0B, 0xEE]]), charset)
    assert text == "あ<EE>"
    assert unknown == [0x1EE]


def test_濁点は1行上から合成する(charset):
    """⚠ DQ3 固有。★け + 上の濁点 = げ。"""
    rows = [[0, 0x6A, 0], [0x20, 0x13, 0x33]]     # 2 行目「にける」/ 1 行目に濁点
    text, _ = text_log.decode(_event(rows), charset)
    assert "にげる" in text


def test_壊れた行があっても止めない(tmp_path):
    """⚠ 1 行の失敗で全部を捨てない。"""
    p = tmp_path / "x.jsonl"
    p.write_text('{"frame":1,"raw_tiles":[[11]]}\nこわれている\n'
                 '{"frame":2,"raw_tiles":[[12]]}\n', encoding="utf-8")
    got = text_log.load(p)
    assert [e.frame for e in got] == [1, 2]


def test_一意な表示にまとめる(charset):
    """★指示書 §23。同じ表示は数えるだけ。"""
    a = _event([[0x0B]], digest="A")
    b = _event([[0x0B]], digest="A")
    c = _event([[0x0C]], digest="B")
    got = text_log.unique_texts([a, b, c], charset)
    assert set(got) == {"A", "B"}
    assert got["A"]["count"] == 2
    assert got["A"]["conversion_status"] == "complete"


def test_読めないものがあればpartialと記録する(charset):
    """★あとで直したいものが分かるように。"""
    got = text_log.unique_texts([_event([[0xEE]], digest="X")], charset)
    assert got["X"]["conversion_status"] == "partial"
    assert got["X"]["unknown"] == [0x1EE]


# --- 実機で貯めたもの ---------------------------------------------------

LOG = ROOT / "work" / "dq3-probe" / "text_events.jsonl"


@pytest.mark.skipif(not LOG.exists() or not LOG.read_text(encoding="utf-8").strip(),
                    reason="実機で貯めた記録が無い")
def test_実機で貯めた記録が読める(charset):
    """★★ 端から端まで。実機 → JSONL → 文字。"""
    events = text_log.load(LOG)
    assert events, "⚠ 1 件も読めない"
    for e in events:
        assert e.raw_tiles, "⚠ raw タイルが空（★一次情報を捨てている）"
    texts = text_log.unique_texts(events, charset)
    joined = " ".join(v["text"] for v in texts.values())
    # ★タイトル画面のメニューが読めているはず
    assert "ぼうけん" in joined, joined[:200]
