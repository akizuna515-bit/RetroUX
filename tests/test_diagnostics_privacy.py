"""診断情報に個人のものを混ぜない（仕様書 13章）。

★2026-08-01 に `test_release_prep.py`（848 実質行）から切り出しました（指示書 §11.1）。
  ⚠ **内容は1件も減らしていません。**機械で切り、件数で確かめています。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _code_lines(text: str) -> list:
    """コメントと空行を落とした行を返す。

    ★★ **「その語がソースにある」だけの検査は穴になる。** ★★
      説明のコメントに同じ語が書いてあると、**実装を消しても緑**のままになる。
      実際に `MessageBox` と `MsgBox` の検査がこれで通り抜けた（2026-07-30）。

    ⚠ PowerShell は `#`、VBS と `.cmd` は `'` / `rem` がコメント。
    """
    made = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "'", "rem ", "REM ")):
            continue
        made.append(stripped)
    return made

# --- 診断情報（仕様書 13章）--------------------------------------------

def test_diagnostics_do_not_leak_personal_paths():
    """★★ **個人のパスを含めない**（仕様書 13章）。 ★★

    問い合わせに貼るものなので、`C:\\Users\\本名\\...` が公開の場に出ると困る。
    """
    from retroux.core import diagnostics
    from retroux.core.config import user_config as uc

    cfg, _ = uc.load()
    text = diagnostics.as_text(diagnostics.collect(user_cfg=cfg))
    # ★利用者名を含みうる文字列が入っていないこと
    assert str(PROJECT_ROOT) not in text
    assert "C:\\Users" not in text
    assert "/Users/" not in text


def test_diagnostics_include_what_support_needs():
    """★仕様書 13章が挙げている項目。"""
    from retroux.core import diagnostics

    info = diagnostics.collect(rom_hash="a" * 64, read_only=False,
                               schema_version=1)
    for key in ("RetroUX", "Python", "OS", "FCEUX", "起動モード",
                "ROMハッシュ", "実行ファイル"):
        assert key in info, key


def test_the_gui_receives_the_whole_config_not_just_the_gui_section():
    """★★ **`gui_config` と `user_config` は別物**（2026-07-30 に取り違えた）★★

    | 渡すもの | 中身 | `path()` |
    | --- | --- | --- |
    | `user_cfg.gui` | 幅・高さ・列などの画面設定 | **無い** |
    | `user_cfg` | 設定ぜんぶ | ある |

    ⚠⚠ `user_cfg.gui` だけを渡していたため、
      **診断情報が「ログ: 不明」になり、ログを開くボタンが無反応**だった
      （Qt はスロットの例外を飲むので「何も起きない」ように見える）。

    ★ここを静的に見張る。実機まで気づけなかった種類の間違いなので。
    """
    text = (PROJECT_ROOT / "retroux" / "gui.py").read_text(encoding="utf-8")
    code = [ln.strip() for ln in text.splitlines()
            if not ln.strip().startswith("#")]

    assert any(ln == "user_config=user_cfg," for ln in code), \
        "MainWindow に UserConfig 全体を渡していない"
    assert not any("user_config=user_cfg.gui" in ln for ln in code), \
        "user_config に GuiConfig を渡している（path() が無い）"
    # ★画面設定はこれまでどおり gui を渡す
    assert any("gui_config=user_cfg.gui," in ln for ln in code)


def test_opening_the_log_folder_selects_the_log_file():
    """★★ `work/` は作業用で**336 個以上**のファイルがある。 ★★

    ⚠ ただフォルダを開くだけだと、その中から `retroux.log` を目で探すことになる
      （実機で「フォルダを開くとここだった。あってる？」と聞かれた）。
      ★Explorer の `/select` で**選択した状態**にする。

    ⚠⚠ **`explorer /select` は成功しても終了コード 1 を返す。**
      戻り値で判定すると「開けませんでした」と出るのに窓は開く、という
      食い違いになる。だから戻り値を見ないこと。

    ⚠⚠ **`CREATE_NO_WINDOW` を必ず付ける。** 付けないとコンソールの窓が
      一瞬出る（R-1 で直したのと同じ話を、ここで作り直さないため）。
    """
    # ★Explorer を起こすのも `WindowManager` へ移した（リファクタ §5.2）。
    #   ⚠ 画面から `subprocess` を呼ばない形にしたため、探す先が変わった。
    text = (PROJECT_ROOT / "retroux" / "ui" / "window_manager.py").read_text(
        encoding="utf-8")
    code = _code_lines(text)

    assert any("/select," in ln for ln in code), \
        "ログを選択した状態で開いていない"
    # ★0x08000000 = CREATE_NO_WINDOW
    # ⚠⚠ **リテラルを探さない。** 名前付き定数にした途端に落ちる。
    #   ★見るのは「`creationflags` を渡していること」と「その値」。
    assert any("creationflags=" in ln for ln in code), \
        "CREATE_NO_WINDOW が無い（コンソールの窓が出る）"
    from retroux.ui import window_manager
    assert window_manager._NO_WINDOW == 0x08000000, \
        "CREATE_NO_WINDOW の値が違う"
    # ⚠ `explorer` の戻り値を信じていないこと
    assert not any("returncode" in ln and "explorer" in ln for ln in code)
    # ★失敗しても Qt の方法へ落ちること（Windows 以外もある）。
    #   ⚠ こちらは**画面の層に残す**のが正しい（Qt は UI の道具）。
    #     Explorer の起動だけを `WindowManager` へ移した。
    fallback = _code_lines(
        (PROJECT_ROOT / "retroux" / "ui" / "main_window.py").read_text(
            encoding="utf-8"))
    assert any("QDesktopServices" in ln for ln in fallback), \
        "Qt の逃げ道が無い（Windows 以外で開けなくなる）"


def test_diagnostics_report_the_log_and_db_paths():
    """★★ **実機で「ログ: 不明」になった不具合の再発防止**（2026-07-30）★★

    ⚠⚠ 原因は `MainWindow` が `user_cfg.gui`（`GuiConfig`）を渡していたこと。
      `GuiConfig` に `path()` は無いので AttributeError になり、
      当時の広すぎる `except Exception` が**「不明」に化けさせていた**。
      しかも `ログ` の行で例外が出たため、**`DB` と `ROMファイル` の行が
      丸ごと消えていた**（まとめて try で囲っていたので後ろが実行されない）。

    ★いまは1項目ずつ囲むので、1つ失敗しても残りは出る。
    """
    from retroux.core.config import user_config as user_config_mod
    from retroux.core import diagnostics

    cfg, _ = user_config_mod.load()
    info = diagnostics.collect(user_cfg=cfg)

    for key in ("ログ", "DB", "ROMファイル"):
        assert key in info, f"{key} の行が消えている"
    assert "不明" not in str(info["ログ"]), info["ログ"]
    assert str(info["ログ"]).endswith("retroux.log"), info["ログ"]
    assert "設定" not in info, "正しい設定を渡したのに警告が出ている"


def test_diagnostics_include_the_log_tail_when_asked(tmp_path):
    """★★ 診断にログの直近数行を入れる（2026-08-11 / 依頼者の要望）★★

    ⚠ 問い合わせで最初に効く。★大きいログを丸ごとではなく**末尾だけ**。
      読めないときは省かず「不明」と書く。
    """
    from retroux.core import diagnostics

    log = tmp_path / "retroux.log"
    log.write_text("\n".join(f"行{i}" for i in range(1, 31)), encoding="utf-8")

    class Cfg:
        def path(self, key):
            return {"log": log}[key]

    info = diagnostics.collect(user_cfg=Cfg(), log_tail=20)
    key = "ログの直近20行"
    assert key in info
    assert isinstance(info[key], list) and len(info[key]) == 20
    assert info[key][0] == "行11" and info[key][-1] == "行30"

    # ★ログの場所が分からないときは省かず理由を出す
    class NoPath:
        pass

    info2 = diagnostics.collect(user_cfg=NoPath(), log_tail=20)
    assert "不明" in str(info2.get("ログの直近20行"))

    # ★頼まれなければ入れない（既定は付けない）
    info3 = diagnostics.collect(user_cfg=Cfg())
    assert not any(k.startswith("ログの直近") for k in info3)


def test_diagnostics_say_so_loudly_when_the_wrong_config_is_passed():
    """★★ **間違ったものを渡されたら「不明」で隠さない。** ★★

    ⚠ 「分からなかった」と「渡すものを間違えた」は**別のこと**。
      混ぜると、プログラムの間違いが利用者の環境の問題に見える。
      実際それで実機まで気づけなかった（2026-07-30）。
    """
    from retroux.core.config import user_config as user_config_mod
    from retroux.core import diagnostics

    cfg, _ = user_config_mod.load()
    info = diagnostics.collect(user_cfg=cfg.gui)      # ★わざと間違える

    assert "設定" in info, "取り違えを黙って通している"
    assert "path()" in info["設定"]
    assert "GuiConfig" in info["設定"], "何を渡されたのか書いていない"


def test_the_fceux_version_comes_from_the_window_title(monkeypatch):
    """★★ **FCEUX の exe には版情報が入っていない**（2026-07-30 実測）。 ★★

    `FileVersion` は空、各パートは 0 だった。だからファイルからは読めない。
    ★ところが窓の題名には入っている: `FCEUX 2.6.6: DQ2_J`
    """
    from retroux.core import diagnostics, window_align
    from retroux.core.window_align import WindowInfo

    monkeypatch.setattr(
        window_align, "find_windows",
        lambda title, match="contains": [
            WindowInfo(handle=1, title="FCEUX 2.6.6: DQ2_J",
                       x=0, y=0, width=100, height=100)])

    assert diagnostics.fceux_version(PROJECT_ROOT) == "2.6.6"


def test_an_all_zero_file_version_is_not_reported_as_a_version():
    """★★ `0.0.0.0` を版として出さない。 ★★

    ⚠ FCEUX 2.6.6 は実際に版情報が全部 0 だった。
      そのまま整形すると `0.0.0.0` になり、
      **入っているのに読めた**ように見えてしまう。
    """
    from retroux.core.diagnostics import format_file_version

    assert format_file_version(0, 0) is None
    # ★中身があるときはちゃんと組み立てる（2.6.6.0 相当）
    assert format_file_version((2 << 16) | 6, (6 << 16) | 0) == "2.6.6.0"


def test_a_missing_fceux_version_says_it_is_absent_not_just_unknown(
        monkeypatch):
    """★「読み損じた」と「元から無い」を区別する。

    ⚠ 「不明」だけだと、利用者は自分の環境の問題かどうか判断できない。
    """
    from retroux.core import diagnostics

    # ★窓からは読めない状況にする（FCEUX が動いていない）
    monkeypatch.setattr(diagnostics, "_version_from_window", lambda: None)

    text = diagnostics.fceux_version(PROJECT_ROOT)
    assert "版情報なし" in text, text
    # ★読める条件を書いてあること（利用者が次の手を打てる）
    assert "起動中" in text, text


def test_the_rom_is_reduced_to_a_short_hash():
    """★ROM 本体は入れない。同じ ROM か確かめられれば十分。"""
    from retroux.core import diagnostics

    info = diagnostics.collect(rom_hash="0123456789abcdef" * 4)
    assert info["ROMハッシュ"] == "0123456789ab"


def test_an_unknown_value_says_unknown_instead_of_being_dropped():
    """⚠ 省くと「無い」と「取れなかった」を区別できない。"""
    from retroux.core import diagnostics

    info = diagnostics.collect()
    assert info["ROMハッシュ"] == "不明"
    assert info["起動モード"] == "不明"


def test_diagnostics_text_is_pasteable():
    from retroux.core import diagnostics

    text = diagnostics.as_text(diagnostics.collect(warnings=["注意1", "注意2"]))
    assert text.startswith("RetroUX 診断情報")
    assert "```" in text
    assert "- 注意1" in text


def test_only_the_last_warnings_are_included():
    """★多すぎると貼るのが面倒になって使われない。"""
    from retroux.core import diagnostics

    info = diagnostics.collect(warnings=[f"w{n}" for n in range(50)])
    assert len(info["直近の警告"]) == diagnostics.MAX_WARNINGS
    assert info["直近の警告"][-1] == "w49"
