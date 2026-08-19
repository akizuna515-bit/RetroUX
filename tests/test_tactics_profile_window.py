"""戦術プロフィールの設定画面（仕様書 4章・14章 / 18章）。

★★ **確かめたいことの中心** ★★

  1. マトリクス形式（3人を横に並べて比べられる / 仕様書 4.3）
  2. ⚠⚠ **使えない項目は消さずグレーアウトし、理由を出す**（仕様書 14.1）
     - まだ実装していないフェーズ → 「今後のフェーズで対応」
     - そのキャラクターに意味が無い → 「回復呪文を使用できません」
  3. ⚠ **グレーアウトした項目は保存しない**
     （保存すると「設定していない未実装項目」が増えて警告が埋もれる）
  4. 未保存の変更に `*` を出し、移るときに聞く（仕様書 14.3）
  5. 見本は編集・削除できない（複製して編集）
  6. 保存に失敗しても画面の値を消さない
  7. Lua へ渡すのは「この戦術を使う」を押したときだけ
"""

from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QSpinBox,
)

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.core.tactics import TacticsRepository, models  # noqa: E402
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
    command = tmp_path / "command.json"
    repo = TacticsRepository(tmp_path / "profiles")
    made = ViewModel(Recorder(db, "HASH", events, command), db, "HASH",
                     tactics=repo)
    # ★Lua へ渡す先をテスト用に差し替える（本物の work/generated を触らない）
    made._tactics_lua_path = tmp_path / "tactics.lua"
    # ⚠⚠ **大目的の置き場も差し替える**（2026-08-05 / 実際に踏んだ）。
    #   ★これが無いと、テストが**利用者の `config/mission.yaml` を読み**、
    #     その人が「レベル上げ」にしていると表示の検査が落ちます。
    #     （書き込む経路もあり、利用者の既定を変えてしまいました）
    made._mission_path = tmp_path / "mission.yaml"
    return made


@pytest.fixture
def window(app, vm):
    win = TacticsProfileWindow(vm)
    win.show()
    app.processEvents()
    yield win, vm
    win.close()


def widget_of(win, section, key, cid="moonbrooke"):
    return win._rows[(section, key)].widgets[cid]


# --- マトリクス -------------------------------------------------------

def test_the_three_characters_are_side_by_side(window):
    """★仕様書 4.3: 比較しやすいマトリクス形式。"""
    win, _vm = window
    for row in win._rows.values():
        assert set(row.widgets) == set(models.CHARACTER_IDS)


def test_every_field_has_a_widget(window):
    win, _vm = window
    for field in models.FIELDS:
        assert (field.section, field.key) in win._rows, field.key


def test_the_presets_are_listed_and_marked(window):
    """⚠ 2026-08-04 に「いのちをだいじに」が増えました（指示書 §3）。

    ★名前を直書きせず `build_presets()` と突き合わせます（表を写さない）。
    """
    from retroux.core.tactics.profile_repository import build_presets

    win, _vm = window
    labels = [win._picker.itemText(i) for i in range(win._picker.count())]
    assert labels == [f"{p.name}（見本）" for p in build_presets()]
    assert "ダンジョン探索（見本）" in labels


def test_the_widget_kinds_match_the_field_kinds(window):
    win, _vm = window
    kinds = {"bool": QCheckBox, "int": QSpinBox, "enum": QComboBox}
    for field in models.FIELDS:
        widget = widget_of(win, field.section, field.key)
        assert isinstance(widget, kinds[field.kind]), field.key


def test_a_spinbox_cannot_go_out_of_range(window):
    """★画面の側でも範囲を越えさせない（検証と二重の守り）。"""
    win, _vm = window
    box = widget_of(win, "healing", "ally_hp_threshold")
    box.setValue(999)
    assert box.value() == 100
    box.setValue(-50)
    assert box.value() == 0


def test_enum_choices_are_shown_in_japanese(window):
    """★英語の値をそのまま出さない。"""
    win, _vm = window
    box = widget_of(win, "root", "role")
    labels = [box.itemText(i) for i in range(box.count())]
    assert "攻撃重視" in labels and "MP温存" in labels
    assert "attack" not in labels


# --- グレーアウト（消さない）------------------------------------------

def test_a_not_applicable_field_is_greyed_out_with_a_reason(window):
    """★★ **消さずにグレーアウトし、理由を出す**（仕様書 14.1）。 ★★

    ⚠ 2026-08-10（UI整理 Phase 2）: 未実装フィールドを全削除したので、
      グレーアウトの主役は「そのキャラに意味が無い項目」になった。
    ★ローレシアは DQ2 で回復呪文を覚えないので、回復系の項目は
      グレーアウトし、理由を出す。
    """
    win, _vm = window
    widget = widget_of(win, "healing", "self_enabled", cid="lorasia")
    assert not widget.isEnabled()
    assert "回復呪文を使用できません" in widget.toolTip()


def test_an_implemented_field_is_editable_on_a_normal_profile(window):
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "編集できる")
    vm.tactics.save(made)
    win.reload(select=made.id)
    assert widget_of(win, "healing", "ally_hp_threshold").isEnabled()
    assert widget_of(win, "root", "enabled").isEnabled()


def test_lorasia_cannot_be_given_healing_settings(window):
    """★★ そのキャラクターに意味が無い項目もグレーアウト（仕様書 5.7）。 ★★

    ⚠ 理由は「MPが0だから」ではなく「**呪文を覚えないから**」。
      宿屋で回復しても変わらない。
    """
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "ローレシアの確認")
    vm.tactics.save(made)
    win.reload(select=made.id)
    widget = win._rows[("healing", "ally_hp_threshold")].widgets["lorasia"]
    assert not widget.isEnabled()
    assert "回復呪文を使用できません" in widget.toolTip()
    # ★ムーンブルクは編集できる（キャラクターごとに違う）
    assert win._rows[("healing", "ally_hp_threshold")].widgets[
        "moonbrooke"].isEnabled()


def test_the_not_applicable_table_only_names_real_fields():
    """⚠ 存在しない項目をグレーアウトの表に書くと、黙って無視される。"""
    for cid, entries in models.NOT_APPLICABLE.items():
        assert cid in models.CHARACTER_IDS
        for path in entries:
            assert path in models.FIELD_BY_PATH, path


def test_a_greyed_out_field_is_not_saved(window):
    """★★ **グレーアウトした項目は保存しない。** ★★

    ⚠ 保存すると「設定していない未実装項目」がプロフィールに増え、
      検証のたびに「いまは効きません」が出る（読まれない通知になる）。
    """
    from retroux.core.tactics import validate_profile

    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "保存の確認")
    vm.tactics.save(made)
    win.reload(select=made.id)
    win._name.setText("保存の確認")
    assert win.save(), win._status.text()

    again = vm.tactics.get(made.id)
    # ★グレーアウトしている**残りの項目**が入らないことを見る（実装済みは attack_spell）
    actions = again.characters["moonbrooke"].get("actions") or {}
    assert set(actions) == {"attack_spell"}, actions
    # ★ローレシアは呪文を使えないので、そもそも項目が無い
    assert "actions" not in again.characters["lorasia"]
    # ★ローレシアの回復設定も入らない（グレーアウトしているので）
    assert "healing" not in again.characters["lorasia"]
    result = validate_profile(again)
    assert result.warnings == [], result.lines()


# --- 見本 -------------------------------------------------------------

def test_a_preset_is_read_only_on_screen(window):
    win, _vm = window
    win.reload(select="balanced")
    assert win._name.isReadOnly()
    assert not widget_of(win, "healing", "ally_hp_threshold").isEnabled()
    assert "見本" in win._status.text()


def test_saving_a_preset_says_to_duplicate(window):
    win, _vm = window
    win.reload(select="balanced")
    assert win.save() is False
    assert "複製" in win._status.text()


def test_deleting_a_preset_says_it_cannot(window):
    win, _vm = window
    win.reload(select="balanced")
    win.delete()
    assert "消せません" in win._status.text()
    assert win.repo.get("balanced") is not None


def test_duplicating_a_preset_gives_an_editable_copy(window):
    win, vm = window
    win.reload(select="no_spells")
    win.duplicate()
    assert win._current.preset is False
    assert widget_of(win, "healing", "ally_hp_threshold").isEnabled()
    # ★元の見本の値を引き継いでいる（呪文を使わない＝回復を切ってある）
    assert win._current.get("moonbrooke", "healing", "ally_enabled") is False
    assert win._current.get("moonbrooke", "healing", "self_enabled") is False


# --- 未保存の変更 -----------------------------------------------------

def test_editing_marks_the_title_with_a_star(window):
    """★仕様書 14.3。"""
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "星の確認")
    vm.tactics.save(made)
    win.reload(select=made.id)
    assert "*" not in win.windowTitle()
    widget_of(win, "healing", "ally_hp_threshold").setValue(77)
    assert "*" in win.windowTitle()
    assert "未保存" in win._dirty_label.text()


def test_saving_clears_the_star(window):
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "星が消える")
    vm.tactics.save(made)
    win.reload(select=made.id)
    widget_of(win, "healing", "ally_hp_threshold").setValue(77)
    assert win.save(), win._status.text()
    assert "*" not in win.windowTitle()
    assert vm.tactics.get(made.id).get("moonbrooke", "healing",
                                       "ally_hp_threshold") == 77


def test_revert_throws_away_unsaved_changes(window):
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "元に戻す")
    vm.tactics.save(made)
    win.reload(select=made.id)
    before = widget_of(win, "healing", "ally_hp_threshold").value()
    widget_of(win, "healing", "ally_hp_threshold").setValue(13)
    win.revert()
    assert widget_of(win, "healing", "ally_hp_threshold").value() == before
    assert "*" not in win.windowTitle()


def test_loading_a_profile_does_not_mark_it_dirty(window):
    """⚠ 開いただけで `*` が付くと、`*` が意味を持たなくなる。"""
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("no_spells"), "開くだけ")
    vm.tactics.save(made)
    win.reload(select=made.id)
    assert win._dirty is False
    assert "*" not in win.windowTitle()


# --- Lua へ渡す -------------------------------------------------------

def test_applying_writes_the_lua_file_and_the_command(window, tmp_path,
                                                     monkeypatch):
    """★「この戦術を使う」で初めて Lua へ渡る。"""
    import json

    from retroux.core.tactics import lua_bridge

    win, vm = window
    out = tmp_path / "tactics.lua"
    monkeypatch.setattr(lua_bridge, "DEFAULT_PATH", out)

    made = vm.tactics.duplicate(vm.tactics.get("no_spells"), "使う戦術")
    vm.tactics.save(made)
    win.reload(select=made.id)
    win.apply_active()

    assert out.exists(), win._status.text()
    body = out.read_text(encoding="utf-8")
    assert "使う戦術" in body
    assert vm.tactics.active_id() == made.id
    command = json.loads(vm.recorder.command_path.read_text(encoding="utf-8"))
    assert command["tactics_revision"] > 0
    # ★★ 「次の戦闘から」と必ず書く（すぐ効くと思われないように）
    assert "次の戦闘" in win._status.text()


def test_ok_saves_the_changes_before_applying(window):
    """★★ **[OK] は「保存してから使う」**（2026-07-31 に統合）★★

    ⚠ 以前は [保存] と [この戦術を使う] が別で、**2回押さないと効かなかった**。
      押し忘れると「直したのに変わらない」になる。
      ★片方だけ押して食い違う、という状態を作らせない。
    """
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "OKで保存")
    vm.tactics.save(made)
    win.reload(select=made.id)
    widget_of(win, "healing", "ally_hp_threshold").setValue(88)
    assert win._dirty, "変更が拾われていない"

    win.apply_active()

    assert not win._dirty, "保存されていない"
    # ★ファイルにも入っていること（画面だけ直っても意味が無い）
    again = vm.tactics.get(made.id)
    assert again.get("moonbrooke", "healing", "ally_hp_threshold") == 88
    assert vm.tactics.active_id() == made.id
    assert "次の戦闘" in win._status.text()


def test_ok_on_a_preset_asks_to_duplicate_first(window):
    """⚠ 見本は保存できないので、直してあるなら**複製を促す**。

    ★黙って「使う」だけ進めると、画面の値と実際の戦術が食い違う。
    """
    win, vm = window
    win.reload(select="balanced")
    widget_of(win, "healing", "ally_hp_threshold").setValue(77)
    win.apply_active()
    assert "複製" in win._status.text()


def test_a_read_only_view_model_does_not_push(tmp_path, app):
    """⚠ 閲覧専用のときは渡さない（別プロセスと取り合う）。"""
    db = Database(tmp_path / "r.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "e.jsonl"
    events.write_text("", encoding="utf-8")
    command = tmp_path / "c.json"
    made = ViewModel(Recorder(db, "HASH", events, command), db, "HASH",
                     read_only=True,
                     tactics=TacticsRepository(tmp_path / "profiles"))
    assert made.push_tactics() is False
    assert not command.exists()


def test_the_label_names_the_characters_left_on_manual(vm):
    """★★ AI操作OFF の人は**必ず出す**。 ★★

    出さないと「その人だけ動かない」を不具合だと思われる。
    """
    # ⚠ 2026-08-19: 見本「手動中心」を廃止（RX-0067）。★見本ではなく
    #   作った作戦で全員 AI操作OFF にして、名前が出ることを確かめる。
    prof = vm.tactics.create("手動の試し")
    for cid in models.CHARACTER_IDS:
        prof.set(cid, "root", "role", models.Role.MANUAL)
        prof.set(cid, "root", "enabled", False)
    vm.tactics.save(prof)
    vm.tactics.set_active(prof.id)
    text = vm.tactics_label()
    for label in models.CHARACTER_LABELS.values():
        assert label in text, text


def test_the_label_says_when_nothing_is_off(vm):
    """⚠ 2026-08-05 に**大目的**を同じ行へ足しました（Phase 3）。

    ★操作直後の一言（`_align_status`）は AUTO の ON/OFF などに
      塗りつぶされるので、いま何で戦っているかは**常時見える場所**に置きます。
    """
    vm.tactics.set_active("balanced")
    text = vm.tactics_label()
    assert "戦術: レベル上げ" in text
    assert "目的: ダンジョン攻略" in text, "★いまの目的も出ること"
    # ★AI操作OFF の人が居なければ「⚠ 手動:」は出ない
    assert "手動:" not in text


def test_the_label_says_when_the_feature_is_off(tmp_path):
    db = Database(tmp_path / "n.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "e.jsonl"
    events.write_text("", encoding="utf-8")
    made = ViewModel(Recorder(db, "HASH", events, tmp_path / "c.json"), db,
                     "HASH", tactics=None)
    assert "無効" in made.tactics_label()
    assert made.push_tactics() is False


# --- 壊れない ---------------------------------------------------------

def test_a_failed_save_keeps_the_screen_values(window, monkeypatch):
    """★★ **設計した戦術が消えるほうが痛い。** ★★"""
    win, vm = window
    made = vm.tactics.duplicate(vm.tactics.get("balanced"), "保存が失敗する")
    vm.tactics.save(made)
    win.reload(select=made.id)
    widget_of(win, "healing", "ally_hp_threshold").setValue(42)

    monkeypatch.setattr(vm.tactics, "save", lambda _p: False)
    assert win.save() is False
    assert widget_of(win, "healing", "ally_hp_threshold").value() == 42
    assert "保存できませんでした" in win._status.text()
    assert "そのまま残して" in win._status.text()


def test_a_window_with_an_unusable_repository_still_opens(app, tmp_path):
    """⚠ 置き場が作れなくても窓は開く（見本だけで動く）。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("フォルダを作れない", encoding="utf-8")
    db = Database(tmp_path / "b.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "e.jsonl"
    events.write_text("", encoding="utf-8")
    made = ViewModel(Recorder(db, "HASH", events, tmp_path / "c.json"), db,
                     "HASH", tactics=TacticsRepository(blocker / "profiles"))
    win = TacticsProfileWindow(made)
    win.show()
    app.processEvents()
    assert win._picker.count() == len(build_presets()), "見本が出ていない"
    win.close()


def test_the_screen_explains_what_does_not_work_yet(window):
    """★★ 画面に「灰色の項目はまだ効かない」と書く。 ★★

    書かないと「設定したのに効かない」になり、設定画面ぜんたいが信用されない。
    """
    win, _vm = window
    texts = [child.text() for child in win.findChildren(type(win._dirty_label))
             if child.text()]
    joined = "\n".join(texts)
    assert "まだ効きません" in joined
    assert "次の戦闘から" in joined


# --- インポートの窓 ---------------------------------------------------

def test_the_import_dialog_needs_a_check_before_importing(app, vm):
    """★★ **検証せずにインポートさせない**（仕様書 12.3）。 ★★"""
    from PySide6.QtWidgets import QDialogButtonBox

    from retroux.ui.tactics_import_dialog import TacticsImportDialog

    dialog = TacticsImportDialog(vm.tactics)
    ok = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    assert "検証" in ok.toolTip()
    dialog.close()


def test_the_import_dialog_enables_import_after_a_good_check(app, vm):
    from PySide6.QtWidgets import QDialogButtonBox

    from retroux.core.tactics.import_export import profile_to_yaml
    from retroux.ui.tactics_import_dialog import TacticsImportDialog

    dialog = TacticsImportDialog(vm.tactics)
    dialog.set_text(profile_to_yaml(vm.tactics.get("no_spells")))
    dialog.check()
    ok = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled(), dialog._status.text()
    dialog.close()


def test_the_import_dialog_blocks_unknown_keys_until_allowed(app, vm):
    """★★ **未知項目を勝手に無視しない**（仕様書 12.5）。 ★★"""
    from PySide6.QtWidgets import QDialogButtonBox

    from retroux.ui.tactics_import_dialog import TacticsImportDialog

    text = ("schema_version: 1\n"
            "profile: {id: from_future, name: 未来の設定}\n"
            "characters:\n"
            "  lorasia:\n"
            "    enabled: true\n"
            "    brand_new_section:\n"
            "      brand_new_key: 1\n")
    dialog = TacticsImportDialog(vm.tactics)
    dialog.set_text(text)
    dialog.check()
    ok = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    assert "知らない項目" in dialog._status.text()
    # ★利用者が明示的に許せば押せる
    dialog._allow_unknown.setChecked(True)
    assert ok.isEnabled()
    dialog.close()


def test_the_import_dialog_shows_why_it_cannot_read(app, vm):
    from retroux.ui.tactics_import_dialog import TacticsImportDialog

    dialog = TacticsImportDialog(vm.tactics)
    dialog.set_text("こわれている: {{{")
    dialog.check()
    assert "読み込めません" in dialog._status.text()
    assert "YAML として読めません" in dialog._preview_view.toPlainText()
    dialog.close()


def test_the_import_dialog_defaults_to_rename_on_conflict(app, vm):
    """★★ **上書きを既定にしない**（仕様書 12.6）。 ★★"""
    from retroux.ui.tactics_import_dialog import TacticsImportDialog

    dialog = TacticsImportDialog(vm.tactics)
    assert dialog._rename.isChecked()
    assert not dialog._overwrite.isChecked()
    dialog.close()


def test_importing_saves_and_returns_the_profile(app, vm):
    from retroux.core.tactics.import_export import profile_to_yaml
    from retroux.ui.tactics_import_dialog import TacticsImportDialog

    source = vm.tactics.duplicate(vm.tactics.get("no_spells"), "配られた戦術")
    text = profile_to_yaml(source)
    dialog = TacticsImportDialog(vm.tactics)
    dialog.set_text(text)
    dialog.check()
    dialog._do_import()
    assert dialog.imported is not None
    assert vm.tactics.get(dialog.imported.id) is not None
    dialog.close()


# --- [OK] は成功したときだけ閉じる（2026-07-31 の指示書 §9）------------
#
# ★★ **閉じてよいのは「全部済んだあと」だけ。** ★★
#   検証・保存・反映のどれかで失敗したら閉じない。
#   ⚠ 閉じてしまうと、直すべき入力が消えて**何が悪かったか分からない**。

def test_ok_closes_the_window_after_it_really_applied(window):
    """★保存 → 選択 → Lua へ反映、が全部できたら閉じる。"""
    win, vm = window
    win.reload()
    win.duplicate()                       # 見本は保存できないので複製してから
    win._dirty = True
    seen: list = []
    win.applied.connect(seen.append)

    win.apply_active()

    assert not win.isVisible(), "成功したのに閉じていない"
    # ★閉じた窓に結果を書いても読まれない。呼び出し元へ渡すこと
    assert len(seen) == 1 and "次の戦闘から" in seen[0]


def test_ok_keeps_the_window_open_when_saving_fails(window, monkeypatch):
    """⚠ 保存に失敗したら閉じない（入力を捨てない）。"""
    win, vm = window
    win.reload()
    win.duplicate()
    win._dirty = True
    seen: list = []
    win.applied.connect(seen.append)
    monkeypatch.setattr(win, "save", lambda: False)

    win.apply_active()

    assert win.isVisible(), "保存に失敗したのに閉じた"
    assert seen == [], "失敗したのに成功を知らせている"


def test_ok_keeps_the_window_open_when_the_bridge_refuses(window, monkeypatch):
    """⚠ Lua へ渡せなかったときも閉じない。

    ★ここが抜けやすい: 保存はできているので「成功した」と見えるが、
      **AI には届いていない**。閉じると気づけない。
    """
    win, vm = window
    win.reload()
    win.duplicate()
    win._dirty = True
    monkeypatch.setattr(vm, "push_tactics", lambda: False)

    win.apply_active()

    assert win.isVisible(), "反映に失敗したのに閉じた"
    assert "渡せませんでした" in win._status.text()


def test_ok_on_an_unsaveable_preset_keeps_the_window_open(window):
    """⚠ 見本を直した状態で押しても閉じない（複製を促す）。"""
    win, vm = window
    win.reload()
    win._dirty = True                     # 見本を選んだまま「直した」状態
    assert win._current is not None and win._current.preset

    win.apply_active()

    assert win.isVisible(), "見本なのに閉じた"
    assert "複製" in win._status.text()



def test_読み込んだ直後は未保存あつかいにしない(window):
    """⚠⚠ **これを間違えると、テストが「赤」ではなく「無反応」になります。**

    ★2026-08-12 に実際に起きたこと:

      `_load_into_screen` の最後が `self._dirty = True` になっていた
        → 作戦を選ぶたびに「保存 / 破棄 / キャンセル」の窓（`QMessageBox.exec()`）
        → ⚠ 人が押すまで**止まる**。テストは無反応のまま終わらない。

    ⚠ 止まるテストは**赤くならない**ので、全件実行そのものが終わりません。
      ★だから「窓が出る前」のこの値を、ここで直に見張ります。
    """
    win, _vm = window
    win.reload()

    assert win._dirty is False, (
        "⚠⚠ 読み込んだ直後に未保存あつかいになっています。"
        "★このままだと作戦を選ぶたびに確認の窓が出て、操作もテストも止まります")


def test_直したときだけ未保存になる(window):
    """★上の裏返し。⚠ 常に False では「未保存あり」の警告が死にます。"""
    win, _vm = window
    win.reload()
    assert win._dirty is False

    win._mark_dirty()

    assert win._dirty is True, "★直したのに未保存あつかいになっていない"


def test_window_fits_common_screen_height(vm, app):
    """★★ RX-0066: 下のボタンが画面外に出ないための歯止め。

    ⚠ 依頼者「1080 に入らず、ボタンが見えない」。設定の本体（マトリクス）は
      `QScrollArea` なので、★窓の**最小高さ**が小さければ、狭い画面でも
      [OK/元に戻す/閉じる] を画面内に置ける。⚠ マトリクスがスクロールから
      外れて min が膨らむと、この検査が赤になる。
    """
    from retroux.ui.tactics_profile_window import TacticsProfileWindow

    w = TacticsProfileWindow(vm)
    w.show()
    app.processEvents()
    # ★1080 画面の作業領域(~1040)で、余白とボタン列を引いても収まる下限
    assert w.minimumSizeHint().height() <= 700, (
        f"⚠ 窓の最小高さが {w.minimumSizeHint().height()} — "
        "マトリクスがスクロールから外れてボタンが切れる恐れ")
    w.close()
