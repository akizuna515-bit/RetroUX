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
START = PROJECT_ROOT / "scripts" / "start-dq2.ps1"


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


# --- 3. ⚠ ログに絶対パスが出ていないか ---------------------------------------
#
# ★前は「利用者の実ログの最後の起動」を見ていた（RX-0043）。⚠ それだと、直したあとでも
#   **直す前の行が残る間は赤**になり、検査の結果が利用者の過去の起動に左右される（RX3-0530）。
# → 通常の検査は、**隔離した一時ログ**に製品の書き出しを通して仕様（相対で書く）を見る。
#   実運用のログは `python -m retroux.tools.audit_log_paths` で別に監査する（読むだけ）。

def _write_real_log(tmp_path, monkeypatch):
    """製品の書き出し（旧の置き場の設定を読んだときのログ）を、一時ログへ流す。"""
    import logging

    from retroux.core import dq2_paths

    program = tmp_path / "program"
    (program / "config").mkdir(parents=True)
    (program / "config" / "mission.yaml").write_text("x", encoding="utf-8")
    monkeypatch.setattr(dq2_paths, "PROJECT_ROOT", program)
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(program))
    monkeypatch.setattr(dq2_paths, "_LEGACY_REPORTED", set())
    log = tmp_path / "retroux.log"
    handler = logging.FileHandler(log, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s"))
    logger = logging.getLogger("retroux.settings")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        got = dq2_paths.setting_to_read(dq2_paths.setting("mission.yaml"), dq2_paths.legacy_setting("mission.yaml"))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        handler.close()
    assert got == dq2_paths.legacy_setting("mission.yaml"), "★旧を読む道を通っていない（検査の前提が崩れている）"
    return log, program


def test_製品が書いたログに絶対パスが出ない(tmp_path, monkeypatch):
    from retroux.tools import audit_log_paths as A

    log, program = _write_real_log(tmp_path, monkeypatch)
    lines = log.read_text(encoding="utf-8").splitlines()
    # ⚠⚠ 「0 件」と「1 行も見ていない」を混ぜない
    assert any("旧の置き場の設定を読みました" in line for line in lines), lines
    # ★隔離した置き場の名前は tmp の中にある → 製品の名前（PROJECT_ROOT.name = 本物の根の名前）ではなく、
    #   隔離した根の名前で数える。書いてあれば、相対でなく絶対で出している
    assert A.find_violations(lines, program.name) == [], lines
    assert "config/mission.yaml" in lines[0] and str(program) not in lines[0]


def test_監査は絶対パスの行を見つけ修正の前後を分ける(tmp_path):
    from datetime import datetime

    from retroux.tools import audit_log_paths as A

    root = A.PROJECT_ROOT.name
    bs = chr(92)
    old = ("2026-10-08 08:05:41 [INFO] settings 旧の置き場の設定を読みました: "
           + bs.join(["C:", "Projects", root, "config", "mission.yaml"]) + "（★保存は …）")
    new = "2026-10-09 09:00:00 [INFO] settings 旧の置き場の設定を読みました: config/mission.yaml"
    lines = ["2026-10-08 08:05:40 [INFO] launcher 設定を変換しています", old, new]
    assert A.last_launch(lines) == lines
    assert A.last_launch(["別の行"]) == []
    found = A.find_violations(lines, root)
    assert [v["stamp"] for v in found] == ["2026-10-08 08:05:41"] and found[0]["line_no"] == 2
    before, after = A.split_by_fix(found, datetime(2026, 10, 8, 18, 0, 0))
    assert (len(before), len(after)) == (1, 0)                 # ★修正より前の記録
    before, after = A.split_by_fix(found, datetime(2026, 10, 8, 8, 0, 0))
    assert (len(before), len(after)) == (0, 1)                 # ★修正より後に出た行 = 違反
    before, after = A.split_by_fix(found, None)
    assert (len(before), len(after)) == (0, 1)                 # ⚠ 修正の日時が分からなければ見逃さない側


def test_監査の道具は読むだけで終了コードを返す(tmp_path):
    from retroux.tools import audit_log_paths as A

    log = tmp_path / "retroux.log"
    assert A.main([str(log)]) == 2                              # ログが無い
    root = A.PROJECT_ROOT.name
    bs = chr(92)
    text = ("2026-12-31 08:05:40 [INFO] launcher 設定を変換しています\n"
            "2026-12-31 08:05:41 [INFO] settings x: " + bs.join(["C:", "Projects", root, "config", "a.yaml"]) + "\n")
    log.write_text(text, encoding="utf-8")
    before = log.read_bytes()
    assert A.main([str(log)]) == 1                              # 修正より後の日時の違反
    assert log.read_bytes() == before, "⚠ 監査がログを書き換えた"
