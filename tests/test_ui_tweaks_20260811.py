"""右側UIの圧縮と使い勝手の直し（2026-08-11 / 依頼者の指摘）。

★★ 確かめたいこと ★★
  1. 出会った敵の札は**横並び**（縦順→横順 / 依頼者）
  2. ツールチップを早く出す設定がある（SH_ToolTip_WakeUpDelay）
  3. 窓の保存は**ゲーム保存の有無に関係なく**、理由つきで終了時に呼ぶ
  4. パーティ状態の段は縦の余りを独占しない（split は stretch なし＋Maximum）
"""

from __future__ import annotations

import os
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return PROJECT_ROOT.joinpath(*parts).read_text(encoding="utf-8")


# --- 1. 出会った敵の札は横並び ----------------------------------------

def test_出会った敵の札は横並び():
    """★縦順→横順（依頼者）。⚠ 縦積み（VBox を self に）へ戻っていない。"""
    src = _read("retroux", "ui", "encounter_panel.py")
    assert "QHBoxLayout(self)" in src
    assert "QVBoxLayout(self)" not in src, "縦積みへ戻っている"


def test_出会った敵のパネルは実際に横レイアウト():
    """★源だけでなく、組み上がった部品が QHBoxLayout であること。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6", reason="PySide6 が無い環境")
    from PySide6.QtWidgets import QApplication, QHBoxLayout

    from retroux.ui.encounter_panel import EncounterPanel

    QApplication.instance() or QApplication([])

    class _VM:
        def monster_name(self, mid):
            return "テスト"

    panel = EncounterPanel(_VM())
    assert isinstance(panel._layout, QHBoxLayout)


# --- 2. ツールチップを早く出す ----------------------------------------

def test_ツールチップを早く出す設定がある():
    src = _read("retroux", "gui.py")
    assert "SH_ToolTip_WakeUpDelay" in src
    assert "setStyle(" in src


# --- 3. 窓の保存は理由つき・ゲーム保存に依らない -----------------------

def test_窓の保存は理由つきで終了時に呼ぶ():
    src = _read("retroux", "ui", "main_window.py")
    # ★理由を受ける（ログに何のとき保存したか残す）
    assert "def save_window_state(self, reason" in src
    # ★終了経路（closeEvent）は必ず保存する。★保存の有無に依らない1か所。
    assert 'save_window_state(reason="終了")' in src


def test_復元は試みと結果をログに残す():
    src = _read("retroux", "ui", "main_window.py")
    assert "窓の復元" in src           # ★どう試みてどうなったかを DEBUG で残す
    assert "窓の状態を保存" in src


# --- 4. パーティ状態の段は縦を独占しない ------------------------------

def test_パーティの段は縦の余りを独占しない():
    """★縦の余りは**最下部**に集める（パーティ状態に持たせない）。

    ⚠ 2026-08-11 に並びを組み替えました（依頼者の指定）。敵情報を
      一番下へ出したのでスプリッタは解体してあり、`root.addWidget(split)`
      はもうありません。★見るのは「余りが最下部へ行くこと」です。
    """
    src = _read("retroux", "ui", "main_window.py")
    assert "root.addWidget(self._build_party_panel())" in src
    # ★どの段にも stretch を付けない（＝縦の余りを全部もらわない）
    assert "stretch=1)" not in src.split("root.addStretch(1)")[0]
    # ★内容ぶんに収める（Maximum）＋余りは最下部の伸縮へ
    assert "QSizePolicy.Policy.Maximum" in src
    assert "root.addStretch(1)" in src
