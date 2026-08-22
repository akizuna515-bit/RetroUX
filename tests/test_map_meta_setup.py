"""マップの大きさ表（maps.json）の自動生成（RX-0093）。

⚠ clone しただけの環境には work/map-data/maps.json が無く、世界地図が
  「歩いた範囲だけ」の描き方になっていた（開発環境と見え方が違う、と依頼者）。
  起動時の自動生成の**判断**をここで固定する（RX-0086 と同じ形）。
"""

from __future__ import annotations

import pathlib

from retroux.tools.map_meta_setup import find_exported, plan


def test_表があれば何もしない():
    assert plan(rom_exists=True, meta_exists=True) == "skip"
    assert plan(rom_exists=False, meta_exists=True) == "skip"


def test_ROMが無ければ作れない():
    """⚠ 黙って skip にしない（no-rom は1行出す約束）。"""
    assert plan(rom_exists=False, meta_exists=False) == "no-rom"


def test_表が無くROMがあれば初回生成():
    assert plan(rom_exists=True, meta_exists=False) == "export"


def test_exportの出力は_sha1_フォルダの下にある(tmp_path):
    """★`dq2rom maps export` は `<out>/<sha1>/maps.json` に書く。RetroUX が読むのは
    平置きの `maps.json` なので、見つけて複製する必要がある。"""
    assert find_exported(tmp_path) is None
    (tmp_path / "abc123").mkdir()
    (tmp_path / "abc123" / "maps.json").write_text("{}", encoding="utf-8")
    assert find_exported(tmp_path) == tmp_path / "abc123" / "maps.json"


def test_起動スクリプトが呼んでいる():
    """⚠ 道具を作っただけで呼んでいない、をやらない。"""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "start-retroux.ps1").read_bytes().decode("utf-8")
    assert "retroux.tools.map_meta_setup" in src
