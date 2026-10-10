"""移行の入口 `migrate-dq2.cmd` と `python -m retroux.migration --interactive`（RX-0165 / D-47）。

★cmd は ASCII・CRLF（⚠ cmd.exe は BOM を読み飛ばさない / LF だけだと goto を見失う）。
★実際に cmd.exe に食わせる: 日本語と空白を含む場所・同梱 Python の代わりの `.venv`・旧フォルダを引数で渡す。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from retroux.core import dq2_data as D
from retroux.migration import __main__ as CLI
from test_dq2_migration import make_legacy

ROOT = Path(__file__).resolve().parents[1]
CMD = ROOT / "migrate-dq2.cmd"


def test_ASCIIだけでBOMが無くCRLF() -> None:
    raw = CMD.read_bytes()
    raw.decode("ascii")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_同梱Pythonを先に見てPATHへは落ちない() -> None:
    text = CMD.read_bytes().decode("ascii")
    assert text.index(r"runtime\python\python.exe") < text.index(r".venv\Scripts\python.exe")
    assert "where python" not in text and '"python"' not in text.lower().replace(r"\python.exe", "")
    assert "--interactive" in text and "-m retroux.migration" in text


# --- 実際に cmd.exe で ----------------------------------------------------------

def _portable(home: Path) -> None:
    """★新しい DQ2 のフォルダの代わり（プログラム ＋ 同梱 Python の代わりの .venv）。"""
    home.mkdir(parents=True)
    shutil.copy2(CMD, home / CMD.name)
    for pkg in ("retroux", "dq2rom"):
        shutil.copytree(ROOT / pkg, home / pkg, ignore=shutil.ignore_patterns("__pycache__"))
    venv = Path(sys.prefix)
    scripts = home / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(Path(sys.executable), scripts / "python.exe")
    shutil.copy2(venv / "pyvenv.cfg", home / ".venv" / "pyvenv.cfg")
    site = home / ".venv" / "Lib" / "site-packages"
    site.mkdir(parents=True)
    (site / "real-venv.pth").write_text(sysconfig.get_paths()["purelib"] + "\n", encoding="utf-8")


def _run(home: Path, *args: str, answers: str = "") -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "RETROUX_WRITE_ROOT", "RETROUX_ROOT")}
    # ★ドラッグ＆ドロップと同じ形（⚠ `cmd /c` に引用符つきを 2 つ渡すと外側の引用符が剥がれる → /s と外側の引用符）
    inner = " ".join(f'"{part}"' for part in (str(home / CMD.name), *args))
    return subprocess.run(f'cmd /s /c "{inner}"', input=answers.encode("utf-8"),
                          capture_output=True, timeout=300, env=env, cwd=str(home.parent))


@pytest.mark.skipif(sys.platform != "win32", reason="⚠ cmd.exe は Windows だけ")
@pytest.mark.skipif(not (Path(sys.prefix) / "pyvenv.cfg").exists(), reason="venv で動いていない")
def test_旧フォルダを渡すと移して結果を日本語で出す(tmp_path) -> None:
    home = tmp_path / "新しい RetroUX DQ2"
    _portable(home)
    old = make_legacy(tmp_path / "旧い RetroUX")
    done = _run(home, str(old), answers="n\n\n")
    out = (done.stdout or b"").decode("utf-8", "replace")
    assert done.returncode == 0, out + (done.stderr or b"").decode("utf-8", "replace")
    assert "移しました" in out and "戦闘の記録 2 件" in out, out
    marker = D.read_marker(home)
    assert marker and marker["history"][-1]["event"] == "migrated"
    con = sqlite3.connect(home / "work" / "retroux.sqlite3")
    try:
        assert con.execute("SELECT COUNT(*) FROM BattleLog").fetchone()[0] == 2
    finally:
        con.close()
    assert (home / "work" / "generated" / "config.lua").exists(), "★作り直しも新しいフォルダのプログラムで"


@pytest.mark.skipif(sys.platform != "win32", reason="⚠ cmd.exe は Windows だけ")
def test_Pythonが無ければ理由を出して落ちる(tmp_path) -> None:
    home = tmp_path / "空 の DQ2"
    home.mkdir()
    shutil.copy2(CMD, home / CMD.name)
    done = _run(home, answers="\n")
    out = (done.stdout or b"").decode("ascii", "replace")
    assert done.returncode == 1
    assert "Could not find Python" in out and r"runtime\python\python.exe" in out


# --- --interactive の流れ（cmd を通さない）----------------------------------------

@pytest.fixture
def answers(monkeypatch):
    queue: list[str] = []

    def fake(prompt=""):
        if not queue:
            raise EOFError
        return queue.pop(0)

    monkeypatch.setattr("builtins.input", fake)
    monkeypatch.setattr(CLI, "running_product", lambda: None)
    monkeypatch.setattr(CLI.regenerate, "run", lambda dest: [])
    return queue


def test_ドラッグした引用符つきのフォルダを受け取る(tmp_path, answers, capsys) -> None:
    old = make_legacy(tmp_path / "old one")
    dest = tmp_path / "new"
    dest.mkdir()
    answers += [f'"{old}"', "", ""]
    assert CLI.main(["--dest", str(dest), "--interactive"]) == 0
    out = capsys.readouterr().out
    assert "移しました" in out and "DQ2.cmd で起動" in out
    assert not (dest / "work" / "rom").exists(), "★ROM は既定で写さない"


def test_ROMを写すかを聞き既定はいいえ(tmp_path, answers, capsys) -> None:
    old = make_legacy(tmp_path / "old")
    dest = tmp_path / "new"
    dest.mkdir()
    answers += ["y", ""]
    # ★偽の ROM なので照合で止まる = 「写そうとした」ことが分かる
    assert CLI.main(["--source", str(old), "--dest", str(dest), "--interactive"]) == 2
    out = capsys.readouterr().out
    assert "ROM の照合" in out and "旧いフォルダは変えていません" in out


def test_RetroUXが動いていれば止める(tmp_path, answers, monkeypatch, capsys) -> None:
    monkeypatch.setattr(CLI, "running_product", lambda: "RetroUX DQ2")
    old = make_legacy(tmp_path / "old")
    dest = tmp_path / "new"
    dest.mkdir()
    answers += [""]
    assert CLI.main(["--source", str(old), "--dest", str(dest), "--interactive"]) == 2
    assert "RetroUX DQ2 が起動中" in capsys.readouterr().out
    assert D.read_marker(dest) is None


def test_フォルダを渡さなければ止める(tmp_path, answers, capsys) -> None:
    answers += ["", ""]
    assert CLI.main(["--dest", str(tmp_path), "--interactive"]) == 2
    assert "フォルダが指定されていません" in capsys.readouterr().out


def test_止めた理由を日本語で出す(tmp_path, answers, capsys) -> None:
    other = tmp_path / "DQ2 ではない"
    other.mkdir()
    dest = tmp_path / "new"
    dest.mkdir()
    answers += ["", ""]
    assert CLI.main(["--source", str(other), "--dest", str(dest), "--interactive"]) == 2
    out = capsys.readouterr().out
    assert "止めました" in out and "DQ2 のフォルダに見えません" in out
