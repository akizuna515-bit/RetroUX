"""DQ2 の events.jsonl の読み書きの根を 1 つに（RX-0162）。

★Lua（書く）と Python（取り込み・世代交代・分析・退避）が、同じ `dq2_paths.events()` を正本にする。
⚠ 以前の Python は `user_config` の `paths.events` を program_root から見ていた（Lua は write_root）。
  開発機と Portable では 2 つの根が同じなので隠れていた。
★Lua が実際に書いたファイルとの突き合わせは `tests/test_log_sandbox.py` の
  `test_Pythonの読み先はLuaが実際に書いたファイル`（実 Lua）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from retroux.core import dq2_paths
from retroux.core.config import dq2_user_config
from retroux.core.config.user_config import UserConfig

ROOT = Path(__file__).resolve().parents[1]


def test_正本はwrite_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    assert dq2_paths.events() == tmp_path / "work" / "events.jsonl"
    assert dq2_paths.legacy_events() == ROOT / "work" / "events.jsonl"
    assert dq2_paths.legacy_events(tmp_path / "old") == tmp_path / "old" / "work" / "events.jsonl"


def test_Luaの書き先とPythonの読み先が同じ相対パス() -> None:
    """★Lua は `write_root .. "/" .. logging.events_path`（plugin の config.yaml）で書く。"""
    plugin = yaml.safe_load((ROOT / "retroux" / "plugins" / "dq2" / "config.yaml")
                            .read_bytes().decode("utf-8"))
    assert plugin["logging"]["events_path"] == dq2_paths.EVENTS_REL
    lua = (ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua").read_bytes().decode("utf-8")
    assert 'self.write_root .. "/" .. self.config.logging.events_path' in lua


def test_取り込みと世代交代は正本を読む() -> None:
    """★GUI と record（どちらも取り込む）と分析ツール。⚠ 設定の paths.events を見ない。"""
    for rel in ("retroux/gui.py", "retroux/record.py"):
        text = (ROOT / rel).read_bytes().decode("utf-8")
        assert 'path("events")' not in text, rel
        assert text.count("dq2_paths.events()") == 2, rel
        # ★RX-0163: 鍵は論理 ID（世代交代と取り込みの両方）。⚠ 渡さないとフォルダを動かしたとき取り込み直す
        assert text.count("stream=MAIN_STREAM") == 2, rel


def test_分析ツールの既定も正本(monkeypatch, tmp_path) -> None:
    from retroux.tools import battle_cases

    assert battle_cases.DEFAULT_EVENTS == dq2_paths.events()


def test_遊んだ記録の退避は正本を見る(monkeypatch, tmp_path) -> None:
    from retroux.tools import playdata

    write, program = tmp_path / "write" / "work", tmp_path / "program" / "work"
    monkeypatch.setattr(playdata, "WRITE_WORK", write)
    monkeypatch.setattr(playdata, "WORK", program)
    assert playdata.play_file("events.jsonl") == write / "events.jsonl"
    assert playdata.play_file("runtime/dq2-log/retroux.log") == write / "runtime/dq2-log/retroux.log"
    assert playdata.play_file("state.json") == program / "state.json"
    files = {name: path for name, path, _size in playdata.survey()["files"]}
    assert files["events.jsonl"] == write / "events.jsonl"


def test_設定でeventsを動かしても効かないと知らせる(tmp_path) -> None:
    own = tmp_path / dq2_user_config.CONFIG_NAME
    own.write_text("paths:\n  events: D:/elsewhere/events.jsonl\n", encoding="utf-8")
    _cfg, notes = dq2_user_config.load(root=tmp_path)
    assert any("paths.events" in n and "使いません" in n for n in notes), notes

    own.write_text("paths:\n  events: work/events.jsonl\n", encoding="utf-8")
    _cfg, notes = dq2_user_config.load(root=tmp_path)
    assert not any("paths.events" in n for n in notes), notes


def test_診断に正本の場所が出る(monkeypatch, tmp_path) -> None:
    from retroux.core import diagnostics

    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    info = diagnostics.collect(root=tmp_path, user_cfg=UserConfig())
    assert "events.jsonl" in info["記録（events）"]
    assert "不明" not in info["記録（events）"]
