"""展開先が深すぎれば、Qt を起こす前に止める（RX-0166 / RX3-0517 / 2026-10-05）。

⚠⚠ 深い場所へ展開すると Qt がエラーも出さずに止まる（★最も長いパス 280 文字で実測 / 194 文字では動く）。
★依頼者 2026-10-05「深い場所に展開しようとしたらチェックエラーにしてOK」。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from retroux.core import path_depth as PD

ROOT = Path(__file__).resolve().parents[1]


def _product(root: Path, longest: int | None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if longest is not None:
        (root / "build-info.json").write_text(json.dumps({"longest_path": longest}), encoding="utf-8")
    return root


def test_build_の値と展開先の文字数で測る(tmp_path: Path) -> None:
    root = _product(tmp_path / "p", 100)
    got = PD.measure(root)
    assert got["total"] == len(str(root)) + 1 + 100
    assert got["ok"] is (got["total"] <= PD.LIMIT)
    assert got["allowed"] == PD.LIMIT - 1 - 100


def test_上限を超えれば止める_実測の280文字(tmp_path: Path) -> None:
    """★2026-10-04 の実測: 最も長いパス 280 文字で Qt が黙って止まった。"""
    root = _product(tmp_path / "p", 280 - len(str(tmp_path / "p")) - 1)
    got = PD.measure(root)
    assert got["total"] == 280 and not got["ok"]


def test_ちょうど上限なら通す(tmp_path: Path) -> None:
    root = _product(tmp_path / "p", PD.LIMIT - len(str(tmp_path / "p")) - 1)
    assert PD.measure(root)["total"] == PD.LIMIT and PD.measure(root)["ok"]
    root2 = _product(tmp_path / "q", PD.LIMIT - len(str(tmp_path / "q")))
    assert not PD.measure(root2)["ok"], "⚠ 上限を 1 文字超えても通している"


def test_展開ツールが長いファイルを飛ばしても_build_の値で測る(tmp_path: Path) -> None:
    """⚠ 中身だけを歩くと、飛ばされたファイルのぶん短く測れてしまう。"""
    root = _product(tmp_path / "p", 400)
    (root / "runtime" / "python").mkdir(parents=True)
    (root / "runtime" / "python" / "x.dll").write_bytes(b"")
    assert not PD.measure(root)["ok"]


def test_build_の値が無ければ中身を歩いて測る(tmp_path: Path) -> None:
    root = _product(tmp_path / "p", None)
    deep = root / "runtime" / ("a" * 60) / ("b" * 60)
    deep.mkdir(parents=True)
    (deep / ("c" * 60 + ".pyd")).write_bytes(b"")
    want = len("runtime") + 1 + 60 + 1 + 60 + 1 + 64
    assert PD.measure(root)["relative"] == want


def test_利用者のwork_は数えない(tmp_path: Path) -> None:
    root = _product(tmp_path / "p", None)
    (root / "work" / ("w" * 200)).mkdir(parents=True)
    assert PD.measure(root)["relative"] == 0


def test_開発repoでは止めない() -> None:
    """★build-info に longest_path が無く、runtime/ も無い → 止めない（⚠ 開発の起動を壊さない）。"""
    assert PD.measure(ROOT)["ok"]


def test_CLIはASCIIで結果と終了コードを返す(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert PD.main(["--root", str(_product(tmp_path / "ok", 10))]) == 0
    assert capsys.readouterr().out.startswith("OK total=")
    assert PD.main(["--root", str(_product(tmp_path / "deep", 400))]) == 3
    out = capsys.readouterr().out
    assert out.startswith("TOO_DEEP total=") and "allowed=" in out
    assert out.isascii(), "⚠ PowerShell 5.1 が化かすので ASCII だけ"


# --- 起動スクリプト（★本物の PowerShell で関数を呼ぶ）------------------------------

def _ps_problem(tmp_path: Path, product: Path) -> str:
    if shutil.which("powershell") is None:
        pytest.skip("⚠ PowerShell が無い環境")
    out = tmp_path / "out.txt"
    script = tmp_path / "probe.ps1"
    body = (
        ". '%s'\n"
        "$got = Get-RetroUXDepthProblem -Python '%s' -Root '%s'\n"
        "$got | Out-File -LiteralPath '%s' -Encoding UTF8\n"
    ) % (ROOT / "scripts" / "launcher-common.ps1", sys.executable, product, out)
    script.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    got = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         cwd=str(ROOT), capture_output=True, timeout=120)
    assert got.returncode == 0, got.stderr.decode("utf-8", "replace")[:400]
    return out.read_text(encoding="utf-8-sig").strip()


def test_起動スクリプトの関数は深ければ理由の文を返す(tmp_path: Path) -> None:
    text = _ps_problem(tmp_path, _product(tmp_path / "deep", 400))
    assert "深すぎます" in text and "259 文字" in text and "C:\\Tools" in text, text


def test_起動スクリプトの関数は浅ければ空(tmp_path: Path) -> None:
    assert _ps_problem(tmp_path, _product(tmp_path / "ok", 10)) == ""


def _code(name: str) -> str:
    text = (ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_DQ2の起動スクリプトはGUIの前に深さを見て止める() -> None:
    code = _code("start-dq2.ps1")
    at = code.index("Get-RetroUXDepthProblem -Python $python -Root $Root")
    assert at < code.index("Get-PythonForGui"), "⚠ 何かを始める前に見ていない"
    assert "Stop-Launcher -Message $depthProblem" in code[at:at + 200]


def test_DQ3の起動スクリプトも深さを見て止める() -> None:
    code = _code("start-dq3.ps1")
    at = code.index("Get-RetroUXDepthProblem -Python $python -Root $Root")
    assert at < code.index("RetroUX_Product") if "RetroUX_Product" in code else True
    assert "Fail $depthProblem" in code[at:at + 200]


# --- 移行の入口（migrate-dq2.cmd）------------------------------------------------

def test_移行の入口も深ければ何もせず止める(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from retroux.migration.__main__ import main

    dest = _product(tmp_path / "deep", 400)
    src = tmp_path / "old"
    src.mkdir()
    assert main(["--source", str(src), "--dest", str(dest), "--interactive", "--no-wait"]) == 2
    out = capsys.readouterr().out
    assert "深すぎます" in out and "旧いフォルダは変えていません" in out
    assert sorted(p.name for p in dest.iterdir()) == ["build-info.json"], "⚠ 止めたのに書いた"
