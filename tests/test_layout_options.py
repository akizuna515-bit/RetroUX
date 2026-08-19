"""4区画の並べ方を設定で決められること（RX-0055 / 2026-08-18）。

依頼者:

> 整列ボタンの配置は、設定ファイルで定義できるようになっている？

★答えは「ほとんどできていなかった」。⚠ 4区画で効いていたのは
`spacing` の2つと `windows.log.height` だけで、**並び順も幅の配分も
ハードコード**だった。

## ★ 出した設定は2つだけ（依頼者の判断 = 推奨案 b）

    layout:
      left_pane: map      # ★ゲーム画面の左に置くもの（map / main）
      side_split: 0.5     # ★左の割合（0.2〜0.8）

⚠ 全部を設定に出すと**組み合わせが爆発**して検査しきれない。
★細かい調整は、窓を手で動かせば `work/window-state.json` が覚える。

## ⚠⚠ 置き場について

`retroux/config/default_layout.yaml` は**同梱ファイル**で、その冒頭に
「利用者が編集する対象ではありません」と書いてある。
★編集させたい設定を、編集するなと書いたファイルへ置けない。
→ ⚠ `config/user_config.yaml` の `layout:` に置く。
"""

from __future__ import annotations

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from retroux.core import layout  # noqa: E402

AREA = (0, 0, 1920, 1032)
EMU = (784, 731)


def _place(pane: dict):
    cfg = {**layout.load_default(), "four_pane": pane}
    return layout.compute_standard(AREA, EMU, cfg)


# --- ★ 並び順 -----------------------------------------------------------

def test_既定は地図が左():
    got = _place({})
    assert got["map"].x < got["emulator"].x < got["main"].x, got


def test_入れ替えられる():
    got = _place({"left_pane": "main"})
    assert got["main"].x < got["emulator"].x < got["map"].x, got
    # ★大きさは変わらない（⚠ 位置だけ入れ替わる）
    assert got["map"].width == got["main"].width


# --- ★ 幅の配分 ---------------------------------------------------------

def test_地図を広くできる():
    got = _place({"side_split": 0.65})
    assert got["map"].width > got["main"].width, (
        got["map"].width, got["main"].width)
    # ⚠ 合計は変わらない（★ゲーム画面を押しのけない）
    base = _place({})
    assert (got["map"].width + got["main"].width
            == base["map"].width + base["main"].width)


def test_ゲーム画面の位置も一緒に動く():
    """⚠ 左を広げたらゲーム画面も右へずれること（★重ならない）。"""
    narrow = _place({"side_split": 0.3})
    wide = _place({"side_split": 0.7})
    assert wide["emulator"].x > narrow["emulator"].x
    for got in (narrow, wide):
        # ★左の右端 < ゲーム画面の左端
        left = min((got["map"], got["main"]), key=lambda p: p.x)
        assert left.x + left.width < got["emulator"].x, got


# --- ⚠ 効かない値を黙って受け取らない -----------------------------------

def test_知らない並び順は既定へ倒すが黙らない():
    got = _place({"left_pane": "nope"})
    assert got["map"].x < got["main"].x, "★既定（地図が左）へ倒していない"
    notes = layout.layout_complaints({"left_pane": "nope"})
    assert notes and "left_pane" in notes[0], notes


def test_範囲外の配分は丸めるが黙らない():
    got = _place({"side_split": 9})
    # ★丸めても、両方が掴める幅を残す
    assert got["map"].width >= layout.MIN_WIDTH
    assert got["main"].width >= layout.MIN_WIDTH
    notes = layout.layout_complaints({"side_split": 9})
    assert notes and "side_split" in notes[0], notes


def test_数値でない配分でも落ちない():
    got = _place({"side_split": "ひろく"})
    assert got["map"].width > 0
    assert layout.layout_complaints({"side_split": "ひろく"})


def test_正しい設定では黙っている():
    """⚠ 鳴りすぎも壊れ方。★既定と正しい値では何も言わない。"""
    assert layout.layout_complaints({}) == ()
    assert layout.layout_complaints(
        {"left_pane": "main", "side_split": 0.6}) == ()


# --- ★ 設定ファイル側 ---------------------------------------------------

def test_user_configで読める(tmp_path):
    """★`layout:` を読めること。

    ⚠⚠ **利用者の `user_config.yaml` を読んで既定値を期待していた**
      （2026-08-19 に赤くなって判明）。★依頼者が `left_pane: main` を
      書いた瞬間に落ちた。⚠ **設定ファイルは利用者のもの**で、
      検査が中身を決めつけてよいものではない。

    ★この計画で**同じ形を3回**やっている:

        ・セーブステートの進行を前提にした（★2回）
        ・利用者の設定を前提にした（★これ）

    → ★検査は**自分で作ったファイル**を読む。
    """
    from retroux.core.config import user_config as uc

    # ★既定値（⚠ ファイルが無いとき）
    empty = tmp_path / "none.yaml"
    got, warnings = uc.load(empty)
    assert hasattr(got, "layout"), "★`layout` の節が無い"
    assert got.layout.left_pane == "map"
    assert got.layout.side_split == 0.5
    assert warnings == [], warnings

    # ★書いたとおりに読めること
    written = tmp_path / "user_config.yaml"
    # ⚠ `\n` を書き間違えて YAML が1行になり、赤くなった（2026-08-19）。
    #   ★行で書けば間違えようがない。
    written.write_text("\n".join([
        "layout:",
        "  left_pane: main",
        "  side_split: 0.65",
    ]) + "\n", encoding="utf-8")
    got, warnings = uc.load(written)
    assert got.layout.left_pane == "main"
    assert got.layout.side_split == 0.65
    assert warnings == [], warnings


def test_利用者の設定でも警告が出ない():
    """⚠ いま置いてある `user_config.yaml` が**読めること**だけ見る。

    ★中身は決めつけない（⚠ 利用者のもの）。
    """
    from retroux.core.config import user_config as uc

    got, warnings = uc.load()
    assert got.layout.left_pane in ("map", "main"), got.layout.left_pane
    assert warnings == [], warnings


def test_同梱ファイルには置かない():
    """⚠⚠ `default_layout.yaml` は「編集するな」と書いてあるファイル。

    ★そこへ編集させたい設定を置かない（RX-0055 の置き場の判断）。
    """
    import yaml

    # ⚠ 文字列で探すと、コメント中の `_compute_four_pane` に当たる
    #   （★実際に一度そう書いて誤検知した / 2026-08-18）。
    #   → ★**読み込んで鍵で見る**。
    got = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "config"
         / "default_layout.yaml").read_text(encoding="utf-8"))
    assert "four_pane" not in got, (
        "★同梱ファイルへ置いている（⚠ 編集するなと書いてあるのに）")


# --- ★★★ ⚠⚠ 配線が**実際に動く**こと ---------------------------------

def test_整列が設定を読んで落ちない():
    """★★★ ⚠⚠ **ここを書かずに `NameError` を作りかけた**（2026-08-18）★★★

    `layout_cfg` を使う行だけ先に足して、**定義する行が当たっていなかった**。
    ⚠ 検査が「文字列があるか」だけなら、これは捕まらない。

    ★F-089（★9か月緑だった文字列検査）と、
      2026-08-14 の `Get-ShortPath`（★起動不能）と同じ形。

    → ★**実際に `arrange` の中身を呼ぶ**。
    """
    from retroux.core.config import user_config as uc
    from retroux.tools import align_windows

    cfg, _ = uc.load()
    pane = {"left_pane": getattr(cfg.layout, "left_pane", "map"),
            "side_split": getattr(cfg.layout, "side_split", 0.5)}
    # ★`arrange` が組み立てているものと同じ形
    layout_cfg = {**layout.load_default(), "four_pane": pane}
    got = layout.compute_standard(AREA, EMU, layout_cfg)
    assert set(got) == {"map", "emulator", "main", "log"}, got.keys()

    # ⚠ `arrange` の中で使う名前が本当にあるか（★未定義を捕まえる）
    src = pathlib.Path(align_windows.__file__).read_text(encoding="utf-8")
    body = src[src.index("def arrange"):src.index("\ndef main")]
    assert "layout_cfg = {" in body, (
        "⚠⚠ `layout_cfg` を組み立てる行が無い（★使う行だけある＝NameError）")
    assert body.index("layout_cfg = {") < body.index(", layout_cfg)"), (
        "⚠⚠ 使う行が、組み立てる行より**前**にある（★NameError）")


def test_整列が構文として通る():
    """⚠ 上の検査は文字列も見るので、**構文**は別に確かめる。"""
    import ast

    from retroux.tools import align_windows

    ast.parse(pathlib.Path(align_windows.__file__).read_text(encoding="utf-8"))
