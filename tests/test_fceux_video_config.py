"""起動時 config で画面フィルタを決める（RX-0108 / 2026-08-26）。

★★ 依頼者の決定

> 「固定10種をベースに起動時 config から持ってくる感じにしたい」

⚠⚠ **同梱の `tools/fceux/fceux.cfg` を書き換えないこと**が要。
CLAUDE.md により `tools/` は書き込み禁止で、★`-cfg` で回避できる（実測で確認）。

⚠ フィルタの**見え方**はここでは見られない。DirectDraw の描画は GDI に出ないので、
`PrintWindow` も画面ごとの `BitBlt` も真っ黒になった（★実測）。
→ 見比べは人の目（`RX-0108` の User verification）。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = (ROOT / "research" / "experiments" / "fceux-speed"
          / "fceux_video_config.py")
BUNDLED = ROOT / "tools" / "fceux" / "fceux.cfg"


@pytest.fixture(scope="module")
def vc():
    if not MODULE.exists():
        pytest.skip("PoC が無い: %s" % MODULE)
    spec = importlib.util.spec_from_file_location("fceux_video_config", MODULE)
    mod = importlib.util.module_from_spec(spec)
    # ⚠ dataclass は `sys.modules` に居ないと壊れる（★実測で踏んだ）
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_10種そろっている(vc):
    """★`src/drivers/win/video.cpp` v2.6.6 の並びと同じであること。"""
    assert len(vc.DISPLAY) == 10
    assert vc.DISPLAY[0] == "<none>"
    assert vc.DISPLAY[3] == "NTSC 2x"
    assert vc.DISPLAY[9] == "PAL 3x"


@pytest.mark.parametrize(("written", "number"), [
    ("NTSC 2x", 3), ("ntsc2x", 3), ("NTSC_2X", 3), ("ntsc-2x", 3),
    ("hq2x", 1), ("Prescale4x", 8), ("<none>", 0), ("none", 0),
])
def test_書き方が揺れても同じ番号になる(vc, written, number):
    """⚠ 人が書く綴りは揺れる。★揺れで黙って別のものにならない。"""
    assert vc.filter_number(written) == number


def test_知らない名前はエラーにする(vc):
    """⚠⚠ 黙って 0（無効）に落とすと、「設定したのに効かない」が静かに起きる。"""
    with pytest.raises(vc.VideoConfigError) as e:
        vc.filter_number("crt-royale")
    assert "使えるのは" in str(e.value), "★使える名前を出していない"


def test_範囲外の番号もエラーにする(vc):
    with pytest.raises(vc.VideoConfigError):
        vc.filter_number(10)


def test_元の設定を書き換えない(vc, tmp_path):
    """★★ ここが一番大事。⚠ `tools/` は書き込み禁止。"""
    if not BUNDLED.exists():
        pytest.skip("同梱 cfg が無い")
    before = BUNDLED.read_bytes()
    out = tmp_path / "retroux.cfg"
    vc.build_config(BUNDLED, out, vc.VideoSettings(filter_name="NTSC 2x"))
    assert BUNDLED.read_bytes() == before, "⚠⚠ 同梱 cfg を書き換えてしまった"
    assert out.exists()


def test_値がちゃんと入る(vc, tmp_path):
    if not BUNDLED.exists():
        pytest.skip("同梱 cfg が無い")
    out = tmp_path / "retroux.cfg"
    vc.build_config(BUNDLED, out,
                    vc.VideoSettings(filter_name="hq3x", ntsc_colour=True))
    text = out.read_text(encoding="utf-8")
    assert "winspecial 4" in text
    assert "ntsccol_enable 1" in text


def test_行が無くても足す(vc, tmp_path):
    """⚠ 元の cfg にその行が無いこともある。★黙って諦めない。"""
    base = tmp_path / "bare.cfg"
    base.write_text("!version 1\nsound 1\n", encoding="utf-8")
    out = tmp_path / "out.cfg"
    vc.build_config(base, out, vc.VideoSettings(filter_name="Scale2x"))
    text = out.read_text(encoding="utf-8")
    assert "winspecial 2" in text
    assert "sound 1" in text, "⚠ 元の内容が消えている"


def test_起動の引数にcfgが入る(vc, tmp_path):
    """⚠ `-cfg` を渡し忘れると、★同梱 cfg が使われて（書き換えられて）しまう。"""
    args = vc.launch_args(pathlib.Path("fceux64.exe"),
                          tmp_path / "retroux.cfg",
                          pathlib.Path("rom.nes"))
    assert "-cfg" in args
    assert args.index("-cfg") + 1 < len(args)
    assert args[args.index("-cfg") + 1].endswith("retroux.cfg")


def test_設定は人が読む名前で持つ(vc):
    """⚠ FCEUX の番号を設定ファイルに書かせない。★意味が読めなくなる。"""
    s = vc.VideoSettings(filter_name="NTSC 2x")
    assert s.filter_name == "NTSC 2x"
    assert s.winspecial == 3
