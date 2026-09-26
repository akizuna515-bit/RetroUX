"""戦闘 AI の設定画面（RX3-0127 / RX3-0198）。★offscreen で開き、触ると 保存 → 生成 → ai_reload が起きる。"""
from __future__ import annotations

import ast
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                     # noqa: E402

pytest.importorskip("PySide6")

from dq3.battle_ai import settings as S           # noqa: E402


class _VM:
    def __init__(self, members=None):
        self.members = members if members is not None else [
            {"slot": "p1", "name": "ゆうしゃ", "attack": 30, "class_gender": 0,
             "spells": [0] * 8, "max_hp": 40},
            {"slot": "p2", "name": "せんし", "attack": 50, "class_gender": 1,
             "spells": [0] * 8, "max_hp": 50}]

    def ai_members(self):
        return list(self.members)


class _Cmd:
    def __init__(self):
        self.sent = []

    def send(self, action, **_p):
        self.sent.append(action)
        return len(self.sent)


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _hub(tmp_path, monkeypatch, vm=None):
    _app()
    from dq3.ui.battle_ai_window import AiSettingsHub
    from dq3.ui.ui_settings import UiSettings

    # ⚠ ROM が無い環境でも通す: 生成は「設定だけ」を書く偽物に差し替える
    from dq3.battle_ai import generate as G

    def fake_regenerate(value, members=None, rom_path=None, out_dir=G.OUT_DIR):
        out_dir.mkdir(parents=True, exist_ok=True)
        # ⚠⚠ 本物（`generate.build`）と**同じ規則**で書くこと。
        #   ★2026-09-20: ここが `value.mp_policy` を直に書いていたため、
        #   ⚠ 「最短撃破では MP 制約を渡さない」を偽物が見逃していました。
        data = {"ok": True, "strategy": value.strategy,
                "mp_policy": S.effective_mp(value.strategy, value.mp_policy),
                "roles": {k: v.as_list() for k, v in S.effective_roles(value, members or []).items()}}
        (out_dir / "dq3_ai.lua").write_text(repr(data), encoding="utf-8")
        return data

    monkeypatch.setattr(G, "regenerate", fake_regenerate)
    monkeypatch.setattr(S, "suggest_roles", lambda members, rom_path=None: {
        m["slot"]: S.RolePref(S.HEAL if m["slot"] == "p1" else S.PHYSICAL, S.DEFEND)
        for m in (members or []) if isinstance(m, dict)})
    cmd = _Cmd()
    hub = AiSettingsHub(vm or _VM(), cmd, UiSettings(tmp_path / "ui.json"), out_dir=tmp_path / "gen")
    return hub, cmd


def _written(tmp_path) -> dict:
    return ast.literal_eval((tmp_path / "gen" / "dq3_ai.lua").read_text(encoding="utf-8"))


def test_作戦を選ぶと保存して生成してLuaへ頼む(tmp_path, monkeypatch):
    from dq3.ui.battle_ai_window import StrategyRow
    from dq3.ui.ui_settings import UiSettings

    hub, cmd = _hub(tmp_path, monkeypatch)
    row = StrategyRow(hub)
    assert [row.picker.itemText(i) for i in range(row.picker.count())] == \
        ["最短撃破", "リソース節約", "生存優先"]
    assert row.picker.itemData(0) == S.LEVELING, "⚠ 内部の語 leveling は保つ（RX3-0198 §1）"
    row.pick(S.SURVIVAL)
    assert hub.value.strategy == S.SURVIVAL
    assert S.load(UiSettings(tmp_path / "ui.json")).strategy == S.SURVIVAL, "⚠ 保存されていない"
    assert "survival" in (tmp_path / "gen" / "dq3_ai.lua").read_text(encoding="utf-8")
    assert cmd.sent == ["ai_reload"]
    assert row.picker.currentData() == S.SURVIVAL


def test_同じ作戦を選び直しても頼まない(tmp_path, monkeypatch):
    from dq3.ui.battle_ai_window import StrategyRow

    hub, cmd = _hub(tmp_path, monkeypatch)
    row = StrategyRow(hub)
    row.pick(hub.value.strategy)
    assert cmd.sent == []


def test_窓でも作戦を選べて右画面と揃う(tmp_path, monkeypatch):
    """★RX3-0198 §7: 窓の作戦と右画面の作戦は 1 つの hub を見る（⚠ 片方だけ古いまま、にしない）。"""
    from dq3.ui.battle_ai_window import BattleAiWindow, StrategyRow

    hub, cmd = _hub(tmp_path, monkeypatch)
    row, w = StrategyRow(hub), BattleAiWindow(hub)
    assert [w.strategy_picker.itemText(i) for i in range(w.strategy_picker.count())] == \
        ["最短撃破", "リソース節約", "生存優先"]
    w._strategy_picked(S.LEVELING)
    assert row.picker.currentData() == S.LEVELING and w.strategy_picker.currentData() == S.LEVELING
    row.pick(S.SURVIVAL)
    assert w.strategy_picker.currentData() == S.SURVIVAL, "⚠⚠ 右画面で変えても窓が前の作戦のまま"
    assert w.behavior["回復"].text() == "早め", "⚠ 「この作戦では」が前の作戦のまま"
    w._strategy_picked(S.SURVIVAL)
    assert cmd.sent == ["ai_reload", "ai_reload"]


@pytest.mark.parametrize("strategy, expected", [
    # ★RX3-0327: 「速攻」→「最短撃破」。⚠ MP は「許容」ではなく**考慮しない**
    (S.LEVELING, ["手数が減るなら", "終わらせられる時は後回し", "手数が減るなら", "考慮しない",
                  "倒しやすい敵から"]),
    (S.ECONOMY, ["必要な時だけ", "やや遅め", "長引く時", "抑える", "倒しやすい敵から"]),
    (S.SURVIVAL, ["危険を減らす時", "早め", "早め", "生存のため使用", "危険な敵から"]),
])
def test_この作戦ではを常に出す(tmp_path, monkeypatch, strategy, expected):
    """★RX3-0198 §6: 作戦の意味を窓に常に出す（⚠ ツールチップだけにしない）。"""
    from PySide6.QtWidgets import QGroupBox

    from dq3.ui.battle_ai_window import BattleAiWindow

    hub, _cmd = _hub(tmp_path, monkeypatch)
    hub.update(hub.value.with_strategy(strategy))
    w = BattleAiWindow(hub)
    assert [w.behavior[k].text() for k in S.BEHAVIOR_ROWS] == expected
    assert "この作戦では" in [b.title() for b in w.findChildren(QGroupBox)]
    assert w.strategy_note.text() == S.STRATEGY_NOTES[strategy]


def test_役割の窓は提案を出し人が変えた欄だけ守る(tmp_path, monkeypatch):
    """★RX3-0198 §15: 第1 と 第2 を別々に覚える / 欄ごとに提案へ戻す。"""
    from dq3.ui.battle_ai_window import SUGGEST_TEXT, TOUCHED_TEXT, BattleAiWindow

    hub, cmd = _hub(tmp_path, monkeypatch)
    w = BattleAiWindow(hub)
    row = w.rows["p1"]
    first, second = row.combos[S.FIRST], row.combos[S.SECOND]
    assert row.name.text() == "ゆうしゃ"
    assert first.currentData() == S.HEAL and second.currentData() == S.DEFEND
    assert row.marks[S.FIRST].text() == SUGGEST_TEXT and not row.marks[S.FIRST].isEnabled()
    assert [first.itemText(i) for i in range(first.count())] == \
        ["物理攻撃", "魔法攻撃", "支援", "ヒール", "防御"]

    # ★人が p1 の第1 だけを 物理攻撃 に変える
    first.setCurrentIndex(first.findData(S.PHYSICAL))
    w._picked("p1", S.FIRST)
    assert hub.value.is_touched("p1", S.FIRST) and not hub.value.is_touched("p1", S.SECOND)
    assert row.marks[S.FIRST].text() == TOUCHED_TEXT and row.marks[S.FIRST].isEnabled()
    assert row.marks[S.SECOND].text() == SUGGEST_TEXT, "⚠ 触っていない第2 まで「人が設定」になった"
    assert "ヒール" in row.marks[S.FIRST].toolTip(), "⚠ 戻したらどうなるか（AI の提案）が見えない"
    assert cmd.sent == ["ai_reload"]

    # ★提案が変わると、触っていない第2 だけが変わる
    monkeypatch.setattr(S, "suggest_roles", lambda members, rom_path=None: {
        m["slot"]: S.RolePref(S.MAGIC, S.SUPPORT) for m in (members or [])})
    hub.regenerate()
    w.refresh()
    assert first.currentData() == S.PHYSICAL, "⚠⚠ 人が決めた第1 が提案で戻った"
    assert second.currentData() == S.SUPPORT, "⚠ 触っていない第2 が提案に付いていかない"

    # ★その欄だけ提案へ戻す
    w.revert_tier("p1", S.FIRST)
    assert hub.value.touched == () and first.currentData() == S.MAGIC
    # ★全員を提案へ戻す
    second.setCurrentIndex(second.findData(S.HEAL))
    w._picked("p1", S.SECOND)
    assert second.currentData() == S.HEAL
    w.reset_roles()
    assert hub.value.touched == () and second.currentData() == S.SUPPORT


def test_MP制約は作戦より優先の3択で保存される(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QGroupBox

    from dq3.ui.battle_ai_window import BattleAiWindow
    from dq3.ui.ui_settings import UiSettings

    hub, cmd = _hub(tmp_path, monkeypatch)
    w = BattleAiWindow(hub)
    assert "MP制約（作戦より優先）" in [b.title() for b in w.findChildren(QGroupBox)]
    assert [w.mp_buttons[p].text() for p in S.MP_POLICIES] == ["おまかせ", "半分程度残す", "使用禁止"]
    assert w.mp_buttons[S.MP_AUTO].isChecked() and w.override_note.text() == ""
    w._mp_picked(S.MP_FORBID)
    assert hub.value.mp_policy == S.MP_FORBID
    assert S.load(UiSettings(tmp_path / "ui.json")).mp_policy == S.MP_FORBID
    assert '"forbid"' in (tmp_path / "gen" / "dq3_ai.lua").read_text(encoding="utf-8").replace("'", '"')
    assert w.mp_buttons[S.MP_FORBID].isChecked()
    assert "使用禁止" in w.override_note.text(), "⚠ MP制約が作戦より優先だと見えない"


def test_最短撃破ではMP制約が押せない(tmp_path, monkeypatch):
    """★依頼者 2026-09-20 §12-2「最短撃破選択時は非活性化」。

    ⚠⚠ **保存値は残します**（★作戦を戻したら元の設定が戻る / 依頼者 §3-1）。
    """
    from dq3.ui.battle_ai_window import BattleAiWindow

    hub, _cmd = _hub(tmp_path, monkeypatch)
    hub.update(hub.value.with_strategy(S.ECONOMY).with_mp(S.MP_SAVE))
    w = BattleAiWindow(hub)
    assert all(b.isEnabled() for b in w.mp_buttons.values()), "⚠ 節約では触れるはず"

    hub.update(hub.value.with_strategy(S.LEVELING))
    assert not any(b.isEnabled() for b in w.mp_buttons.values()), "⚠⚠ 最短撃破で押せてしまう"
    assert not w.mp_box.isEnabled()
    assert w.override_note.text() == S.MP_UNUSED_NOTE
    # ★保存値は消えていない（⚠ 「半分程度残す」のまま）
    assert hub.value.mp_policy == S.MP_SAVE
    assert w.mp_buttons[S.MP_SAVE].isChecked(), "⚠ 何が選ばれていたか見えない"


def test_最短撃破ではMP制約をLuaへ渡さない(tmp_path, monkeypatch):
    """★依頼者 §3-1「ユーザー設定のMP制約は無視」。⚠ 保存は残す。"""
    hub, _cmd = _hub(tmp_path, monkeypatch)
    out = tmp_path / "gen" / "dq3_ai.lua"

    hub.update(hub.value.with_strategy(S.ECONOMY).with_mp(S.MP_FORBID))
    assert '"forbid"' in out.read_text(encoding="utf-8").replace("'", '"')

    hub.update(hub.value.with_strategy(S.LEVELING))
    text = out.read_text(encoding="utf-8").replace("'", '"')
    assert '"auto"' in text, "⚠⚠ 最短撃破なのに MP 制約が渡っている"
    assert 'mp_policy = "forbid"' not in text
    # ★戻したら元どおり（⚠ 保存値は書き換えていない）
    hub.update(hub.value.with_strategy(S.ECONOMY))
    assert '"forbid"' in out.read_text(encoding="utf-8").replace("'", '"')


def test_パーティが変わったら作り直してLuaへ(tmp_path, monkeypatch):
    """★RX3-0198 §16: 入れ替え・呪文を覚えた・攻撃力で作り直す。⚠ HP / MP だけ・空では作り直さない。"""
    from dq3.ui.battle_ai_window import BattleAiWindow

    vm = _VM()
    hub, cmd = _hub(tmp_path, monkeypatch, vm)
    hub.regenerate()                                  # ★起動時
    w = BattleAiWindow(hub)
    assert hub.sync_party() is False and cmd.sent == [], "⚠ 同じパーティで作り直した"

    vm.members = vm.members + [{"slot": "p3", "name": "まほうつかい", "attack": 10,
                                "class_gender": 4, "spells": [0] * 8, "max_hp": 20}]
    assert hub.sync_party() is True and cmd.sent == ["ai_reload"]
    assert w.rows["p3"].name.text() == "まほうつかい", "⚠ 作り直したのに窓が前のまま"
    assert _written(tmp_path)["roles"]["p3"] == ["physical", "defend"]

    vm.members = [dict(vm.members[0], hp=1, mp=0)] + vm.members[1:]
    assert hub.sync_party() is False, "⚠ HP / MP の変化で作り直した（★毎ターン作り直しになる）"
    vm.members = [dict(vm.members[0], spells=[1] + [0] * 7)] + vm.members[1:]
    assert hub.sync_party() is True, "⚠ 呪文を覚えても作り直さない"
    vm.members = []
    assert hub.sync_party() is False, "⚠ パーティが届いていない時に空で作り直した"
    assert cmd.sent == ["ai_reload", "ai_reload"]


def test_窓の役割とLuaへ渡した役割が同じ(tmp_path, monkeypatch):
    """★RX3-0198 §17: 窓は「生成に使ったパーティ」で計算する（⚠ 今のパーティで計算すると Lua とずれる）。"""
    from dq3.ui.battle_ai_window import BattleAiWindow

    vm = _VM()
    hub, _cmd = _hub(tmp_path, monkeypatch, vm)
    hub.update(hub.value.with_tier("p2", S.SECOND, S.SUPPORT))
    w = BattleAiWindow(hub)

    def shown():
        return {slot: [row.combos[t].currentData() for t in S.TIERS] for slot, row in w.rows.items()}

    assert shown() == _written(tmp_path)["roles"]
    # ★生成の後に p1 が抜けた（まだ作り直していない）→ 窓も Lua と同じ役割のまま
    vm.members = vm.members[1:]
    w.refresh()
    assert shown() == _written(tmp_path)["roles"] and shown()["p1"] == ["heal", "defend"]
    # ★作り直すと、両方そろって変わる
    assert hub.sync_party() is True
    assert shown() == _written(tmp_path)["roles"] and shown()["p1"] == ["physical", "defend"]


def test_窓は画面の名前を出す(tmp_path, monkeypatch):
    """★名前は `party_names`（まんたんの窓と同じ入口）から。⚠ state.json の party の name は `p1` のまま。"""
    from dq3.ui.battle_ai_window import BattleAiWindow

    vm = _VM([dict(m, name="p%d" % (i + 1)) for i, m in enumerate(_VM().members)])
    vm.party_names = lambda: ["アレル", "ロト"]
    hub, _cmd = _hub(tmp_path, monkeypatch, vm)
    w = BattleAiWindow(hub)
    assert [w.rows[s].name.text() for s in ("p1", "p2", "p3")] == ["アレル", "ロト", "p3"]


def test_数値の入力欄は無い(tmp_path, monkeypatch):
    """⚠⚠ 指示書 §16: 閾値を人に触らせない。"""
    from PySide6.QtWidgets import QDoubleSpinBox, QLineEdit, QSpinBox

    from dq3.ui.battle_ai_window import BattleAiWindow, StrategyRow

    hub, _cmd = _hub(tmp_path, monkeypatch)
    for widget in (BattleAiWindow(hub), StrategyRow(hub)):
        assert not widget.findChildren(QSpinBox)
        assert not widget.findChildren(QDoubleSpinBox)
        assert not widget.findChildren(QLineEdit)


def test_生成に失敗しても画面は続く(tmp_path, monkeypatch):
    from dq3.ui.battle_ai_window import BattleAiWindow

    hub, _cmd = _hub(tmp_path, monkeypatch)
    from dq3.battle_ai import generate as G

    def boom(*_a, **_k):
        raise OSError("disk")

    monkeypatch.setattr(G, "regenerate", boom)
    w = BattleAiWindow(hub)
    w._mp_picked(S.MP_SAVE)
    assert hub.value.mp_policy == S.MP_SAVE
    assert w.note.text().startswith("⚠")
    assert hub.sync_party() is False, "⚠ 失敗したパーティで毎回やり直す（★右画面が重くなる）"


def test_battle_windowはAIの行に色を付け最新の戦況を1行に出す(tmp_path):
    from dq3.ui import battle_window as BW

    assert BW.colour_of("AI turn=1 戦況=均衡") == BW.AI_COLOR
    assert BW.colour_of("AI ⚠ 魔法 ができる人が居ない") == "#8a5a00"
    assert BW.colour_of("AUTO_V0 turn=1") == BW.PLAIN_COLOR
