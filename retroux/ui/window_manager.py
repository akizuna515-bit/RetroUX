"""ウィンドウと OS まわりの世話係（2026-08-01 のリファクタ指示書 §5.2）。

★★ **画面から Windows API を追い出す。** ★★

  `main_window.py` が `window_align` と `subprocess` を直に呼んでいた。
  ⚠ そうすると:
    ・画面のテストが Win32 を必要とする
    ・「窓をどう探すか」がボタンごとに散らばる
    ・Windows 以外へ持っていくとき、画面ごと書き直しになる

  ★ここが**唯一の窓口**。画面は「並べて」「ゲームへ戻して」と言うだけ。

## 何を持つか（指示書 §5.2）

  FCEUX と Lua Script の探索 / 初期配置 / 保存位置の復元 / 標準レイアウト /
  画面外補正 / DPI・作業領域 / フォーカス復帰 / Lua Script の最小化

## ⚠ 使えない環境でも落ちない

  Windows 以外や、Win32 が使えない環境では**何もせず False を返す**。
  ★例外を投げると、画面の組み立てごと止まる。窓が並ばないだけなら遊べる。
"""

from __future__ import annotations

import pathlib
import subprocess

from ..core import layout, window_align

#: エクスプローラ等を出すときの旗。⚠ コンソールを一瞬も光らせない。
#  （`CREATE_NO_WINDOW`。R-1 で「黒い窓が出る」を潰した経緯がある）
_NO_WINDOW = 0x08000000


class WindowManager:
    """窓の配置と OS への働きかけをまとめる。

    ★依存は**コンストラクタで注入**する（指示書 §18）。
      ⚠ 中でグローバル設定を読むと、テストが本物の設定を触ることになる。
    """

    def __init__(self, config_loader, logger=None) -> None:
        #: `user_config` を返す呼び出し可能なもの（呼ぶたびに読み直せる）
        self._config = config_loader
        self._log = logger

    # --- 使えるか ---------------------------------------------------

    @property
    def available(self) -> bool:
        """この環境で窓を操作できるか。★できなくても遊べる。"""
        return window_align.available()

    def foreground_window_title(self) -> str:
        """いま最前面のウィンドウ名（★フォーカス確認の切り分け用 / RX-0078）。"""
        return window_align.foreground_title()

    def _emulator_title(self) -> str:
        return self._config().emulator.window_title_contains

    def _lua_title(self) -> str:
        return self._config().emulator.lua_window_title

    # --- 並べる -----------------------------------------------------

    def arrange(self, *, force: bool = False, wait: float = 0.0):
        """標準レイアウトへ並べる。戻り値: `(動かした数, 報告の行)`。

        ★並べ方は `tools/align_windows.arrange` に1つだけ置く。
          ⚠ コマンドとボタンで別々に書くと、片方だけ直したときに静かにずれる。
        """
        from ..tools import align_windows

        return align_windows.arrange(self._config(), wait=wait, force=force)

    def reset_layout(self, forget_window_state=None):
        """覚えている配置を捨てて標準へ戻す（指示書 §7.1）。

        手順は指示書のとおり:
          1. 覚えている配置を捨てる
          2. 標準レイアウトを計算し直して並べる
          3. Lua Script を最小化（`arrange` の中）

        ⚠ 1 をしないと `arrange` が「覚えているから動かさない」と判断して
          **押しても何も起きない**。

        @param forget_window_state 画面側が持つ記憶を捨てる処理（あれば）
        """
        layout.clear()
        if forget_window_state is not None:
            forget_window_state()
        return self.arrange(force=True)

    # --- フォーカス -------------------------------------------------

    def focus_emulator(self) -> bool:
        """ゲーム画面へ操作を返す。

        ★★ **前面化を呼ぶのはここだけ**（指示書 §5.2）★★
          ⚠ 各ボタンに書くと、どれかで必ず書き忘れる。

        ⚠ Windows は前面化を拒否することがある。**失敗しても例外にしない**
          （アクション自体は成功している）。
        """
        if not self.available:
            return False
        return window_align.focus(self._emulator_title())

    # --- Lua Script -------------------------------------------------

    def minimize_lua_window(self) -> bool:
        """Lua Script を最小化する。

        ⚠⚠ **閉じない**（閉じると Lua が止まる）。
          隠す（`SW_HIDE`）にもしない。タスクバーからも消えて戻せなくなる。
        """
        if not self.available:
            return False
        return window_align.minimize(self._lua_title())

    def show_lua_window(self) -> bool:
        """最小化した Lua Script を戻す（障害調査用 / 指示書 §9.2）。

        ★**再表示手段を必ず残す**。戻せない機能は入れない。
        """
        if not self.available:
            return False
        return window_align.restore(self._lua_title())

    # --- 終了を伝える -----------------------------------------------

    def ask_emulator_to_close(self) -> bool:
        """FCEUX に「閉じて」と伝える。★**強制終了しない**。

        ⚠ 強制終了すると、書きかけのセーブステートが壊れうる。
        """
        if not self.available:
            return False
        closed = window_align.close_window(self._emulator_title())
        # ★Lua Script も一緒に閉じる（本体が消えたのに残ると邪魔）
        window_align.close_window(self._lua_title())
        return closed

    # --- OS へ見せる -------------------------------------------------

    def reveal_in_explorer(self, path) -> str | None:
        """エクスプローラでその場所を開く。戻り値は**失敗の理由**。

        ★ファイルを指定したときは**そのファイルを選んだ状態**で開く。
          ⚠ フォルダだけ開くと、目当てのファイルを探させることになる。
        """
        target = pathlib.Path(path)
        try:
            if target.is_file():
                args = ["explorer", f"/select,{target.resolve()}"]
            else:
                args = ["explorer", str(target.resolve())]
            # ⚠ コンソールを一瞬も光らせない（R-1 の経緯）
            subprocess.Popen(args, creationflags=_NO_WINDOW)
        except Exception as exc:                       # noqa: BLE001
            if self._log is not None:
                self._log.warning("フォルダを開けません（%s）: %s", target, exc)
            return f"フォルダを開けませんでした: {exc}"
        return None

    def open_with_default_app(self, path) -> str | None:
        """OS 既定のアプリで開く（設定ファイルの外部編集など）。"""
        target = pathlib.Path(path)
        try:
            subprocess.Popen(["cmd", "/c", "start", "", str(target)],
                             creationflags=_NO_WINDOW)
        except Exception as exc:                       # noqa: BLE001
            if self._log is not None:
                self._log.warning("開けません（%s）: %s", target, exc)
            return f"開けませんでした: {exc}"
        return None
