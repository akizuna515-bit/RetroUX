"""AUTO と 高速化 が**独立した2軸**であること（2026-07-31 の指示書 §2）。

    | 軸 | 状態 | 所有 |
    | --- | --- | --- |
    | 誰が操作するか | `auto_enabled` | `battle_controller.lua` |
    | どの速度で動かすか | `turbo_enabled` | `speed_controller.lua` |

★★ **2026-08-01 のリファクタで、実装文字列の検査をやめた。** ★★

  前は `bridge.lua` の中身を `assert "_set_turbo" in source` のように
  文字列で見ていた。⚠ **分割するたびに、直っているのに赤くなる。**
  リファクタ指示書 §10.2-C が消せと言っている形そのもの。

  いまは **`research/probes/active/auto_turbo_test.lua` を本物の Lua で走らせて**、
  公開インターフェースの振る舞いを見る（§10.3）。
  12 節・約40 項目あり、順序も理由の文言も向こうで押さえてある。

★ここに残すのは **契約**（`state.json` に何が出るか）と
  **同梱の既定が正しいか**だけ。そこは静的検査が適切（§10.2-A）。
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = PROJECT_ROOT / "research" / "probes" / "active" / "auto_turbo_test.lua"
DLL = PROJECT_ROOT / "tools" / "fceux" / "lua5.1.dll"


# --- 1. 本物の Lua で振る舞いを確かめる -------------------------------

@pytest.mark.skipif(not (DLL.exists() and RUNNER.exists() and HARNESS.exists()),
                    reason="Lua を動かす材料が無い")
def test_the_two_axes_behave_independently():
    """★★ **本題**。`battle_controller` と `speed_controller` を実際に動かす。

    ⚠ 落ちたときは Lua 側の出力をそのまま出す（どの節で落ちたか分かる）。
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT)
    assert proc.returncode == 0, (
        "AUTO と高速化の独立が壊れています:\n"
        + (proc.stdout or "") + (proc.stderr or ""))
    assert "すべて通りました" in (proc.stdout or "")


# --- 2. 契約（`state.json` に何が出るか）------------------------------

def _bridge() -> str:
    return (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
            / "bridge.lua").read_text(encoding="utf-8")


def test_both_axes_are_reported_separately():
    """★画面が2つのトグルを別々に描けること（指示書 §5.5）。

    ⚠ 片方から他方を推測させない（「速いなら AUTO だろう」は成り立たない）。
    """
    src = _bridge()
    for key in ("auto_input", "force_auto", "manual_latched",
                "auto_enabled", "turbo_enabled"):
        assert f'add("{key}"' in src, f"{key} を state.json に出していない"


def test_a_missing_field_stays_unknown_rather_than_off():
    """⚠ 古い Lua が繋がっているときに「切ってある」と誤表示しない。"""
    from retroux.core.bridge.state_reader import _parse

    assert _parse({}).turbo_enabled is None
    assert _parse({}).auto_enabled is None
    assert _parse({"turbo_enabled": False}).turbo_enabled is False
    assert _parse({"auto_enabled": True}).auto_enabled is True


def test_the_a_key_is_actually_wired_to_the_toggle():
    """⚠⚠ **関数の中身が正しくても、呼ばれていなければ意味がない。**

    ★`research/probes/active/break_release.py` が見つけた穴（2026-07-31）。
      振る舞いテストは「関数を直接呼ぶ」ので、**繋がっているか**は見ない。
    """
    src = _bridge()
    i = src.index("function Bridge:_poll_hotkeys")
    j = src.index("\nfunction Bridge:", i + 10)
    body = src[i:j]
    assert 'action == "toggle_auto" or action == "force_auto"' in body, \
        "AUTO の分岐が無い（または古い名前を受けなくなっている）"
    k = body.index('action == "toggle_auto"')
    assert "_toggle_auto_from_hotkey" in body[k:k + 200]


# --- 3. 画面: 2つのトグルが互いを上書きしないこと ---------------------

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPushButton,
)

from retroux.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        created = QApplication([])
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")
    yield created


class _Stub:
    """追従の処理が触るものだけを持つ入れ物。"""

    def __init__(self, auto: bool, turbo: bool) -> None:
        self._auto_button = self._make("AUTO", auto)
        self._turbo_button = self._make("高速化", turbo)
        self.written: list = []
        self.clicks: list = []
        self._auto_button.toggled.connect(
            lambda on: self.clicks.append(("auto", on)))
        self._turbo_button.toggled.connect(
            lambda on: self.clicks.append(("turbo", on)))
        self.vm = types.SimpleNamespace(read_only=False)
        # ★人が頼んだ値の控え（2026-08-07 / 軽量化指示書 §7.3）。
        #   ⚠ ここの検査は「人は押していない」場面なので**空**が正しい。
        #     ★空なら、これまでどおり実機の値がそのまま効きます。
        self._pending_toggle: dict = {}
        self._align_status = QLabel("")

    @staticmethod
    def _make(label: str, checked: bool) -> QPushButton:
        b = QPushButton(f"{label} {'ON' if checked else 'OFF'}")
        b.setCheckable(True)
        b.setChecked(checked)
        return b

    def _write_turbo_command(self, on: bool):
        self.written.append(("turbo", on))
        return None

    def _write_auto_command(self, on: bool):
        self.written.append(("auto", on))
        return None

    _sync_toggle = MainWindow._sync_toggle
    # ★2026-08-11: 合わせる道もツールチップを書き直すようになった
    #   （⚠ 前はアイコンの字を「AUTO ON」に潰していた）。
    _apply_toggle_tip = staticmethod(MainWindow._apply_toggle_tip)
    _auto_tip = "AI に戦闘の操作を任せるかを切り替えます"
    _turbo_tip = "戦闘速度だけを切り替えます"

    def sync_turbo(self, value) -> None:
        MainWindow._sync_turbo_button(self, value)

    def sync_auto(self, value) -> None:
        MainWindow._sync_auto_button(self, value)


def test_syncing_one_axis_leaves_the_other_alone(app):
    stub = _Stub(auto=True, turbo=True)
    stub.sync_auto(False)
    assert stub._auto_button.isChecked() is False
    assert stub._turbo_button.isChecked() is True, "高速化まで変わった"
    assert stub.written == [("auto", False)]

    stub.sync_turbo(False)
    assert stub._auto_button.isChecked() is False
    assert stub.written == [("auto", False), ("turbo", False)]


def test_following_the_hotkey_does_not_write_back(app):
    """⚠⚠ `toggled` が飛ぶと command.json を書き返して往復する。"""
    for name in ("auto", "turbo"):
        stub = _Stub(auto=True, turbo=True)
        getattr(stub, f"sync_{name}")(False)
        assert stub.clicks == [], f"{name}: toggled が飛んだ"


def test_syncing_the_same_value_does_nothing(app):
    """⚠ 追従は**毎回**呼ばれる。同じ値で書くと command.json を書き続ける。"""
    stub = _Stub(auto=True, turbo=True)
    for _ in range(5):
        stub.sync_auto(True)
        stub.sync_turbo(True)
    assert stub.written == []


def test_an_undelivered_state_leaves_the_buttons_alone(app):
    """⚠ 届いていない（None）ときに勝手に OFF へ倒さない。"""
    stub = _Stub(auto=True, turbo=True)
    stub.sync_auto(None)
    stub.sync_turbo(None)
    assert stub._auto_button.isChecked() is True
    assert stub._turbo_button.isChecked() is True
    assert stub.written == []


def test_the_next_click_after_a_hotkey_change_still_reaches_lua(app):
    """★追従でファイルも書き戻さないと、次の1回が効かない。"""
    stub = _Stub(auto=True, turbo=True)
    stub.sync_auto(False)
    assert stub.written == [("auto", False)]
    stub._auto_button.setChecked(True)
    assert stub.clicks == [("auto", True)]
