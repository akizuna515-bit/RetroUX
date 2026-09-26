"""戦闘の状態の基盤（RX3-0166）— Python 側と、生成・fixture・既知の敵の橋渡し。

★判定の中身（Lua）は `research/probes/active/dq3_battle_speed_test.lua` が動かして見ます。
ここで見るのは:

```text
Python の段階の決め方が Lua と同じ          dq3/battle_state.py
profile → 生成物 → Lua の番地が 1 本に通る   ⚠ profile の値を誰も読まない、にしない
fixture のセーブで「戦闘中」が DQ3 自身の式  ★目で見た正解と一致（RX3-0165 §6）
倒した敵を Lua へ渡す                        dq3/phase0/enemy_book_overlay.py
高速化のあと、人が選んだ倍率を送り直す       dq3/ui/main_window.py `_note_turbo`
```
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3 import battle_state as BS

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- ★段階（⚠ Lua の `BattleState.classify` と同じ表）---------------------------

@pytest.mark.parametrize(("mode", "flags", "track", "phase", "fighting"), [
    (0x00, 0x00, 0x0F, BS.NONE, False),        # ★建物の中・預かり所・登録所
    (0x00, 0x00, 0x04, BS.NONE, False),        # ★フィールド
    (0x00, 0xDF, 0x04, BS.NONE, False),        # ⚠ $60B7 のほかの bit（物語のフラグ）
    (0x00, 0x00, 0x10, BS.ENTERING, False),    # ★遭遇して曲が変わった直後
    (0xFD, 0x20, 0x10, BS.ACTIVE, True),       # ★戦闘の本体（1 手目も 2 手目以降も）
    (0xFD, 0x20, 0x12, BS.ACTIVE, True),       # ★$62 == 9 の曲
    (0xFD, 0x20, 0x16, BS.RESULT, True),       # ★ファンファーレ
    (0xFD, 0x20, 0x04, BS.RESULT, True),       # ★結果の文（場所の曲に戻った）
    (0xFD, 0x00, 0x04, BS.EXITING, False),     # ★逃げた直後 / 出口
])
def test_段階と戦闘中はDQ3自身の式(mode, flags, track, phase, fighting):
    assert BS.classify(mode, flags, track * 2) == phase
    assert BS.classify(mode, flags, track * 2 + 1) == phase, "⚠ bit0（処理中の印）で段階が変わった"
    assert BS.is_in_battle(mode, flags) is fighting


def test_profileの番地を読む_旧い形は受けない():
    spec = BS.spec_from_profile()
    assert (spec.mode, spec.mode_battle, spec.flags, spec.flag_bit, spec.track) == (
        0x32, 0xFD, 0x60B7, 0x20, 0x06F0)
    assert spec.battle_tracks == (0x10, 0x12)
    with pytest.raises(ValueError):
        BS.spec_from_profile({"runtime": {"in_battle": {"address": "0x0062"}}})


def test_生成物にprofileの番地が載り旧いin_battleは渡さない():
    """⚠ profile に書いた値を誰も読まない、にしない（★教訓「profile に書いた値を誰も読んでいない」）。

    ★Lua が `CFG.battle_state` を読むことは `dq3_battle_speed_test.lua` の最後の節が見ています。
    """
    from dq3.phase0.generate_lua import build

    cfg = build()
    assert "in_battle" not in cfg, "⚠⚠ 旧い `$62` の番地がまだ渡っている"
    assert cfg["battle_state"] == BS.spec_from_profile().as_lua()


def test_fixtureのセーブで戦闘中はDQ3自身の式():
    """★RX3-0165 §6: 目で見た正解（戦闘 2 枚 / ほか 5 枚）と一致すること。

    ★2026-09-13: 依頼者の save2（じごくのハサミ 3 匹と戦闘中 / 画面にパーティの窓と戦闘の枠）を足した（RX3-0226）。
    """
    from dq3.testing import fixtures as FX

    # ★2026-09-20: `battle_baramos`（バラモス戦の最中 / RX3-0301）を足した。
    battle = {"battle_ai_easy_battle", "battle_ai_injured_party", "battle_hasami_sukult",
              "battle_baramos"}
    seen = 0
    for fx in FX.all_fixtures():
        if not fx.path.exists():
            continue
        got = FX.conditions_of(fx.path)
        assert got["in_battle"] is (fx.id in battle), fx.id
        seen += 1
    if seen == 0:
        pytest.skip("⚠ fixture のセーブが無い環境")
    assert seen >= 2


def test_セーブの段階はWRAMも読む(tmp_path):
    ram = bytearray(0x800)
    wram = bytearray(0x2000)
    ram[0x32], ram[0x06F0] = 0xFD, 0x10 * 2
    assert BS.of_memory(bytes(ram), bytes(wram)) == {"in_battle": False,
                                                      "battle_phase": BS.EXITING}
    wram[0xB7] = 0x20
    assert BS.of_memory(bytes(ram), bytes(wram)) == {"in_battle": True,
                                                      "battle_phase": BS.ACTIVE}


# --- ★倒した敵を Lua へ -------------------------------------------------------

class _Book:
    def __init__(self, defeated, met):
        self.defeated, self.met = set(defeated), set(met)


def test_倒した敵の番号だけを渡す(tmp_path):
    from dq3.phase0 import enemy_book_overlay as EO

    text = EO.overlay_lua(_Book({3, 0}, {0, 3, 5}))
    assert "return {defeated = {[0] = true, [3] = true}, met = {[0] = true, [3] = true, [5] = true}}" in text
    assert EO.overlay_lua(None).strip().endswith("return {defeated = {}, met = {}}")
    path = EO.write_overlay(_Book({1}, {1}), out_dir=tmp_path)
    assert path.name == "dq3_enemy_book.lua"
    raw = path.read_bytes()
    assert b"\r\n" not in raw and b"[1] = true" in raw
    assert not (tmp_path / "dq3_enemy_book.lua.tmp").exists()


def test_戦闘を覚えたら倒した敵をLuaへ渡す(tmp_path, monkeypatch):
    """⚠ 覚えただけで Lua へ渡さないと、次の戦闘でも「初見」のまま（★速くならない）。"""
    from dq3.knowledge.enemies_seen import EnemyBook
    from dq3.phase0 import enemy_book_overlay as EO
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"in_battle": False, "party": []}), encoding="utf-8")
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "knowledge.json")
    vm._enemy_names = EnemyBook(tmp_path / "enemy-names.json")
    calls = []
    monkeypatch.setattr(EO, "write_overlay", lambda book, out_dir=None: calls.append(
        sorted(book.defeated)) or tmp_path / "x.lua")
    vm._pending_battle = ([{"id": 7, "n": 2}], 100)
    monkeypatch.setattr(vm, "_total_exp", lambda: 140)
    vm._note_battle_end()
    assert calls == [[7]], "⚠⚠ 倒した敵を Lua へ渡していない: %r" % calls


# --- ★高速化のあと、人が選んだ倍率を送り直す ----------------------------------------

class _Speed:
    def __init__(self):
        self.sent = 0

    def reassert(self):
        self.sent += 1
        return True


def test_ターボが切れたら人が選んだ倍率を送り直す():
    from dq3.ui.main_window import Dq3MainWindow

    win = Dq3MainWindow.__new__(Dq3MainWindow)
    win.speed = _Speed()
    assert win._note_turbo(False) is False            # ★最初（前が分からない）
    assert win._note_turbo(True) is False             # ★ターボに入った
    assert win._note_turbo(True) is False
    assert win._note_turbo(False) is True             # ★切れた → 送り直す
    assert win.speed.sent == 1
    assert win._note_turbo(False) is False            # ⚠ 切れたままなら何度も送らない
    assert win._note_turbo(None) is False
    assert win.speed.sent == 1
