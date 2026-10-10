"""DQ2 の起動で FCEUX の場所が壊れていても黙らない（RX-0168 / RX-0169）。

★2026-10-05 の実機: dq2_user_config.yaml に `fceux: "C:/Emu/fceux-2.6.6-win6/\\fceux64.exe"`。
  YAML の "…" の中で `\\f` が**改ページ**に化け、起動スクリプトは FCEUX の起動で記録も箱も無く終わった。
  ⚠ さらに exe の無い場所に `fceux.cfg` をフォルダごと作っていた。
"""

from __future__ import annotations

import json
from pathlib import Path

from retroux.core import dq2_paths
from retroux.core.config import dq2_user_config

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "scripts" / "start-dq2.ps1"


def _cfg(tmp_path: Path, body: str):
    (tmp_path / dq2_user_config.CONFIG_NAME).write_bytes(body.encode("utf-8"))
    return dq2_user_config.load(root=tmp_path)[0]


def test_引用符の中の円記号fが改ページに化けたら止める理由を出す(tmp_path) -> None:
    """★実機と同じ書き方（★YAML を本当に読む）。"""
    cfg = _cfg(tmp_path, 'paths:\n  fceux: "C:/Emu/fceux-2.6.6-win6/\\fceux64.exe"\n')
    assert "\f" in cfg.paths.fceux, "★YAML は本当に改ページに読む（この検査の前提）"
    got = dq2_paths.path_problems(cfg)
    assert len(got) == 1 and "paths.fceux" in got[0] and "改ページ" in got[0] and "/ に書き換えて" in got[0]


def test_スラッシュや一重引用符なら問題なし(tmp_path) -> None:
    for line in ('  fceux: "C:/Emu/fceux-2.6.6-win64/fceux64.exe"\n',
                 "  fceux: 'C:\\Emu\\fceux-2.6.6-win64\\fceux64.exe'\n",
                 '  fceux: ""\n'):
        assert dq2_paths.path_problems(_cfg(tmp_path, "paths:\n" + line)) == [], line


def test_ROMの場所も見る(tmp_path) -> None:
    cfg = _cfg(tmp_path, 'paths:\n  rom: "D:/roms\\tDQ2_J.nes"\n')
    got = dq2_paths.path_problems(cfg)
    assert len(got) == 1 and "paths.rom" in got[0] and "タブ" in got[0]


def test_起動スクリプトへ問題を渡す(tmp_path, capsys, monkeypatch) -> None:
    cfg = _cfg(tmp_path, 'paths:\n  fceux: "C:/x/\\fceux64.exe"\n')
    monkeypatch.setattr(dq2_paths, "_cfg", lambda c=None: cfg)
    assert dq2_paths.main(["--launch-json"]) == 0
    out = capsys.readouterr().out
    out.encode("ascii")                         # ★ASCII のまま（PowerShell の文字コードに左右されない）
    got = json.loads(out)
    assert got["problems"] and "paths.fceux" in got["problems"][0]


def _text() -> str:
    return PS1.read_bytes().decode("utf-8-sig")


def test_問題があればFCEUXの前に止める() -> None:
    text = _text()
    stop = text.index("$launch.problems")
    assert stop < text.index("retroux.tools.fceux_scale $scale --cfg") < text.index("Start-Dq2Emulator @startArgs")
    assert "Stop-Launcher" in text[stop:stop + 600]


def test_exeが無ければfceux_cfgを書かない() -> None:
    text = _text()
    i = text.index("retroux.tools.fceux_scale $scale --cfg")
    assert "Test-Path -LiteralPath $launch.fceux" in text[i - 300:i]


def test_FCEUXの起動の失敗を黙らせない() -> None:
    text = _text()
    i = text.index("Start-Dq2Emulator @startArgs")
    block = text[i - 200:i + 400]
    assert "try {" in block and "} catch {" in block and "Stop-Launcher" in block
