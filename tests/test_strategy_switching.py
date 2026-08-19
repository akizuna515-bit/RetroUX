"""作戦の切替と画面間の同期（2026-08-04 / 指示書 §4〜§6・§18.1〜18.3）。

★★ **確かめたいことの中心** ★★

  1. メイン画面でも戦術設定画面でも作戦を切り替えられる
  2. 片方で変えたら、もう片方の表示も同期する（§19 受入条件3）
  3. ⚠⚠ **同じ作戦の再選択では、保存も通知もしない**（§6・§15）
  4. ⚠⚠ **画面の初期化で誤発火しない**（§5.4）
  5. 不正な作戦IDは既定へフォールバックする
  6. ⚠ 入力途中の詳細値は、保存前に戦闘AIへ渡らない（§5.3）

## ⚠⚠ なぜ「初期化での誤発火」をここまで気にするか（§5.4）

リストへ現在値を入れると `currentIndexChanged` が鳴ります。
そこに切替処理を付けていると、**窓を開いただけで**

    [TACTICS] strategy changed: ...

が走り、保存もLuaへの通知も起きます。★`activated`（人の操作でだけ鳴る）
を使い、さらに `blockSignals` でも守っています。
"""

from __future__ import annotations

import os
import pathlib
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.core.tactics import TacticsRepository  # noqa: E402
from retroux.core.tactics.profile_repository import (  # noqa: E402
    build_presets,
)
from retroux.ui.tactics_profile_window import (  # noqa: E402
    TacticsProfileWindow,
)
from retroux.ui.view_model import ViewModel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        yield QApplication([])
    except Exception as exc:                          # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")


@pytest.fixture
def vm(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    repo = TacticsRepository(tmp_path / "profiles")
    made = ViewModel(Recorder(db, "HASH", events, tmp_path / "command.json"),
                     db, "HASH", tactics=repo)
    made._tactics_lua_path = tmp_path / "tactics.lua"
    # ⚠ 大目的の置き場も差し替える（★利用者の config/mission.yaml を触らない）
    made._mission_path = tmp_path / "mission.yaml"
    return made


# --- ★★ 一元管理（§6）----------------------------------------------------

def test_作戦を切り替えられる(vm):
    result = vm.set_active_tactics("life_first", source="main_window")
    assert result.ok and result.changed
    assert vm.tactics.active_id() == "life_first"
    assert "ダンジョン探索" in result.message


def test_同じ作戦の再選択では何もしない(vm):
    """★★ §6 必須要件「同じ作戦を再選択した場合は不要な保存・通知を行わない」。

    ⚠ ここが効かないと、画面のちょっとした操作で毎回
      Lua への書き込みが走ります。
    """
    vm.set_active_tactics("life_first", source="main_window")
    before = vm.tactics.active_path.stat().st_mtime_ns

    again = vm.set_active_tactics("life_first", source="main_window")
    assert again.ok is True
    assert again.changed is False, "⚠ 変わっていないのに変わったと言っている"
    assert vm.tactics.active_path.stat().st_mtime_ns == before, \
        "⚠ 同じ作戦なのに保存し直している"


def test_不正な作戦IDは既定へ落ちる(vm):
    """⚠ §6・§15「不正な作戦IDの場合は安全な既定作戦へフォールバック」。"""
    vm.set_active_tactics("balanced", source="main_window")
    result = vm.set_active_tactics("そんな作戦は無い", source="main_window")
    assert result.ok is False
    assert result.changed is False
    # ★選択は動かさない（勝手に別の作戦で戦わせない）
    assert vm.tactics.active_id() == "balanced"
    assert "見つかりません" in result.message


def test_選んだ作戦は再起動後も残る(vm, tmp_path):
    """★§18.1「再起動後も最後に選択した作戦が復元される」。"""
    vm.set_active_tactics("life_first", source="main_window")
    again = TacticsRepository(tmp_path / "profiles")
    assert again.active_id() == "life_first"
    assert again.active().name == "ダンジョン探索"


def test_作戦リストに見本が全部出る(vm):
    ids = [pid for pid, _label in vm.tactics_choices()]
    assert ids == [p.id for p in build_presets()]
    assert "life_first" in ids


def test_戦闘中は次のターンからと伝える(vm):
    """★§4.2 の表示例。⚠ 戦闘外では出さない。"""
    vm.recorder.stats.in_battle = True
    result = vm.set_active_tactics("no_spells", source="main_window")
    assert "次のターンから" in result.message

    vm.recorder.stats.in_battle = False
    result = vm.set_active_tactics("balanced", source="main_window")
    assert "次のターンから" not in result.message


def test_プロフィール機能が無効でも落ちない():
    """⚠ §15。★理由を出して続くこと（例外を投げない）。"""
    made = ViewModel.__new__(ViewModel)
    made.tactics = None
    result = made.set_active_tactics("balanced", source="main_window")
    assert result.ok is False
    assert "無効" in result.message


# --- ★★ 画面の同期（§5・§19 受入条件3）----------------------------------

def test_窓を開いただけでは切り替わらない(app, vm):
    """★★★ **§5.4 の誤発火**。

    ⚠ リストへ現在値を入れると `currentIndexChanged` が鳴ります。
      そこに切替を付けていると、**開いただけで**保存とLua通知が走ります。
    """
    seen = []
    win = TacticsProfileWindow(vm)
    win.strategy_changed.connect(seen.append)
    app.processEvents()
    try:
        assert seen == [], "⚠⚠ 窓を開いただけで作戦が切り替わっている"
        assert vm.tactics.active_id() is None, "⚠⚠ 勝手に選択が入っている"
    finally:
        win.close()


def test_戦術画面で選ぶと即時に切り替わる(app, vm):
    """★§5.2「戦術設定画面の作戦リストを変更した場合も即時変更」。"""
    win = TacticsProfileWindow(vm)
    app.processEvents()
    try:
        index = win._picker.findData("life_first")
        assert index >= 0
        win._picker.setCurrentIndex(index)
        win._on_picked_by_user(index)          # ★人が選んだのと同じ
        assert vm.tactics.active_id() == "life_first"
    finally:
        win.close()


def test_戦術画面の切替がメイン画面へ伝わる(app, vm):
    """★§19 受入条件3「どちらから変更しても、現在作戦が同期される」。"""
    seen = []
    win = TacticsProfileWindow(vm)
    win.strategy_changed.connect(seen.append)
    app.processEvents()
    try:
        index = win._picker.findData("no_spells")
        win._picker.setCurrentIndex(index)
        win._on_picked_by_user(index)
        assert seen, "⚠ メイン画面へ知らせていない"
        assert "呪文を使わない" in seen[0]
    finally:
        win.close()


def test_戦術画面でも同じ作戦の再選択は黙っている(app, vm):
    win = TacticsProfileWindow(vm)
    app.processEvents()
    try:
        index = win._picker.findData("life_first")
        win._picker.setCurrentIndex(index)
        win._on_picked_by_user(index)
        seen = []
        win.strategy_changed.connect(seen.append)
        win._on_picked_by_user(index)
        assert seen == [], "⚠ 同じ作戦なのに知らせている"
    finally:
        win.close()


# --- ⚠⚠ 入力途中の値を戦闘へ渡さない（§5.3・§18.3）----------------------

def test_編集中の値は保存前にAIへ渡らない(app, vm):
    """★★★ **§5.3 の要求**。

        50 -> 5 -> 55

    ⚠ この途中の `5%` を戦闘へ反映してはいけません。

    ★作りとしては、画面のウィジェットの値は `save()` を通るまで
      プロフィールへ入りません（`_collect` が保存時にだけ呼ばれる）。
    """
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "編集の確認")
    vm.tactics.save(made)
    win = TacticsProfileWindow(vm)
    app.processEvents()
    try:
        win.reload(select=made.id)
        box = win._rows[("healing", "ally_hp_threshold")].widgets["moonbrooke"]
        before = vm.tactics.get(made.id).get(
            "moonbrooke", "healing", "ally_hp_threshold")

        box.setValue(5)                    # ★入力途中
        assert vm.tactics.get(made.id).get(
            "moonbrooke", "healing", "ally_hp_threshold") == before, \
            "⚠⚠ 入力途中の値が保存されている"

        box.setValue(55)                   # ★打ち終わり
        assert win.save(), win._status.text()
        assert vm.tactics.get(made.id).get(
            "moonbrooke", "healing", "ally_hp_threshold") == 55
    finally:
        win.close()


def test_元に戻すで編集内容を捨てられる(app, vm):
    """★§5.3「元に戻すボタン: 保存前の編集内容を破棄」。"""
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "取り消しの確認")
    vm.tactics.save(made)
    win = TacticsProfileWindow(vm)
    app.processEvents()
    try:
        win.reload(select=made.id)
        box = win._rows[("healing", "ally_hp_threshold")].widgets["moonbrooke"]
        original = box.value()
        box.setValue(11)
        win.revert()
        assert win._rows[("healing", "ally_hp_threshold")].widgets[
            "moonbrooke"].value() == original
    finally:
        win.close()


def test_範囲外のしきい値は入力できない(app, vm):
    """★§18.3「0〜100%以外のしきい値を拒否する」。"""
    win = TacticsProfileWindow(vm)
    app.processEvents()
    try:
        for key in ("protect_hp_threshold", "emergency_self_hp_threshold"):
            box = win._rows[("healing", key)].widgets["moonbrooke"]
            box.setValue(999)
            assert box.value() == 100, key
            box.setValue(-5)
            assert box.value() == 0, key
    finally:
        win.close()


# --- ★ 後方互換（§13・§18.3）--------------------------------------------

def test_古いプロフィールを読める(vm, tmp_path):
    """★§13「新項目が無い旧設定では既定値を補完する」。

    ⚠ 新しい項目を足したせいで、前の版で保存したファイルが
      読めなくなってはいけません。
    """
    vm.tactics.ensure_dir()
    path = vm.tactics.dir / "old_style.yaml"
    path.write_text(
        "schema_version: 1\n"
        "profile: { id: old_style, name: 古い作戦 }\n"
        "characters:\n"
        "  lorasia: { enabled: true }\n"
        "  samaltria: { enabled: true }\n"
        "  moonbrooke: { enabled: true }\n",
        encoding="utf-8")
    prof = vm.tactics.get("old_style")
    assert prof is not None, vm.tactics.problems
    # ★新項目は既定値で補完される
    assert prof.get("moonbrooke", "healing", "protect_target") == "none"
    assert prof.get("moonbrooke", "healing", "protect_hp_threshold") == 50
    assert prof.get("moonbrooke", "healing",
                    "avoid_duplicate_healing") is True


def test_守る相手の既定は決めない():
    """★★★ **触らなければ従来どおり**（§19 受入条件13）。

    ⚠ 既定が `lorasia` だと、いままでの作戦の挙動まで変わります。
    """
    from retroux.core.tactics import models

    field = models.FIELD_BY_PATH[("healing", "protect_target")]
    assert field.default is models.ProtectTarget.NONE
    assert field.implemented, "★画面で選べること"
