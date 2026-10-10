"""Python の置き場を決めるのは 1 か所（RX3-0473 / 2026-09-29）。

## ⚠⚠ なぜ要るか

★配布 Runtime には `.venv` がありません。⚠ 以前は 3 本の launcher が
`.venv\\Scripts\\python.exe` を**独立に組み立てて**いたので、
★Runtime 対応は「全部を同じように直す」作業になっていました。

```text
★解決の順番（`scripts/launcher-common.ps1`）
  1 <root>\\runtime\\python\\python.exe    ★製品 Runtime（同梱）
  2 <root>\\.venv\\Scripts\\python.exe     ★開発環境
  3 見つからない → $null（⚠ 呼ぶ側が案内を出す）

⚠⚠ PATH の python.exe / py.exe へは**落ちません**。
  ★利用者の PC に偶然入っている Python を拾うと、⚠ 依存パッケージが
    そこに無いので「起動したのに import で落ちる」になります。
```

## ⚠ この検査の限界（★正直に）

★`.ps1` を**実行していません**（このセッションでは PowerShell の起動が
許可規則で止まります）。⚠ ここで見ているのは
**順番を決めているデータ**と**各 launcher が resolver を呼んでいること**です。
→ ★実行の確認は `scripts/dq3_python_resolver_check.ps1` を人が 1 度回してください。
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMON = ROOT / "scripts" / "launcher-common.ps1"

#: ★配布物に入る launcher（⚠ ここに Python の判定をコピーしないこと）
LAUNCHERS = ("scripts/start-dq3.ps1", "scripts/start-dq2.ps1",
             "scripts/launcher-common.ps1")  # ★旧 start.ps1 は start-dq2.ps1 へ（RX-0154）


def read(rel) -> str:
    # ⚠ `.ps1` は UTF-8 BOM 付き（★`utf-8-sig` で読む）
    return (ROOT / rel).read_text(encoding="utf-8-sig", errors="replace")


def code_lines(text: str) -> list[str]:
    """⚠ 註を外す（★誤検知を避ける）。"""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("<#"):
            continue
        out.append(line)
    return out


def test_解決順はruntimeが先でvenvが後() -> None:
    """★順番を決めているのは 1 つのデータ（`$script:RetroUXPythonLayouts`）。"""
    text = read(COMMON)
    block = re.search(r"\$script:RetroUXPythonLayouts\s*=\s*@\((.*?)\n\)",
                      text, re.S)
    assert block is not None, "⚠⚠ RetroUXPythonLayouts が見つかりません"
    body = block.group(1)
    runtime = body.index(r"runtime\python")
    venv = body.index(r".venv\Scripts")
    assert runtime < venv, (
        "⚠⚠ .venv を先に見ています（★製品 Runtime が同梱の Python を使えません）")


def test_resolverがある() -> None:
    text = read(COMMON)
    for name in ("function Get-RetroUXPython", "function Get-RetroUXPythonHint",
                 "function Get-PythonForGui"):
        assert name in text, f"⚠ {name} がありません"


def test_PATHのPythonへ落ちない() -> None:
    """⚠⚠ 利用者の PC に偶然入っている Python に依存させない（依頼者 §2）。"""
    lines = code_lines(read(COMMON))
    joined = "\n".join(lines)
    for banned in ("Get-Command python", "Get-Command py", "py.exe",
                   "where.exe python", "$env:PATH"):
        assert banned not in joined, (
            f"⚠⚠ launcher-common.ps1 が {banned} を見ています（★PATH に落ちる道）")


def test_見つからなければnullを返す() -> None:
    """★案内は呼ぶ側が出す（⚠ でたらめな道を返さない）。"""
    text = read(COMMON)
    got = re.search(r"function Get-RetroUXPython\b.*?\n\}", text, re.S)
    assert got is not None
    assert "return $null" in got.group(0), (
        "⚠ 見つからないときに $null を返していません")


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_launcherが判定をコピーしていない(rel: str) -> None:
    """⚠⚠ 同じ判定が散ると、★1 か所直しても残りが `.venv` を見続ける。"""
    if rel == "scripts/launcher-common.ps1":
        pytest.skip("★ここが正本")
    lines = code_lines(read(rel))
    hits = [ln.strip() for ln in lines
            if re.search(r'\.venv[\\/]+Scripts[\\/]+python', ln)]
    assert hits == [], (
        f"⚠⚠ {rel} が Python の道を自分で組み立てています "
        "（★Get-RetroUXPython を使ってください）:\n" + "\n".join(hits))


@pytest.mark.parametrize("rel", ("scripts/start-dq3.ps1", "scripts/start-dq2.ps1"))
def test_launcherがresolverを呼んでいる(rel: str) -> None:
    """⚠ 関数が正しくても、★呼ばれていなければ意味がない。"""
    text = read(rel)
    assert "Get-RetroUXPython" in text, f"⚠ {rel} が resolver を呼んでいません"
    assert "launcher-common.ps1" in text, f"⚠ {rel} が共通部品を読み込んでいません"


def test_DQ3のlauncherは案内を出す() -> None:
    """★見つからないときに「探した場所」を人に見せること。"""
    text = read("scripts/start-dq3.ps1")
    assert "Get-RetroUXPythonHint" in text
    assert "Fail " in text, "⚠ ダイアログを出していません"


def test_ps1がBOM付きのまま() -> None:
    """⚠⚠ BOM 無しの `.ps1` は cp932 として読まれ、★日本語註が構文エラーになる。"""
    for rel in LAUNCHERS:
        raw = (ROOT / rel).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), f"⚠⚠ {rel} の BOM が消えています"


def test_runtimeの置き場の名前が1か所で決まっている() -> None:
    """★`runtime/python` を別名で書いている場所が無いこと。"""
    hits = []
    for rel in LAUNCHERS:
        for number, line in enumerate(code_lines(read(rel)), start=1):
            if re.search(r"runtime[\\/]+python", line):
                hits.append(f"{rel}:{number}")
    assert len(hits) == 1, (
        "⚠ `runtime/python` を書いている場所が 1 つではありません: " + ", ".join(hits))
