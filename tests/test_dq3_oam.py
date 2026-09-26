"""OAM の写しから NPC 候補を起こす（RX3-0049 B-3）。

★入力は `dq3_oam_probe.lua` が 2026-09-02 に実機で見た形（先頭 (128,107) / 仲間が真下）。

⚠⚠ 実機のアリアハンで分かったこと（★検査に写した）:

```text
歩くと絵が変わる      同じ兵士が 2 コマで別の tile の組になる
同じ絵の NPC が 2 体   離れた場所に同じ兵士が居る
仲間 3 人            主人公を追って動く
```
"""

from __future__ import annotations

import json

from dq3.testing import oam


def _party(y0=107):
    """★主人公（⚠ 仲間は歩くと画面を動くので、ここでは先頭だけ固定）。"""
    return [[y0, 4, 0, 128], [y0, 5, 0, 136], [y0 + 8, 6, 0, 128], [y0 + 8, 7, 0, 136]]


def _char(x, y, tile=0x96):
    return [[y, tile, 0x43, x], [y, tile, 0x03, x + 8],
            [y + 8, tile + 2, 0x43, x], [y + 8, tile + 1, 0x43, x + 8]]


def _sample(frame, px, py, extra=()):
    return {"frame": frame, "kind": 1, "map_id": 9, "px": px, "py": py,
            "s": _party() + list(extra)}


def _screen_of(px, py, cx, cy):
    """★升 (cx, cy) に居るものの画面位置（⚠ 主人公 (px,py) が (128,107)）。"""
    return 128 + (cx - px) * 16, 107 + (cy - py) * 16


def test_16x16にまとめる():
    chars = oam.group_characters(_party() + _char(160, 75))
    assert len(chars) == 2 and all(c["whole"] for c in chars)
    assert chars[1]["x"] == 128 and chars[1]["y"] == 107
    assert chars[1]["tiles"] == (4, 5, 6, 7)


def test_そろわないものは1枚ずつ():
    chars = oam.group_characters([[50, 0x10, 0, 40]])
    assert len(chars) == 1 and chars[0]["whole"] is False


def test_画面に固定されたものがplayer():
    samples = [_sample(i * 15, 8 + i, 18) for i in range(10)]
    got = oam.analyze(samples)
    assert got["player"]["screen"] == [128, 107]
    assert got["npc_candidates"] == [] and got["party_followers"] == []


def test_主人公が歩かなくても止まったNPCをplayerにしない():
    """⚠⚠ 主人公が止まっていると、止まった NPC も画面に固定される。"""
    samples = [_sample(i * 15, 8, 18, _char(160, 75)) for i in range(5)]
    got = oam.analyze(samples)
    assert got["player"]["screen"] == [128, 107]
    assert len(got["npc_candidates"]) == 1


def test_止まっているNPCはstationary():
    """★主人公が動いても、NPC の**地図の升**は変わらない。"""
    samples = []
    for i in range(6):
        px = 8 + i
        sx, sy = _screen_of(px, 18, 12, 16)
        samples.append(_sample(i * 15, px, 18, _char(sx, sy)))
    got = oam.analyze(samples)
    assert len(got["npc_candidates"]) == 1
    npc = got["npc_candidates"][0]
    assert npc["kind"] == "stationary" and npc["observed"] == 6
    assert npc["cells"][0] == {"x": 12, "y": 16, "seen": 6} and npc["map_id"] == 9


def test_絵が変わっても同じ個体():
    """★歩きの 2 コマ（tile の組が違う）を**同じ NPC**と数える。"""
    samples = []
    for i in range(6):
        sx, sy = _screen_of(8, 18, 12, 16)
        tile = 0x96 if i % 2 == 0 else 0x98         # ⚠ 2 コマ
        samples.append(_sample(i * 15, 8, 18, _char(sx, sy, tile=tile)))
    got = oam.analyze(samples)
    assert len(got["npc_candidates"]) == 1, "⚠⚠ 絵ごとに別の NPC にしている"
    assert len(got["npc_candidates"][0]["appearances"]) == 2


def test_同じ絵でも離れていれば別の個体():
    """★指示書 §24-3「同一外観 NPC」: 離れた 2 体の兵士。"""
    samples = []
    for i in range(6):
        a = _char(*_screen_of(8, 18, 8, 16))
        b = _char(*_screen_of(8, 18, 5, 4))
        samples.append(_sample(i * 15, 8, 18, a + b))
    got = oam.analyze(samples)
    assert len(got["npc_candidates"]) == 2, "⚠⚠ 同じ絵の 2 体を 1 つにまとめた"
    assert all(c["kind"] == "stationary" for c in got["npc_candidates"])


def test_動くNPCはmoving():
    samples = []
    for i in range(6):
        sx, sy = _screen_of(8, 18, 12 + i, 12)      # ★1 升ずつ右へ
        samples.append(_sample(i * 15, 8, 18, _char(sx, sy)))
    got = oam.analyze(samples)
    assert len(got["npc_candidates"]) == 1
    npc = got["npc_candidates"][0]
    assert npc["kind"] == "moving" and npc["distinct_cells"] == 6


def test_仲間は主人公を追うのでNPCにしない():
    """★仲間は主人公の真後ろ（2 升以内）に**ほぼ常に**居て、一緒に動く。"""
    samples = []
    for i in range(8):
        px = 8 + i
        # ⚠ 仲間は 1〜2 升後ろを**遅れて**追う（★画面では揺れるので固定点にならない）
        lag = 1 if i % 2 == 0 else 2
        sx, sy = _screen_of(px, 18, px - lag, 18)
        samples.append(_sample(i * 15, px, 18, _char(sx, sy, tile=0x24)))
    got = oam.analyze(samples)
    assert got["party_followers"] == ["t24-24-26-25"], got["party_followers"]
    assert got["npc_candidates"] == [], "⚠⚠ 仲間を NPC と数えた"


def test_欠片は個体にしない():
    """⚠ 2x2 に揃わないスプライト（窓の飾りなど）を NPC にしない。"""
    samples = [_sample(i * 15, 8, 18, [[40, 0x10, 0, 200]]) for i in range(4)]
    got = oam.analyze(samples)
    assert got["npc_candidates"] == [] and got["fragments"] == 4


def test_同じ絵が時間をおいて別の場所に出たら別の個体():
    """★時間を見ずに升だけで繋ぐと、⚠ 300 歩ぶんの足跡が 1 つにまとまる（実機）。"""
    samples = []
    for i in range(6):
        samples.append(_sample(i * 15, 8, 18, _char(*_screen_of(8, 18, 12, 12))))
    for i in range(6):
        samples.append(_sample(1000 + i * 15, 8, 18, _char(*_screen_of(8, 18, 13, 12))))
    got = oam.analyze(samples)
    # ★同じ絵で 1 升しか離れていない → ⚠ 画面から外れて戻った**同じ個体**とみなす
    assert len(got["npc_candidates"]) == 1, "⚠ 近くに戻ってきた同じ絵を別の個体にした"
    far = [_sample(2000 + i * 15, 8, 18, _char(*_screen_of(8, 18, 20, 20))) for i in range(6)]
    got = oam.analyze(samples + far)
    assert len(got["npc_candidates"]) == 2, "⚠⚠ 離れた場所の同じ絵を 1 つに繋いだ"


def test_1回しか見えないものはunknown():
    samples = [_sample(i * 15, 8, 18) for i in range(5)]
    samples[2]["s"] += _char(200, 50, tile=0x70)
    got = oam.analyze(samples)
    assert got["npc_candidates"] == []
    assert len(got["unknown"]) == 1 and got["unknown"][0]["kind"] == "once"


def test_観測が無ければそう言う():
    got = oam.analyze([])
    assert got["samples"] == 0 and "why" in got


def test_ファイルから読んで書く(tmp_path):
    src = tmp_path / "oam.jsonl"
    rows = [_sample(i * 15, 8, 18, _char(160, 75)) for i in range(6)]
    src.write_text("\n".join(json.dumps(r) for r in rows) + "\n壊れた行\n", encoding="utf-8")
    got = oam.write_report(src, tmp_path / "npc_candidates.json")
    assert got["samples"] == 6
    body = json.loads((tmp_path / "npc_candidates.json").read_text(encoding="utf-8"))
    assert body["npc_candidates"][0]["observed"] == 6


def test_無いファイルは空():
    assert oam.load("無い.jsonl") == []
