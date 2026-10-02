"""⚠⚠ skip を「件数」ではなく「理由」で見る歯止め自身の検査（D-35 / RX3-0475）。

```text
★守りたいこと
  ① ⚠⚠ 起きてはいけない理由で飛んだら**赤にする**（★`SKIP_MUST_NOT`）
  ② ⚠ 素材が無いだけの skip は赤にしない（★鳴りすぎも壊れ方 / RX3-0193）
  ③ ★許可の項目には**理由と WI 番号**が付いている（⚠ 素の文字列を置かない）
```

⚠ `_skipped_reasons` は**本物の走行の器**です。★この検査では `monkeypatch` で
差し替えます（⚠ 直に足すと、この走行そのものが赤くなります）。
"""
from __future__ import annotations

import conftest
import pytest


# --- ★理由の取り出し -----------------------------------------------------

class _Report:
    def __init__(self, nodeid, longrepr, skipped=True, when="call"):
        self.nodeid, self.longrepr, self.skipped = nodeid, longrepr, skipped
        self.when = when


def test_理由をlongreprから取り出せる():
    got = conftest._skip_reason(_Report("t.py::a", ("t.py", 12, "Skipped: ROM が読めません")))
    assert got == "ROM が読めません"


def test_Skipped接頭辞が無くても取り出せる():
    """⚠ pytest の版で形が変わっても、★理由の文字が残ること。"""
    assert conftest._skip_reason(_Report("t.py::a", ("t.py", 3, "採取データが無い"))) \
        == "採取データが無い"


def test_longreprが文字列でも落ちない():
    assert conftest._skip_reason(_Report("t.py::a", "Skipped: ない")) == "ない"


def test_longreprがNoneでも落ちない():
    assert conftest._skip_reason(_Report("t.py::a", None)) == ""


# --- ⚠ 何を skip として数えるか -------------------------------------------

def test_xfailは理由に混ぜない(monkeypatch):
    """⚠⚠ `xfail` も `report.skipped` で来ます（★2026-09-29 に実測）。

    ★混ぜると、理由の一覧に **assert の本文**が並びます（⚠ 理由で管理できない）。
    """
    box: dict = {}
    monkeypatch.setattr(conftest, "_skipped_reasons", box)

    skip = _Report("t.py::skip", ("t.py", 1, "Skipped: 採取データが無い"))
    xfail = _Report("t.py::xfail", "assert 1 == 2\nE   AssertionError")
    xfail.wasxfail = ""                       # ★pytest が xfail に付ける印

    conftest.pytest_runtest_logreport(skip)
    conftest.pytest_runtest_logreport(xfail)

    assert list(box) == [("t.py::skip", "採取データが無い")], box


def test_飛んでいないものは数えない(monkeypatch):
    box: dict = {}
    monkeypatch.setattr(conftest, "_skipped_reasons", box)
    conftest.pytest_runtest_logreport(_Report("t.py::ok", None, skipped=False))
    assert box == {}


# --- ⚠⚠ 鳴ること -------------------------------------------------------

def test_起きてはいけない理由なら赤にする(monkeypatch):
    """⚠⚠ これが鳴らなければ、★`RX3-0474` は次も 10 日気づけません。"""
    monkeypatch.setattr(conftest, "_skipped_reasons",
                        {("tests/test_dq3_reachable.py::x", "ROM が読めません"): 1})
    monkeypatch.setattr(conftest, "SKIP_MUST_NOT",
                        (("ROM が読めません", "RX3-0474", "★理由", lambda: True),))
    got = conftest._skip_violations()
    assert len(got) == 1, got
    nodeid, reason, wi, _why, count = got[0]
    assert nodeid.endswith("::x") and reason == "ROM が読めません"
    assert wi == "RX3-0474" and count == 1


def test_理由の一部でも当たる(monkeypatch):
    """★実際の理由には番地や枚数が付く（⚠ 完全一致では当たらない）。"""
    monkeypatch.setattr(conftest, "_skipped_reasons",
                        {("t.py::x", "⚠ ROM が読めません（★work/rom/DQ3_J.nes）"): 1})
    monkeypatch.setattr(conftest, "SKIP_MUST_NOT",
                        (("ROM が読めません", "RX3-0474", "★理由", lambda: True),))
    assert len(conftest._skip_violations()) == 1


def test_複数件でも全部並べる(monkeypatch):
    monkeypatch.setattr(conftest, "_skipped_reasons",
                        {("t.py::a", "ROM が読めません"): 1,
                         ("t.py::b", "ROM が読めません"): 1,
                         ("t.py::c", "採取データが無い"): 1})
    monkeypatch.setattr(conftest, "SKIP_MUST_NOT",
                        (("ROM が読めません", "RX3-0474", "★理由", lambda: True),))
    assert len(conftest._skip_violations()) == 2


# --- ⚠ 鳴らないこと（★鳴りすぎも壊れ方）---------------------------------

def test_素材が無いだけの理由では赤にしない(monkeypatch):
    monkeypatch.setattr(conftest, "_skipped_reasons",
                        {("t.py::x", "採取データが無い"): 1,
                         ("t.py::y", "街のセーブステートが無い"): 1})
    assert conftest._skip_violations() == []


def test_条件が成り立たない環境では赤にしない(monkeypatch):
    """⚠⚠ ROM を置いていない人の走行を赤にしないこと（★`applies` が False）。"""
    monkeypatch.setattr(conftest, "_skipped_reasons",
                        {("t.py::x", "ROM が読めません"): 1})
    monkeypatch.setattr(conftest, "SKIP_MUST_NOT",
                        (("ROM が読めません", "RX3-0474", "★理由", lambda: False),))
    assert conftest._skip_violations() == []


def test_飛んだものが無ければ何も言わない(monkeypatch):
    monkeypatch.setattr(conftest, "_skipped_reasons", {})
    assert conftest._skip_violations() == []


# --- ★許可の項目そのものの形 ---------------------------------------------

def test_項目には理由とWI番号が付いている():
    """⚠ 素の文字列だけの項目を置かないこと（★`docs/90-retrospective.md` の作法）。"""
    assert conftest.SKIP_MUST_NOT, "⚠ 空なら歯止めは何もしていない"
    for want, wi, why, applies in conftest.SKIP_MUST_NOT:
        assert want and isinstance(want, str)
        assert wi.startswith("RX"), "⚠ WI 番号が無い: %r" % (wi,)
        assert len(why) > 20, "⚠ 理由が短すぎる: %r" % (why,)
        assert callable(applies), "⚠ いつ見るかの条件が無い: %r" % (want,)


def test_条件判定はrom_namesのmemoを経由しない(monkeypatch):
    """⚠⚠ 2026-09-29 に**実際に空振りさせた**形（★歯止めの空振りは気づけません）。

    ★条件を `rom_names.place_maps()` で見ていたので、⚠ memo が汚れると
      「読めない環境」と判定され、**汚れているときに限って鳴らない**歯止めでした。
    """
    from dq3.knowledge import rom_names as RN

    if not conftest._dq3_rom_is_readable():
        pytest.skip("ROM を置いていない環境なので確かめられない")
    monkeypatch.setattr(RN, "_points_tried", True)
    monkeypatch.setattr(RN, "_points", None)
    monkeypatch.setattr(RN, "_tried", True)
    monkeypatch.setattr(RN, "_cache", None)
    assert RN.place_maps() == [], "⚠ 汚せていない（★検査の前提が崩れた）"
    assert conftest._dq3_rom_is_readable() is True, \
        "⚠⚠ 条件が memo を見ている（★汚れたときだけ歯止めが消えます）"


def test_この環境では歯止めが効いている():
    """★ROM が読めるなら、⚠ 歯止めは**武装している**こと。"""
    if not conftest._dq3_rom_is_readable():
        # ⚠ ここで「ROM が読めません」と書くと自分で歯止めに当たります（★別の言い方に）
        pytest.skip("ROM を置いていない環境なので確かめられない")
    assert conftest._skip_violations() == [], \
        "⚠⚠ いまこの走行に、飛んではいけない skip があります"
