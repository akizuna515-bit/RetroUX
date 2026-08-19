"""アクション層とキーバインドのテスト（2026-08-01 の指示書 §11・§12・§14）。

★★ **「何を押したか」と「何をするか」を切り離す。** ★★

    GUIボタン ─┐
    キーボード ─┼→ ActionDispatcher → 実際の処理
    ゲームパッド ┘      （将来）

ここで守りたいこと:

  1. フォーカスの後始末を**1か所**で行う（ボタンごとに書き忘れない）
  2. 設定が壊れていても**起動できる**（キー1つで遊べなくならない）
  3. キーの重複を**見つけて教える**（押しても片方しか動かない、を防ぐ）
  4. 部分的に採らない（半分だけ効いた状態がいちばん分かりにくい）
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core import keybindings as kb
from retroux.application.action_dispatcher import ActionDispatcher
from retroux.application.models import ACTION_BY_NAME, action_names


# --- 1. アクションの定義 ---------------------------------------------

def test_every_action_says_whether_it_returns_focus():
    """★★ フォーカスの扱いは**属性**（指示書 §10.3）★★

    ⚠ 各ボタンに Windows API 呼び出しを書くと、必ずどれかで書き忘れる。
    """
    for spec in ACTION_BY_NAME.values():
        assert isinstance(spec.restore_emulator_focus, bool)


def test_gameplay_actions_return_focus_and_editors_do_not():
    """★見分け方: **そのあとキーボードを使うのはどちらか**。"""
    for name in ("toggle_auto", "toggle_turbo", "open_map",
                 "toggle_map_follow", "reset_layout", "focus_emulator"):
        assert ACTION_BY_NAME[name].restore_emulator_focus is True, name
    for name in ("open_tactics_profile", "open_settings",
                 "open_keybinding_settings"):
        assert ACTION_BY_NAME[name].restore_emulator_focus is False, name


def test_the_dispatcher_returns_focus_only_when_asked():
    calls: list = []
    d = ActionDispatcher(focus_emulator=lambda: calls.append("focus"))
    d.register("toggle_auto", lambda: calls.append("auto"))
    d.register("open_tactics_profile", lambda: calls.append("tactics"))

    assert d.dispatch("toggle_auto").success is True
    assert calls == ["auto", "focus"], "順番が違う（先に返すと入力が漏れる）"

    calls.clear()
    assert d.dispatch("open_tactics_profile").success is True
    assert calls == ["tactics"], "編集画面なのにフォーカスを返した"


def test_the_action_runs_before_the_focus_returns():
    """⚠ フォーカスを先に返すと、処理中のキー入力がゲームへ届く。"""
    order: list = []
    d = ActionDispatcher(focus_emulator=lambda: order.append("focus"))
    d.register("toggle_auto", lambda: order.append("action"))
    d.dispatch("toggle_auto")
    assert order.index("action") < order.index("focus")


def test_a_failing_action_is_reported_not_swallowed():
    """⚠ 1つのアクションが落ちても画面ごと止めない。**ただし黙らない。**"""
    def boom():
        raise RuntimeError("わざと")

    d = ActionDispatcher()
    d.register("toggle_auto", boom)
    result = d.dispatch("toggle_auto")
    assert result.success is False and "わざと" in result.message


def test_a_refused_focus_does_not_make_the_action_fail():
    """⚠ 前面化は Windows に拒否されることがある。処理は成功している。"""
    def refuse():
        raise OSError("拒否された")

    d = ActionDispatcher(focus_emulator=refuse)
    d.register("toggle_auto", lambda: None)
    assert d.dispatch("toggle_auto").success is True


def test_an_unregistered_action_does_not_crash():
    """⚠ 古い名前が設定に残っていても遊べること。"""
    d = ActionDispatcher()
    assert "使えません" in d.dispatch("toggle_auto").message
    assert "知らない" in d.dispatch("no_such_action").message


def test_registering_an_unknown_action_is_refused():
    """⚠ 呼ばれないアクションが静かに増えるのを防ぐ。"""
    d = ActionDispatcher()
    with pytest.raises(KeyError):
        d.register("no_such_action", lambda: None)


# --- 2. キー表記の正規化（指示書 §12.3）------------------------------

@pytest.mark.parametrize("raw,want", [
    ("a", "A"),
    ("A", "A"),
    ("f9", "F9"),
    ("ctrl+r", "Ctrl+R"),
    ("Shift+Ctrl+R", "Ctrl+Shift+R"),      # ★並び順を固定する
    ("alt+shift+ctrl+k", "Ctrl+Alt+Shift+K"),
    ("escape", "Escape"),
    ("  Ctrl + K  ", "Ctrl+K"),
])
def test_keys_are_normalized(raw, want):
    """⚠ そろえないと「重複しているのに気づけない」。"""
    fixed, why = kb.normalize_key(raw)
    assert (fixed, why) == (want, None)


@pytest.mark.parametrize("raw,hint", [
    ("Ctr+A", "Ctrl+A"),          # ★打ち間違いは直し方まで出す
    ("", "空"),
    ("Ctrl", "組み合わせる"),      # 修飾キーだけ
    ("Ctrl+", "+ の前後"),
    ("A+B", "2つ以上"),
    ("なにか", "知らないキー"),
])
def test_bad_keys_explain_how_to_fix(raw, hint):
    fixed, why = kb.normalize_key(raw)
    assert fixed is None
    assert hint in why, why


# --- 3. 検証（指示書 §13.4・§14）-------------------------------------

def _doc(bindings, version=1):
    return {"schema_version": version, "bindings": bindings}


def test_duplicate_keys_are_an_error():
    """★★ 同じキーに2つの操作を割り当てさせない（指示書 §14.2）★★

    ⚠ 許すと「押しても片方しか動かない」が**静かに**起きる。
    """
    issues = kb.validate(_doc({
        "toggle_auto": {"keyboard": ["A"]},
        "toggle_turbo": {"keyboard": ["a"]},        # ★正規化して同じ
    }))
    errors = [i for i in issues if i.level == "error"]
    assert len(errors) == 1
    assert "重複" in errors[0].message


def test_an_unknown_action_is_an_error():
    """⚠ タイポで静かに無効になるのを防ぐ（指示書 §14.1）。"""
    issues = kb.validate(_doc({"toggle_atuo": {"keyboard": ["A"]}}))
    assert any(i.level == "error" and "知らないアクション" in i.message
               for i in issues)


def test_a_wrong_schema_version_is_an_error():
    issues = kb.validate(_doc({}, version=999))
    assert any("schema_version" in i.where for i in issues)


def test_keyboard_must_be_a_list():
    issues = kb.validate(_doc({"toggle_auto": {"keyboard": "A"}}))
    assert any("リスト" in i.message for i in issues)


def test_all_problems_are_reported_together():
    """⚠ 1つ目で止めない。直しては怒られるを繰り返させない。"""
    issues = kb.validate(_doc({
        "toggle_auto": {"keyboard": ["Ctr+A"]},
        "toggle_turbo": {"keyboard": ["なにか"]},
        "no_such": {"keyboard": ["B"]},
    }))
    assert len([i for i in issues if i.level == "error"]) >= 3


def test_an_empty_list_means_no_key(tmp_path):
    """★空配列は「割り当てなし」（指示書 §14.3）。エラーではない。"""
    assert [i for i in kb.validate(_doc({"toggle_auto": {"keyboard": []}}))
            if i.level == "error"] == []


# --- 4. 読み込みとマージ（指示書 §12.2・§14.4）------------------------

def test_the_shipped_defaults_are_valid():
    """★★ 同梱の既定が壊れていたら、そもそも何も始まらない。 ★★"""
    import yaml
    data = yaml.safe_load(kb.DEFAULT_PATH.read_text(encoding="utf-8"))
    errors = [i for i in kb.validate(data) if i.level == "error"]
    assert errors == [], [str(e) for e in errors]


def test_every_action_appears_in_the_defaults():
    """⚠ 定義したのに既定に無いアクションを作らない（設定画面で見えない）。"""
    import yaml
    data = yaml.safe_load(kb.DEFAULT_PATH.read_text(encoding="utf-8"))
    assert set(data["bindings"]) == set(action_names())


def test_the_user_file_overrides_only_what_it_writes(tmp_path):
    """★マージは**アクション単位**（指示書 §12.2）。"""
    user = tmp_path / "keybindings.yaml"
    user.write_text("schema_version: 1\nbindings:\n"
                    "  toggle_auto:\n    keyboard: [Space]\n",
                    encoding="utf-8")
    made = kb.load(user_path=user)
    assert made.used_user_file is True
    assert made.keys["toggle_auto"] == ["Space"], "上書きが効いていない"
    assert made.keys["toggle_turbo"] == ["T"], "書いていない項目まで消えた"


def test_the_user_file_replaces_the_key_list_rather_than_adding(tmp_path):
    """⚠ 既定の A が残ると「変えたはずのキーがまだ効く」ことになる。"""
    user = tmp_path / "keybindings.yaml"
    user.write_text("schema_version: 1\nbindings:\n"
                    "  toggle_auto:\n    keyboard: [Space]\n",
                    encoding="utf-8")
    made = kb.load(user_path=user)
    assert "A" not in made.keys["toggle_auto"]


def test_a_missing_user_file_is_not_a_problem(tmp_path):
    made = kb.load(user_path=tmp_path / "nope.yaml")
    assert made.problems == []
    assert made.keys["toggle_auto"] == ["A"]


def test_a_broken_user_file_falls_back_to_the_defaults(tmp_path):
    """★★ **設定が壊れていても起動する**（指示書 §14.4）★★

    ⚠ キーが1つ間違っているだけでゲームが遊べなくなるのは筋が悪い。
    """
    user = tmp_path / "keybindings.yaml"
    user.write_text("schema_version: 1\nbindings:\n  toggle_auto: [",
                    encoding="utf-8")
    made = kb.load(user_path=user)
    assert made.used_user_file is False
    assert made.keys["toggle_auto"] == ["A"], "既定へ落ちていない"
    assert made.problems, "黙って既定へ落ちている（理由を出すこと）"


def test_a_user_file_with_one_error_is_not_partly_applied(tmp_path):
    """★★ **部分的に採らない。** ★★

    ⚠ 半分だけ効いた状態は「なぜこのキーが動かないか」がいちばん分かりにくい。
    """
    user = tmp_path / "keybindings.yaml"
    user.write_text("schema_version: 1\nbindings:\n"
                    "  toggle_auto:\n    keyboard: [Space]\n"
                    "  toggle_turbo:\n    keyboard: [Ctr+T]\n",  # ★誤り
                    encoding="utf-8")
    made = kb.load(user_path=user)
    assert made.used_user_file is False
    assert made.keys["toggle_auto"] == ["A"], "誤りがあるのに一部を採った"
    assert any("Ctr" in p or "keybindings.yaml" in p for p in made.problems)


def test_looking_up_an_action_by_key_normalizes_first():
    made = kb.load(user_path=pathlib.Path("no-such-file.yaml"))
    assert made.action_for("a") == "toggle_auto"
    assert made.action_for("ctrl+shift+r") == "reset_layout"
    assert made.action_for("Z") is None
