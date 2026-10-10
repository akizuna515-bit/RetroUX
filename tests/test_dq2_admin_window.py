"""DQ2 の管理画面（RX-0171〜0174 / 2026-10-06）。

★依頼者 2026-10-06: 状態（版・build・ROM / FCEUX / データ保存場所・控え）/ キー設定（既存の窓を開く）/
  プレイデータ（保存場所・最新の退避・退避）。⚠ 初期化・復元・移行の実行・場所の変更はしない。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from retroux.core import dq2_admin as A  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# --- 控えの状態（BP-27 / ★画面側の判定）-------------------------------------------

@pytest.mark.parametrize("fceux, fcs, running, saves, want", [
    (True, True, True, 3, A.OK),
    (True, True, False, 3, A.STOPPED),
    (True, False, True, 0, A.NO_FCS),
    (True, True, True, 0, A.NO_SAVES),
    (False, False, False, 0, A.NO_FCEUX),        # ★場所の問題を先に（= 直す手がかり）
    (True, False, False, 0, A.NO_FCS),
])
def test_控えの状態を区別する(fceux, fcs, running, saves, want):
    assert A.judge_backup(fceux_exists=fceux, fcs_exists=fcs, running=running, saves=saves) == want
    assert A.BACKUP_LABELS[want]


def _cfg(tmp_path: Path, *, fceux=True, fcs=True, saves=("DQ2_J.fc1",)):
    """★dq2_paths が読む設定の代わり（⚠ 本物の設定・本物の FCEUX を見ない）。"""
    exe = tmp_path / "fceux" / "fceux64.exe"
    if fceux:
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"")
    if fcs:
        (exe.parent / "fcs").mkdir(parents=True, exist_ok=True)
        for name in saves:
            (exe.parent / "fcs" / name).write_bytes(b"s")
    import types

    rom = tmp_path / "rom" / "DQ2_J.nes"
    # ★dq2_paths は `cfg.paths.rom` / `cfg.paths.fceux` を読む（★本物の dq2_user_config と同じ形）
    return types.SimpleNamespace(paths=types.SimpleNamespace(rom=str(rom), fceux=str(exe)))


def test_控えの状態を本物の置き場で数える(tmp_path, monkeypatch):
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    cfg = _cfg(tmp_path, saves=("DQ2_J.fc1", "DQ2_J.fc2", "DQ3_J.fc1"))
    got = A.backup_view(cfg, lock=tmp_path / "x.lock", busy=lambda _lock: True)
    assert got.code == A.OK and got.label == "正常"
    lines = dict(got.lines)
    assert lines["セーブステート"].startswith("2 件"), "⚠ DQ3 のセーブまで数えている / 数えていない"
    assert str(tmp_path / "fceux" / "fcs") == lines["監視先"]


def test_控えが止まっていれば止まっていると出す(tmp_path, monkeypatch):
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    got = A.backup_view(_cfg(tmp_path), lock=tmp_path / "x.lock", busy=lambda _lock: False)
    assert got.code == A.STOPPED and got.warning


def test_FCEUXやfcsやセーブが無いことを区別する(tmp_path, monkeypatch):
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    busy = lambda _lock: True                                  # noqa: E731
    assert A.backup_view(_cfg(tmp_path / "a", fceux=False, fcs=False), lock=tmp_path / "l",
                         busy=busy).code == A.NO_FCEUX
    assert A.backup_view(_cfg(tmp_path / "b", fcs=False), lock=tmp_path / "l", busy=busy).code == A.NO_FCS
    assert A.backup_view(_cfg(tmp_path / "c", saves=()), lock=tmp_path / "l", busy=busy).code == A.NO_SAVES


def test_控えの状態ファイルの形は変えていない():
    """⚠ DQ3 も `backup_status` を読む → 欄を足さず、画面側で判定する（依頼者 2026-10-06）。"""
    import inspect

    from retroux.core import backup_status

    params = list(inspect.signature(backup_status.write).parameters)
    assert params == ["lock_path", "running", "generations", "watching", "destination",
                      "interval", "last_backup", "session", "last_error"], params


# --- 版・Python の種別（BP-05）--------------------------------------------------

def test_版とbuildを1行で出す():
    from retroux.core import dq2_version

    got = dq2_version.stamp()
    assert got.startswith("RetroUX DQ2 " + dq2_version.get_version()) and " / build " in got


@pytest.mark.parametrize("exe, want", [
    (r"C:\Tools\RetroUX-DQ2-1.2.0\runtime\python\pythonw.exe", "同梱 Python"),
    (r"C:\Projects\RetroUX\.venv\Scripts\pythonw.exe", "開発環境（.venv）"),
    (r"C:\Python312\python.exe", "そのほかの Python"),
])
def test_Pythonの種別(exe, want):
    assert A.runtime_kind(exe) == want


def test_診断にbuildと種別と置き場所を足しても個人のパスは出さない():
    from retroux.core import diagnostics

    got = diagnostics.collect()
    assert got["build"] and got["Python の種別"] and got["置き場所"]
    text = diagnostics.as_text(got)
    assert str(ROOT) not in text, "⚠⚠ 診断に場所そのものが出ている"


# --- 移行の状態（★実行しない）-----------------------------------------------------

def test_移行の状態を言葉にする(monkeypatch):
    from retroux.core import dq2_data as D

    here = D.Places(write_root=Path("x"), db=Path("x/db"), events=Path("x/e"), fcs_dir=Path("x/f"))
    monkeypatch.setattr(D, "read_marker", lambda _root: {"history": [{"event": "created"}]})
    monkeypatch.setattr(D, "used_reason", lambda _places: None)
    got = A.migration_view(here)
    assert got.can_migrate and "まだ遊んでいません" in got.text
    monkeypatch.setattr(D, "used_reason", lambda _places: "戦闘の記録 58 件")
    got = A.migration_view(here)
    assert not got.can_migrate and "戦闘の記録 58 件" in got.reason
    monkeypatch.setattr(D, "read_marker", lambda _root: {"history": [
        {"event": "created"}, {"event": "migrated", "at": "2026-10-05T07:00:00+09:00"}]})
    got = A.migration_view(here)
    assert not got.can_migrate and "移行済み" in got.text and "2026-10-05 07:00" in got.text


# --- 画面 -------------------------------------------------------------------------

def _window(app, tmp_path, **kw):
    from retroux.ui.admin_window import AdminWindow

    long = "C:\\" + "\\".join(["とても長いフォルダの名前" * 3] * 6) + "\\DQ2_J.nes"
    places = [A.Place("ROM", long, True), A.Place("FCEUX", "", False),
              A.Place("データ保存場所", str(tmp_path), True)]
    opts = dict(places=lambda: places,
                backup_view=lambda: A.BackupView(A.NO_SAVES, (("監視先", "x"),)),
                migration=lambda: A.MigrationView("このフォルダで遊んでいます", False, "移行できるのは新しいフォルダだけです"),
                latest=lambda: None, reveal=lambda _p: None)
    opts.update(kw)
    return AdminWindow(None, **opts), long


def test_3つの区分で独立した窓として開く(app, tmp_path):
    from PySide6.QtCore import Qt

    win, _long = _window(app, tmp_path)
    assert [win.tabs.tabText(i) for i in range(win.tabs.count())] == ["状態", "キー設定", "プレイデータ"]
    assert win.windowFlags() & Qt.WindowType.Window
    win.close()


def test_長いパスを省略せずコピーできる(app, tmp_path):
    from PySide6.QtWidgets import QApplication, QLineEdit

    win, long = _window(app, tmp_path)
    row = win.path_rows["ROM"]
    assert isinstance(row.edit, QLineEdit) and row.edit.isReadOnly()
    assert row.edit.text() == long, "⚠⚠ パスを省略している"
    row.copy()
    assert QApplication.clipboard().text() == long
    assert win.path_notes["FCEUX"].text() == "⚠ 見つかりません"
    assert not win.path_rows["FCEUX"].copy_button.isEnabled()
    win.close()


def test_データ保存場所には開くがある(app, tmp_path):
    opened = []
    win, _long = _window(app, tmp_path, reveal=lambda p: opened.append(p))
    row = win.path_rows["データ保存場所"]
    assert row.open_button is not None and row.open_button.isEnabled()
    row.open()
    assert opened == [str(tmp_path)]
    win.close()


def test_キー設定は渡された口で開く(app, tmp_path):
    """★本体の `_open_keybinding_window` を呼ぶ（RX-0173 / ⚠ 自分で窓を作らない）。"""
    calls = []
    win, _long = _window(app, tmp_path, open_keybindings=lambda: calls.append("open"))
    win.keys_button.click()
    assert calls == ["open"]
    win.close()
    win2, _long = _window(app, tmp_path, open_keybindings=None)
    assert not win2.keys_button.isEnabled() and "Ctrl+K" in win2.keys_button.toolTip()
    win2.close()


def test_押せないボタンでも理由が出る(app, tmp_path):
    """★BP-35: Qt は押せない部品にツールチップを届けない → 入れ物が代わりに出す。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip

    win, _long = _window(app, tmp_path)
    win.show()
    win.tabs.setCurrentIndex(2)
    app.processEvents()
    button = win.migrate_button
    assert not button.isEnabled()
    box = button.parentWidget()
    QToolTip.hideText()
    pos = button.mapTo(box, button.rect().center())
    ok = app.sendEvent(box, QHelpEvent(QEvent.Type.ToolTip, pos, box.mapToGlobal(pos)))
    app.processEvents()
    got = QToolTip.text()
    QToolTip.hideText()
    win.close()
    assert ok and "新しいフォルダだけ" in got, "⚠⚠ 押せない理由が出ない: %r" % got


def test_退避は別の糸で動き結果と最新を出す(app, tmp_path):
    started = []
    latest = {"v": None}

    def fake_backup():
        started.append(time.monotonic())
        time.sleep(0.2)
        latest["v"] = {"name": "20261006-0700", "created": "2026-10-06T07:00:01", "count": 1, "path": tmp_path}
        return {"ok": True, "target": tmp_path / "20261006-0700", "saved": ["retroux.sqlite3"], "error": None}

    win, _long = _window(app, tmp_path, backup=fake_backup, latest=lambda: latest["v"])
    assert win.latest_label.text() == "まだありません"
    assert win.start_backup() is True
    assert not win.backup_button.isEnabled() and "退避しています" in win.backup_button.toolTip()
    assert win.start_backup() is False, "⚠ 2 重に走らせた"
    win._backup_thread.join(5)
    win.finish_backup()
    assert "退避しました" in win.backup_message.text()
    assert "2026-10-06 07:00" in win.latest_label.text()
    assert win.backup_button.isEnabled()
    win.close()


def test_退避の失敗を黙らせない(app, tmp_path):
    def broken():
        raise OSError("ディスクがいっぱい")

    win, _long = _window(app, tmp_path, backup=broken)
    win.start_backup()
    win._backup_thread.join(5)
    win.finish_backup()
    assert "ディスクがいっぱい" in win.backup_message.text()
    win.close()


# --- プレイデータの退避（関数 / ★名前を重ねない）-------------------------------------

def test_同じ分に2回退避しても重ならない(tmp_path, monkeypatch):
    from retroux.tools import playdata as P

    monkeypatch.setattr(P, "VAULT", tmp_path / "vault")
    monkeypatch.setattr(P, "DB_PATH", tmp_path / "none.sqlite3")
    monkeypatch.setattr(P, "survey", lambda: {"db": {"size": 0, "rows": {}}, "files": [], "dirs": []})
    monkeypatch.setattr(P, "_stamp", lambda: "20261006-0700")
    a = P.backup()
    b = P.backup()
    assert a["ok"] and b["ok"]
    assert a["target"] != b["target"], "⚠⚠ 同じフォルダへ重ねて書いた"
    assert b["target"].name == "20261006-0700-2"
    got = P.latest_backup()
    assert got["count"] == 2 and got["name"] == "20261006-0700-2"
    assert json.loads((b["target"] / "manifest.json").read_text(encoding="utf-8"))["saved"] == []


def test_退避が無ければ最新はNone(tmp_path, monkeypatch):
    from retroux.tools import playdata as P

    monkeypatch.setattr(P, "VAULT", tmp_path / "vault")
    assert P.latest_backup() is None


# --- 本体とのつなぎ -----------------------------------------------------------------

#: ⚠ 本体の窓は ROM を読む（★本体の他の検査と同じ決まり / test_icon_buttons_have_tooltips）
_ROM = ROOT / "work" / "rom" / "DQ2_J.nes"
_needs_rom = pytest.mark.skipif(not _ROM.exists(), reason="ROM が無い環境")

@_needs_rom
def test_本体の右端に管理ボタンがあり既存の3つも残る(app):
    from PySide6.QtWidgets import QPushButton

    from retroux.gui import build_view_model
    from retroux.ui.main_window import MainWindow

    vm, _db = build_view_model(read_only=True)
    window = MainWindow(vm, interval_ms=100000, heartbeat=None)
    try:
        texts = [b.text() for b in window.findChildren(QPushButton)]
        for want in ("📄", "📁", "🩺", "⚙"):
            assert want in texts, want
        assert "open_settings" in window._actions.registered
        window._open_admin_window()
        admin = window._admin_window
        assert admin._open_keybindings == window._open_keybinding_window, \
            "⚠ 本体のキー設定の口を渡していない（★保存後のショートカットの作り直しがつながらない）"
        admin.keys_button.click()
        kb = window._keybinding_window
        got = []
        window._on_keybindings_applied = lambda message: got.append(message)
        kb.applied.emit("テスト")
        assert kb.isWindow()
        admin.close()
        kb.close()
    finally:
        window.close()


@_needs_rom
def test_本体のアイコンの列は右列に収まる(app):
    """⚠ 本体の右列は 362px（1366×768 で押せる幅 / 2026-08-09）。★ボタンを足しても収まる。"""
    from PySide6.QtWidgets import QPushButton

    from retroux.gui import build_view_model
    from retroux.ui.main_window import MainWindow

    vm, _db = build_view_model(read_only=True)
    window = MainWindow(vm, interval_ms=100000, heartbeat=None)
    try:
        gear = next(b for b in window.findChildren(QPushButton) if b.text() == "⚙")
        row = gear.parentWidget().layout()
        width = row.minimumSize().width() if row is not None else 0
        assert gear.width() <= 38 or gear.maximumWidth() == 38
        assert width <= 362, f"⚠ アイコンの列が右列（362px）に収まらない: {width}"
    finally:
        window.close()
