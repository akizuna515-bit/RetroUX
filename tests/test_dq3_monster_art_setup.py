"""モンスターの絵の初回生成（RX3-0431 / 2026-09-25）。

⚠⚠ **道具を作っただけで呼んでいない**、をやらないための検査を含みます。
★`ensure()` は前からありましたが、⚠ 誰も呼んでいなかったため、
  clone しただけの人は図鑑と戦闘画面で「絵がありません」のままでした。
"""
from __future__ import annotations

import pathlib

from dq3.knowledge import monster_art
from dq3.tools.monster_art_setup import INSTALL, NO_ROM, SKIP, main, plan

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- plan()
def test_絵がそろっていて印も合っていれば何もしない() -> None:
    assert plan(rom_exists=True, art_count=139, stamp_ok=True) == SKIP
    assert plan(rom_exists=True, art_count=1, stamp_ok=True) == SKIP


def test_絵があっても作り方が変わっていれば作り直す() -> None:
    # ⚠ ここが DQ2 版と違う所。★「1 枚でもあれば触らない」だと
    #   半分に切れた古い絵が残り続ける（RX3-0223）。
    assert plan(rom_exists=True, art_count=139, stamp_ok=False) == INSTALL


def test_ROMが無ければ作れない() -> None:
    assert plan(rom_exists=False, art_count=0, stamp_ok=False) == NO_ROM
    # ★絵が古くても、ROM が無ければ作り直せない
    assert plan(rom_exists=False, art_count=139, stamp_ok=False) == NO_ROM


def test_絵が無くROMがあれば初回に作る() -> None:
    assert plan(rom_exists=True, art_count=0, stamp_ok=False) == INSTALL


# ------------------------------------------------------------- ensure()
def test_ROMが無くても落ちない(tmp_path: pathlib.Path) -> None:
    """⚠ 公開版を入れた直後（ROM をまだ置いていない）の形。"""
    made = monster_art.ensure(art_dir=tmp_path / "art", rom_path=tmp_path / "無い.nes")
    assert made == 0
    assert monster_art.last_error  # ★黙らない
    assert "ROM" in monster_art.last_error


def test_絵が無ければ画面は絵なしとして扱う(tmp_path: pathlib.Path) -> None:
    assert monster_art.path_of(3, art_dir=tmp_path) is None
    assert monster_art.path_of(None, art_dir=tmp_path) is None


# ------------------------------------------------ ★呼んでいることの検査
def test_起動スクリプトが呼んでいる() -> None:
    """⚠⚠ 作っただけで呼び忘れる形を止める（★RX3-0431 はこれで見つかった）。"""
    src = (ROOT / "scripts" / "start-dq3.ps1").read_bytes().decode("utf-8-sig")
    assert "dq3.tools.monster_art_setup" in src


def test_起動スクリプトは絵の失敗で止めない() -> None:
    """★絵は表示だけの機能。⚠ `Fail` に繋いでいないこと。"""
    src = (ROOT / "scripts" / "start-dq3.ps1").read_bytes().decode("utf-8-sig")
    line = next(x for x in src.splitlines() if "dq3.tools.monster_art_setup" in x)
    after = src.split(line, 1)[1].splitlines()[:2]
    assert not any("Fail" in x for x in after), after


def test_入口は常に0を返す(monkeypatch, tmp_path: pathlib.Path, capsys) -> None:
    """⚠ 起動を止めないこと（★どの道でも 0）。"""
    monkeypatch.setattr(monster_art, "ART_DIR", tmp_path / "art")
    monkeypatch.setattr(monster_art, "ROM_PATH", tmp_path / "無い.nes")
    assert main() == 0
    assert "ROM" in capsys.readouterr().out
