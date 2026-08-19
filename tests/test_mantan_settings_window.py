"""まんたん設定画面のテスト（2026-08-02 / 指示書 §15.2）。

★★ 確かめたいことの中心 ★★

  1. 保存済みの設定が画面に出る
  2. ⚠ **表示名と内部値が対応している**（画面に文字列を直書きしない）
  3. 保存で YAML ができ、キャンセルでは何も書かない
  4. 既定値へ戻せる（★戻しただけでは保存しない）
  5. ⚠⚠ **設定が壊れていても画面が開き、理由が出る**（指示書 §4.2）
  6. 戦術プロフィール画面への導線が動く
"""

from __future__ import annotations

import os

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from retroux.core.mantan import (            # noqa: E402
    ITEM_POLICY_LABELS, MP_POLICY_LABELS, MantanSettings, save,
)
from PySide6.QtWidgets import QApplication      # noqa: E402
from retroux.ui.mantan_settings_window import (  # noqa: E402
    MantanSettingsWindow,
)


@pytest.fixture(scope="module")
def qapp():
    """★既存の GUI テストと同じ形（`test_tactics_profile_window.py`）。"""
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        yield QApplication([])
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    """★書き込み先を tmp へ逃がす。本物の config/ を汚さない。"""
    path = tmp_path / "mantan.yaml"
    # ⚠ 設定生成は本物を動かさない（work/generated を書き換えないため）
    monkeypatch.setattr(MantanSettingsWindow, "_regenerate",
                        lambda self: (True, ""))
    win = MantanSettingsWindow(user_path=path)
    yield win, path
    win.close()


def test_既定値が画面に出る(window):
    win, _path = window
    assert win._percent.value() == 90
    assert win._herb.currentData() == "after_spells"
    assert win._mp.currentData() == "remaining_ratio_balance"
    assert win._spells.isChecked() is True
    assert win._reserve.isChecked() is True


def test_保存済みの設定が画面に出る(window):
    win, path = window
    save(MantanSettings(target_hp_percent=65, herb_policy="before_spells",
                        mp_policy="most_mp", healing_spells_enabled=False),
         path)
    win.reload()
    assert win._percent.value() == 65
    assert win._herb.currentData() == "before_spells"
    assert win._mp.currentData() == "most_mp"
    assert win._spells.isChecked() is False


def test_表示名と内部値が対応している(window):
    """⚠ 画面に文字列を直書きすると、設定ファイル側と食い違う。

    ★`settings.py` の対応表だけを使っていることを確かめる。
    """
    win, _path = window
    got = {win._herb.itemData(i): win._herb.itemText(i)
           for i in range(win._herb.count())}
    assert got == ITEM_POLICY_LABELS
    got = {win._mp.itemData(i): win._mp.itemText(i)
           for i in range(win._mp.count())}
    assert got == MP_POLICY_LABELS


def test_HP割合の範囲は50から100(window):
    win, _path = window
    assert win._percent.minimum() == 50
    assert win._percent.maximum() == 100


def test_保存するとYAMLができる(window):
    win, path = window
    win._percent.setValue(80)
    win._mp.setCurrentIndex(win._mp.findData("spent_mp_balance"))
    assert win.save_settings() is True
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["target_hp_percent"] == 80
    assert data["mp_allocation"]["policy"] == "spent_mp_balance"


def test_キャンセルでは保存しない(window):
    win, path = window
    win._percent.setValue(55)
    win.close()
    assert not path.exists()


def test_既定値に戻せる_ただし保存はしない(window):
    win, path = window
    win._percent.setValue(55)
    win._herb.setCurrentIndex(win._herb.findData("disabled"))
    win.restore_defaults()
    assert win._percent.value() == 90
    assert win._herb.currentData() == "after_spells"
    # ★戻しただけでは書かない（押し間違いを守る）
    assert not path.exists()
    assert "保存していません" in win._status.text()


def test_壊れたYAMLでも画面は開き理由が出る(qapp, tmp_path, monkeypatch):
    """⚠⚠ **ここが落ちると、設定を1文字間違えただけで画面が開かなくなる。**"""
    path = tmp_path / "mantan.yaml"
    path.write_text("target_hp_percent: [壊れて\n  います:\n", encoding="utf-8")
    monkeypatch.setattr(MantanSettingsWindow, "_regenerate",
                        lambda self: (True, ""))
    win = MantanSettingsWindow(user_path=path)
    try:
        assert win._percent.value() == 90          # ★既定へ落ちる
        assert win._problems.isVisible() or win._problems.text()
        assert "壊れ" in win._problems.text()
    finally:
        win.close()


def test_範囲外の値でも画面は開き理由が出る(qapp, tmp_path, monkeypatch):
    path = tmp_path / "mantan.yaml"
    path.write_text(yaml.safe_dump({"target_hp_percent": 999}),
                    encoding="utf-8")
    monkeypatch.setattr(MantanSettingsWindow, "_regenerate",
                        lambda self: (True, ""))
    win = MantanSettingsWindow(user_path=path)
    try:
        assert win._percent.value() == 90
        assert "999" in win._problems.text()
    finally:
        win.close()


def test_保存に失敗しても画面の値を消さない(window, monkeypatch):
    """⚠ 失敗を黙って飲み込まない。★入力もそのまま残す。"""
    win, _path = window
    import retroux.ui.mantan_settings_window as mod

    def _boom(*_a, **_kw):
        raise OSError("書けません")

    monkeypatch.setattr(mod, "save", _boom)
    monkeypatch.setattr(mod.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    win._percent.setValue(70)
    assert win.save_settings() is False
    assert win._percent.value() == 70            # ★消えていない
    assert "保存できませんでした" in win._status.text()


def test_戦術プロフィールへの導線が動く(window):
    win, _path = window
    fired = []
    win.open_tactics.connect(lambda: fired.append(1))
    win._tactics_button.click()
    assert fired == [1]


def test_最低残存MPの数値欄は作らない(window):
    """指示書 §5.2「この画面に最低残存MPの数値入力欄は作らない」。

    ★戦術プロフィールと二重管理にしないため。
    """
    from PySide6.QtWidgets import QSpinBox

    spins = win_spins = [w for w in window[0].findChildren(QSpinBox)]
    assert len(win_spins) == 1, [s.objectName() for s in spins]
    assert win_spins[0] is window[0]._percent


def test_保存後にLuaへの反映を試みる(qapp, tmp_path, monkeypatch):
    """★保存しただけでは Lua に届かない（指示書 §13）。"""
    path = tmp_path / "mantan.yaml"
    calls = []
    monkeypatch.setattr(MantanSettingsWindow, "_regenerate",
                        lambda self: (calls.append(1), (True, ""))[1])
    win = MantanSettingsWindow(user_path=path)
    try:
        assert win.save_settings() is True
        assert calls == [1]
        assert "次のまんたんから反映" in win._status.text()
    finally:
        win.close()


def test_反映に失敗しても保存は伝える(qapp, tmp_path, monkeypatch):
    """⚠ 保存とLua反映は別のこと。★両方の結果を出す。"""
    path = tmp_path / "mantan.yaml"
    monkeypatch.setattr(MantanSettingsWindow, "_regenerate",
                        lambda self: (False, "生成に失敗"))
    win = MantanSettingsWindow(user_path=path)
    try:
        assert win.save_settings() is True
        assert path.exists()
        assert "保存しました" in win._status.text()
        assert "生成に失敗" in win._status.text()
    finally:
        win.close()


def test_本体画面から開く導線がある():
    """★★ 「呼んでいるのに定義が無い」を機械で見張る。

    ⚠ ボタンを足しても、押したときのメソッドが無ければ実行時に落ちる。
      Python は属性が無くても**押すまで**エラーにならない。
    """
    import inspect

    from retroux.ui import main_window

    src = inspect.getsource(main_window)
    # ★ボタンがある
    assert "まんたん設定を開く" in src
    # ★押したときのメソッドが定義されている
    assert hasattr(main_window.MainWindow, "_open_mantan_settings_window")
    assert hasattr(main_window.MainWindow, "_ensure_mantan_settings_window")
    # ⚠ 戦術プロフィールへ飛べる（指示書 §5.2）
    assert "open_tactics.connect" in src


def test_窓を用意するメソッドが実際に動く(qapp):
    """⚠ ソースの文字列検査だけでは「動くか」は分からない。

    ★`MainWindow` を丸ごと作らずに、**メソッドの中身をそのまま実行**する。
      窓が作られ、シグナルが繋がるところまで通す。
    """
    from PySide6.QtWidgets import QLabel

    from retroux.ui.main_window import MainWindow

    class _Stub:
        def __init__(self):
            self._align_status = QLabel()
            self.opened = []

        def _open_tactics_window(self):
            self.opened.append(1)

    stub = _Stub()
    window = MainWindow._ensure_mantan_settings_window(stub)
    try:
        assert isinstance(window, MantanSettingsWindow)
        # ★2回目は同じ窓（増やさない）
        assert MainWindow._ensure_mantan_settings_window(stub) is window
        # ★保存の結果が本体の表示へ流れる
        window.applied.emit("できました")
        assert stub._align_status.text() == "できました"
        # ★「戦術プロフィールを開く」が本体へ届く
        window.open_tactics.emit()
        assert stub.opened == [1]
    finally:
        window.close()
