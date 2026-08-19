"""対応していない ROM と、× ボタンでの終了（RX-0057 / RX-0058）。

★どちらも公開前チェックリスト §1 の項目で、⚠ **実装が足りていなかった**。

## ⚠⚠ RX-0057: 対応していない ROM を黙って受け入れていた

`memory_map.yaml` に期待するハッシュが書いてあるのに、
★どこも照合していなかった。⚠ iNES ヘッダさえあれば起動した。

    ・パーティ状態に**でたらめな数値**が出る（★エラーは出ない）
    ・⚠ AUTO と倍速が**見当違いのタイミングでキーを押す**

## ⚠⚠ RX-0058: × ボタンでは FCEUX が残っていた

    「終了」ボタン … ★FCEUX も止まる
    ⚠ × ボタン    … ⚠ **止まらない**（子窓を閉じるだけ）

★後始末が `_shutdown()` の中にしか無かった。
→ ⚠ **すべての終了経路が通る `closeEvent`** へ移した。
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from retroux.core import rom as rom_mod  # noqa: E402

MEMORY_MAP = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml"
ROM_PATH = pathlib.Path(
    os.environ.get("DQ2_ROM_PATH") or "work/rom/DQ2_J.nes")
needs_rom = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"ROM がありません（{ROM_PATH}）")


def _expected() -> dict:
    return yaml.safe_load(MEMORY_MAP.read_text(encoding="utf-8"))["rom"]


# --- ★ RX-0057: ROM の照合 ---------------------------------------------

def test_期待するハッシュが設定に書いてある():
    """⚠ これが無いと照合しようがない（★照合の前提）。"""
    got = _expected().get("prg_sha256")
    assert got and len(got) == 64, got


@needs_rom
def test_本物のROMは通る():
    info = rom_mod.identify(ROM_PATH)
    rom_mod.check_expected(info, _expected())      # ★例外が出なければ合格


@needs_rom
def test_違うROMは止まる():
    """★★★ ⚠⚠ **ここが「黙って壊れる」の正体** ★★★"""
    info = rom_mod.identify(ROM_PATH)
    with pytest.raises(rom_mod.WrongRomError) as got:
        rom_mod.check_expected(info, {"prg_sha256": "0" * 64,
                                      "title": "にせもの"})
    text = str(got.value)
    # ⚠ 何を置いたか・何を求めているかが分かること（★「違います」だけでは直せない）
    assert "にせもの" in text, text
    assert info.path.name in text, text
    assert info.prg_sha256[:16] in text, text


@needs_rom
def test_期待値が無ければ確かめない():
    """⚠ 他のゲームを足したとき、ハッシュ未記入で起動できなくならないこと。"""
    info = rom_mod.identify(ROM_PATH)
    rom_mod.check_expected(info, {})
    rom_mod.check_expected(info, None)


def test_WrongRomErrorはInvalidRomErrorの仲間():
    """★`gui.py` の `except` が既に拾える形であること。

    ⚠ 別系統の例外にすると、起動時に**素通り**する。
    """
    assert issubclass(rom_mod.WrongRomError, rom_mod.InvalidRomError)


@needs_rom
def test_起動の道でも確かめている():
    """⚠⚠ **関数を作っただけで呼んでいない**をやらないこと。

    ★`build_view_model` が `check_expected` を通ること。
    """
    import inspect

    from retroux import gui

    body = inspect.getsource(gui.build_view_model)
    assert "check_expected" in body, (
        "⚠ 起動の道で照合していない（★作っただけになっている）")
    # ★`identify` のあと、DB へ登録する**前**に確かめること
    assert body.index("check_expected") < body.index("register_rom"), (
        "⚠ 別 ROM を DB へ登録してから確かめている")


# --- ★ RX-0058: × ボタンでの終了 ---------------------------------------

pytest.importorskip("PySide6", reason="PySide6 が無い環境")


def test_後始末はcloseEventにある():
    """★すべての終了経路が通る場所にあること。"""
    import inspect

    from retroux.ui.main_window import MainWindow

    body = inspect.getsource(MainWindow.closeEvent)
    assert "_teardown()" in body, (
        "⚠⚠ × ボタンで閉じたとき、FCEUX が残る")


def test_終了ボタンも同じ後始末を通る():
    """⚠ 2つの道で別々に書くと、片方だけ古くなる。"""
    import inspect

    from retroux.ui.main_window import MainWindow

    body = inspect.getsource(MainWindow._shutdown)
    assert "self.close()" in body, body
    # ★後始末を二重に持っていないこと
    assert "ask_emulator_to_close" not in body, (
        "⚠ `_shutdown` が後始末を抱えたまま（★2か所になる）")


def test_後始末は1度しか動かない():
    """★ボタン → `close()` → `closeEvent` で2回通る。

    ⚠ 2回目に「閉じて」を送ると、次に起動した FCEUX を閉じかねない。
    """
    from retroux.ui.main_window import MainWindow

    class Fake:
        called = 0

        def ask_emulator_to_close(self):
            Fake.called += 1
            return True

    class Stub:
        _torn_down = False
        windows = Fake()
        _teardown = MainWindow._teardown

    stub = Stub()
    stub._teardown()
    stub._teardown()
    assert Fake.called == 1, f"★{Fake.called} 回呼ばれた（⚠ 1回であるべき）"


def test_後始末で落ちても閉じられる():
    """⚠ 後始末が失敗しても、窓は閉じられること（★閉じられないほうが困る）。"""
    from retroux.ui.main_window import MainWindow

    class Boom:
        def ask_emulator_to_close(self):
            raise RuntimeError("わざと")

    class Stub:
        _torn_down = False
        windows = Boom()
        _teardown = MainWindow._teardown

    Stub()._teardown()          # ★例外が外へ出なければ合格
