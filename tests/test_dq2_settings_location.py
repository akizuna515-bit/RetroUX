"""DQ2 の利用者設定の置き場と、CWD に依らない書き先（RX-0156 / 依頼 §9・§10）。

★利用者設定（keybindings / mantan / mission）は write_root 側の `work/dq2-settings/` に書く。
⚠ 旧 `config/*.yaml` は**読むだけ**（新しい方が無いときだけ）。★書き戻さない。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from retroux.core import dq2_paths
from retroux.core import keybindings as kb
from retroux.core.mantan import repository as mantan_repo
from retroux.core.mantan.settings import MantanSettings
from retroux.core.mission import repository as mission_repo
from retroux.core.mission.settings import Mission, MissionSettings

ROOT = Path(__file__).resolve().parents[1]


# --- 置き場 -------------------------------------------------------------

def test_設定の置き場はwrite_rootのdq2_settings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    for name in dq2_paths.SETTING_NAMES:
        assert dq2_paths.setting(name) == tmp_path / "work" / "dq2-settings" / name
        assert dq2_paths.legacy_setting(name) == ROOT / "config" / name


def test_各設定の既定の書き先は新しい置き場() -> None:
    """★import の時点の write_root（conftest が一時フォルダへ逃がしている）から決まる。"""
    base = dq2_paths.settings_dir()
    assert kb.USER_PATH == base / "keybindings.yaml"
    assert mantan_repo.USER_PATH == base / "mantan.yaml"
    assert mission_repo.USER_PATH == base / "mission.yaml"
    assert kb.LEGACY_PATH == ROOT / "config" / "keybindings.yaml"
    assert mantan_repo.LEGACY_PATH == ROOT / "config" / "mantan.yaml"
    assert mission_repo.LEGACY_PATH == ROOT / "config" / "mission.yaml"


def test_読む場所の順番(tmp_path) -> None:
    new, old = tmp_path / "new.yaml", tmp_path / "old.yaml"
    assert dq2_paths.setting_to_read(new, old) == new          # ★どちらも無い → 新（書く所）
    old.write_text("x", encoding="utf-8")
    assert dq2_paths.setting_to_read(new, old) == old          # ★旧だけ → 旧を読む
    new.write_text("y", encoding="utf-8")
    assert dq2_paths.setting_to_read(new, old) == new          # ★両方 → 新


def test_旧を読んだらログに1行だけ(tmp_path, caplog) -> None:
    new, old = tmp_path / "new.yaml", tmp_path / "old.yaml"
    old.write_text("x", encoding="utf-8")
    with caplog.at_level("INFO", logger="retroux.settings"):
        for _ in range(3):
            dq2_paths.setting_to_read(new, old)
    lines = [r.getMessage() for r in caplog.records if r.name == "retroux.settings"]
    assert len(lines) == 1, lines
    # ⚠ ログに絶対パスを出さない（RX-0043）。★根の外のものは名前だけ
    assert "old.yaml" in lines[0] and "new.yaml" in lines[0]
    assert str(tmp_path) not in lines[0], lines[0]


def test_旧を読んだログは根からの相対で書く() -> None:
    """★実ログの検査（test_log_paths_and_format）が見る形。⚠ 絶対パスを出していた（RX3-0530）。"""
    old = dq2_paths.legacy_setting("mission.yaml")
    new = dq2_paths.setting("mission.yaml")
    assert dq2_paths._for_log(old) == "config/mission.yaml"
    assert dq2_paths._for_log(new) == "work/dq2-settings/mission.yaml"


# --- 旧を読み、新へ書き、旧は変えない ------------------------------------

@pytest.fixture
def places(tmp_path, monkeypatch):
    new_dir, old_dir = tmp_path / "write" / "work" / "dq2-settings", tmp_path / "program" / "config"
    old_dir.mkdir(parents=True)
    for mod, name in ((kb, "keybindings.yaml"), (mantan_repo, "mantan.yaml"),
                      (mission_repo, "mission.yaml")):
        monkeypatch.setattr(mod, "USER_PATH", new_dir / name)
        monkeypatch.setattr(mod, "LEGACY_PATH", old_dir / name)
    return new_dir, old_dir


def test_キーバインドは旧を読み新を優先する(places) -> None:
    new_dir, old_dir = places
    (old_dir / "keybindings.yaml").write_text(
        "schema_version: 1\nbindings:\n  toggle_auto:\n    keyboard: [Space]\n", encoding="utf-8")
    made = kb.load()
    assert made.used_user_file is True
    assert made.keys["toggle_auto"] == ["Space"], "旧 config/keybindings.yaml を読んでいない"

    new_dir.mkdir(parents=True)
    (new_dir / "keybindings.yaml").write_text(
        "schema_version: 1\nbindings:\n  toggle_auto:\n    keyboard: [B]\n", encoding="utf-8")
    assert kb.load().keys["toggle_auto"] == ["B"], "新しい置き場が優先されていない"


def test_まんたんは旧を読み新へ書き旧を変えない(places) -> None:
    new_dir, old_dir = places
    old = old_dir / "mantan.yaml"
    # ★比べる値は、この検査が自分で書いたもの（⚠ 利用者の設定の中身は決めつけない / RX-0063）
    wrote = {"target_hp_percent": 70}
    old.write_text(yaml.safe_dump(wrote), encoding="utf-8")
    before = old.read_bytes()

    got, problems, used = mantan_repo.load()
    assert used is True, problems
    assert got.target_hp_percent == wrote["target_hp_percent"], problems

    saved = dataclasses.replace(got, target_hp_percent=60)
    written = mantan_repo.save(saved)
    assert written == new_dir / "mantan.yaml"
    assert old.read_bytes() == before, "⚠ 旧 config/mantan.yaml を書き換えた"
    assert mantan_repo.load()[0].target_hp_percent == saved.target_hp_percent


def test_大目的は旧を読み新へ書き旧を変えない(places) -> None:
    new_dir, old_dir = places
    old = old_dir / "mission.yaml"
    old.write_text(yaml.safe_dump(MissionSettings(mission=Mission.GRINDING).to_yaml_dict()),
                   encoding="utf-8")
    before = old.read_bytes()

    got, problems = mission_repo.load()
    assert got.mission is Mission.GRINDING, problems

    ok, why = mission_repo.save(MissionSettings(mission=Mission.BOSS_MANUAL))
    assert ok, why
    assert (new_dir / "mission.yaml").is_file()
    assert old.read_bytes() == before, "⚠ 旧 config/mission.yaml を書き換えた"
    assert mission_repo.load()[0].mission is Mission.BOSS_MANUAL


def test_設定が無ければ既定で動き何も作らない(places) -> None:
    new_dir, _old = places
    assert mantan_repo.load()[2] is False
    assert mission_repo.load()[0] == MissionSettings()
    assert kb.load().used_user_file is False
    assert not new_dir.exists(), "⚠ 読んだだけで置き場を作った"


# --- CWD に依らない ------------------------------------------------------

def test_既定の書き先はCWDに依らない(tmp_path, monkeypatch) -> None:
    """⚠ 以前は `Path("work/...")` で、起動した場所の下に書いていた（RX-0156）。"""
    monkeypatch.chdir(tmp_path)
    from retroux.core.tactics import lua_bridge, profile_repository
    from retroux.ui.map.metatile_renderer import MetatileRenderer

    # ⚠ lua_bridge.DEFAULT_PATH は conftest が一時フォルダへ逃がしているので、元の決め方を見る
    assert dq2_paths.generated("tactics.lua") == ROOT / "work" / "generated" / "tactics.lua"
    assert 'DEFAULT_PATH = dq2_paths.generated("tactics.lua")' in Path(
        lua_bridge.__file__).read_bytes().decode("utf-8")
    assert profile_repository.DEFAULT_DIR == ROOT / "work" / "tactics" / "profiles"
    assert profile_repository.TacticsRepository().dir.is_absolute()
    store = MetatileRenderer().store
    root = getattr(store, "root", None) or getattr(store, "_root", None)
    assert root is not None and Path(root) == ROOT / "work" / "map-assets"
    assert dq2_paths.window_state() == dq2_paths.write_root() / "work" / "window-state.json"


def test_retrouxにCWD基準の置き場が残っていない() -> None:
    """★`Path("work/...")` / `Path("config/...")` を書くと、起動した場所次第になる。

    ⚠ 例外は `retroux/ui/window_state.py` の既定だけ（★DQ3 も使う部品なので変えない / D-42 J1。
      DQ2 の呼び手は `dq2_paths.window_state()` を渡す）。
    """
    bad = []
    for path in sorted((ROOT / "retroux").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for no, line in enumerate(path.read_bytes().decode("utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if ('Path("work/' in code or 'Path("config/' in code) and "`" not in code:
                if rel == "retroux/ui/window_state.py":
                    continue
                bad.append(f"{rel}:{no}")
    assert not bad, bad


def test_DQ2の窓の状態はresolverの置き場を使う(monkeypatch) -> None:
    """★DQ2 の呼び手が WindowState() を引数なしで作ると、CWD の work/ に書く。"""
    for rel in ("retroux/ui/main_window.py", "retroux/tools/align_windows.py"):
        text = (ROOT / rel).read_bytes().decode("utf-8")
        assert "WindowState()" not in text, rel
        assert "WindowState(dq2_paths.window_state())" in text, rel


@pytest.mark.parametrize("modname", ["monster_art_setup", "map_meta_setup"])
def test_ROMの初回展開はCWDに依らない(modname, tmp_path, monkeypatch, capsys) -> None:
    """★相対の `paths.rom` は program_root から（⚠ 以前は `Path(cfg.paths.rom)` で CWD から）。"""
    import importlib

    from retroux.core.config import dq2_user_config
    from retroux.core.config.user_config import UserConfig

    cfg = UserConfig()
    cfg.paths.rom = "work/rom/無い.nes"
    monkeypatch.setattr(dq2_user_config, "load", lambda *a, **k: (cfg, []))
    # ⚠ 本物の program_root だと、絵・マップ表がそろった環境では「ROM が無い」の文言まで
    #   辿り着かない（RX3-0530）。★空の program_root を立てて、環境の状態に依らず同じ道を通す
    program = tmp_path / "program"
    program.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(dq2_paths, "PROJECT_ROOT", program)
    monkeypatch.chdir(cwd)
    mod = importlib.import_module(f"retroux.tools.{modname}")
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert str(program / "work" / "rom" / "無い.nes") in out, out
    assert not (cwd / "work").exists(), "⚠ CWD の下に置き場を作った"

def test_gitに入らない置き場() -> None:
    """★人それぞれの設定なので共有しない（⚠ work/ は Git 管理外）。"""
    import subprocess

    got = subprocess.run(["git", "check-ignore", "-q", "work/dq2-settings/mantan.yaml"],
                         cwd=ROOT, capture_output=True)
    assert got.returncode == 0, got.stderr


def test_キーバインド設定の画面は旧を出し新へ保存する(places) -> None:
    """★Ctrl+K の画面（⚠ 以前は旧の置き場を直に読み書きしていた）。"""
    pytest.importorskip("PySide6", reason="PySide6 が無い環境")
    from PySide6.QtWidgets import QApplication

    from retroux.ui.keybinding_window import KeybindingWindow

    _app = QApplication.instance() or QApplication([])
    new_dir, old_dir = places
    old = old_dir / "keybindings.yaml"
    old.write_text("schema_version: 1\nbindings:\n  toggle_auto:\n    keyboard: [Space]\n",
                   encoding="utf-8")
    before = old.read_bytes()

    window = KeybindingWindow()
    try:
        assert window.path == new_dir / "keybindings.yaml"
        assert "[Space]" in window._editor.toPlainText(), "旧の中身を出していない"
        assert "旧の" in window._result.toPlainText()
        assert window.save_and_apply() is True
    finally:
        window.close()
    assert (new_dir / "keybindings.yaml").read_bytes().decode("utf-8").count("Space") == 1
    assert old.read_bytes() == before, "⚠ 旧 config/keybindings.yaml を書き換えた"
