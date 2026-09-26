"""検査は依頼者のプレイデータ（`work/dq3-knowledge`）を書かない（RX-0141 / 2026-09-18）。

⚠⚠ **`work/dq3-knowledge/` は遊んだ記録の正本**です。ここを検査が書くと、
★画面には出ないまま「聞いたはずの人」「開けたはずの宝箱」が変わります。

```text
2026-09-18  location-book.json が全件検査の間に 2 回以上書き換わった
            （★tests/test_dq3_sandbox.py が「本番が変わった」で赤くなって気づいた）
2026-09-18  隠し道具の検査が memo_path を渡し忘れ、本物の memos.jsonl に 1 行書いた
```

★直し方は `conftest.py`（`RETROUX_WRITE_ROOT` を import より前に一時フォルダへ）。
⚠ ここは**その口が本当に効いているか**を見ます。

## ⚠⚠ この検査の作り（★足し忘れで素通りしないこと）

★`dq3/knowledge/` を**総なめ**して、`work/dq3-knowledge` を指す既定値を**見つけた分だけ**確かめます。
⚠ 名簿を手で持つと、口が増えたときに黙って漏れます（`RX3-0215` / `RX-0138` と同じ型）。
"""
from __future__ import annotations

import importlib
import os
import pathlib
import pkgutil

from dq3 import paths as P3

#: ★repo の中の本物（⚠ `P3.work` は検査中は一時フォルダに逃げている）
REAL_ROOT = P3.repo("work").resolve()
REAL_KNOWLEDGE = P3.repo("work", "dq3-knowledge").resolve()


def _inside_repo_work(path) -> bool:
    got = pathlib.Path(path).resolve()
    return REAL_ROOT == got or REAL_ROOT in got.parents


def _knowledge_defaults() -> list[tuple[str, pathlib.Path]]:
    """★`dq3/knowledge/**` の定数のうち、プレイデータの置き場を指しているもの。"""
    import dq3.knowledge as K

    out = []
    for info in pkgutil.iter_modules(K.__path__):
        try:
            mod = importlib.import_module("dq3.knowledge.%s" % info.name)
        except Exception:                                    # noqa: BLE001 ⚠ 読めない環境でも止めない
            continue
        for name in dir(mod):
            if name.startswith("_"):
                continue
            value = getattr(mod, name)
            # ⚠⚠ `LazyPath` も拾う（RX3-0342 / 2026-09-21）。★`isinstance(pathlib.Path)` は
            #   **False** なので、⚠ ここを直さないとこの検査が**黙って 1 件しか見なくなります**
            #   （★実際に 8 件 → 1 件になった / `RX3-0215` と同じ「見張りが盲目になる」型）。
            if not isinstance(value, (pathlib.Path, P3.LazyPath)):
                continue
            got = pathlib.Path(os.fspath(value))
            if "dq3-knowledge" in got.as_posix():
                out.append(("dq3.knowledge.%s.%s" % (info.name, name), got))
    return out


def test_プレイデータの既定はrepoの外を指す():
    """⚠⚠ 口が 1 つでも repo の中を指していたら、そこから本物が書かれる。"""
    found = _knowledge_defaults()
    assert len(found) >= 8, "⚠ 探せていない（★この検査が何も見ていない）: %d 件" % len(found)
    leaked = [(name, str(path)) for name, path in found if _inside_repo_work(path)]
    assert not leaked, "⚠⚠ 検査から本物のプレイデータへ書ける口: %r" % leaked


def test_書き先そのものがrepoの外():
    assert not _inside_repo_work(P3.work()), "⚠⚠ 書き先が repo の中: %s" % P3.work()
    assert not _inside_repo_work(P3.work("dq3-knowledge"))
    # ★読む口（repo）は動かない（⚠ ROM・fixture はここを通る）
    assert _inside_repo_work(P3.repo("work", "rom"))


def test_既定のまま書いても本物は変わらない(tmp_path):
    """★実際に書いてみる（⚠ 「指しているだけ」では確かめたことにならない）。

    ## ⚠⚠ 書く前に止める（★2026-09-18 に実際にやってしまった）

      ⚠ 壊す実験で `conftest.py` の逃がしを外したとき、この検査が**依頼者の遊んでいる記録**へ
        書きました（★勇者メモ 1 行 / 聞いた台帳 1 回 / 会話の記録 1 行 ― 手で外した）。
      → ★逃がせていないと分かった時点で、**書かずに**赤くする。
    """
    from dq3.knowledge import npc_heard as H
    from dq3.knowledge.memos import MemoStore

    assert not _inside_repo_work(P3.work("dq3-knowledge")), (
        "⚠⚠ 書き先が repo の中（★本物を書く前に止める）: %s" % P3.work("dq3-knowledge"))

    watched = {}
    for name in ("memos.jsonl", "npc-heard.json", "location-book.json", "chests.json"):
        real = REAL_KNOWLEDGE / name
        watched[name] = real.read_bytes() if real.exists() else None

    # ★既定のパスで書く（⚠ 検査が path を渡し忘れた状態をわざと作る）
    MemoStore().add("★RX-0141 の検査", source="conversation")
    ledger = H.HeardLedger()
    ledger.record(9, 1, 11, time="day", at="2026-09-18T00:00:00", text="★RX-0141 の検査")
    ledger.save()

    for name, before in watched.items():
        real = REAL_KNOWLEDGE / name
        now = real.read_bytes() if real.exists() else None
        assert now == before, "⚠⚠ 本物のプレイデータが変わった: %s" % name
    # ★逃がした先には書けている（⚠ 「書けていないから無事」では意味が無い）
    assert (P3.work("dq3-knowledge") / "memos.jsonl").exists()


def test_逃がした道をrepo側へ読み替えられる():
    """★「Git の外か」を見る検査のための読み替え（`paths.as_repo` / RX-0141）。

    ⚠ 一時フォルダを `git check-ignore` に渡しても意味が無い（★repo の外だから必ず外れる）。
    """
    got = P3.as_repo(P3.work("dq3-knowledge", "topic-state.json"))
    assert got == P3.repo("work", "dq3-knowledge", "topic-state.json"), got
    assert P3.as_repo(P3.work()) == P3.repo("work")
    # ⚠ 書き先の下でない道は触らない
    outside = pathlib.Path(__file__).resolve()
    assert P3.as_repo(outside) == outside


def test_state_jsonやUIの設定も本物を触らない():
    """⚠ 遊びの記録は `dq3-knowledge` だけではない（★窓の位置・設定・IPC も）。"""
    from dq3.ui.ui_settings import DEFAULT_PATH as UI_SETTINGS

    for path in (P3.work("state.json"), P3.work("dq3-command.json"),
                 P3.work("dq3-window-state.json"), UI_SETTINGS):
        assert not _inside_repo_work(path), "⚠⚠ 本物を触る: %s" % path
