"""`events.jsonl` の世代交代（製品版ログ整理 Phase 7 / 指示書 §25）。

## ⚠⚠ ここで守っていること

`retroux.log` と違い、`events.jsonl` は

    書き手 … Lua（`Bridge:emit`）
    読み手 … Python（`Recorder`。`IngestState` に「どこまで読んだか」を持つ）

と分かれています。★だから rename するだけでは**2通りに壊れます**:

  1. Lua が名前の変わった側へ書き続ける
     → `Bridge:emit` を「書くたびに開き直す」形にして塞いだ
  2. 取り込み位置が古いまま残り、**新しいファイルの先頭を読み飛ばす**
     → `rotate_events` が世代交代と位置のリセットを**対で**行う

⚠ さらに、取り込みが追いついていないうちに切り替えると、
  **まだ DB に入っていない行を置き去りに**します。★そこも見ます。
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from retroux.core.events_rotation import archives, rotate  # noqa: E402

LINE = '{"type":"battle_end","frame":1,"time":1786000000}\n'


def _make(path: pathlib.Path, size: int) -> int:
    """おおよそ `size` バイトのイベントファイルを作る。"""
    body = LINE * (size // len(LINE) + 1)
    path.write_text(body, encoding="utf-8")
    return path.stat().st_size


# --- 上限に届いていないとき ----------------------------------------------

def test_上限未満なら何もしない(tmp_path):
    p = tmp_path / "events.jsonl"
    n = _make(p, 100)
    got = rotate(p, ingested_offset=n, max_bytes=10_000)
    assert got.rotated is False
    assert p.exists() and p.stat().st_size == n
    assert archives(p) == []


def test_ファイルが無ければ何もしない(tmp_path):
    got = rotate(tmp_path / "events.jsonl", ingested_offset=0, max_bytes=1)
    assert got.rotated is False
    assert "ありません" in got.reason


# --- ★★ 取り込みが追いついていないとき（要）------------------------------

def test_取り込みが遅れていたら切り替えない(tmp_path):
    """⚠⚠ **未取り込みの行を置き去りにしない。**

    ★ここが抜けると、上限に達した瞬間に「まだ DB に入っていない戦闘」が
      静かに消えます（★ファイルは残りますが、誰も読みません）。
    """
    p = tmp_path / "events.jsonl"
    n = _make(p, 5_000)
    got = rotate(p, ingested_offset=n - 500, max_bytes=1_000)
    assert got.rotated is False, "取り込みが遅れているのに切り替えた"
    assert "遅れています" in got.reason
    assert p.stat().st_size == n


def test_追いついていれば切り替える(tmp_path):
    p = tmp_path / "events.jsonl"
    n = _make(p, 5_000)
    got = rotate(p, ingested_offset=n, max_bytes=1_000)
    assert got.rotated is True, got.reason
    assert got.archived is not None and got.archived.exists()
    assert got.archived.stat().st_size == n, "退避したファイルの中身が違う"
    assert p.exists() and p.stat().st_size == 0, "新しいファイルが空でない"


# --- 世代の数 -------------------------------------------------------------

def test_決めた数だけ残して古いものを消す(tmp_path):
    p = tmp_path / "events.jsonl"
    kept = []
    for i in range(6):
        _make(p, 2_000)
        got = rotate(p, ingested_offset=p.stat().st_size, max_bytes=1_000,
                     generations=3,
                     now=datetime(2026, 8, 13, 9, 0, i, tzinfo=timezone.utc))
        assert got.rotated, got.reason
        kept.append(got.archived)
    left = archives(p)
    assert len(left) == 3, [x.name for x in left]
    # ★残っているのは**新しいほうから3つ**
    assert {x.name for x in left} == {x.name for x in kept[-3:]}


def test_同じ秒に二度来ても上書きしない(tmp_path):
    """⚠ 記録を消さない。★諦めるほうが安全。"""
    p = tmp_path / "events.jsonl"
    when = datetime(2026, 8, 13, 9, 0, 0, tzinfo=timezone.utc)
    _make(p, 2_000)
    first = rotate(p, ingested_offset=p.stat().st_size, max_bytes=1_000, now=when)
    assert first.rotated
    kept = first.archived.read_bytes()
    size = _make(p, 2_000)
    second = rotate(p, ingested_offset=p.stat().st_size, max_bytes=1_000, now=when)
    assert second.rotated is False
    assert "既にあります" in second.reason
    # ★先に退避したものが**そのまま**残っていること（⚠ 上書きされていない）
    assert first.archived.read_bytes() == kept, "先の世代を上書きした"
    # ★いまのファイルも消えていないこと
    assert p.stat().st_size == size, "切り替えていないのに中身が変わった"


# --- ★★ 取り込み位置と対で動くこと（要）---------------------------------

def test_世代交代したら取り込み位置が0へ戻る(tmp_path):
    """⚠⚠ **片方だけやると壊れる。**

        rename だけ → 位置が古いまま。★新しいファイルの先頭を読み飛ばす
        reset だけ  → 同じ行をもう一度取り込む（二重記録）
    """
    from retroux.core.db.database import Database
    from retroux.core.recorder import rotate_events

    db = Database(tmp_path / "n.sqlite3")
    p = tmp_path / "events.jsonl"
    n = _make(p, 5_000)
    source = str(p.resolve())
    db.set_ingest_state(source, n, "sig")

    got = rotate_events(db, p, max_bytes=1_000)
    assert got.rotated, got.reason
    offset, sig = db.get_ingest_state(source)
    assert offset == 0, f"取り込み位置が {offset} のまま（★先頭を読み飛ばす）"
    assert sig is None, "古い署名が残っている"
    db.close()


def test_切り替えなかったときは取り込み位置を触らない(tmp_path):
    """⚠ 触ると**同じ行をもう一度**取り込む。"""
    from retroux.core.db.database import Database
    from retroux.core.recorder import rotate_events

    db = Database(tmp_path / "n.sqlite3")
    p = tmp_path / "events.jsonl"
    n = _make(p, 500)
    source = str(p.resolve())
    db.set_ingest_state(source, n, "sig")

    got = rotate_events(db, p, max_bytes=10_000)
    assert got.rotated is False
    offset, sig = db.get_ingest_state(source)
    assert (offset, sig) == (n, "sig"), "切り替えていないのに位置を変えた"
    db.close()


# --- ⚠ Lua 側がハンドルを持っていないこと ---------------------------------

def test_Luaはeventsのハンドルを持たない():
    """★持ったままだと、世代交代しても**名前の変わった側**へ書き続ける。

    ⚠ しかもエラーが出ないので気づけない（`retroux.log` で踏んだのと同じ形）。
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "retroux" / "emulator" / "fceux" / "bridge.lua").read_text(
        encoding="utf-8")
    assert "self.events = io.open" not in src, (
        "events のハンドルを持ったままになっている")
    assert "io.open(self.events_path" in src, "emit が開き直していない"
