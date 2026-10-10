"""移行のあとの作り直し（RX-0158 / 依頼 §13）。

★失敗は移行の失敗（★印を書かない）。⚠ ただし「置く前のもの」が無いのは失敗にしない:
  モンスターの絵は FCEUX の色見本が要る（★2026-10-03 の実データで、FCEUX を移さないので必ず落ちた）。
★子プロセスは差し替える（★本物の作り直しは実データの確認で回した / docs/30-command-log.md）。
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from retroux.migration import regenerate as G


@pytest.fixture
def dest(tmp_path) -> Path:
    d = tmp_path / "dest"
    (d / "retroux" / "core").mkdir(parents=True)
    (d / "retroux" / "core" / "dq2_paths.py").write_bytes(b"")
    return d


def _fake(dest: Path, *, rc: dict | None = None, makes=G.ALWAYS + G.WITH_ROM, art: bool = False):
    calls = []

    def run(cmd, cwd=None, env=None, capture_output=None, timeout=None):
        mod = cmd[-1]
        calls.append((mod, cwd, env.get("PYTHONPATH")))
        for rel in makes:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_bytes(b"x")
        if art:
            (dest / "work" / "monster-art-rom").mkdir(parents=True, exist_ok=True)
            (dest / "work" / "monster-art-rom" / "1.png").write_bytes(b"x")
        return types.SimpleNamespace(returncode=(rc or {}).get(mod, 0), stdout=b"", stderr=b"boom")

    return run, calls


def _rom(monkeypatch, dest: Path, exists: bool) -> None:
    rom = dest / "work" / "rom" / "DQ2_J.nes"
    if exists:
        rom.parent.mkdir(parents=True, exist_ok=True)
        rom.write_bytes(b"x")
    monkeypatch.setattr(G, "_rom_of", lambda d: rom)


def test_移行先のプログラムで動かす(dest, monkeypatch) -> None:
    run, calls = _fake(dest, makes=G.ALWAYS)
    monkeypatch.setattr(G.subprocess, "run", run)
    _rom(monkeypatch, dest, exists=False)
    assert G.run(dest) == []
    assert [c[0] for c in calls] == list(G.MODULES)
    assert all(c[1] == str(dest) and c[2] == str(dest) for c in calls)


def test_終了コードが0でなければ失敗(dest, monkeypatch) -> None:
    run, _ = _fake(dest, rc={"retroux.core.config.generate_lua": 1})
    monkeypatch.setattr(G.subprocess, "run", run)
    _rom(monkeypatch, dest, exists=False)
    got = G.run(dest)
    assert got and "generate_lua" in got[0]


def test_ROMがあるのに作られていなければ失敗(dest, monkeypatch) -> None:
    run, _ = _fake(dest, makes=G.ALWAYS)
    monkeypatch.setattr(G.subprocess, "run", run)
    _rom(monkeypatch, dest, exists=True)
    got = G.run(dest)
    assert any("enemy_tables.json" in p for p in got) and any("maps.json" in p for p in got)


def test_色見本があるのに絵が無ければ失敗(dest, monkeypatch) -> None:
    (dest / G.PALETTE).parent.mkdir(parents=True)
    (dest / G.PALETTE).write_bytes(b"x")
    run, _ = _fake(dest)
    monkeypatch.setattr(G.subprocess, "run", run)
    _rom(monkeypatch, dest, exists=True)
    assert any("monster-art-rom" in p for p in G.run(dest))


def test_色見本が無ければ絵は置いたあとに回す(dest, monkeypatch, capsys) -> None:
    run, _ = _fake(dest)
    monkeypatch.setattr(G.subprocess, "run", run)
    _rom(monkeypatch, dest, exists=True)
    assert G.run(dest) == []
    assert "FCEUX" in capsys.readouterr().out


def test_絵が揃えば成功(dest, monkeypatch) -> None:
    (dest / G.PALETTE).parent.mkdir(parents=True)
    (dest / G.PALETTE).write_bytes(b"x")
    run, _ = _fake(dest, art=True)
    monkeypatch.setattr(G.subprocess, "run", run)
    _rom(monkeypatch, dest, exists=True)
    assert G.run(dest) == []


def test_プログラムが無ければ失敗(tmp_path) -> None:
    assert G.run(tmp_path) and "プログラム" in G.run(tmp_path)[0]
