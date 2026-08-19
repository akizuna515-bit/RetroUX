"""ROM 地図の設定（2026-08-03 / Phase 5）。

★★ **何があっても既定へ落ちること**を固定します。
⚠ ここで例外が出ると GUI が起動できません。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import settings as S

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"


def test_既定はいまの実際の挙動と同じ():
    """★★ **勝手に切り替わりません。**

    ⚠⚠ **2026-08-12 に既定を `observed` から `rom_master` へ変えました**
      （監査 P0-A）。ここは「安全側へ倒した」のではなく、
      ★**実際の挙動に合わせた**ものです。

    この設定は 2026-08-03 に書かれてから 2026-08-12 まで
    **どこからも呼ばれていませんでした**。その間に地図は ROM 描画へ
    変わり（README 2026-08-09 / 08-11）、⚠ 既定の `observed` だけが
    取り残されていました。★配線するときに `observed` のままにすると、
    「設定を繋いだら地図の絵が消えた」ことになります。
    """
    got = S.load({})
    assert got.renderer == S.RENDERER_ROM_MASTER
    assert got.uses_rom_master


def test_既定は歩いたマスだけ():
    """★指示書 §2.2。⚠ 全部見せるのは検証用です。"""
    assert S.load({}).reveal_mode == S.REVEAL_EXPLORED
    assert not S.load({}).reveals_everything


def test_既定では分からない物を出さない():
    assert S.load({}).show_unknown_objects is False


@pytest.mark.parametrize("config", [
    None, {}, {"map": None}, {"map": {}}, {"map": {"rom_master": None}},
    {"map": {"rom_master": "ちがう"}}, {"map": {"rom_master": []}},
    "まったく違うもの", 42,
])
def test_設定が壊れていても落ちない(config):
    """⚠⚠ **GUI が起動できなくなるのが一番困ります。**"""
    got = S.load(config)
    # ⚠ 2026-08-12: 既定は `rom_master`（＝いまの実際の挙動）。
    #   ★「壊れていても落ちない」ことが要点で、値そのものではありません。
    assert got.renderer == S.RENDERER_ROM_MASTER
    assert got.reveal_mode == S.REVEAL_EXPLORED


def test_知らない値は既定へ落として理由を残す():
    """⚠ 黙って直しません。★何を直したか言います。"""
    got = S.load({"map": {"rom_master": {"renderer": "まほう",
                                         "reveal_mode": "ぜんぶ"}}})
    assert got.renderer == S.RENDERER_ROM_MASTER
    assert got.reveal_mode == S.REVEAL_EXPLORED
    assert len(got.notes) == 2
    assert all("⚠" in n for n in got.notes)


def test_真偽値でない値も直して理由を残す():
    got = S.load({"map": {"rom_master": {"show_dynamic_objects": "はい"}}})
    assert got.show_dynamic_objects is True
    assert got.notes


def test_正しく指定すればそのまま使う():
    got = S.load({"map": {"rom_master": {
        "renderer": "rom_master", "reveal_mode": "all",
        "show_dynamic_objects": False, "show_unknown_objects": True,
        "show_regions": True}}})
    assert got.uses_rom_master
    assert got.reveals_everything
    assert got.show_dynamic_objects is False
    assert got.show_unknown_objects is True
    assert got.show_regions is True
    assert got.notes == (), "★正しい設定では直す点が無いはず"


def test_要約が出る():
    assert "ROM の地図" in S.load({}).summary()
    assert "歩いたマスだけ" in S.load({}).summary()
    old = S.load({"map": {"rom_master": {"renderer": "observed"}}})
    assert "現行表示" in old.summary()
    rom = S.load({"map": {"rom_master": {"renderer": "rom_master",
                                         "reveal_mode": "all"}}})
    assert "ROM の地図" in rom.summary()
    assert "検証用" in rom.summary()


def test_同梱の設定ファイルが読める():
    """★`config.yaml` を読んで、**直すところが無い**こと。

    ⚠⚠ 「`renderer` が `observed` であること」は**見ません**。
      2026-08-03、依頼者が動作確認のため `rom_master` にしたまま
      このテストが落ちました。★**利用者が設定を変えるのは当たり前**で、
      それをテストが縛るのは間違いです。

    ★「既定がいまの挙動と同じであること」は
      `test_既定はいまの実際の挙動と同じ` が見ています
      （設定ファイルではなく `S.load({})` で）。
    """
    import yaml

    if not CONFIG.exists():
        pytest.skip("★設定ファイルがありません")
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    got = S.load(config)
    assert got.notes == (), f"⚠ 設定に直すところがあります: {got.notes}"
    # ★書いてある値が「使える値」であること（★何であってもよい）
    assert got.renderer in S.RENDERERS
    assert got.reveal_mode in S.REVEAL_MODES


def test_Qtに依存しない():
    source = pathlib.Path(S.__file__).read_bytes().decode("utf-8")
    for banned in ("PySide6", "QtWidgets", "QtGui"):
        assert banned not in source
