"""Lua が書く「いまの状態」の読み取り（MVP2 Phase 2）。

★events.jsonl と役割が違う:
    events.jsonl … 起きたこと（追記・DBへ）
    state.json   … いまの値（上書き・表示用）

守りたい契約:
  1. 読めたら値が入る
  2. **書き換えの一瞬に当たっても落ちない**（前回の値を返す）
  3. まだ無いときは fresh=False（画面は「未接続」を出せる）
  4. 更新されていなければ読み直さない（0.5秒ごとの無駄を避ける）
"""

from __future__ import annotations

import json

from retroux.core.bridge.state_reader import StateReader

SAMPLE = {
    "frame": 100, "time": 1784980800, "in_battle": True, "speed": 4,
    "danger": False, "danger_reason": None, "auto_input": True,
    "force_auto": False, "manual_latched": False, "caution": False,
    "party": [
        {"name": "samaltria", "index": 1, "hp": 18, "max_hp": 65,
         "mp": 22, "max_mp": 48, "level": 16, "alive": True,
         "poisoned": True, "status": 164},
    ],
    "enemy_groups": [{"id": 6, "count": 2, "name": "Healer"}],
    "actor": "samaltria", "ai_action": "ホイミ -> samaltria",
    "ai_reason": "HPが半分未満",
}


def test_missing_file_is_not_fresh(tmp_path):
    """まだ FCEUX が動いていないだけ。**例外にしない。**"""
    state = StateReader(tmp_path / "state.json").read()
    assert state.fresh is False
    assert state.party == []


def test_reads_values(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")

    state = StateReader(path).read()

    assert state.fresh is True
    assert state.in_battle is True
    assert state.speed == 4
    assert state.actor == "samaltria"
    m = state.party[0]
    assert (m.hp, m.max_hp, m.mp) == (18, 65, 22)
    assert m.poisoned is True
    assert round(m.hp_ratio, 3) == round(18 / 65, 3)
    assert state.enemy_groups[0].name == "Healer"


def test_broken_json_keeps_previous(tmp_path):
    """★書き換えの一瞬に当たることがある。前回の値を返して静かに待つ。

    ここで例外を投げると、**正常な運用中に画面が落ちる**。
    """
    path = tmp_path / "state.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    reader = StateReader(path)
    first = reader.read()
    assert first.fresh is True

    path.write_text('{"frame": 12, "party": [', encoding="utf-8")  # 書きかけ
    second = reader.read()

    assert second.fresh is True          # 前回の値
    assert second.frame == first.frame


def test_no_reread_when_unchanged(tmp_path, monkeypatch):
    """更新されていなければ JSON を読み直さない（0.5秒ごとの無駄を省く）。"""
    path = tmp_path / "state.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    reader = StateReader(path)
    reader.read()

    calls = []
    original = type(path).read_text

    def counting(self, *a, **kw):
        calls.append(1)
        return original(self, *a, **kw)

    monkeypatch.setattr(type(path), "read_text", counting)
    reader.read()
    reader.read()
    assert calls == []                   # 一度も読み直していない


def test_hp_ratio_without_max(tmp_path):
    """最大HPが0でもゼロ除算しない（未加入の残留値を掴んだ場合など）。"""
    path = tmp_path / "state.json"
    data = dict(SAMPLE)
    data["party"] = [{"name": "x", "hp": 0, "max_hp": 0, "mp": 0, "max_mp": 0}]
    path.write_text(json.dumps(data), encoding="utf-8")

    m = StateReader(path).read().party[0]
    assert m.hp_ratio == 0.0
    assert m.mp_ratio == 0.0


# --- 敵の個体HP（2026-07-26 に特定 / MVP2 Phase 2）--------------------


def test_enemy_instances(tmp_path):
    """敵は**個体ごと**に読める。同じ名前が複数いても別々に扱う。"""
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "in_battle": True,
        "enemies": [
            {"index": 0, "id": 6, "name": "Healer", "hp": 26,
             "hp_start": 55, "status": 0},
            {"index": 1, "id": 6, "name": "Healer", "hp": 52,
             "hp_start": 52, "status": 0},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    state = StateReader(path).read()

    assert [e.hp for e in state.enemies] == [26, 52]
    assert round(state.enemies[0].hp_ratio, 2) == 0.47
    assert state.enemies[1].hp_ratio == 1.0


def test_enemy_ratio_uses_battle_start_hp(tmp_path):
    """★分母は**戦闘開始時のHP**であって最大HPではない。

    DQ2 の敵HPは最大HPの75〜100%でばらつき、最大HPは RAM に無い
    （ROM のステータス表にしかない）。推測の最大値を分母にすると、
    画面の割合が実際と食い違う。
    """
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "enemies": [{"index": 0, "id": 1, "name": "Slime",
                     "hp": 3, "hp_start": 6}],
    }), encoding="utf-8")

    e = StateReader(path).read().enemies[0]
    assert e.hp_ratio == 0.5          # 3/6。最大HP(8など)では割らない


def test_enemy_without_start_does_not_divide_by_zero(tmp_path):
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "enemies": [{"index": 0, "id": 1, "hp": 0, "hp_start": 0}],
    }), encoding="utf-8")

    assert StateReader(path).read().enemies[0].hp_ratio == 0.0


def test_enemy_uses_rom_max_hp_when_available(tmp_path):
    """★分母は**種族の最大HP**（ROM 由来）を優先する。

    DQ2 の敵は最大HPの75〜100%で出てくる。戦闘開始時のHPを 100% に
    見せると、実際は8割しかない敵が満タンに見える。
    """
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "enemies": [{"index": 0, "id": 0x33, "name": "Hibabango",
                     "hp": 48, "hp_start": 48, "max_hp": 60}],
    }), encoding="utf-8")

    e = StateReader(path).read().enemies[0]
    assert e.hp_denominator == 60
    assert e.hp_ratio == 0.8          # 48/60。48/48=1.0 にしない


def test_enemy_falls_back_to_start_hp(tmp_path):
    """表に無い敵は、戦闘開始時のHPで割る（分母が無いよりまし）。"""
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "enemies": [{"index": 0, "id": 999, "hp": 5, "hp_start": 10}],
    }), encoding="utf-8")

    e = StateReader(path).read().enemies[0]
    assert e.max_hp is None
    assert e.hp_denominator == 10
    assert e.hp_ratio == 0.5


def test_missing_exp_is_none_not_zero(tmp_path):
    """★「届いていない」と「0」を混ぜない。

    エミュレータ側が古いと exp が state.json に無い。0 として扱うと
    LV20 のキャラが「経験値 0 = 最大レベル」に見える（実際に画面でそうなった）。
    """
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "party": [{"name": "lorasia", "level": 20, "hp": 95, "max_hp": 95}],
    }), encoding="utf-8")

    m = StateReader(path).read().party[0]
    assert m.exp is None
    assert m.next_level is None


def test_exp_and_next_level(tmp_path):
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "party": [{"name": "lorasia", "level": 19, "exp": 33000,
                   "next_level": 20, "exp_to_next": 7000}],
    }), encoding="utf-8")

    m = StateReader(path).read().party[0]
    assert (m.exp, m.next_level, m.exp_to_next) == (33000, 20, 7000)


def test_exp_zero_is_kept(tmp_path):
    """本当に 0 のとき（冒険の最初）は 0 として届く。"""
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "party": [{"name": "lorasia", "level": 1, "exp": 0,
                   "next_level": 2, "exp_to_next": 12}],
    }), encoding="utf-8")

    m = StateReader(path).read().party[0]
    assert m.exp == 0            # None ではない
