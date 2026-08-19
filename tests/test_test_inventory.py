"""テスト資産の棚卸し（2026-08-05 / テスト高度化指示書 Test Phase A）。

★★ **棚卸しの数字が古くならないよう見張る。** ★★

  ⚠ 文書に手で書いた件数は、テストが増えても**黙って古いまま**残ります。
    `docs/design/battle-ai-test-inventory.md` の表は
    `test_inventory.py` が作ります。

## ⚠⚠ この分類器で踏んだこと（記録）

日本語のコメントの語で分類したところ、★`理由ログ` が
**79本 / 1416個**になりました。「理由」と書いてあるだけで当たったのです。
次に `reason=` を入れたら `pytest.importorskip(..., reason="…")` に当たり
**52本**になりました。

⚠ これは「鳴りすぎ」の壊れ方で、**どの層が薄いかが見えなくなります**。
★コード上の印（モジュール名・関数名）だけを見るように直しました。
"""

from __future__ import annotations

import pathlib

import pytest

from research.probes.reusable import test_inventory as inv

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = PROJECT_ROOT / "docs" / "design" / "battle-ai-test-inventory.md"


@pytest.fixture(scope="module")
def rows():
    return inv.collect()


def test_道具が動く():
    assert inv.main([]) == 0


def test_全部のテストファイルを見ている(rows):
    """⚠ 見落としがあると「薄い層」を見誤ります。"""
    files = {row["file"] for row in rows}
    on_disk = {p.name for p in (PROJECT_ROOT / "tests").glob("test_*.py")}
    assert files == on_disk


# --- ⚠⚠ 分類器が鳴りすぎないこと ----------------------------------------

def test_コメントの語だけで分類しない():
    """★★★ **上の説明のとおり、実際に踏んだ**。

    ⚠ `reason=` は `pytest.importorskip` の引数に当たります。
    """
    source = (PROJECT_ROOT / "research" / "probes" / "reusable"
              / "test_inventory.py").read_bytes().decode("utf-8")
    for pattern, why in ((r'r"reason="', "importorskip に当たる"),
                         (r'r"理由"', "日本語コメントに当たる"),
                         (r'r"AUTO"', "語が広すぎる")):
        assert pattern not in source, f"⚠ {pattern} は使えません（{why}）"


def test_鳴りすぎていないか数で見張る(rows):
    """⚠ どの対象も**全体の半分を超えない**こと。

    ★超えたら、その分類は「何にでも当たる」印を使っています。
    """
    total = len(rows)
    counts = {}
    for row in rows:
        for name in row["targets"]:
            counts[name] = counts.get(name, 0) + 1
    for name, got in counts.items():
        assert got < total * 0.5, (
            f"⚠⚠ 『{name}』が {got}/{total} 本に当たっています。"
            "分類の印が広すぎます")


# --- ★ 指示書が指摘した「足りない層」を固定する --------------------------

def test_戦闘終了の穴が埋まったことを記録する(rows):
    """★★★ **2026-08-05 に埋まりました**（Test Phase D）。

    ⚠ 棚卸しの時点では **0本 / 0個**でした。実機ログに
      `回復は間に合いませんでした（戦闘が先に終わった）` が9件出ており、
      ★戦闘終了付近は実際に穴がありました。

    いまは `showing_victory` を見て、次の3つを検出できます:

      ・最大ターン超過
      ・同一状態の反復
      ・★**勝利メッセージ中の誤入力**（フィールドのメニューが開く原因）

    ⚠ この検査は「もう一度 0 に戻っていないか」を見張ります。
    """
    got = sum(1 for row in rows if "戦闘終了" in row["targets"])
    assert got >= 1, (
        "⚠⚠ 戦闘終了のテストが無くなりました。"
        "★Test Phase D で埋めた穴が空いています")


def test_複数ターンが薄いことを記録する(rows):
    """⚠ いまの Lua テストは**すべて1ターンで完結**します。

    ★「予約はターンをまたがない」を試す2本だけが `turn_no` を進めますが、
      AIの行動結果を次ターンの状態へ**反映していません**。
    """
    got = sum(1 for row in rows if "★複数ターン" in row["targets"])
    assert got <= 4, (
        f"★複数ターンのテストが {got} 本に増えました。"
        "棚卸しの文書を更新してください")


def test_実キー入力が薄いことを記録する(rows):
    """⚠ 「AIが何を選んだか」は試せますが、

    ★**FCEUX に実際に何を押したか**は追えていません。
    """
    got = sum(1 for row in rows if "実キー入力" in row["targets"])
    assert got <= 3, f"★実キー入力のテストが {got} 本に増えました"


# --- ★ 文書と道具が食い違わないこと --------------------------------------

def test_文書が道具を指している():
    assert DOC.exists(), "⚠ 棚卸しの文書がありません"
    text = DOC.read_bytes().decode("utf-8")
    assert "test_inventory.py" in text, "★数字の出どころを書くこと"
    # ★指示書が挙げた層が全部載っていること
    for name, _ in inv.KINDS:
        assert name in text, f"⚠ 文書に種別 {name} がありません"
