"""使わない呪文を作戦ごとに選ぶ（RX3-0370 / 2026-09-22）。

⚠⚠ 依頼者「勇者がギガデインを使いすぎる。AI 判断は難しいので、
  **使わない呪文をモード毎に設定**するのが良い」。

★ここで守ること:

```text
⚠⚠ 「AI が使う呪文」の決まりを **2 か所に書かない**（★roles.lua から読み出す）
⚠⚠ 除外は「使わない ID」で持つ（★増えた呪文が黙って使われなくならない）
⚠  作戦をまたがない（★リソース節約の除外が最短撃破に効かない）
⚠  除外した呪文は **caps に入らない**（★下流が知らなくてよい）
```
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "input" / "Dragon Quest 3 (J).nes"
ROLES = ROOT / "dq3" / "phase0" / "ai" / "roles.lua"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が無い")


# ----------------------------------------------------------------------
# ★設定（作戦ごとの除外）
# ----------------------------------------------------------------------

def test_除外は作戦ごとに持つ():
    from dq3.battle_ai import settings as S

    v = S.BattleAiSettings()
    assert v.bans_of(S.ECONOMY) == frozenset()
    v = v.with_ban(S.ECONOMY, 17, True)
    assert v.is_banned(S.ECONOMY, 17)
    assert not v.is_banned(S.LEVELING, 17), "⚠⚠ 別の作戦にまで効いている"
    assert not v.is_banned(S.SURVIVAL, 17)


def test_除外は戻せる():
    from dq3.battle_ai import settings as S

    v = S.BattleAiSettings().with_ban(S.ECONOMY, 17, True).with_ban(S.ECONOMY, 18, True)
    assert v.bans_of(S.ECONOMY) == frozenset({17, 18})
    v = v.with_ban(S.ECONOMY, 17, False)
    assert v.bans_of(S.ECONOMY) == frozenset({18})
    v = v.without_bans(S.ECONOMY)
    assert v.bans_of(S.ECONOMY) == frozenset()
    assert v.banned == {}, "⚠ 空の節が残っている（★保存が膨らむ）"


def test_知らない作戦は作らない():
    from dq3.battle_ai import settings as S

    v = S.BattleAiSettings().with_ban("なにか", 17, True)
    assert v.banned == {}, "⚠⚠ 知らない作戦の節を作った"


def test_保存して読み直せる():
    from dq3.battle_ai import settings as S

    v = S.BattleAiSettings().with_ban(S.ECONOMY, 17, True).with_ban(S.LEVELING, 9, True)
    got = S.BattleAiSettings.from_json(v.to_json())
    assert got.bans_of(S.ECONOMY) == frozenset({17})
    assert got.bans_of(S.LEVELING) == frozenset({9})


def test_除外が無ければ欄ごと出さない():
    """★古い版に戻しても読める（⚠ 知らない欄で落ちない）。"""
    from dq3.battle_ai import settings as S

    assert "banned" not in S.BattleAiSettings().to_json()


def test_壊れた保存でも落ちない():
    from dq3.battle_ai import settings as S

    got = S.BattleAiSettings.from_json(
        {"banned": {"economy": ["x", 17], "なにか": [1], "leveling": "17"}})
    assert got.bans_of(S.ECONOMY) == frozenset({17})
    assert got.bans_of(S.LEVELING) == frozenset()


# ----------------------------------------------------------------------
# ★「AI が使う呪文」の決まりは 1 か所
# ----------------------------------------------------------------------

def test_決まりはrolesluaから読み出す():
    """⚠⚠ **写さないこと**（★2 か所に書くと、片方だけ直って画面と AI がずれる）。"""
    from dq3.battle_ai import spell_picker as SP

    rule = SP.rule()
    src = ROLES.read_text(encoding="utf-8")
    for kind in rule.support_kinds:
        assert kind in src
    assert rule.beat_effect == "beat"
    assert rule.support_kinds == frozenset({"buff", "debuff"})
    assert rule.support_effects == frozenset({"surround", "sleep"})
    # ⚠ Python 側に同じ表を持っていないこと
    py = (ROOT / "dq3" / "battle_ai" / "spell_picker.py").read_text(encoding="utf-8")
    body = py.split(chr(34) * 3, 2)[2]
    assert "debuff" not in body, "⚠⚠ 決まりを写している（★roles.lua から読むこと）"


def test_決まりが読めなければ止まる(tmp_path):
    """⚠⚠ 黙って既定値に落ちないこと（★落ちると画面と AI がずれる）。"""
    from dq3.battle_ai import spell_picker as SP

    broken = tmp_path / "broken_roles.lua"
    broken.write_text("-- ★表が無い\n", encoding="utf-8")
    with pytest.raises(ValueError):
        SP.rule(broken)


def test_AIが使わない呪文は箱に入らない():
    from dq3.battle_ai import spell_picker as SP

    rule = SP.rule()
    assert rule.bucket("field", None) is None, "⚠ ルーラのような呪文を出している"
    assert rule.bucket("attack", None) == "attack"
    assert rule.bucket("heal", None) == "heal"
    assert rule.bucket("revive", None) == "revive"
    assert rule.bucket("instant", "beat") == "instant"
    assert rule.bucket("instant", "robmagic") == "drain"
    assert rule.bucket("instant", "sleep") == "support"
    assert rule.bucket("buff", None) == "support"


@needs_rom
def test_覚えている呪文だけを出す():
    from dq3.battle_ai import spell_picker as SP
    from dq3.knowledge import spell_info as SI

    hero = {"slot": "p1", "spells": [0xFF, 0xFF, 0xFF, 0, 0, 0, 0, 0], "class_gender": 0}
    rows = SP.rows_for([hero], ROM)
    assert rows, "⚠ 1 つも出ない"
    known = set(SI.learned_for(hero, ROM))
    for r in rows:
        assert r.spell_id in known, "⚠⚠ 覚えていない呪文を出した: %s" % r.name
        assert r.who == ("p1",)
        assert r.mp >= 0 and r.name
    # ⚠ 覚えていない人だけなら空
    assert SP.rows_for([{"slot": "p1", "spells": [0] * 8, "class_gender": 0}], ROM) == []
    # ⚠ 呪文が届いていなければ空（★推測しない）
    assert SP.rows_for([{"slot": "p1"}], ROM) == []
    # ⚠⚠ AI が使わない呪文（★ルーラ・トヘロス等）を**出さない**
    field = [sid for sid in known
             if (SI.info(sid, ROM) or type("x", (), {"kind": ""})()).kind == "field"]
    shown = {r.spell_id for r in rows}
    for sid in field:
        assert sid not in shown, (
            "⚠⚠ AI が使わない呪文を出した: %s" % sid)


@needs_rom
def test_重い呪文が上に来る():
    """★依頼者が探しているのは「使いすぎる重い呪文」（⚠ ギガデイン）。"""
    from dq3.battle_ai import spell_picker as SP

    hero = {"slot": "p1", "spells": [0xFF, 0xFF, 0xFF, 0, 0, 0, 0, 0], "class_gender": 0}
    attack = [r for r in SP.rows_for([hero], ROM) if r.bucket == "attack"]
    assert len(attack) >= 2
    assert attack == sorted(attack, key=lambda r: (-r.mp, r.spell_id))


# ----------------------------------------------------------------------
# ★生成物と Lua
# ----------------------------------------------------------------------

@needs_rom
def test_生成物に作戦ごとの除外が入る():
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S

    value = S.BattleAiSettings().with_ban(S.ECONOMY, 17, True)
    data = G.build(value)
    assert data["banned"] == {S.ECONOMY: [17]}
    # ⚠ 除外が無ければ空（★生成物を膨らませない）
    assert G.build(S.BattleAiSettings())["banned"] == {}


# ⚠⚠ 「文字列がある」だけの検査は置きません。
#   ★除外が**手札に入らない**ことは足場の SB③、
#   ★**本番の道（pipeline）で効く**ことは SB⑥ が動きで見ます
#   （`research/probes/active/dq3_ai_test.lua` / `tests/test_dq3_battle_ai.py` から走る）。


# ----------------------------------------------------------------------
# ★画面（⚠ offscreen で開く）
# ----------------------------------------------------------------------

def _window(tmp_path, monkeypatch):
    """★`test_dq3_battle_ai_window` と同じ足場を使う（⚠ 偽の生成に差し替え）。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    mod = pytest.importorskip("tests.test_dq3_battle_ai_window")
    hub, cmd = mod._hub(tmp_path, monkeypatch)
    from dq3.ui.spell_ban_window import SpellBanWindow

    return SpellBanWindow(hub), hub, cmd


def test_窓は呪文が読めなくても開ける(tmp_path, monkeypatch):
    """⚠ パーティが呪文を持っていない足場でも落ちないこと。"""
    from dq3.ui import spell_ban_window as SB

    win, _hub, _cmd = _window(tmp_path, monkeypatch)
    assert win.list.count() >= 1
    assert win.list.item(0).text() == SB.EMPTY
    assert not win.all_on.isEnabled()


#: ★四角を触る検査のための作り物（⚠ 足場のパーティは呪文を持っていない）
def _fake_rows():
    from dq3.battle_ai import spell_picker as SP

    return [SP.Row(spell_id=17, name="ギガデイン", mp=30, bucket="attack", who=("p1",)),
            SP.Row(spell_id=9, name="ヒャド", mp=3, bucket="attack", who=("p4",)),
            SP.Row(spell_id=20, name="ベホイミ", mp=5, bucket="heal", who=("p3",))]


def _item_of(win, spell_id):
    from PySide6.QtCore import Qt

    for i in range(win.list.count()):
        item = win.list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == spell_id:
            return item
    raise AssertionError("⚠ 行が見つからない: %d" % spell_id)


def test_四角を外すと保存と生成が走る(tmp_path, monkeypatch):
    """⚠⚠ **四角を実際に触ること**（★`hub.update` を直に呼んでも道は確かめられない）。"""
    from PySide6.QtCore import Qt

    from dq3.battle_ai import settings as S

    win, hub, cmd = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(type(win), "rows", lambda _self: _fake_rows())
    win.strategy.setCurrentIndex(list(S.STRATEGIES).index(S.ECONOMY))
    win.refresh()
    # ★見出しの行は押せない / ⚠ 呪文の行は押せる
    assert win.list.count() == len(_fake_rows()) + 2, "⚠ 見出しが 2 つ出るはず"
    item = _item_of(win, 17)
    assert item.checkState() == Qt.CheckState.Checked, "★はじめは「使う」"
    before = len(cmd.sent)
    item.setCheckState(Qt.CheckState.Unchecked)            # ★ここが人の操作
    assert hub.value.is_banned(S.ECONOMY, 17), "⚠⚠ 四角を外しても除外されない"
    assert not hub.value.is_banned(S.ECONOMY, 9), "⚠ 別の呪文まで止めた"
    assert len(cmd.sent) == before + 1, "⚠⚠ Lua に読み直しを頼んでいない"
    assert S.load(hub.settings).is_banned(S.ECONOMY, 17), "⚠ 保存されていない"
    # ★戻せる
    item.setCheckState(Qt.CheckState.Checked)
    assert not hub.value.is_banned(S.ECONOMY, 17)


def test_作り直しの間は四角の合図を無視する(tmp_path, monkeypatch):
    """⚠⚠ `_refreshing` の歯止め（★`RX3-0353` で実際に起きた）。"""
    from dq3.battle_ai import settings as S

    win, hub, _cmd = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(type(win), "rows", lambda _self: _fake_rows())
    win.strategy.setCurrentIndex(list(S.STRATEGIES).index(S.ECONOMY))
    hub.update(hub.value.with_ban(S.ECONOMY, 17, True))
    win.refresh()
    before = len(_cmd.sent)
    win.refresh()                                          # ⚠ ここで合図が飛ぶ
    assert hub.value.bans_of(S.ECONOMY) == frozenset({17}), (
        "⚠⚠ 作り直しの合図で設定が書き換わった")
    assert len(_cmd.sent) == before, (
        "⚠⚠ 作り直すたびに Lua へ頂みに行っている"
        "（★%d 回）" % (len(_cmd.sent) - before))


def test_見出しは押せない(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    win, _hub, _cmd = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(type(win), "rows", lambda _self: _fake_rows())
    win.refresh()
    heads = [win.list.item(i) for i in range(win.list.count())
             if win.list.item(i).data(Qt.ItemDataRole.UserRole) is None]
    assert len(heads) == 2
    for item in heads:
        assert not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable), (
            "⚠ 見出しに四角が出ている: %s" % item.text())


def test_全部使うで戻る(tmp_path, monkeypatch):
    from dq3.battle_ai import settings as S

    win, hub, _cmd = _window(tmp_path, monkeypatch)
    win.strategy.setCurrentIndex(list(S.STRATEGIES).index(S.ECONOMY))
    hub.update(hub.value.with_ban(S.ECONOMY, 17, True))
    win._use_all()
    assert hub.value.bans_of(S.ECONOMY) == frozenset()


def test_作戦を切り替えると表示も変わる(tmp_path, monkeypatch):
    from dq3.battle_ai import settings as S

    win, hub, _cmd = _window(tmp_path, monkeypatch)
    hub.update(hub.value.with_ban(S.ECONOMY, 17, True))
    win.strategy.setCurrentIndex(list(S.STRATEGIES).index(S.ECONOMY))
    assert win.current_strategy() == S.ECONOMY
    win.strategy.setCurrentIndex(list(S.STRATEGIES).index(S.LEVELING))
    assert win.current_strategy() == S.LEVELING
    assert not hub.value.bans_of(S.LEVELING), "⚠⚠ 作戦をまたいでいる"


def test_設定窓から開ける(tmp_path, monkeypatch):
    """⚠ 2 つ開かないこと（★管理画面と同じ開き方）。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    mod = pytest.importorskip("tests.test_dq3_battle_ai_window")
    hub, _cmd = mod._hub(tmp_path, monkeypatch)
    from dq3.ui.battle_ai_window import BattleAiWindow

    win = BattleAiWindow(hub)
    assert win.spell_button.text() == "選ぶ…"
    win.open_spell_window()
    first = win._spell_window
    win.open_spell_window()
    assert win._spell_window is first, "⚠⚠ 窓を 2 つ作った"


def test_設定窓に件数が出る(tmp_path, monkeypatch):
    """★「何件を使わない設定か」が一目で分かること。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    mod = pytest.importorskip("tests.test_dq3_battle_ai_window")
    from dq3.battle_ai import settings as S

    hub, _cmd = mod._hub(tmp_path, monkeypatch)
    from dq3.ui.battle_ai_window import BattleAiWindow

    win = BattleAiWindow(hub)
    assert "全部使います" in win.spell_summary.text()
    hub.update(hub.value.with_strategy(S.ECONOMY).with_ban(S.ECONOMY, 17, True))
    win.refresh()
    assert "1 件" in win.spell_summary.text()
    assert S.STRATEGY_LABELS[S.ECONOMY] in win.spell_summary.text()
