"""ログのパスと書式（RX-0043 / RX-0044 / 指示書 §26）。

## ⚠⚠ 実機ログで見つかった2つ（2026-08-14）

### 1. 絶対パスが残っていた（§26 未達）

    C:\\Projects\\260721_RetroUX\\.venv\\Scripts\\pythonw.exe    ← launcher
    C:\\Projects\\260721_RetroUX\\tools\\fceux\\fcs              ← savestate_backup
    C:\\Projects\\260721_RetroUX\\work\\savestate-backup         ← 同上

★Lua 側（`caution.txt`）だけ相対化して、⚠ **Python と PowerShell を
直していなかった**。

⚠ この環境では `C:\\projects\\` にあるため利用者名が出ていない。
★危険が消えているのではなく、**置き場所のおかげ**。

### 2. ⚠ 3つ目の書式があった

    2026-08-14 08:39:27 INFO [launcher] ...   ← ⚠ 段階が角括弧の**外**
    2026-08-14 08:39:29 [INFO] console ...    ← Python
    2026-08-14 08:39:30 [INFO] lua ...        ← Lua

★画面の段階絞り込み（`main_window._show_in_gui`）は
`日時 [段階] 名前` の並びを読むので、⚠ launcher の行は**段階を読めず**
「読めない行は出す」側へ倒れていた。
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

LAUNCHER = PROJECT_ROOT / "scripts" / "launcher-common.ps1"
START = PROJECT_ROOT / "scripts" / "start-retroux.ps1"


# --- 1. パスの短縮 ---------------------------------------------------------

def test_プロジェクト内は相対になる():
    from retroux.core.console import short_path

    got = short_path(PROJECT_ROOT / "work" / "savestate-backup")
    assert got == "work/savestate-backup", got


def test_プロジェクト外はそのまま():
    """⚠ 勝手に切ると「どこの話か」が分からなくなる。"""
    from retroux.core.console import short_path

    outside = "D:/somewhere/else/file.txt"
    assert short_path(outside) == outside


def test_Noneでも落ちない():
    from retroux.core.console import short_path

    assert short_path(None) == ""


def test_savestate_backupが短縮を使っている():
    src = (PROJECT_ROOT / "retroux" / "tools"
           / "savestate_backup.py").read_text(encoding="utf-8")
    assert "console.short_path(args.src)" in src, "監視先が絶対パスのまま"
    assert "console.short_path(args.dst)" in src, "保存先が絶対パスのまま"


def test_launcherが短縮を使っている():
    """⚠ 配線があること。★動くかどうかは下の `test_Get_ShortPathが実際に動く`。"""
    body = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "function Get-ShortPath" in body
    start = START.read_text(encoding="utf-8-sig")
    assert "Get-ShortPath $guiPython" in start, "exe のパスが絶対のまま"
    # ★基準が設定されていないと素通りする
    assert "$script:RetroUXRoot = $Root" in start, (
        "Get-ShortPath の基準が設定されていない（★絶対パスをそのまま返す）")


def test_Get_ShortPathが実際に動く():
    """★★★ ⚠⚠ **これが無くて起動不能にした**（2026-08-14）★★★

    ## 何が起きたか

      `Get-ShortPath` に

          .TrimStart('\\\\', '/')

      と書いた。⚠ PowerShell の `'\\\\'` は**2文字**（★1文字ではない）。
      `TrimStart` は `[char[]]` を取るので変換できず、**例外で落ちる**。

      ★`RetroUX.vbs` が **9回**起動を試み、すべて
      「この起動の札」の直後で止まっていた（ログで確認）。

    ## ⚠⚠ なぜ検査をすり抜けたか

      上の `test_launcherが短縮を使っている` は
      **「`Get-ShortPath $guiPython` という文字列があるか」しか見ていない**。

      ★これは F-089（★9か月緑だった文字列検査）と**同じ形**。
      ⚠ この計画で「文字列検査は弱い」と何度も書きながら、**自分でやった**。

    → ★**実際に呼ぶ**（V2 相当）。
    """
    import subprocess

    if sys.platform != "win32":
        pytest.skip("PowerShell が要る")

    script = (
        f"$script:RetroUXRoot = '{PROJECT_ROOT}'; "
        f". '{LAUNCHER}'; "
        "$inside = Get-ShortPath (Join-Path $script:RetroUXRoot 'work\\x.log'); "
        "$outside = Get-ShortPath 'D:\\somewhere\\else.txt'; "
        "$empty = Get-ShortPath ''; "
        "Write-Output \"INSIDE=$inside\"; "
        "Write-Output \"OUTSIDE=$outside\"; "
        "Write-Output \"EMPTY=[$empty]\""
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, timeout=60)
    out = (done.stdout or b"").decode("utf-8", "replace")
    # ⚠ 端末の文字コードで出るので cp932 も試す（★中身より「出たか」を見る）
    err = (done.stderr or b"").decode("cp932", "replace")

    # ⚠⚠ **`returncode` を信じない**（2026-08-14 に踏んだ）。
    #   ★PowerShell は**非終了エラー**では 0 を返す。
    #     壊れた版で確かめたら `rc=0` のまま stderr にだけ出ていた。
    #   → ★**戻り値そのもの**と **stderr の有無**の両方を見る。
    assert not err.strip(), f"★Get-ShortPath がエラーを出している:\n{err}\n{out}"
    assert "OUTSIDE" in out, f"出力が足りない:\n{out}\n{err}"

    got = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    # ★プロジェクト内は相対（⚠ 壊れた版はここで絶対パスが返る）
    assert got.get("INSIDE", "").strip() == "work\\x.log", (
        f"★短縮されていない（壊れた版と同じ症状）: {got}")
    # ⚠ 外はそのまま
    assert got.get("OUTSIDE", "").strip() == "D:\\somewhere\\else.txt", got
    # ⚠ 空でも落ちない
    assert got.get("EMPTY", "").strip() == "[]", got


def test_起動スクリプトが構文として通る():
    """⚠ 構文誤りは**実行するまで**分からない（★PowerShell は動的）。

    ★少なくとも parse は通ることを見る。
    ⚠ ただし `TrimStart` の件は**parse は通った**（実行時の型変換で落ちた）。
      ★だから上の「実際に動かす」検査のほうが要る。
    """
    import subprocess

    if sys.platform != "win32":
        pytest.skip("PowerShell が要る")

    for path in (LAUNCHER, START):
        script = (
            "$e = $null; "
            f"[void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{path}', [ref]$null, [ref]$e); "
            "if ($e) { Write-Output 'NG'; $e | ForEach-Object "
            "{ Write-Output $_.Message } } else { Write-Output 'OK' }"
        )
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=60)
        out = (done.stdout or b"").decode("utf-8", "replace")
        assert out.strip().startswith("OK"), f"{path.name}:\n{out}"


# --- 2. ⚠⚠ 書式をそろえる（★ここが要）----------------------------------

def test_launcherの書式がPythonとそろっている():
    """★`日時 [段階] 名前 本文`。⚠ 3つ目の書式を作らない。"""
    body = LAUNCHER.read_text(encoding="utf-8-sig")
    assert '"$stamp [$Level] launcher $Message"' in body, (
        "launcher の書式が Python / Lua とそろっていない")
    assert '"$stamp $Level [launcher] $Message"' not in body, (
        "⚠ 古い書式（段階が角括弧の外）が残っている")


def test_画面の絞り込みがlauncherの行を読める():
    """★書式をそろえた効果を、**絞り込み側で**確かめる。

    ⚠ 書式を直しただけでは「読めるようになった」と言えない。
    """
    import logging

    from retroux.ui.main_window import MainWindow

    class Fake:
        _gui_level_rank = logging.INFO
        _LEVEL_RANK = MainWindow._LEVEL_RANK

    fake = Fake()
    # ★新しい書式（段階を読める）
    new = "2026-08-14 08:39:27 [DEBUG] launcher 設定を変換しています"
    assert MainWindow._show_in_gui(fake, new) is False, (
        "launcher の DEBUG が画面に出てしまう")
    keep = "2026-08-14 08:39:27 [INFO] launcher RetroUX 起動"
    assert MainWindow._show_in_gui(fake, keep) is True

    # ⚠ 古い書式は段階を読めない → 「読めない行は出す」側へ倒れる
    old = "2026-08-14 08:39:27 INFO [launcher] RetroUX 起動"
    assert MainWindow._show_in_gui(fake, old) is True, (
        "★この検査の前提が崩れている（古い書式が読めてしまう）")


# --- 3. ⚠ 実ログに絶対パスが出ていないか（あれば）-------------------------

def test_実ログの絶対パスを数える():
    """★実機のログで確かめる（RX-0043）。

    ⚠ いまのログには**直す前の行が残っている**ので、
      ★直したあとの行だけを見る（過去は直せない）。

    ★★ ⚠⚠ **境目を「明日」にしていた**（2026-08-14 に気づいた）★★
      `2026-08-15` と書いてあったので、⚠ **この検査は1行も見ていなかった**。
      ★「0 件」は通っていたのではなく、**通っていなかった**だけ。

    ★★ ⚠ **日付を書くのをやめた** ★★
      境目をその日へ下げたら、⚠ **同じ日の直す前の起動**（08:39）が
      引っかかった。★日付では「直す前／後」を切り分けられない。
      → ★**最後の起動から先だけ**を見る。⚠ 日付を書かないので古びない。
    """
    log = PROJECT_ROOT / "work" / "retroux.log"
    if not log.exists():
        pytest.skip("実ログが無い")
    pat = re.compile(r"[A-Za-z]:[/\\][A-Za-z0-9_.\-]+(?:[/\\][A-Za-z0-9_.\-]+)+")
    root_name = PROJECT_ROOT.name
    #: ★起動の1行目（`launcher-common.ps1` が必ず出す）。ここから先を見る
    START_MARK = "launcher 設定を変換しています"
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [i for i, l in enumerate(lines) if START_MARK in l]
    if not starts:
        pytest.skip("★起動の目印が見つからない（古いログ）")
    recent = lines[starts[-1]:]

    bad = []
    for line in recent:
        for m in pat.finditer(line):
            if root_name in m.group(0):
                bad.append(m.group(0))
    # ⚠⚠ **「0 件」と「1行も見ていない」を混ぜない**（★前はこれで素通りしていた）
    assert len(recent) > 1, (
        f"★最後の起動のログが {len(recent)} 行しかない。⚠ 何も見ていない")
    assert bad == [], (
        f"⚠ 最後の起動のログ {len(recent)} 行に絶対パスが {len(bad)} 件: {bad[:3]}")
