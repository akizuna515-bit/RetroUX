"""書き先は**あとから**変えても効くこと（RX3-0342 / 2026-09-21）。

## ⚠⚠ なぜ要るか

★2026-09-21、実機ランナーが**依頼者の `work/dq3-knowledge/` へ書きました**。

```text
⚠ 置き場が import 時の定数（`DEFAULT_PATH = paths.work(...)`）
⚠ 隔離の環境変数（RETROUX_WRITE_ROOT）は `open_sandbox()` が立てる = **import の後**
→ ⚠⚠ 定数はもう**本番**を指している
```

★pytest は `conftest.py` が `pytest_configure`（collection より前）で立てるので無事でした。
⚠⚠ **すり抜けたのは `scripts/*_run.py` の単体起動**です。

## ★この検査が見るもの

⚠ 「環境変数を**後から**立てても、置き場がそちらを向くか」。
★向かなければ、⚠ それは本番へ書く道が残っているということです。
"""
from __future__ import annotations

import importlib
import os
import pathlib

import pytest

from dq3 import paths

#: ★依頼者のデータを持つ置き場（⚠ ここが本番を指したら事故）
WATCHED = (
    ("dq3.knowledge.location_book", "BOOK_PATH"),
    ("dq3.knowledge.locations", "BOOK_PATH"),
    ("dq3.knowledge.locations", "KNOWLEDGE_PATH"),
    ("dq3.knowledge.enemies_seen", "DEFAULT_PATH"),
    ("dq3.knowledge.chest_book", "DEFAULT_PATH"),
    ("dq3.knowledge.explored_map", "DEFAULT_PATH"),
    ("dq3.knowledge.hidden_items", "DEFAULT_PATH"),
    ("dq3.knowledge.item_names", "DEFAULT_PATH"),
    ("dq3.knowledge.memos", "DEFAULT_PATH"),
    ("dq3.knowledge.progress", "DEFAULT_PATH"),
    ("dq3.knowledge.seen_map", "DEFAULT_PATH"),
    ("dq3.knowledge.npc_heard", "DEFAULT_DIR"),
    ("dq3.knowledge.playdata", "KNOWLEDGE"),
    ("dq3.knowledge.place_readings", "DRAFT_PATH"),
    ("dq3.knowledge.guide", "STATE_PATH"),
    ("dq3.knowledge.concepts", "CONVERSATIONS"),
    ("dq3.knowledge.concepts", "MEMOS"),
    ("dq3.ui.ui_settings", "DEFAULT_PATH"),
    ("dq3.ui.view_model", "DEFAULT_STATE"),
    ("dq3.ui.view_model", "DEFAULT_KNOWLEDGE"),
    ("dq3.ui.commands", "DEFAULT_COMMAND"),
)


@pytest.mark.parametrize("module_name,attr", WATCHED)
def test_書き先を後から変えても置き場が追随する(module_name, attr, tmp_path, monkeypatch):
    """⚠⚠ ここが赤いなら、★本番へ書く道が残っています。"""
    mod = importlib.import_module(module_name)
    got = getattr(mod, attr, None)
    assert got is not None, "⚠ %s に %s がありません（★名前が変わった？）" % (module_name, attr)

    monkeypatch.setenv(paths.ENV, str(tmp_path))
    after = pathlib.Path(os.fspath(getattr(mod, attr)))

    assert str(after).startswith(str(tmp_path)), (
        "⚠⚠ %s.%s が隔離先を向きません（★import 時に固まっている）\n"
        "   いま: %s\n   期待: %s の下" % (module_name, attr, after, tmp_path))


def test_本番のrepo直下を指したままにならない(tmp_path, monkeypatch):
    """★代表で 1 本だけ、⚠ 「repo の下」を指していないことも見る。"""
    from dq3.knowledge import location_book as LB

    monkeypatch.setenv(paths.ENV, str(tmp_path))
    got = pathlib.Path(os.fspath(LB.BOOK_PATH))
    assert paths.ROOT not in got.parents, (
        "⚠⚠ 隔離しているのに repo の下を指しています: %s" % got)
