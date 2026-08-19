"""窓を測る道具（`scripts/snap-windows.ps1`）が動くこと（RX-0062）。

## ⚠⚠ なぜ検査するか

★この道具は「画面レイアウトを**目測で判断しない**」ための足場です。
⚠ 使いたいときに壊れていたら、また目測で判断することになります。

## ⚠ この計画で踏んだ罠

- `SetProcessDPIAware()` を呼ばないと、⚠ **画面の左上 2/3 しか撮れない**
- `Get-Process | Where MainWindowTitle` は ⚠ **プロセスごとに1つ**しか返さない
  （★「見た地図」「ログ」は同じ pythonw の窓なので取れない）
- `New-Object ... $a, $b` は引数の解釈でつまずく
- 相対パスだと `Save` が「GDI+ で汎用エラー」で落ちる
"""

from __future__ import annotations

import pathlib
import struct
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "snap-windows.ps1"

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="PowerShell が要る")


def test_道具がある():
    assert SCRIPT.exists(), f"★{SCRIPT.name} が無い"


def test_DPIを意識させている():
    """★★ ⚠⚠ **これが無いと左上 2/3 しか撮れない** ★★

    ⚠ 呼ぶ**順番**も要る。★測ったあとでは効かない。
    """
    body = SCRIPT.read_text(encoding="utf-8-sig")
    assert "SetProcessDPIAware" in body, "⚠ DPI を意識させていない"
    call = body.index("[void][Snap]::SetProcessDPIAware()")
    measure = body.index("PrimaryScreen")
    assert call < measure, "⚠ 測ったあとに呼んでいる（★効かない）"


def test_全部の窓を列挙している():
    """⚠ `Get-Process` では同じプロセスの窓を取りこぼす。"""
    body = SCRIPT.read_text(encoding="utf-8-sig")
    assert "EnumWindows" in body, (
        "★`EnumWindows` を使っていない（⚠ 地図とログが取れない）")


@windows_only
def test_実際に動く():
    """★★★ ⚠⚠ **「書いてある」で終わらせない** ★★★

    ⚠ この計画では PowerShell の書き間違いで**起動不能**を作っている
      （2026-08-14 / `TrimStart`）。★字面ではなく**動かす**。
    """
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
        capture_output=True, timeout=180, cwd=str(PROJECT_ROOT))
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("cp932", "replace")

    # ⚠⚠ **`returncode` を信じない**（★PowerShell は非終了エラーで 0 を返す）
    assert not err.strip(), "⚠ エラーが出ている: " + err + " / " + out
    assert "WORKAREA" in out, "★作業領域を測れていない: " + out
    assert "SCREEN" in out, "★画面の大きさを測れていない: " + out
    assert "WIN\t" in out, "★窓を1つも列挙できていない: " + out

    for name in ("_windows.txt", "_desktop.png"):
        got = PROJECT_ROOT / "work" / name
        assert got.exists(), f"★{name} ができていない"
        assert got.stat().st_size > 0, f"★{name} が空"


@windows_only
def test_撮った画面が画面いっぱいである():
    """⚠ DPI を意識していないと、★左上 2/3 だけの画像になる。"""
    png = PROJECT_ROOT / "work" / "_desktop.png"
    txt = PROJECT_ROOT / "work" / "_windows.txt"
    if not (png.exists() and txt.exists()):
        pytest.skip("★先に `test_実際に動く` を通すこと")
    width, height = struct.unpack(">II", png.read_bytes()[16:24])
    line = next(l for l in txt.read_text(encoding="utf-8").splitlines()
                if l.startswith("SCREEN"))
    want = line.split("\t")[-1]
    assert f"{width}x{height}" == want, (
        f"⚠ 撮った画像 {width}x{height} と画面 {want} が違う"
        "（★DPI を意識していない疑い）")
