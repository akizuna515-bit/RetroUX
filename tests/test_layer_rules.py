"""層をまたぐ参照の検査（2026-08-01 のリファクタ指示書 §14）。

★★ **依存は一方通行にする。** ★★

    ui
     ↓
    application
     ↓
    core / emulator / plugins

⚠ 逆向きの参照ができると、片方を直すたびにもう片方が壊れる。
  分割の意味が無くなるので、**機械で見張る**。

★見るのは `import` だけ（AST）。⚠ 内部の関数名は固定しない
  （指示書 §14.2「内部関数名を固定するテストにはしない」）。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _module_names(path: pathlib.Path) -> list[str]:
    """そのファイルが import しているものの名前。

    ★相対 import は `.` の数を付けて返す（`..core` のように）。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):                     # pragma: no cover
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append("." * (node.level or 0) + (node.module or ""))
    return found


def _files(*parts: str):
    return sorted((PROJECT_ROOT.joinpath(*parts)).rglob("*.py"))


def _is_ui(module: str) -> bool:
    """その名前は画面の層を指しているか。

    ⚠⚠ **末尾一致で判定しない。** `PySide6.QtGui` は "ui" で終わるので、
      `endswith("ui")` だと**画像処理まで画面扱い**になる（実際に踏んだ）。
    ★区切りで割って、部品として `ui` があるかを見る。
    """
    parts = module.lstrip(".").split(".")
    return "ui" in parts or module.endswith("main_window")


def _violations(root: str, is_bad) -> list[str]:
    hits = []
    for path in _files("retroux", root):
        for name in _module_names(path):
            if is_bad(name):
                hits.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}"
                            f" -> {name}")
    return hits


# --- 逆向きの参照を作らない -------------------------------------------

def test_core_does_not_import_the_ui():
    """⚠ `core` が画面を知ると、画面なしでは動かなくなる。"""
    assert _violations("core", _is_ui) == [], _violations("core", _is_ui)


def test_application_does_not_import_the_ui():
    """★★ アクション層は画面を知らない（指示書 §2.3）★★

    ⚠ 知ると、キーボードやゲームパッドから使うときに画面が要る。
    """
    bad = _violations("application", _is_ui)
    assert bad == [], bad


def test_application_does_not_import_qt():
    """⚠ Qt を知ると、画面のない環境（テスト・将来のCLI）で使えない。"""
    bad = _violations("application", lambda m: m.startswith("PySide6"))
    assert bad == [], bad


def test_plugins_do_not_import_the_ui():
    bad = _violations("plugins", _is_ui)
    assert bad == [], bad


def test_the_ui_does_not_touch_sqlite_directly():
    """⚠ 画面が SQL を書くと、同じ問い合わせが2か所に増える。"""
    bad = _violations("ui", lambda m: m == "sqlite3")
    assert bad == [], bad


# --- Phase 1 の受入条件（指示書 §20-4）--------------------------------

def test_the_main_window_does_not_write_the_command_file_itself():
    """★★ **受入条件4**: 画面から command.json への直接書込を除去 ★★

    ⚠ 画面が JSON を組み立てていると、キー名と `request_id` の規則が
      画面のあちこちへ漏れる。契約は `CommandService` 1か所に置く。
    """
    source = (PROJECT_ROOT / "retroux" / "ui" / "main_window.py").read_text(
        encoding="utf-8")
    calls = [line.strip() for line in source.splitlines()
             if "write_command(" in line and not line.strip().startswith("#")]
    assert calls == [], calls


def test_only_the_command_service_writes_the_command_file():
    """★書き手を1つに保つ。⚠ 画面・アクション層のどこにも増やさない。"""
    writers = []
    for path in _files("retroux", "ui") + _files("retroux", "application"):
        if path.name == "command_service.py":
            continue
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            if "write_command(" in line and not line.strip().startswith("#"):
                writers.append(f"{path.name}: {line.strip()}")
    assert writers == [], writers


# --- 既知の例外（黙って許さず、理由を書いて許す）----------------------

def test_the_only_qt_use_in_core_is_the_image_helper():
    """⚠ `core/art/trim.py` だけ `QtGui` を使う（画像の切り出しのため）。

    ★★ **例外は黙って通さない。** ★★
      ここに名前を書いてあるものだけを許し、増えたら気づけるようにする。
      増やすときは「なぜ画像処理が core に要るのか」を考え直すこと。
    """
    allowed = {"retroux/core/art/trim.py"}
    bad = {v.split(" -> ")[0]
           for v in _violations("core", lambda m: m.startswith("PySide6"))}
    assert bad <= allowed, sorted(bad - allowed)


# --- Phase 3 の受入条件（指示書 §20-5）--------------------------------

def test_the_main_window_does_not_call_windows_apis():
    """★★ **受入条件5**: 画面から Windows API 処理を除去 ★★

    ⚠ 画面が Win32 を直に呼ぶと:
      ・画面のテストが Windows を必要とする
      ・「窓をどう探すか」がボタンごとに散らばる
      ・Windows 以外へ持っていくとき画面ごと書き直しになる

    ★窓口は `ui/window_manager.py` 1つだけ。
    """
    import ast

    path = PROJECT_ROOT / "retroux" / "ui" / "main_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # ⚠⚠ **文字列で探さない。** 説明文の中の `window_align.py` まで拾う
    #   （実際に踏んだ）。★AST で「呼び出し」だけを見る。
    banned = {"subprocess", "ctypes", "window_align", "align_windows"}
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in banned:
                hits.append(f"{node.value.id}.{node.attr}")
        elif isinstance(node, ast.Import):
            hits += [a.name for a in node.names if a.name in banned]
    assert hits == [], f"Windows API を直に呼んでいる: {sorted(set(hits))}"


# --- Phase 5 の受入条件（指示書 §8.2 / §8.3）--------------------------

def test_the_map_canvas_does_not_know_about_the_database():
    """★★ **§8.2「DBやSQLiteを参照しない」** ★★

    ⚠ 描き方を試すのに記録を用意しないと動かせない、という状態を避ける。
      canvas に渡すのは**マスの並びだけ**。どこから来たかは知らない。
    """
    banned = ("sqlite3", "db", "repository", "navigation")
    bad = []
    for name in _module_names(
            PROJECT_ROOT / "retroux" / "ui" / "map" / "canvas.py"):
        parts = name.lstrip(".").split(".")
        if any(p in banned for p in parts):
            bad.append(name)
    assert bad == [], f"canvas が記録の側を知っている: {bad}"


def test_the_map_presenter_does_not_touch_widgets():
    """★★ **§8.3**: presenter は**出す中身**だけを作る ★★

    ⚠ 触ると「この文言で合っているか」を確かめるのに画面を建てる必要が出る。
      ★分割前は `_floor_text` が文字列を作りながら `setStyleSheet` していた。
        いまは `FloorText(text, warn)` を返し、**色は画面が決める**。
    """
    path = PROJECT_ROOT / "retroux" / "ui" / "map" / "presenter.py"
    bad = [n for n in _module_names(path) if n.startswith("PySide6")]
    assert bad == [], f"presenter が Qt を知っている: {bad}"

    # ⚠ import だけでなく**呼び出し**も見る（遅延 import で逃げられる）
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [node.attr for node in ast.walk(tree)
             if isinstance(node, ast.Attribute)
             and node.attr in {"setStyleSheet", "setText", "setEnabled",
                               "addItem", "update"}]
    assert calls == [], f"presenter が widget を触っている: {sorted(set(calls))}"


def test_the_old_map_window_only_re_exports():
    """★旧 `map_window.py` は**呼び出し口だけ**（指示書 §8）。

    ⚠ ここに中身を書き足すと、また1つの大きなファイルに戻る。
    """
    path = PROJECT_ROOT / "retroux" / "ui" / "map_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = [n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    assert defined == [], f"再エクスポート以外が書かれている: {defined}"


def test_only_the_window_manager_touches_the_os():
    """★UI の層で OS を叩いてよいのは `window_manager.py` だけ。

    ⚠ `QDesktopServices` は Qt の道具なので画面に残してよい（対象外）。
    """
    offenders = []
    for path in _files("retroux", "ui"):
        if path.name == "window_manager.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "`" in stripped:
                continue
            if "subprocess." in stripped or "ctypes.WinDLL" in stripped:
                offenders.append(f"{path.name}: {stripped}")
    assert offenders == [], offenders
