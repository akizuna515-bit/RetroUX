"""利用者のものを**決めつけている**検査が無いこと（RX-0063）。

## ⚠⚠ 同じ形を3回やった

| いつ | 何を決めつけた | ★どうなったか |
| --- | --- | --- |
| 以前 | セーブは「ローレシア単独」 | ⚠ サマルトリアが加入して落ちた |
| 2026-08-19 | セーブは「遊びの途中」 | ⚠ タイトル画面で保存されて落ちた |
| 2026-08-19 | `user_config.yaml` は既定値 | ⚠ 依頼者が `left_pane: main` を書いて落ちた |

★どれも**製品の不具合ではない**。⚠ 検査の前提が、利用者の都合で崩れただけ。

## ★ 決めごと

**利用者のもの**（`user_config.yaml` / セーブステート / DB / 窓の配置）は:

  ★読めること・壊れていないことは見てよい
  ⚠ **中身が特定の値であることは決めつけない**

★値を確かめたいときは、**検査が自分で作ったファイル**を読む
（`tmp_path` を使う）。

## ⚠ ここで見るもの

`uc.load()`（★引数なし＝利用者のファイル）の戻り値を、
**特定の値と比べていないか**。
"""

from __future__ import annotations

import ast
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TESTS = PROJECT_ROOT / "tests"

#: ★「利用者のものを読む」呼び出し（⚠ 引数なしのとき）
USER_LOADS = ("load",)

#: ★決めつけてよい比較（⚠ 「読める」「壊れていない」の確認）
SAFE = ("warnings", "hasattr", "is not None", "in (", "in [")


def _reads_user_config(node: ast.AST) -> bool:
    """`uc.load()` のように**引数なし**で呼んでいるか。"""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        name = ""
        if isinstance(sub.func, ast.Attribute):
            name = sub.func.attr
        if name in USER_LOADS and not sub.args and not sub.keywords:
            return True
    return False


def test_利用者の設定の中身を決めつけていない():
    """★★★ ⚠⚠ **3回やった形を、機械で止める** ★★★"""
    bad = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == "test_user_data_assumptions.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("test"):
                continue
            if not _reads_user_config(node):
                continue
            src = path.read_text(encoding="utf-8").splitlines()
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Assert):
                    continue
                line = src[sub.lineno - 1].strip()
                if any(w in line for w in SAFE):
                    continue
                # ⚠ 定数と `==` で比べていたら決めつけ
                t = sub.test
                if (isinstance(t, ast.Compare)
                        and any(isinstance(o, ast.Eq) for o in t.ops)
                        and any(isinstance(c, ast.Constant)
                                for c in t.comparators)):
                    bad.append(f"{path.name}:{sub.lineno} {line[:70]}")
    assert not bad, ["⚠ 利用者の設定の中身を決めつけている:"] + bad


def test_この検査が空回りしていない():
    """⚠ 「0 件」が「見ていない」でないこと。

    ★引数なしの `load()` を使っている検査が、実際に在ること。
    """
    found = []
    for path in sorted(TESTS.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name.startswith("test")
                    and _reads_user_config(node)):
                found.append(f"{path.name}::{node.name}")
    assert found, "★引数なしの `load()` が1件も無い（⚠ 検査が空回り）"


def test_セーブステートの進行を決めつけていない():
    """⚠ セーブは利用者の進行で変わる。★人数や状態を固定しない。"""
    body = (TESTS / "test_party_status.py").read_text(encoding="utf-8")
    assert "_in_game(" in body, (
        "★遊びの途中かを確かめずにセーブを使っている"
        "（⚠ タイトル画面で落ちる）")
    # ★飛ばすときは理由を出すこと（⚠ 黙って飛ばさない）
    assert "遊びの途中ではありません" in body
