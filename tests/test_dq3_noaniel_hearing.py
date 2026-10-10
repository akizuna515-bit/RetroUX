"""ノアニール: 目覚めた後の会話を聞き込みで聞く（RX3-0210 / 2026-09-12 依頼者「210 Aで」）。

★原因（`docs/research/260912_dq3-noaniel-sleep.md`）: 眠っている間は全員「ぐうぐう‥‥。」（ROM 13:B20E / talk_id は同じ）。
⚠ heard は「一度話したか」だけだったので、眠っている間に話した 10 人が目覚めた後も済みのまま候補から外れた。
→ ★案 A: `$60B7`（Lua → state.json の story_60b7）で段階を決め、heard に段階を残す。目覚めた後は起きている時の会話だけ済み。
"""
from __future__ import annotations

from dq3.knowledge import npc_heard as H
from dq3.knowledge import story as S
from dq3.knowledge import town_service as TS
from dq3.testing import passability as P

SLEEP = "＊「ぐうぐう‥‥。"


def test_眠りの村の段階():
    assert S.phase_of(11, 0x00) == S.ASLEEP and S.phase_of(11, 0x04) == S.AWAKE
    assert S.phase_of(120, 0x04) == S.AWAKE
    assert S.phase_of(9, 0x00) is None and S.phase_of(11, None) is None, "⚠ ほかの map / 読めない時まで段階を付けた"
    assert S.is_sleep_text(SLEEP) and not S.is_sleep_text("＊「ぐうぐう‥‥。 おや？ めがさめた！")


def test_眠っている間に話した人は_目覚めた後は未会話(tmp_path):
    led = H.HeardLedger(tmp_path)
    led.record(11, 1, 129, at="t1", text=SLEEP, phase=S.ASLEEP)
    assert led.is_heard(11, 1) and led.is_heard(11, 1, S.ASLEEP)
    assert not led.is_heard(11, 1, S.AWAKE), "⚠⚠ 目覚めた後も済みのまま（★新しい台詞を聞きに行かない）"
    led.record(11, 1, 129, at="t2", text="＊「ありがとう！ めがさめた！", phase=S.AWAKE)
    assert led.is_heard(11, 1, S.AWAKE)


def test_段階の無い昔の記録_眠りの台詞だけなら未会話(tmp_path):
    """★依頼者の記録（09:26 に 10 人が「ぐうぐう」/ 段階なし）をそのまま使えること。"""
    led = H.HeardLedger(tmp_path)
    led.record(11, 2, 130, at="t", text=SLEEP)
    assert not led.is_heard(11, 2, S.AWAKE)
    led.record(11, 0, 50, at="t", text="＊「ここは どうぐやです。")
    assert led.is_heard(11, 0, S.AWAKE), "⚠ 起きている時の本文があるのに未会話にした"
    led.record(11, 3, 131, at="t")
    assert led.is_heard(11, 3, S.AWAKE), "⚠ 本文が無い記録まで未会話にした（★分からないときは済みのまま）"


def _service(tmp_path):
    table = [0x00] * 32
    table[2] = 0x80 | 0x10
    # ★3 行の広間（⚠ 1 行の廊下だと、動かない人の升を通れず 2 人目から届かない）
    tiles = [[2 if c == "#" else 8 for c in row] for row in [".......", ".......", "......."]]
    heard = H.HeardLedger(tmp_path)
    svc = TS.TownService(heard=heard, rom_maps={11: P.RomMap(11, tiles, table, 0)})
    npcs = [{"npc_id": i, "slot": 4 + i, "x": 1 + 2 * i, "y": 0, "movement": "fixed", "talk_id": 129 + i,
             "appearance_id": 20, "role": None, "role_status": None} for i in range(3)]
    svc.current_npcs = lambda *a, **k: {"map_id": 11, "time": "day", "status": "DEFAULT",
                                        "npcs": npcs, "runtime_count": 3}
    for i in range(3):
        heard.record(11, i, 129 + i, at="t", text=SLEEP)          # ★眠っている間に全員と話した（段階なし）
    svc.heard.reload = lambda: None
    return svc


def test_聞き込みの候補と数が同じ決まり(tmp_path):
    svc = _service(tmp_path)
    assert svc.unheard_reachable_npcs(11, 0, None, (0, 2)) == [], "前提: 段階を渡さなければ今までどおり済み"
    got = svc.unheard_reachable_npcs(11, 0, None, (0, 2), phase=S.AWAKE)
    assert sorted(c["npc"]["npc_id"] for c in got) == [0, 1, 2], "⚠⚠ 目覚めた後の聞き込みの候補に入らない"
    assert svc.counts(11, 0, None, phase=S.AWAKE)["heard"] == 0, "⚠ 数（もう全員 / 未完）が候補と食い違う"
    assert svc.counts(11, 0, None)["heard"] == 3


def test_画面が段階を渡す(tmp_path):
    from dq3 import action_log as AL
    from dq3.ui.town_bar import TownNavController

    class VM:
        def position(self): return (1, 11, 3, 1)
        def time_byte(self): return 0
        def npc_table_hex(self): return "00"
        def _raw(self): return {"story_60b7": 0x04}

    ctl = TownNavController(VM(), _service(tmp_path), None, clock=lambda: 0.0, action_log=AL.ActionLog(clock=lambda: 0.0))
    assert ctl._here()["phase"] == S.AWAKE, "⚠⚠ 画面が段階を読んでいない"
    assert TownNavController._phase_kw({"phase": None}) == {}, "⚠ 眠りの村でないのに段階を渡した"
