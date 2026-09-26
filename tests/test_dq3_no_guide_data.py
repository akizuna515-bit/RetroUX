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
- 攻略ナビ（勇者会議）だけが、★自然に無効化される

を守ります。⚠ 「壊れている」のと「無い」のは違います（★壊れていたら今までどおり止めます）。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.knowledge import guide as G
from dq3.knowledge import guide_master as GM

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ------------------------------------------------ ★無いときの読み込み
def test_正本が無ければNoneを返す(tmp_path: pathlib.Path) -> None:
    assert GM.resolve_path(tmp_path / "無い.csv") is None


def test_正本が無ければ空のTopicになる(tmp_path: pathlib.Path) -> None:
    """⚠ 例外にしない（★無いのは環境であって事故ではない）。"""
    assert G.load_master(tmp_path / "無い.csv") == {}


def test_規則が無ければ空の一覧になる(tmp_path: pathlib.Path) -> None:
    assert G.load_rules(tmp_path / "無い.csv") == []


def test_両方無くてもTopicBookは作れる(tmp_path: pathlib.Path) -> None:
    book = G.TopicBook(master=G.load_master(tmp_path / "無い1.csv"),
                       rules=G.load_rules(tmp_path / "無い2.csv"))
    assert book.rules == []
    assert book.head_candidate() is None


# ------------------------------------------------ ★勇者会議の無効化
def test_攻略データが無ければ会議は開けないと分かる(tmp_path: pathlib.Path,
                                                    monkeypatch) -> None:
    """★入口を出さない判断が、`resolve_path` だけで決まること。"""
    from dq3.ui.memo_panel import MemoPanel

    monkeypatch.setattr(GM, "CANDIDATE_PATHS", (tmp_path / "無い.csv",))
    assert MemoPanel._guide_available() is False


def test_攻略データがあれば会議を出す() -> None:
    """⚠ 開発機では今までどおり出ること（★消してしまわない）。"""
    from dq3.ui.memo_panel import MemoPanel

    if GM.resolve_path() is None:
        pytest.skip("★この環境には Guide Master がありません")
    assert MemoPanel._guide_available() is True


# ------------------------------------------------ ★壊れているのは別
def test_壊れていたら今までどおり止める(tmp_path: pathlib.Path) -> None:
    """⚠ 「無い」を許したせいで「壊れている」まで見逃さないこと。"""
    broken = tmp_path / "壊れ.csv"
    broken.write_text("topic_id,title\n,,\n", encoding="utf-8", newline="")
    with pytest.raises(GM.GuideMasterError):
        GM.load(broken, strict=True)


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
