"""DQ2 の場所の決め方（RX-0146 / D-42）。

★Phase 1 は既定の場所を**変えない**。変わるのは「設定に書いた場所が FCEUX の起動に効く」ことだけ
（⚠ 以前は `paths.rom` が FCEUX の起動に効かず、公開 README の説明と食い違っていた）。
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from retroux.core import dq2_paths as P
from retroux.core.config.user_config import UserConfig

ROOT = Path(__file__).resolve().parents[1]


def _cfg(**paths) -> UserConfig:
    cfg = UserConfig()
    for key, value in paths.items():
        setattr(cfg.paths, key, value)
    return cfg


def test_既定の場所は今までどおり() -> None:
    cfg = _cfg()
    base = ROOT / "tools" / "fceux"
    assert P.fceux_exe(cfg).parent == base
    assert P.fceux_exe(cfg).name in P.FCEUX_NAMES
    assert P.fcs_dir(cfg) == base / "fcs"
    assert P.fceux_cfg(cfg) == base / "fceux.cfg"
    assert P.rom(cfg) == ROOT / "work" / "rom" / "DQ2_J.nes"


def test_FCEUXを指定するとfcsとcfgも一緒に動く(tmp_path: Path) -> None:
    exe = tmp_path / "FCEUX DQ2" / "fceux64.exe"
    cfg = _cfg(fceux=str(exe))
    assert P.fceux_exe(cfg) == exe
    assert P.fcs_dir(cfg) == exe.parent / "fcs"
    assert P.fceux_cfg(cfg) == exe.parent / "fceux.cfg"


def test_相対の指定はプログラムの直下から() -> None:
    cfg = _cfg(fceux="emu/fceux.exe", rom="roms/DQ2.nes")
    assert P.fceux_exe(cfg) == ROOT / "emu" / "fceux.exe"
    assert P.rom(cfg) == ROOT / "roms" / "DQ2.nes"


def test_fceux64が無ければfceux_exeを使う(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tools" / "fceux").mkdir(parents=True)
    (tmp_path / "tools" / "fceux" / "fceux.exe").write_bytes(b"")
    monkeypatch.setattr(P, "PROJECT_ROOT", tmp_path)
    assert P.fceux_exe(_cfg()).name == "fceux.exe"


def test_書き先の根は環境変数に従う(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    assert P.work("runtime") == tmp_path / "work" / "runtime"
    monkeypatch.delenv("RETROUX_WRITE_ROOT")
    assert P.write_root() == ROOT


def test_起動用のJSONはASCIIで日本語と空白の場所も運べる(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    exe = tmp_path / "ゲーム 用" / "fceux64.exe"
    rom = tmp_path / "ロム" / "DQ2_J.nes"
    from retroux.core.config import dq2_user_config

    monkeypatch.setattr(dq2_user_config, "load",
                        lambda *a, **k: (_cfg(fceux=str(exe), rom=str(rom)), []))
    assert P.main(["--launch-json"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.isascii()
    got = json.loads(out)
    assert Path(got["fceux"]) == exe
    assert Path(got["rom"]) == rom
    assert Path(got["fcs"]) == exe.parent / "fcs"
    assert Path(got["fceux_cfg"]) == exe.parent / "fceux.cfg"


def test_旧設定ファイルのDQ3用FCEUXはDQ2に効かない(tmp_path: Path) -> None:
    """★DQ3 のために `user_config.yaml` に書いた FCEUX で DQ2 が起動しない（RX-0147 の読み手が空にする）。"""
    from retroux.core.config import dq2_user_config

    (tmp_path / "user_config.yaml").write_text(
        "paths:\n  fceux: C:/Emu-DQ3/fceux64.exe\n", encoding="utf-8")
    cfg, _ = dq2_user_config.load(root=tmp_path)
    assert P.fceux_exe(cfg).parent == ROOT / "tools" / "fceux"


# --- 起動スクリプト ------------------------------------------------------------

def _code(rel: str) -> list[str]:
    text = (ROOT / rel).read_text(encoding="utf-8-sig")
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def test_起動スクリプトは場所をresolverから受け取りFCEUXに渡す() -> None:
    code = "\n".join(_code("scripts/start-dq2.ps1"))
    assert "-m retroux.core.dq2_paths --launch-json" in code
    assert '$startArgs["Fceux"] = $launch.fceux' in code
    assert '$startArgs["Rom"] = $launch.rom' in code
    assert "--cfg $launch.fceux_cfg" in code


def test_FCEUXの起動はFCEUXの場所を受け取る() -> None:
    """★旧 scripts/start.ps1 は start-dq2.ps1 の関数 Start-Dq2Emulator へ取り込んだ（RX-0154）。"""
    code = "\n".join(_code("scripts/start-dq2.ps1"))
    assert '[string]$Fceux = ""' in code
    assert "$fceux = $Fceux" in code


def test_控えと保存のセーブの場所もresolverから(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★FCEUX を外に置くとセーブも一緒に動く。⚠ 控えと「保存して終了」が古い場所を見ると空振りする。"""
    from retroux.core.config import dq2_user_config
    from retroux.tools import dq2_savestate_backup as B
    from retroux.ui.main_window import MainWindow

    exe = tmp_path / "emu" / "fceux64.exe"
    cfg = _cfg(fceux=str(exe))
    assert MainWindow._savestate_file(types.SimpleNamespace(), cfg, 1) == exe.parent / "fcs" / "DQ2_J.fc1"

    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    monkeypatch.setattr(dq2_user_config, "load", lambda *a, **k: (cfg, []))
    (exe.parent / "fcs").mkdir(parents=True)
    (exe.parent / "fcs" / "DQ2_J.fc0").write_bytes(b"now")
    gen = B.default_dst() / "DQ2_J.fc0"
    gen.mkdir(parents=True)
    (gen / "20261001-000000-000000-000001.bak").write_bytes(b"old")
    assert B.main(["--restore", "DQ2_J.fc0"]) == 0
    assert (exe.parent / "fcs" / "DQ2_J.fc0").read_bytes() == b"old"
