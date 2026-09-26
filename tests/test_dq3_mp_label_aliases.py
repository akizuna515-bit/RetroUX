"""昔の名前で書かれたログを、いまの名前で数える（RX3-0333 / 2026-09-21）。

⚠⚠ 依頼者「MP 方針の名前が画面とログでずれている（「半分程度残す」／「温存」）」。

```text
★画面        「半分程度残す」   dq3/battle_ai/settings.py  MP_LABELS
⚠ 戦闘ログ   「温存」           dq3/phase0/ai/pipeline.lua MP_LABEL（★直した）
```

## ★直し方（2 段）

```text
① ★これからのログ  `pipeline.lua` が画面と同じ字を書く
② ⚠ 過去のログ      **書き換えない**。★読む側（coverage.py）が寄せる
```

⚠ ここで見るのは②です（★①の突き合わせは `test_dq3_battle_ai_labels.py`）。
"""
from __future__ import annotations

import pathlib

from dq3.battle_ai import coverage as C
from dq3.battle_ai import settings as S

NOW = S.MP_LABELS[S.MP_SAVE]
OLD = "温存"


def _run(tmp_path: pathlib.Path, mp: str) -> pathlib.Path:
    """★実機 run 1 本ぶんの `report.md` を作る（⚠ 本番の `work/` には書かない）。"""
    run = tmp_path / ("run_" + mp)
    run.mkdir()
    (run / "report.md").write_text(
        "AI turn=1 戦況=均衡 win=3.0 lose=20.0 作戦=最短撃破 MP=%s / なにか\n" % mp,
        encoding="utf-8")
    return run


def test_昔の名前のログがいまの名前で数えられる(tmp_path):
    """⚠⚠ これが依頼者の症状（★過去ログが 1 件も見つからない）。"""
    got = C.scan_run(_run(tmp_path, OLD))
    assert got["mp"][NOW] == 1, (
        "⚠⚠ 「%s」と書かれた行が「%s」で数えられない（★過去の run が全部「その他」へ落ちる）"
        % (OLD, NOW))
    assert got["mp"][OLD] == 0, "⚠ 古い名前のまま数えている（★2 か所に分かれる）"


def test_いまの名前のログもそのまま数えられる(tmp_path):
    """⚠ 読み替えが新しい行を壊していないこと（★片側だけ見ない）。"""
    got = C.scan_run(_run(tmp_path, NOW))
    assert got["mp"][NOW] == 1, "⚠ いまの名前の行を数えていない"


def test_新旧が同じところへ合流する(tmp_path):
    """★同じ設定の run が 2 本あれば、⚠ **1 つの欄に 2 件**になること。"""
    root = tmp_path / "runs"
    root.mkdir()
    for i, mp in enumerate((OLD, NOW)):
        run = root / ("run_%d" % i)
        run.mkdir()
        (run / "report.md").write_text(
            "AI turn=1 戦況=均衡 win=3.0 lose=20.0 作戦=最短撃破 MP=%s / なにか\n" % mp,
            encoding="utf-8")
    data = C.collect(root=root)
    assert data["mp"][NOW] == 2, (
        "⚠⚠ 新旧が合流していない: %s" % dict(data["mp"]))


def test_ほかの方針は読み替えない(tmp_path):
    """⚠ 「おまかせ」「使用禁止」は名前が変わっていない（★余計に寄せない）。"""
    for label in (S.MP_LABELS[S.MP_AUTO], S.MP_LABELS[S.MP_FORBID]):
        got = C.scan_run(_run(tmp_path, label))
        assert got["mp"][label] == 1, "⚠ %s を読み替えてしまった: %s" % (label, dict(got["mp"]))


def test_知らない名前は落とさない(tmp_path):
    """⚠ 表に無い字が来ても、★そのまま数える（⚠ 黙って消さない）。"""
    got = C.scan_run(_run(tmp_path, "しらない方針"))
    assert got["mp"]["しらない方針"] == 1, "⚠⚠ 知らない名前を黙って捨てた"
