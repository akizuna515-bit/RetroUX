"""ダブルクリックの入口（`RetroUX.cmd` / `DQ3.cmd`）— RX3-0459 / 2026-09-28。

★★ **開発版と配布版で、利用者から見た起動の仕方を分けない。** ★★

```text
開発 repo   RetroUX.cmd  ダブルクリック → DQ2
配布物      RetroUX.cmd  ダブルクリック → DQ2     ★同じ名前・同じ挙動
開発 repo   DQ3.cmd      ダブルクリック → DQ3
配布物      DQ3.cmd      ダブルクリック → DQ3
```

⚠ もとは `DQ3.vbs` が「開発版 / 遊びモード / そのまま遊ぶ」の**3 択ダイアログ**を
出していました（★通常起動でモードを選ばせない / RX3-0459）。

## ⚠⚠ この 2 本だけ文字コードの規則が違う

| 拡張子 | 文字コード | なぜ |
| --- | --- | --- |
| `.ps1` | UTF-8 **BOM あり** | BOM が無いと PS 5.1 は ANSI として読む |
| `.vbs` | cp932 / BOM なし | WSH は `.vbs` を既定で ANSI として読む |
| 既存の `.cmd` | cp932 / BOM なし | ★日本語のコメントが入っているため |
| **この 2 本** | **ASCII のみ** | ★コードページに依存しない（⚠ 配布先の環境を選ばない） |

★`chcp` が何であっても化けません。⚠ だから**日本語を入れない**ことを検査で固定します。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★入口 → 渡す先（⚠ 増やしたらここに足す / RX3-0122「見張る対象を足し忘れる」）
LAUNCHERS = {
    "RetroUX.cmd": "scripts/start-retroux.ps1",
    "DQ3.cmd": "scripts/start-dq3.ps1",
}


def _code_lines(rel: str) -> list[str]:
    """⚠ コメントと空行を落とす。★「説明に書いてある」で通さない。"""
    text = (PROJECT_ROOT / rel).read_bytes().decode("ascii")
    made = []
    for line in text.splitlines():
        bare = line.strip()
        if not bare or bare.lower().startswith("rem"):
            continue
        made.append(bare)
    return made


# --- 形 ---------------------------------------------------------------

@pytest.mark.parametrize("rel", sorted(LAUNCHERS))
def test_入口がある(rel):
    assert (PROJECT_ROOT / rel).exists(), "⚠⚠ ダブルクリックの入口が無い: %s" % rel


@pytest.mark.parametrize("rel", sorted(LAUNCHERS))
def test_ASCIIだけでBOMが無い(rel):
    """⚠⚠ `.cmd` は**コメントも含めて** ASCII（★配布先のコードページに依存させない）。

    ⚠ cmd.exe は BOM を読み飛ばしません（★1 行目が `?@echo off` になって化けます）。
    """
    raw = (PROJECT_ROOT / rel).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "⚠⚠ BOM がある: %s" % rel
    bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, "⚠⚠ ASCII でないバイトがある: %s %s" % (rel, bad[:5])


@pytest.mark.parametrize("rel", sorted(LAUNCHERS))
def test_改行がCRLF(rel):
    """⚠ cmd.exe は LF だけのバッチで `goto` を見失うことがある。"""
    raw = (PROJECT_ROOT / rel).read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n"), "⚠⚠ CRLF でない行がある: %s" % rel


@pytest.mark.parametrize("rel", sorted(LAUNCHERS))
def test_rootは自分の置き場から決める(rel):
    """★カレントディレクトリに依存しない（⚠ ショートカットの作業フォルダは当てにならない）。"""
    code = _code_lines(rel)
    assert any('set "ROOT=%~dp0"' in line for line in code), \
        "⚠⚠ %~dp0（自分の置き場）から root を取っていない: %s" % rel
    # ⚠ 末尾の \ を落とすこと（★PowerShell の -Root "..." が `\"` に化ける）
    assert any("ROOT:~0,-1" in line for line in code), \
        "⚠⚠ 末尾の \\ を落としていない: %s" % rel
    # ⚠ カレントに頼る書き方をしない
    assert not any("cd /d" in line or "%CD%" in line for line in code), \
        "⚠ カレントディレクトリに依存している: %s" % rel


@pytest.mark.parametrize("rel", sorted(LAUNCHERS))
def test_通常起動で何も選ばせない(rel):
    """★★ **通常起動にダイアログも選択肢も出さない**（RX3-0459）。 ★★

    ⚠ もとの `DQ3.vbs` は 3 択の `MsgBox` を出していました。
    """
    code = _code_lines(rel)
    for word in ("choice", "set /p", "MsgBox", "pause"):
        hits = [line for line in code if word.lower() in line.lower()]
        if word == "pause":
            # ★`pause` は**失敗の道だけ**（⚠ 正常時に止めない）
            assert len(hits) <= 2, "⚠⚠ 正常時にも止まりそう: %s %s" % (rel, hits)
            continue
        assert not hits, "⚠⚠ 通常起動で選ばせている: %s %s" % (rel, hits)


@pytest.mark.parametrize("rel,script", sorted(LAUNCHERS.items()))
def test_渡す先が正しい(rel, script):
    code = _code_lines(rel)
    tail = script.replace("/", "\\")
    assert any(tail in line for line in code), \
        "⚠⚠ 渡す先が違う: %s → %s" % (rel, script)
    assert (PROJECT_ROOT / script).exists(), "⚠⚠ 渡す先が無い: %s" % script


def test_DQ2だけQuietを渡す():
    """★配布版は窓を出さない（`-Quiet` → pythonw）。

    ⚠ DQ3 の `start-dq3.ps1` に `-Quiet` は**無い**（★渡すと引数エラーで落ちる）。
    """
    assert any("-Quiet" in line for line in _code_lines("RetroUX.cmd")), \
        "⚠⚠ RetroUX.cmd が -Quiet を渡していない"
    assert not any("-Quiet" in line for line in _code_lines("DQ3.cmd")), \
        "⚠⚠ DQ3.cmd が -Quiet を渡している（★start-dq3.ps1 に無い引数）"


@pytest.mark.parametrize("rel", sorted(LAUNCHERS))
def test_失敗したら黙らない(rel):
    """⚠ 窓が出ない起動なので、★「何も起きない」を作らない（仕様書 5.1）。"""
    code = _code_lines(rel)
    assert any("goto :no_script" in line for line in code), \
        "⚠⚠ 起動スクリプトが無いときの道が無い: %s" % rel
    assert any("exit /b 1" in line for line in code), \
        "⚠⚠ 失敗しても 0 を返している: %s" % rel


# --- 実際に動かす（★読むだけでは足りない / 2026-07-30 の教訓）------------

@pytest.mark.skipif(sys.platform != "win32", reason="⚠ cmd.exe は Windows だけ")
@pytest.mark.parametrize("rel,script", sorted(LAUNCHERS.items()))
def test_空白入りのパスで正しいrootを渡す(rel, script):
    """★★ **文字を読むだけでは足りない。実際に cmd.exe に食わせる。** ★★

    ⚠⚠ 空白を含むフォルダに置くと引数が切れる、という事故が実際にありました
      （★`RetroUX.vbs` の註）。→ ⚠ **空白入りの場所**で実行して確かめます。
    ★渡す先を「受け取った引数を書き出すだけの偽物」に差し替えるので、
      ⚠ FCEUX も GUI も**起動しません**。
    ★カレントを別の場所にして実行します（⚠ cwd 非依存を見るため）。
    """
    stub = ("﻿# stub\r\n"
            "param([string]$Root = '', [switch]$Quiet)\r\n"
            "$out = Join-Path $PSScriptRoot '..\\got.txt'\r\n"
            "Set-Content -LiteralPath $out -Value \"root=$Root|quiet=$Quiet\" "
            "-Encoding utf8\r\n")
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / "My Games" / "Retro UX"
        (home / "scripts").mkdir(parents=True)
        (home / rel).write_bytes((PROJECT_ROOT / rel).read_bytes())
        (home / script.replace("/", "\\")).write_bytes(stub.encode("utf-8"))

        done = subprocess.run(["cmd", "/c", str(home / rel)],
                              cwd=tempfile.gettempdir(),     # ⚠ わざと別の場所
                              capture_output=True, timeout=120)
        assert done.returncode == 0, done.stdout[-400:]

        got = home / "got.txt"
        for _ in range(80):                                   # ★最大 20 秒待つ
            if got.exists():
                break
            time.sleep(0.25)
        assert got.exists(), "⚠⚠ 渡す先が呼ばれていない（★何も起きない起動）"
        text = got.read_text(encoding="utf-8-sig").strip()

    assert text.startswith("root=%s|" % home), \
        "⚠⚠ 自分の置き場を root にしていない: %s（★期待 %s）" % (text, home)
    want_quiet = "True" if rel == "RetroUX.cmd" else "False"
    assert text.endswith("quiet=%s" % want_quiet), text


@pytest.mark.skipif(sys.platform != "win32", reason="⚠ cmd.exe は Windows だけ")
@pytest.mark.parametrize("rel", sorted(LAUNCHERS))
def test_渡す先が無ければ理由を出して落ちる(rel):
    """⚠⚠ 「ダブルクリックしたのに何も起きない」を作らない。

    ★`pause` で止まるので、⚠ 標準入力を閉じて実行します。
    """
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / "Retro UX"
        home.mkdir(parents=True)
        (home / rel).write_bytes((PROJECT_ROOT / rel).read_bytes())
        # ★scripts/ ごと無い状態（⚠ 利用者が中身だけ動かした事故）
        done = subprocess.run(["cmd", "/c", str(home / rel)],
                              cwd=tempfile.gettempdir(), input=b"\r\n",
                              capture_output=True, timeout=120)
    out = (done.stdout or b"").decode("ascii", errors="replace")
    assert done.returncode == 1, "⚠⚠ 失敗したのに %d を返した" % done.returncode
    assert "Missing startup script" in out, out[-400:]
