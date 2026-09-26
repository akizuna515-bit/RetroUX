"""検査は Lua の読む本物の生成物を書かない（RX3-0215 / 2026-09-12）。

⚠⚠ 全件検査の最中に、本物の `work/generated/dq3_enemy_book.lua` が `defeated = {}` で上書きされ、
依頼者のオートターボが「初見の敵」で断り続けた（save5）。★`conftest.py` の `_本物の生成物を書かない` が
書き先を一時フォルダへ向ける。ここは**その口が本当に効いているか**を見る。
"""
from __future__ import annotations

from dq3 import paths as P3
from dq3.battle_ai import generate as G
from dq3.phase0 import battle_auto_overlay as BA
from dq3.phase0 import enemy_book_overlay as EO
from dq3.phase0 import mantan_settings as MS

#: ★**本物**の生成物（⚠ `P3.work` は検査中は一時フォルダに逃げている / RX-0141）
REAL = P3.repo("work", "generated")


def _outside_real(path) -> bool:
    return REAL.resolve() not in path.resolve().parents


def test_書き先の既定は一時フォルダ():
    for path in (EO.overlay_path(), BA.overlay_path(), MS.overlay_path(), G.OUT_DIR / "dq3_ai.lua"):
        assert _outside_real(path), "⚠⚠ 検査が本物の生成物を書く: %s" % path


def test_書いても本物は変わらない():
    real = REAL / EO.OVERLAY_NAME
    before = real.read_bytes() if real.exists() else None

    class Book:
        defeated = ()
        met = (0,)

    got = EO.write_overlay(Book())
    assert _outside_real(got) and got.exists()
    assert "defeated = {}" in got.read_text(encoding="utf-8")
    assert (real.read_bytes() if real.exists() else None) == before, "⚠⚠ 本物の倒した敵の記録を上書きした"


def test_戦闘AIの生成も一時フォルダ():
    real = REAL / ("%s.lua" % G.MODULE)
    before = real.read_bytes() if real.exists() else None
    got = G.write({"ok": False, "strategy": "economy"})
    assert _outside_real(got), "⚠⚠ 検査が本物の dq3_ai.lua を書いた（★遊んでいる人の作戦が変わる）"
    # ★画面の窓が呼ぶ入口（⚠ 既定の引数が定義した時に固まっていると、向け直しが効かない）
    from dq3.battle_ai import settings as S

    G.regenerate(S.BattleAiSettings(), [])
    assert (G.OUT_DIR / real.name).exists()
    assert (real.read_bytes() if real.exists() else None) == before, "⚠⚠ regenerate が本物を書いた"
