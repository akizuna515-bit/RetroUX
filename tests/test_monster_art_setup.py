"""モンスターの絵の自動展開（RX-0086）。

⚠ clone しただけの環境で敵の絵が1枚も出なかった（work/ は Git 管理外なので
  ROM 由来の絵が配布されない）。起動時の自動展開の**判断**をここで固定する。
"""

from __future__ import annotations

from retroux.tools.monster_art_setup import plan


def test_絵がそろっていれば何もしない():
    assert plan(rom_exists=True, art_count=82) == "skip"
    # ★1枚でもあれば触らない（部分的に消した人の意図を上書きしない）
    assert plan(rom_exists=True, art_count=1) == "skip"


def test_ROMが無ければ展開できない():
    """⚠ 黙って skip にしない（no-rom は1行出す約束）。"""
    assert plan(rom_exists=False, art_count=0) == "no-rom"


def test_絵が無くROMがあれば初回展開():
    assert plan(rom_exists=True, art_count=0) == "install"


def test_起動スクリプトが呼んでいる():
    """⚠ 道具を作っただけで呼んでいない、をやらない（過去8回踏んだ形）。"""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "start-retroux.ps1").read_bytes().decode("utf-8")
    assert "retroux.tools.monster_art_setup" in src
