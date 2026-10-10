"""DQ2 専用の設定ファイル（RX-0147 / D-42 / 依頼者の判断 J4）。

★DQ2 は `dq2_user_config.yaml` を読む。無いときだけ旧 `user_config.yaml` を**読むだけ**で使う。
⚠ 旧ファイルの `paths.fceux` / `paths.dq3_rom` は DQ3 用なので取り込まない（★それまで DQ2 に効いていなかった値）。
⚠ DQ3 の読み方（`user_config.load()`）は変えない。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from retroux.core.config import dq2_user_config as D
from retroux.core.config import generate_lua
from retroux.core.config import user_config as U

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """★設定ファイルを探すフォルダ（⚠ 利用者の本物を読まない / 必ず `root=` で渡す）。"""
    return tmp_path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


LEGACY = ("paths:\n  rom: D:/roms/DQ2.nes\n  fceux: C:/Emu/fceux64.exe\n  dq3_rom: D:/roms/DQ3.nes\n"
          "emulator:\n  window_scale: 3\n")


def test_DQ2の設定ファイルがあればそれを読む(root: Path) -> None:
    _write(root / "dq2_user_config.yaml", "emulator:\n  window_scale: 4\n")
    _write(root / "user_config.yaml", LEGACY)
    cfg, warnings = D.load(root=root)
    assert cfg.emulator.window_scale == 4
    assert cfg.source == root / "dq2_user_config.yaml"
    assert warnings == []


def test_無ければ旧ファイルを読み移行を案内する(root: Path) -> None:
    _write(root / "user_config.yaml", LEGACY)
    cfg, warnings = D.load(root=root)
    assert cfg.emulator.window_scale == 3
    assert str(cfg.path("rom")).replace("\\", "/") == "D:/roms/DQ2.nes"
    assert warnings and "dq2_user_config.yaml" in warnings[0]


def test_旧ファイルのDQ3用の値は取り込まない(root: Path) -> None:
    """⚠ DQ3 のために書いた FCEUX が、DQ2 に効き始めてはいけない（★製品が独立しない）。"""
    _write(root / "user_config.yaml", LEGACY)
    cfg, _ = D.load(root=root)
    assert cfg.paths.fceux == ""
    assert cfg.paths.dq3_rom == ""


def test_旧ファイルに書き戻さない(root: Path) -> None:
    legacy = root / "user_config.yaml"
    _write(legacy, LEGACY)
    before = (legacy.read_bytes(), legacy.stat().st_mtime_ns)
    D.load(root=root)
    assert (legacy.read_bytes(), legacy.stat().st_mtime_ns) == before
    assert not (root / "dq2_user_config.yaml").exists()


def test_どちらも無ければ既定値(root: Path) -> None:
    cfg, warnings = D.load(root=root)
    assert cfg.emulator == U.UserConfig().emulator
    assert warnings == []
    assert D.source_path(root) is None


def test_ファイルを渡されたらそれを読む(root: Path) -> None:
    other = root / "elsewhere.yaml"
    _write(other, "emulator:\n  window_scale: 5\n")
    _write(root / "dq2_user_config.yaml", "emulator:\n  window_scale: 4\n")
    cfg, _ = D.load(other)
    assert cfg.emulator.window_scale == 5


def test_DQ3の読み方は変わらない(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★DQ3 は `user_config.load()` で `user_config.yaml` を読む（⚠ DQ2 のファイルを見ない）。"""
    _write(root / "dq2_user_config.yaml", "emulator:\n  window_scale: 4\n")
    _write(root / "user_config.yaml", LEGACY)
    monkeypatch.setattr(U, "USER_CONFIG_PATH", root / "user_config.yaml")
    cfg, _ = U.load(path=None)          # ★引数なし = DQ3 と同じ読み方（既定のファイル）
    assert cfg.emulator.window_scale == 3
    assert cfg.paths.fceux == "C:/Emu/fceux64.exe"


def test_Luaの上書きもDQ2の設定ファイルから(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _write(tmp_path / "dq2_user_config.yaml", "battle:\n  engine: layered\n")
    _write(tmp_path / "user_config.yaml", "battle:\n  engine: legacy2\n")
    monkeypatch.setattr(generate_lua, "PROJECT_ROOT", tmp_path)
    got = generate_lua._apply_user_overrides({"auto_input": {"engine": "legacy"}})
    assert got["auto_input"]["engine"] == "layered"
    assert "dq2_user_config.yaml で上書き" in capsys.readouterr().out


def test_DQ2の呼び出し側は専用の読み手を使う() -> None:
    """⚠ 1 か所でも元の `user_config.load()` に残ると、そこだけ DQ3 の設定を読む。"""
    from retroux import gui, record
    from retroux.tools import align_windows, dq2_savestate_backup  # noqa: F401
    from retroux.ui import main_window  # noqa: F401

    assert gui.user_config_mod is D
    assert record.user_config_mod is D
    assert align_windows.user_config_mod is D
    # ★関数の中で import している所は、元の読み手を名指ししていないことを見る
    offenders = []
    for rel in ("retroux/ui/main_window.py", "retroux/tools/dq2_savestate_backup.py",
                "retroux/tools/map_meta_setup.py", "retroux/tools/monster_art_setup.py",
                "retroux/tools/map_prune.py", "retroux/tools/tile_reset.py",
                "retroux/tools/dq2_map.py", "retroux/ui/keybinding_window.py",
                "retroux/core/config/generate_lua.py", "scripts/start-dq2.ps1"):
        text = (ROOT / rel).read_text(encoding="utf-8-sig")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if ("import user_config" in line and "dq2_user_config" not in line) or \
                    "core.config.user_config import load" in line:
                offenders.append(f"{rel}: {line.strip()}")
    assert offenders == []


def test_雛形はDQ2専用の名前で公開される() -> None:
    example = ROOT / "dq2_user_config.example.yaml"
    cfg, warnings = U.load(example)
    assert warnings == []
    assert "dq2_user_config.yaml" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    # ★公開一覧（release/public-manifest.yaml）に雛形が載っていることは test_build_runtime_dq2.py が見る
    #   （RX3-0528: public-manifest は公開しないので、公開木ではこの行が FileNotFoundError になった）



# --- ★DQ2 のログ（RX-0149 / 依頼者の判断 J3）------------------------------------


def test_DQ2のログは専用の場所(root: Path) -> None:
    cfg, _ = D.load(root=root)
    assert cfg.paths.log == "work/runtime/dq2-log/retroux.log"


def test_雛形のままのログの場所もDQ2の場所へ読み替える(root: Path) -> None:
    _write(root / "dq2_user_config.yaml", "paths:\n  log: work/retroux.log\n")
    cfg, _ = D.load(root=root)
    assert cfg.paths.log == "work/runtime/dq2-log/retroux.log"


def test_人が書いたログの場所は尊重する(root: Path) -> None:
    _write(root / "dq2_user_config.yaml", "paths:\n  log: D:/logs/dq2.log\n")
    cfg, _ = D.load(root=root)
    assert cfg.paths.log == "D:/logs/dq2.log"


def test_DQ3のログの場所は変わらない() -> None:
    """★DQ3 の控えは `user_config.load()` の `paths.log`（旧 work/retroux.log）に書く（⚠ 変えない）。"""
    assert U.PathsConfig().log == "work/retroux.log"


def test_ログを送るのはDQ2のログ(tmp_path: Path) -> None:
    from retroux.tools import dq2_log

    log = tmp_path / "dq2.log"
    log.write_text("前回\n", encoding="utf-8")
    shared = tmp_path / "retroux.log"
    shared.write_text("DQ3 の控え\n", encoding="utf-8")
    config = tmp_path / "dq2_user_config.yaml"
    _write(config, f"paths:\n  log: {log.as_posix()}\n")

    assert dq2_log.main(["rotate", "--config", str(config)]) == 0
    assert (tmp_path / "dq2.log.1").read_text(encoding="utf-8") == "前回\n"
    assert not log.exists()
    assert shared.read_text(encoding="utf-8") == "DQ3 の控え\n"


def test_起動スクリプトはDQ2のログへ書きフォルダを先に作る() -> None:
    text = (ROOT / "scripts" / "start-dq2.ps1").read_text(encoding="utf-8-sig")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert r'$script:RetroUXLogPath = Join-Path $Root "work\runtime\dq2-log\retroux.log"' in code
    assert "New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:RetroUXLogPath)" in code
    assert "-m retroux.tools.dq2_log rotate" in code
    assert "retroux.tools.session rotate-log" not in code


def test_LuaもDQ2のログへ書く() -> None:
    src = (ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua").read_text(encoding="utf-8")
    assert 'self.log_path         = self.write_root .. "/work/runtime/dq2-log/retroux.log"' in src
