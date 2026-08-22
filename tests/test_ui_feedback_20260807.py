"""画面についての依頼者の指摘6件（2026-08-07）。

    ・最初のウィンドウがいろいろ重なる（標準レイアウトボタン押すと直る）
    ・MAPが画面の下に置きたいが、外面に重なっている
    ・ロードでPを押すと戦術画面が出る。キーが被っている。
      戦術画面はいったんボタン起動のみでよい
    ・上画面の文字は薄い。普通のこさで良い
    ・戦況、役割は戦闘終了後クリアしなくて良い
    ・高速化ONOFFボタンを押しても利かない時がある

★★ **直したつもりを防ぐための検査**です。
⚠ 直したときは通り、戻したら落ちる形にしてあります。
"""

from __future__ import annotations

import pathlib

import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
KEYBINDINGS = PROJECT_ROOT / "retroux" / "config" / "default_keybindings.yaml"
MAIN_WINDOW = PROJECT_ROOT / "retroux" / "ui" / "main_window.py"
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
SPEED = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
         / "speed_controller.lua")


def _bindings() -> dict:
    """割り当ての表を返す。⚠ 入れ物の名前が変わっても壊れないようにする。"""
    data = yaml.safe_load(KEYBINDINGS.read_bytes().decode("utf-8")) or {}
    got = data.get("bindings") or data.get("actions")
    assert isinstance(got, dict) and got, (
        f"⚠⚠ 割り当ての表が読めません（★形が変わった？）: {list(data)}")
    return got


# --- ★ 3. ロードの P と衝突していた -----------------------------------

def test_戦術画面にキーを割り当てない():
    """★★★ **P は FCEUX のセーブステート読み込み**です。

    ⚠ ロードのたびに戦術画面が開いていました。
      ★依頼者の指示は「戦術画面はいったんボタン起動のみでよい」。
    """
    got = _bindings().get("open_tactics_profile")
    assert got is not None, "⚠ open_tactics_profile がありません"
    assert got.get("keyboard") == [], (
        f"⚠ 戦術画面にキーが割り当たっています: {got.get('keyboard')!r}")


def test_FCEUXの予約キーを使っていない():
    """⚠⚠ **同じ轍を踏まない。**

    ★FCEUX 側の予約（`config.yaml` に実測で記録）:
      `Q R M W Z I L O P Tab Space Enter F1-F12 数字 記号`
    ⚠ ここでは**画面側の割り当て**だけを見ます（★ゲーム操作と衝突しない）。
    """
    reserved = {"P", "Q", "W", "Z", "I", "L", "O"}
    actions = _bindings()
    bad = []
    for name, spec in actions.items():
        for key in (spec.get("keyboard") or []):
            # ★修飾キー付き（Ctrl+K など）は FCEUX と衝突しない
            if "+" in str(key):
                continue
            if str(key).upper() in reserved:
                bad.append(f"{name}={key}")
    assert not bad, f"⚠⚠ FCEUX の予約キーを使っています: {bad}"


# --- ★ 4. 上画面の文字が薄い ------------------------------------------

def test_上部ステータスの文字色を1か所で決めている():
    """⚠ 以前は `#c8c8c8` と `#8a8a8a` が各所に直書きされていました。

    ★1つ変えるのに探し回ることになります。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    assert "_STATUS_TEXT" in source
    # ⚠ 2026-08-11: 右列を圧縮し、状態・速度・版・いまどこ・取り込み・戦術は
    #   **画面に出さなくなった**（部品は隠しで残す）。★共通色を使うかは、
    #   いま画面に出している見出しだけで確かめる。
    # ⚠ 2026-08-12: 戦況欄を4行にしたので、`_assessment_label` /
    #   `_roles_label` は `_assessment_rows` の作成ループになりました。
    for name in ("_backup_label",):
        assert f"self.{name}.setStyleSheet(_STATUS_TEXT)" in source, (
            f"⚠ {name} が共通の色を使っていません")
    assert source.count("setStyleSheet(_STATUS_TEXT)") >= 2, (
        "⚠ 共通の色を使っている場所が減りすぎています")
    # ★戦況の4行も共通の色で作ること（★ループの中で1回だけ書く）
    rows = source[source.index("self._assessment_rows = []"):]
    assert "label.setStyleSheet(_STATUS_TEXT)" in rows[:600], (
        "⚠ 戦況の4行が共通の色を使っていません")


def test_文字色を決め打ちしていない():
    """★★★ **色を決め打ちすると、テーマのどちらかで読めなくなります。**

    ⚠⚠ 2026-08-07 に**2回**間違えました:

      1回目: `#c8c8c8` → `#e8e8e8` と**明るく**した。
             ⚠ 画面は**白背景**だったので、★さらに読めなくなった。
      2回目: 画面を組んで色を測ったが、★**背景を見ていなかった**。
             ⚠ `#e8e8e8` という値だけ確かめて「直った」と言った。

    ★色はテーマに任せます。⚠ 薄く見せたいなら**大きさ**で差をつけます。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    line = next(l for l in source.splitlines()
                if l.startswith("_STATUS_TEXT"))
    assert "color:" not in line, (
        "⚠⚠ 文字色を決め打ちしています: " + line
        + " / ★白背景でも黒背景でも読めるよう、テーマに任せてください")


# --- ★ 5. 戦闘終了後にクリアしない ------------------------------------

def test_戦闘が終わっても見立てを残す():
    """★依頼者の指示（2026-08-07）。

        > 戦況、役割は戦闘終了後クリアしなくて良い。

    ⚠ 私は最初「いまの値だから消すべき」と実装しました。
      ★戦闘は数秒で終わるので、**消すと読む間がありません**。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    start = source.index("function Bridge:_on_battle_end")
    body = source[start:start + 2600]
    assert "self.last_assessment_view = nil" not in body


# --- ★ 1・2. 起動時の重なりと MAP の位置 ------------------------------

def test_地図を開いたときに並べ直す():
    """★★★ **これが「最初のウィンドウが重なる」の直接の原因**でした。

    ⚠⚠ 起動スクリプトは並べ替えを呼びますが、★**その時点で地図の窓が
      まだ存在しません**。後から開くと任意の場所に出て重なります。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    start = source.index("def _open_map_window")
    body = source[start:start + 1200]
    assert "self._place_map_window()" in body, (
        "⚠ 地図を開いたあとに並べていません")

    # ★★★ **並べるのは `show()` の後**（2026-08-07 に踏んだ）★★★
    #   ⚠⚠ Qt は `show()` するまで**ウィンドウを作りません**。
    #     出す前に並べても、窓が無いので飛ばされます。
    #     ★実際、作った直後に並べて**効きませんでした**。
    assert body.index("window.show()") < body.index(
        "self._place_map_window()"), (
        "⚠⚠ show() より前に並べています（★窓が無いので効きません）")


def test_地図を毎回並べ直さない():
    """⚠ 開くたびに並べ直すと、★**利用者が動かした位置を奪います**。"""
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    start = source.index("def _open_map_window")
    body = source[start:start + 1200]
    assert "_map_needs_placing" in body, (
        "⚠ 1回だけにする印がありません")


def test_並べ方を書き写していない():
    """⚠⚠ **測り方を2か所に書かない。**

    ★作業領域も FCEUX の実寸も `WindowManager.arrange()` が持っています。
      書き写すと、片方だけ直したときに静かにずれます。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    start = source.index("def _place_map_window")
    body = source[start:start + 900]
    assert "self.windows.arrange()" in body
    assert "compute_standard" not in body, (
        "⚠ 並べ方を書き写しています（★二重管理になります）")


# --- ⚠ 6. 高速化が効かない（★原因を測れるようにした）------------------

def test_押した側で記録する():
    """⚠⚠ **Lua 側に警告を入れたら 195件出てログが埋まりました**（★私のミス）。

    `apply_command` の「ファイルの値が前と同じ」は、**押していないときに
    毎ポーリング通る道**です。★異常ではありません。
    ⚠ 「鳴りすぎも壊れ方」を自分でやりました。

    ★知りたいのは「押した瞬間」なので、**押した側**で1回だけ残します。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    assert '高速化ボタン: %s を書きます' in source, (
        "⚠ 押したことを記録していません")
    assert 'AUTOボタン: %s を書きます' in source


def test_押した側で記録するの挙動(tmp_path, caplog):
    """★RX-0011: 字面の検査に挙動を併設。

    実物の窓でボタンを**押し**、`retroux.gui` の DEBUG に「書きます」が
    **1回だけ**出ることを見ます。★そのあと実機の値を何度取り込んでも
    増えない（⚠ 毎ポーリング鳴るのが 195件の正体）。
    """
    import logging
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import pytest

    pytest.importorskip("PySide6", reason="PySide6 が無い環境")
    from PySide6.QtWidgets import QApplication

    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.main_window import MainWindow
    from retroux.ui.view_model import ViewModel

    assert QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_bytes(b"")
    vm = ViewModel(Recorder(db, "HASH", events, tmp_path / "command.json"),
                   db, "HASH", {1: "スライム"})
    vm._mission_path = tmp_path / "mission.yaml"
    win = MainWindow(vm, interval_ms=10 ** 6, log_path=tmp_path / "r.log")
    try:
        def presses(label: str) -> list[str]:
            return [r.getMessage() for r in caplog.records
                    if r.name == "retroux.gui" and r.getMessage().startswith(label)]

        # ★初期の入切は問わない（押せば**反対**になる）
        t1 = "OFF" if win._turbo_button.isChecked() else "ON"
        a1 = "OFF" if win._auto_button.isChecked() else "ON"
        t2 = "ON" if t1 == "OFF" else "OFF"
        with caplog.at_level(logging.DEBUG, logger="retroux.gui"):
            win._turbo_button.click()          # ★人が押す道（toggled 経由）
            assert presses("高速化ボタン") == [f"高速化ボタン: {t1} を書きます"]
            win._auto_button.click()
            assert presses("AUTOボタン") == [f"AUTOボタン: {a1} を書きます"]

            # ★押していない間に実機の値を何度も取り込む（毎ポーリングの道）
            for _ in range(10):
                win._sync_turbo_button(False)
                win._sync_auto_button(False)
                vm.recorder.poll()
            assert presses("高速化ボタン") == [f"高速化ボタン: {t1} を書きます"], (
                "⚠ 押していないのに鳴っています（★鳴りすぎも壊れ方）")
            assert presses("AUTOボタン") == [f"AUTOボタン: {a1} を書きます"]

            win._turbo_button.click()          # ★もう一度押す（戻す）
            assert presses("高速化ボタン")[-1] == f"高速化ボタン: {t2} を書きます"
            assert len(presses("高速化ボタン")) == 2
    finally:
        win.close()


def test_毎ポーリング通る道にログを置かない():
    """★★★ **これが 195件の正体**（2026-08-07）。

    ⚠⚠ `apply_command` の「値が変わっていない」分岐は**正常な道**です。
      ★ここにログを書くと、押していなくても毎回出ます。
    """
    source = SPEED.read_bytes().decode("utf-8")
    start = source.index("if want == self.turbo_commanded then")
    body = source[start:start + 120]
    assert "self:log" not in body, (
        "⚠⚠ 毎ポーリング通る道にログがあります（★195件出ます）")


def test_AUTOと高速化を排他にしていない():
    """⚠⚠ **2つは独立した軸**（2026-07-31 の指示書 §2）。

    ★ラジオボタンにすると【AUTO ON かつ 高速化 ON】が選べなくなります。
      ⚠ それが**いちばん普通の使い方**（自動戦闘を倍速で回す）です。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    # ★どちらも押せるトグルであること
    assert "self._auto_button" in source and "self._turbo_button" in source
    # ⚠ 片方から他方を決めていないこと
    assert "_sync_auto_button(getattr(game, \"auto_enabled\", None))" in source
    assert "_sync_turbo_button(getattr(game, \"turbo_enabled\", None))" \
        in source


# --- ⚠⚠ 状態バーに内部の表現を出さない（★画面写真で気づいた）----------

def test_成功したアクションを警告にしない():
    """★★★ **`None でない = 失敗` ではありません**（2026-08-07）。

    `dispatch()` は**成功しても結果を返します**。そのため成功のたびに
    状態バーへ中身がそのまま出ていました:

        ⚠ ActionResult(success=True, message='', restore_focus=None)

    ⚠ 内部の表現を人に見せない。★依頼者の画面写真で気づきました。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    start = source.index("def run_action")
    body = source[start:start + 1400]
    assert "getattr(result, \"success\", True)" in body, (
        "⚠⚠ 成功/失敗を見ずに、返り値の有無で判定しています")
    assert 'f"⚠ {problem}"' not in body, (
        "⚠ 結果の中身をそのまま画面へ出しています")


def test_理由が空でも何ができなかったか出す():
    """⚠ 空欄だと「押したのに何も起きない」と同じです。"""
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    start = source.index("def run_action")
    body = source[start:start + 1400]
    assert "を実行できません" in body
