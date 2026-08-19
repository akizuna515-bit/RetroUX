"""利用者設定の分離のテスト（MVP2 Phase 1）。

守りたい契約:
  1. **ファイルが無くても起動できる**（既定値で動く）
  2. 書いた値が効く
  3. 壊れていても例外で落ちず、警告を返して既定値で動く
     → 記録が止まるより「効いていない」を伝えるほうが害が小さい
  4. **知らないキーは黙って捨てない**（設定したのに効かない、に気づけるように）
"""

from __future__ import annotations

from retroux.core.config import user_config


def test_missing_file_uses_defaults(tmp_path):
    cfg, warnings = user_config.load(tmp_path / "いない.yaml")

    assert warnings == []
    assert cfg.source is None
    assert cfg.gui.width == 1920
    assert cfg.paths.rom.endswith("DQ2_J.nes")
    assert cfg.logging.backup_count == 5


def test_values_are_applied(tmp_path):
    path = tmp_path / "user_config.yaml"
    path.write_text(
        "gui:\n"
        "  width: 1280\n"
        "  interval_ms: 250\n"
        "paths:\n"
        "  rom: my/rom.nes\n"
        "emulator:\n"
        "  align_window: true\n",
        encoding="utf-8",
    )
    cfg, warnings = user_config.load(path)

    assert warnings == []
    assert cfg.gui.width == 1280
    assert cfg.gui.interval_ms == 250
    assert cfg.paths.rom == "my/rom.nes"
    assert cfg.emulator.align_window is True
    # 書かなかった項目は既定のまま
    assert cfg.gui.height == 1080
    assert cfg.source == path


def test_gamepad_defaults(tmp_path):
    """★既定は「挿すだけ」= 有効・NES 注入 ON・DEBUG OFF（RX-0076/0078）。"""
    cfg, warnings = user_config.load(tmp_path / "いない.yaml")
    assert warnings == []
    assert cfg.gamepad.enabled is True
    assert cfg.gamepad.inject_nes_input is True
    assert cfg.gamepad.debug is False


def test_gamepad_inject_can_be_turned_off(tmp_path):
    """★★ 検証モード（RX-0078）: NES 注入だけ OFF にできる。

    ⚠ 独自機能まで消えないこと（enabled は True のまま）。★知らないキー扱いに
      ならず、警告ゼロで効くこと（section 登録漏れの回帰よけ）。
    """
    path = tmp_path / "user_config.yaml"
    path.write_text(
        "gamepad:\n"
        "  inject_nes_input: false\n"
        "  debug: true\n",
        encoding="utf-8",
    )
    cfg, warnings = user_config.load(path)
    assert warnings == []                       # ★「知らない項目」と言われない
    assert cfg.gamepad.enabled is True          # 独自機能は生きる
    assert cfg.gamepad.inject_nes_input is False
    assert cfg.gamepad.debug is True


def test_broken_yaml_falls_back_with_warning(tmp_path):
    path = tmp_path / "user_config.yaml"
    path.write_text("gui:\n  width: [壊れている\n", encoding="utf-8")

    cfg, warnings = user_config.load(path)

    assert cfg.gui.width == 1920            # 既定値で動く
    assert len(warnings) == 1
    assert "user_config.yaml" in warnings[0]


def test_unknown_keys_are_reported(tmp_path):
    """知らないキーを黙って捨てると「設定したのに効かない」に気づけない。"""
    path = tmp_path / "user_config.yaml"
    path.write_text(
        "gui:\n  widht: 1280\n"          # 綴りの間違い
        "しらない項目:\n  a: 1\n",
        encoding="utf-8",
    )
    cfg, warnings = user_config.load(path)

    assert cfg.gui.width == 1920
    assert any("gui.widht" in w for w in warnings)
    assert any("しらない項目" in w for w in warnings)


def test_path_returns_absolute(tmp_path):
    cfg, _ = user_config.load(tmp_path / "いない.yaml")
    assert cfg.path("db").is_absolute()
    assert cfg.path("db").name == "retroux.sqlite3"


def test_example_file_matches_defaults():
    """★雛形と既定値がずれると、雛形をコピーした人だけ挙動が変わる。"""
    import yaml

    from retroux.core.config.user_config import PROJECT_ROOT

    example = PROJECT_ROOT / "user_config.example.yaml"
    assert example.exists(), "雛形が無いと利用者は何を書けるか分からない"

    raw = yaml.safe_load(example.read_text(encoding="utf-8"))
    cfg, warnings = user_config.load(example)

    # 雛形に未知のキーが混ざっていない（＝説明と実装がずれていない）
    assert warnings == [], warnings
    # 代表的な値が既定と一致する
    assert cfg.gui.width == raw["gui"]["width"] == 1920
    assert cfg.logging.backup_count == raw["logging"]["backup_count"] == 5
