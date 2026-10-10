"""攻略データが無くても動く（RX3-0431 / 2026-09-25）。

⚠⚠ **公開版に攻略データを同梱しません。**

```text
input/dq3_guide_topic_master*.csv   ★第三者の攻略サイト由来（全 30 行が source_url を持つ）
data/dq3/topic-rules.csv            ★その機械可読版
```

★ゲームコンテンツでも RetroUX の解析成果でもないため（`docs/00-project-policy.md` §4）。

## ⚠ ここで固定すること

公開版＝**この 2 つが無い環境**です。そこで

- 起動できる（★例外を投げない）
- 勇者メモ・聞き込み・MAP・戦闘 AI は**そのまま使える**
- 勇者会議は、★人が書いた勇者メモ（`data/dq3/hero-memo.yaml`）で動く
  （⚠ 2026-09-27 / RX3-0432 までは「自然に無効化される」だった）

を守ります。

★2026-10-03（RX3-0432）: 旧 2 表を読む口そのものを消しました（★表も依頼者が削除）。
⚠ 公開物の除外（manifest）は**歯止めとして残します**（★誰かが戻しても公開されない）。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.knowledge import guide as G
from dq3.knowledge import guide_master as GM

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ------------------------------------------------ ★旧 2 表を読む口が無い（RX3-0432）
def test_TopicBookは正本を省くと空で_旧2表を読まない(tmp_path: pathlib.Path) -> None:
    """⚠⚠ 2026-10-03 まで、省くと**黙って旧 2 表を読んで**いた（★検査 15 件がそれに頼っていた）。"""
    book = G.TopicBook(path=tmp_path / "s.json")
    assert book.master == {} and book.rules == []
    assert book.head_candidate() is None


def test_旧2表を読む口が無い() -> None:
    for name in ("load_master", "load_rules", "MASTER_PATH", "RULES_PATH"):
        assert not hasattr(G, name), "⚠⚠ 旧 2 表を読む口が戻っている: guide.%s" % name
    for name in ("load", "resolve_path", "OFFICIAL_PATH", "DRAFT_PATH", "CANDIDATE_PATHS"):
        assert not hasattr(GM, name), "⚠⚠ 旧 2 表を読む口が戻っている: guide_master.%s" % name


# ------------------------------------------------ ★勇者会議の無効化
def test_勇者メモの原本が無ければ会議は開けないと分かる(tmp_path: pathlib.Path,
                                                        monkeypatch) -> None:
    """★入口を出さない判断が、勇者メモの原本の在り処だけで決まること（RX3-0432）。"""
    from dq3.knowledge import hero_memo as HM
    from dq3.ui.memo_panel import MemoPanel

    monkeypatch.setattr(HM, "DEFAULT_PATH", tmp_path / "無い.yaml")
    assert MemoPanel._guide_available() is False


def test_攻略データが無くても勇者メモがあれば会議を出す(tmp_path: pathlib.Path,
                                                      monkeypatch) -> None:
    """⚠⚠ 公開版（Guide Master が無い）でも会議が出ること（★窓は勇者メモで動く / RX3-0432）。"""
    from dq3.knowledge import hero_memo as HM
    from dq3.ui.memo_panel import MemoPanel

    memo = tmp_path / "hero-memo.yaml"
    memo.write_bytes(b"schema_version: 1\nleads: []\n")
    monkeypatch.setattr(HM, "DEFAULT_PATH", memo)
    assert MemoPanel._guide_available() is True


# ------------------------------------------------ ★公開物に混ざらない
MANIFEST = ROOT / "release" / "public-manifest.yaml"


@pytest.mark.skipif(not MANIFEST.exists(),
                    reason="★manifest は公開版に同梱しない（⚠ 開発 repo でだけ見る / RX3-0431）")
def test_公開manifestが攻略データを除外している() -> None:
    """⚠⚠ ここが緩むと、第三者の著作物が黙って公開されます。

    ⚠ このファイルの**他の検査は公開版でも走ります**（★攻略データ無しで動くこと）。
    ここだけ `release/` を見るので、公開木では skip します（2026-09-26 に実測）。
    """
    text = MANIFEST.read_text(encoding="utf-8")
    for must in ("data/dq3/topic-rules.csv", "input/**"):
        assert must in text, must
