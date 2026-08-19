"""画面（System Log）に出す段階の絞り込み（製品版ログ整理 Phase 7）。

## ⚠⚠ 何が壊れていたか

`user_config.yaml` には

    gui_level … System Log に出す下限。★INFO（読める量に絞る）

と書いてあり、`GuiLogHandler` も `gui_level` を見ています。
★**しかし効いていませんでした。**

`MainWindow._drain_system_log` は `_log_path` があると
`_drain_log_file()`（＝**ファイルを直接読む**道）へ入り、
⚠ `GuiLogHandler` を通りません。つまり画面にはファイルの中身
（＝`level` の下限。既定 DEBUG）がそのまま出ていました。

★「設定に書いてあるのに効いていない」は、いちばん追いにくい壊れ方です
（`docs/audit/source-to-doc.md` に同じ形の例が並んでいます）。

## ★ ここで見ること

  1. 下限より軽い行を出さない
  2. 下限以上の行は出す
  3. ⚠ **段階が読めない行は出す**（★消すより出すほうが安全）
  4. 起動直後の流し込みにも同じ絞り込みが効く
"""

from __future__ import annotations

import logging
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

MAIN_WINDOW = (pathlib.Path(__file__).resolve().parents[1]
               / "retroux" / "ui" / "main_window.py")


class _Fake:
    """`_show_in_gui` だけを借りる。⚠ Qt を起動しない（★速さと安定のため）。"""

    def __init__(self, rank: int | None) -> None:
        self._gui_level_rank = rank

    @property
    def _LEVEL_RANK(self):                              # noqa: N802
        from retroux.ui.main_window import MainWindow

        return MainWindow._LEVEL_RANK

    def show(self, line: str) -> bool:
        from retroux.ui.main_window import MainWindow

        return MainWindow._show_in_gui(self, line)


@pytest.fixture(scope="module", autouse=True)
def _qt():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6", reason="PySide6 が無い環境")


def _line(level: str, name: str = "lua", body: str = "本文") -> str:
    return f"2026-08-13 09:00:00 [{level}] {name} {body}"


# --- 1・2. 下限で絞る ------------------------------------------------------

def test_INFOが下限ならDEBUGを出さない():
    f = _Fake(logging.INFO)
    assert f.show(_line("DEBUG")) is False


def test_INFOが下限ならINFO以上を出す():
    f = _Fake(logging.INFO)
    for lv in ("INFO", "WARNING", "ERROR", "CRITICAL"):
        assert f.show(_line(lv)) is True, lv


def test_DEBUGが下限なら全部出す():
    f = _Fake(logging.DEBUG)
    for lv in ("DEBUG", "INFO", "WARNING", "ERROR"):
        assert f.show(_line(lv)) is True, lv


def test_設定が無ければ絞らない():
    """⚠ 読めないときに**消す**側へ倒さない。"""
    f = _Fake(None)
    assert f.show(_line("DEBUG")) is True


# --- 3. ⚠ 読めない行は出す ------------------------------------------------

def test_段階が読めない行は出す():
    """★消すより出すほうが安全。読めないのはこちらの都合。"""
    f = _Fake(logging.INFO)
    for line in ("段階のない行",
                 "2026-08-13 09:00:00 段階なしの Lua 旧形式",
                 "",
                 "2026-08-13 09:00:00 [なにか] name 本文"):
        assert f.show(line) is True, line


def test_PythonとLuaの両方の形を読める():
    """★並びを揃えたので1本の規則で読める。"""
    f = _Fake(logging.INFO)
    assert f.show("2026-08-13 09:00:00 [DEBUG] navigation 想定外の座標変化") is False
    assert f.show("2026-08-13 09:00:00 [DEBUG] lua [狙い] ...") is False
    assert f.show("2026-08-13 09:00:00 [INFO] gui RetroUX 起動") is True


# --- 4. 起動直後の流し込みにも効く ----------------------------------------

def test_初回の流し込みにも絞り込みが入っている():
    """⚠ ここを忘れると「起動直後だけ DEBUG がどっと出る」ちぐはぐになる。"""
    src = MAIN_WINDOW.read_text(encoding="utf-8")
    head = src.split("def _drain_log_file")[1].split("def ")[0]
    assert "_show_in_gui" in head, (
        "初回の流し込みが絞り込みを通っていない")


def test_追記の道にも絞り込みが入っている():
    src = MAIN_WINDOW.read_text(encoding="utf-8")
    head = src.split("def _append_log_lines")[1].split("def ")[0]
    assert "_show_in_gui" in head, "追記が絞り込みを通っていない"
