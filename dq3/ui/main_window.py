"""DQ3 の右パネル（RX3-0019 / 2026-08-29）。

★指示書 §12。DQ2 の思想を継承します。

依頼者 2026-08-29:

    1. DQ2 で採用していたボタンは引き継げるものは引き継ぎたい。
    2. 左右下のウィンドウ配置で、下ウィンドウに戦闘モンスターとログを
       表示させたい。

```text
  左        中央           右          下
  見た地図  FCEUX          この画面    戦闘
```

★戦闘は `dq3/ui/battle_window.py`（**別ウィンドウ**）へ出しました。

## ⚠ DQ2 から引き継いだボタン

| ボタン | DQ2 での名前 | ⚠ 引き継ぎ方 |
| --- | --- | --- |
| 整列 | `align` | ★同じ並び（左=地図 / 中央=FCEUX / 右=この画面 / 下=戦闘） |
| AUTO | `auto` | ★`dq3-command.json` 経由で Lua の `A` と同じこと（★戦闘の本体でだけ押せる / RX3-0169） |
| ターボ | `turbo` | ★同じく `T`。★**Auto 中の戦闘の速さ**（⚠ Auto OFF のときは押せない / RX3-0169） |
| まんたん | `mantan` | ★同じく `M` |
| 終了 | `exit` | ⚠ **窓を閉じるだけ**（★DQ2 のようなセーブ保護はまだ無い） |

⚠ 引き継げなかったもの: 図鑑・戦術・戦況（★DQ3 の中身がまだ無い）。

## ⚠⚠ `retroux/` は変更しません

`RX3-0011` の前提です。★import するだけ。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMessageBox,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import paths
# ★DQ3 の FCEUX の窓だけに働きかける（RX3-0504 / DQ2 共存安全化）。
#   ⚠ 題名だけで探すと、DQ2 の FCEUX を閉じる・動かす・Lua 窓を最小化する（調査 §3 Q3）。
from . import fceux_windows as window_align
from . import icon_button
from . import layout as layout_mod
from .battle_window import Dq3BattleWindow
from .commands import CommandWriter
from .map_window import Dq3MapWindow
from .party_panel import Dq3PartyPanel

#: ★画面を見直す間隔。⚠ DQ2 と同じ 500ms
DEFAULT_INTERVAL_MS = 500

#: ★★ AUTO / TURBO の意味（RX3-0237 / 依頼者「DQ3 戦闘AUTO / TURBO UI見直し仕様」）
#:   AUTO = AI に任せる（★入れると TURBO も入る / 切ると TURBO も切れる）、TURBO = 戦闘の速さだけ（★AUTO は変えない）。
#:   ⚠ RX3-0169（2026-09-11）の「Turbo = Auto 中の速さ」から変えた（★AUTO OFF / TURBO ON = 手動操作・高速）。
AUTO_TIP = ("戦闘をAIに任せます（Turboも入ります）。" + chr(10) + "もう一度押すと手動に戻ります（Turboも切れます）。"
            + chr(10) + "戦闘中は A キーでも切り替えられます。")
TURBO_TIP = ("戦闘の速さだけを切り替えます（Autoはそのまま）。" + chr(10)
             + "戦闘中は T キーでも切り替えられます。")
TURBO_TIP_DISABLED = "Turboは戦闘中に使えます。" + chr(10) + TURBO_TIP


def battle_buttons(raw: dict) -> dict:
    """★★ state.json から、AUTO / TURBO ボタンの**実効の**状態を決める（RX3-0237 仕様 §4・§7）。

    ```text
    MANUAL        AUTO OFF / TURBO OFF   通常操作・等速
    MANUAL_TURBO  AUTO OFF / TURBO ON    手動操作・高速
    AUTO_NORMAL   AUTO ON  / TURBO OFF   自動戦闘・等速
    AUTO_TURBO    AUTO ON  / TURBO ON    自動戦闘・高速（★ふつうはこれ）
    ```

    ⚠ 表示は「希望」ではなく**いま実際にどう動いているか**（★速くなっていなければ TURBO OFF）。
    ★押せるのは戦闘の本体（ACTIVE）だけ（★AUTO・TURBO とも / ⚠ RX3-0169 は TURBO を AUTO 中だけにしていた）。
    """
    raw = raw or {}
    active = raw.get("battle_phase") == "ACTIVE"
    auto = bool(raw.get("auto_enabled"))
    turbo = bool(raw.get("turbo_enabled"))
    state = ("AUTO_TURBO" if turbo else "AUTO_NORMAL") if auto else ("MANUAL_TURBO" if turbo else "MANUAL")
    return {"state": state, "auto_on": auto, "turbo_on": turbo,
            "auto_enabled": active, "turbo_enabled": active}

#: ★★ 1 段に何個並ぶかは**測って決めます**（RX3-0325 / 2026-09-20）。
#:
#:   ⚠⚠ 以前はここで `BUTTONS_PER_ROW = 9` と決め打ちしていました。
#:     ★字 1 つのボタン（34px）だったので数えられましたが、⚠ アイコン＋字にすると
#:     **幅が字の長さとフォントで変わります**（「まんたん」と「終」では倍ちがう）。
#:   → ★`icon_button.wrap_rows()` が、実際の幅を見て入るだけ並べます
#:     （⚠ 決め打ちだと、画面外では入るのに**実機でだけはみ出します** / RX3-0074・RX3-0084）。
#:
#:   ★右パネルで使える幅は `icon_button.PANEL_WIDTH`（= 360 − 左右の余白 10 ずつ）。

#: ★★ FCEUX の「Lua Script」窓（⚠ **閉じない**。閉じると Lua が止まる）。
#:
#: 依頼者 2026-08-29:「Lua 画面は最小化して非アクティブにしたい」
#: ⚠ 隠す（`SW_HIDE`）のではなく**最小化**する。★隠すとタスクバーからも消え、
#:   利用者が戻す手段を失う（`retroux/core/window_align.py` の註）。
LUA_WINDOW_TITLE = "Lua Script"

#: ★★ FCEUX の窓（⚠ **前方一致**で探す。「含む」だと関係ない窓を動かす）。
#:   依頼者 2026-08-29:「1920x1080 にピッタリハマるように。
#:   いまはメイン画面と被ってしまっている」
#:   → ★中央の場所を空けるだけでなく、**FCEUX もそこへ動かす**。
FCEUX_WINDOW_TITLE = "FCEUX"

#: ★★ 窓の位置の記録（RX3-0200 / 2026-09-12 依頼者「終了した時、ウィンドウ位置を保存して再開時にその位置で始めてほしい」）。
#:   ★DQ2 の `WindowState` を使う。⚠ DQ2 の `window-state.json` とは分ける（★2 つの起動が互いの記録を上書きしない）。
WINDOW_STATE_PATH = paths.lazy_work("dq3-window-state.json")
#: ★記録の鍵（⚠ 名前を変えると前回の位置を忘れる）
WINDOW_KEYS = {"main": "dq3_main", "map": "dq3_map", "battle": "dq3_battle", "fceux": "dq3_fceux"}
#: ★これより小さい記録は使わない（⚠ 戦闘の窓は背が低い: layout.BOTTOM_H = 226）
WINDOW_MIN_W, WINDOW_MIN_H = 160, 100
#: ★FCEUX の窓が出るまで待って戻す（⚠ 起動直後は窓がまだ無い / ★戻せたら 2 回目はしない）
FCEUX_RESTORE_DELAYS_MS = (2000, 6000)


def _place(window, box) -> None:
    """★窓を、**枠ごと**その場所へ収める。

    ⚠⚠ `setGeometry` が決めるのは**中身の枠**（client）で、
    ★題名の帯や縁はその**外側**に付きます。そのまま並べると、
    下の窓が上の窓へ食い込みます（★依頼者「上と下で被っている」/ 2026-08-29）。

    → ★一度置いてから `frameGeometry` との差を測り、そのぶん縮めます。
    ⚠ 環境によって帯の高さが違うので、**決め打ちしない**。
    """
    # ⚠⚠ **置いた直後に測らない。** `setGeometry` のあとすぐ `frameGeometry` を
    #   読むと、Windows では**古い値**が返ることがある（実際に踏んだ:
    #   右パネルだけ 360 のはずが 556 のままだった / 2026-08-29）。
    #   → ★いまの状態から枠の厚みを測り、**1 回で**置く。
    frame = window.frameGeometry()
    inner = window.geometry()
    left = inner.x() - frame.x()
    top = inner.y() - frame.y()
    extra_w = max(0, frame.width() - inner.width())
    extra_h = max(0, frame.height() - inner.height())
    window.setGeometry(box.x + left, box.y + top,
                       max(120, box.w - extra_w),
                       max(80, box.h - extra_h))


# ⚠ 2026-09-21（RX3-0328）: 節の見出し（`_section`）は**使わなくなりました**。
#   ★「操作」「自動戦闘」を外したため（依頼者「縦を稼ぎたい」）。
#   ⚠ 使わない飾りは残しません（★また要るなら `git log` から戻せます）。


# ⚠⚠ 2026-09-07（RX3-0104）: `_HearingSpeedHook` は `dq3/ui/auto_env.py` の
#   `AutoOperationEnvironment` に置き換えました。
#   ★理由は 3 つ:
#     ① 音（Mute）も同じ入口で扱う ― ⚠ 聞き込みと店移動に別々に書かない
#     ② ⚠⚠ 戻すのは **100% ではなく開始前の速度**（★覚えてから変える）
#     ③ ★管理画面が開いていなくても効く（⚠ 旧 hook は `_admin` が無いと**何もしなかった**）


class Dq3MainWindow(QWidget):
    """右パネル（★戦闘は下の別ウィンドウ）。"""

    def __init__(self, view_model, *, interval_ms: int = DEFAULT_INTERVAL_MS,
                 memo_limit: int = 3, show_map: bool = True,
                 show_battle: bool = True, command_path=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.commands = CommandWriter(command_path)
        # ★窓の名前（RX3-0306 / 依頼者「右：RetroUX DQ3」）
        #
        #   ⚠ 2026-09-29（RX3-0464）: 版を足しました（例 `RetroUX DQ3 1.1.0`）。
        #     ★DQ2 と同じ作法（`retroux/ui/main_window.py:315`）。
        #     ⚠⚠ ここに数字を**書き写さない**（出どころは `pyproject.toml` の 1 か所）。
        #   ⚠ 子窓（会議・図鑑・地図ほか）は `— RetroUX DQ3` のままにします
        #     （★版は親の題名 1 か所でよい）。
        from dq3 import startup as _startup

        self.setWindowTitle(_startup.title())
        # ★★ 起動直後から画面にぴったり収める（依頼者 2026-08-29）。
        #   ⚠ 420 幅では**パーティの表が切れて**いた（実機の画面で確認）。
        self._layout = layout_mod.default_sizes(layout_mod.qt_area())
        self.setGeometry(*self._layout.panel.as_tuple())

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._status = QLabel("接続待ち")
        self._status.setStyleSheet("color: #8a93a5;")
        # ⚠⚠ **長い文が窓の幅を決めてしまう。**
        #   ★整列で 360px にしても、失敗の文（「FCEUX で始まるウィンドウが
        #   見つかりません…」）が入った瞬間に **556px へ広がった**
        #   （2026-08-29 に実際に踏んだ。★右パネルが画面からはみ出した）。
        #   → ⚠ 文字が幅を決めないようにする（★DQ2 の `ElidedLabel` と同じ狙い）。
        self._status.setWordWrap(True)
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Preferred)
        self._status.setMinimumWidth(0)
        root.addWidget(self._status)

        # --- ★パーティ（4 人固定 / 所持金つき）--------------------------
        #   ⚠ 見出しは `Dq3PartyPanel` が持つ（★所持金を同じ行に出すため）
        self.party = Dq3PartyPanel()
        root.addWidget(self.party)

        # --- ★操作（⚠ DQ2 から引き継ぐ）--------------------------------
        # ⚠ 2026-09-21（RX3-0328）: 見出し「操作」は外しました（★依頼者「縦を稼ぎたい」）。
        #   ★アイコンだけの行が何かは、ツールチップが言います。
        root.addWidget(self._build_buttons())
        root.addWidget(self._build_town_bar())      # ★街ナビ＋聞き込みの 1 行（RX3-0058）
        self._strategy_row = self._build_strategy_row()  # ★戦略 [作戦▼] [AI設定]（RX3-0127）
        root.addWidget(self._strategy_row)
        self.mantan_row = self._build_mantan_row()      # ★まんたん [設定]（RX3-0160）
        # ★倒した敵を Lua へ 1 度渡しておく（★戦闘の高速化が「初見か」を見る / RX3-0166）
        self.vm.write_enemy_overlay()
        # ★戦闘開始時 自動 / 手動（戦闘AI設定画面の設定 / RX3-0237）も 1 度渡す（⚠ 落ちても起動は続ける）
        try:
            from ..phase0 import battle_auto_overlay as BA

            BA.write_overlay(self.settings)
        except OSError:
            pass
        root.addWidget(self.mantan_row)

        root.addStretch(1)

        # --- ★別ウィンドウ ---------------------------------------------
        self.map_window = Dq3MapWindow(view_model, memo_limit=memo_limit)
        # ★行動履歴（RX3-0109 / RX3-0111）。⚠ アプリで 1 本だけ持つ
        from dq3 import action_log as _AL

        from .auto_watch import LuaActionWatcher

        self.action_log = _AL.shared()
        self.action_watch = LuaActionWatcher(self.action_log)
        # ★呪文の結果（RX3-0271）: 戦闘が終わったら view_model が 1 回だけまとめる（★同じ Writer で行動履歴へ）
        from .spell_watch import SpellWatcher

        view_model.spell_watch = SpellWatcher(writer=self.action_watch.writer)
        # ★「詳しいログ」の入り切りは管理画面と同じ置き場から（RX3-0276）
        self.battle_window = Dq3BattleWindow(view_model, action_log=self.action_log,
                                             settings=getattr(self, "settings", None))

        # ★オート戦闘サマリー（RX3-0149）。⚠ 空いている下の領域へ
        #   （★`addStretch` の**前**に入れる / ⚠ 戦っていないときは中段が消える）
        from .auto_panel import AutoBattlePanel

        self.auto_panel = AutoBattlePanel(view_model, self.action_log)
        # ⚠ 2026-09-21（RX3-0328）: 見出し「自動戦闘」も外しました。
        #   ★`AutoBattlePanel` の 1 行目が「AUTO ●ON」なので、見出しが無くても分かります。
        # ★★ 2026-09-21（RX3-0329 / 依頼者「満タン設定と Auto 戦闘の振る舞いの順番は逆
        #   （満タン設定のほうが上に）」）: ⚠ **まんたんの行の下**へ入れます。
        #   ★並びは 街の行 → 戦略 → まんたん → 自動戦闘 の順になります。
        root.insertWidget(root.indexOf(self.mantan_row) + 1, self.auto_panel)
        # ★前回の終了時の位置へ戻す（RX3-0200）。⚠ 記録が無ければ今までどおり（★整列で置く）
        self.restore_window_positions()
        if show_map:
            self.map_window.show()
        if show_battle:
            self.battle_window.show()

        # ★Lua の窓を最小化する（⚠ 起動直後は窓がまだ無いので少し待つ）
        QTimer.singleShot(1500, self.minimize_lua_window)
        # ★FCEUX も前回の位置へ（⚠ 窓が出るまで少し待つ / RX3-0200）
        for delay in FCEUX_RESTORE_DELAYS_MS:
            QTimer.singleShot(delay, self.restore_emulator_position)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(max(100, int(interval_ms)))
        self.refresh()

    # --- ★操作のボタン --------------------------------------------------

    def _build_town_bar(self) -> QWidget:
        """★街ナビ＋聞き込みの 1 行（RX3-0058 §2）。⚠ 大きなパネルは作らない。"""
        from ..knowledge.town_service import TownService
        from .auto_env import AutoOperationEnvironment, town_speed_log
        from .emu_speed import EmulatorSpeedController
        from .game_focus import GameFocus
        from .mute import MuteController
        from .town_bar import TownBar

        # ★FCEUX の速度と音（RX3-0059 / RX3-0104 / RX3-0170）。
        #   ⚠⚠ 2026-09-11 依頼者: 聞き込み・街移動は **Turbo ＋ 無音**（旧 400%）。
        #     ★終わったら**開始前の速度・音**へ戻す（⚠ 固定で 100% ・ Unmute にしない）。
        #   ★Turbo の入り切りは Lua（`town_speed.lua`）、無音と開始前の倍率は `AutoOperationEnvironment`
        #     （⚠ 聞き込みと店移動で `set_speed` / `mute` を別々に書かない）。
        self.speed = EmulatorSpeedController()
        self.mute = MuteController()
        # ★終わったらゲームへ操作を返す（RX3-0116 / 2026-09-08 依頼者）。
        #   ⚠ 人へ見せている窓（確認ダイアログ等）があるときは戻しません。
        self.game_focus = GameFocus(blockers=self._modal_titles)
        # ★聞き込み・街移動・補充はいつも高速（⚠ 管理画面の「高速実行」のチェックは RX3-0259 で外した）
        self.auto_env = AutoOperationEnvironment(
            self.speed, self.mute, focus=self.game_focus, log=town_speed_log)
        from .ui_settings import UiSettings

        #: ★画面の小さな設定（★補充の目標など。⚠ 管理画面と同じ置き場）
        self.settings = UiSettings()
        self.town_bar = TownBar(self.vm, TownService(), self.commands, env_hook=self.auto_env,
                                settings=self.settings)
        return self.town_bar

    def _modal_titles(self) -> list[str]:
        """⚠ いま人へ見せている窓（★あれば FCEUX へ戻さない / RX3-0116）。

        ⚠⚠ 「開いている窓」ではなく「**人が読むべき窓**」です。
        ★地図や図鑑は開いていてもゲームへ戻してよい（⚠ 邪魔をしない作りなので）。
        """
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

        got = []
        for widget in QApplication.topLevelWidgets():
            if not widget.isVisible():
                continue
            if isinstance(widget, QMessageBox):
                got.append(widget.windowTitle() or "確認")
            elif isinstance(widget, QDialog) and widget.isModal():
                got.append(widget.windowTitle() or "ダイアログ")
        return got

    def open_admin(self) -> None:
        """★管理画面（RX3-0059）。⚠ 2 つ開かない。"""
        got = getattr(self, "_admin", None)
        if got is None:
            from .admin_window import AdminWindow

            got = self._admin = AdminWindow(self.vm, self.commands, speed=self.speed,
                                            town_bar=self.town_bar, settings=self.settings,
                                            on_detail_log=self.battle_window.set_show_detail)
        got.refresh()
        got.show()
        got.raise_()

    def _build_strategy_row(self) -> QWidget:
        """★戦闘 AI の作戦（RX3-0127）。⚠ DQ2 の `_build_strategy_row` と同じ場所・同じ作り。

        ★役割と MP 制約は別の窓（`open_battle_ai`）。⚠ ここに数値は置かない（§16）。
        """
        from .battle_ai_window import AiSettingsHub, StrategyRow

        self.ai_hub = AiSettingsHub(self.vm, self.commands, self.settings)
        # ★起動時に 1 度、いまの設定で生成物を作っておく（⚠ Lua が古い作戦で戦わないように）。
        #   ★パーティが届いた・変わったら `refresh` の `sync_party` が作り直す（RX3-0198 §16）
        self.ai_hub.regenerate()
        self.strategy_row = StrategyRow(self.ai_hub, open_window=self.open_battle_ai)
        return self.strategy_row

    def _apply_battle_buttons(self, raw: dict) -> dict:
        """★オート / ターボ の ON 表示・押せるか・ヒント（RX3-0169 / RX3-0325）。

        ⚠⚠ **鍵は役割です**（`"auto"` / `"turbo"`）。★画面に出す字ではありません。
          以前は `buttons.get("A")` のように**表示の字**を鍵にしていたため、
          ⚠ 字を変えると**例外も出さずに何もしなくなる**作りでした。

        ⚠ ここは `state.json` の鏡です（★押した瞬間ではなく、Lua が書いた実際の状態）。
        """
        got = battle_buttons(raw)
        buttons = getattr(self, "_buttons", {}) or {}
        auto, turbo = buttons.get("auto"), buttons.get("turbo")
        if auto is not None:
            auto.setEnabled(got["auto_enabled"])
            icon_button.set_on(auto, got["auto_on"])
        if turbo is not None:
            turbo.setEnabled(got["turbo_enabled"])
            icon_button.set_on(turbo, got["turbo_on"])
            turbo.setToolTip(TURBO_TIP if got["turbo_enabled"] else TURBO_TIP_DISABLED)
        return got

    def _note_turbo(self, turbo, normal_count=None) -> bool:
        """★★ ターボが切れたら、人が選んでいた倍率（管理画面の 2 倍速など）を送り直す（RX3-0166）。

        ⚠ Lua の `emu.speedmode("normal")` は FCEUX を 100% に戻すので、⚠ 送り直さないと
          戦闘の高速化のあとに**勝手に 100% へ固定**してしまう（依頼者 §22）。
        ★倍率が 100% なら何も送らない（`reassert` の中で見る）。戻り値: 送り直したか。

        ★★ RX3-0170: Lua が normal を送った回数（`speed_normal_count`）が来ていれば、そちらで見る。
          ⚠ 聞き込みの Turbo は NPC の間で短く入り切りするので、0.5 秒ごとの「ON → OFF」では
            見逃す（★見逃すと区間減速の 400% や人の 2 倍速が 100% のままになる）。
        """
        last_count = getattr(self, "_last_normal", None)
        if normal_count is not None:
            changed = last_count is not None and normal_count > last_count
            self._last_normal = normal_count
        else:
            changed = bool(getattr(self, "_last_turbo", None)) and turbo is False
        self._last_turbo = turbo
        if not changed:
            return False
        try:
            return bool(self.speed.reassert())
        except Exception:                                  # noqa: BLE001 - ★画面を止めない
            return False

    def _build_mantan_row(self) -> QWidget:
        """★まんたんの設定（RX3-0160）。★戦略の行と同じ置き方。"""
        from ..phase0 import mantan_settings as MS
        from .mantan_window import MantanRow

        # ★起動時に 1 度、いまの画面の設定をまんたんへ渡しておく（⚠ 落ちても起動は続ける）
        try:
            MS.write_overlay(self.settings)
        except OSError:
            pass
        return MantanRow(self.settings, self.vm, open_window=self.open_mantan)

    def open_mantan(self) -> None:
        """★まんたん設定の窓。⚠ 2 つ開かない（★戦闘 AI 設定と同じ開き方）。"""
        got = getattr(self, "_mantan", None)
        if got is None:
            from .mantan_window import MantanWindow

            got = self._mantan = MantanWindow(self.settings, self.vm, self.commands,
                                              getattr(self, "action_log", None))
        got.refresh()
        got.show()
        got.raise_()

    def open_battle_ai(self) -> None:
        """★戦闘 AI 設定の窓。⚠ 2 つ開かない（★管理画面と同じ開き方）。"""
        got = getattr(self, "_battle_ai", None)
        if got is None:
            from .battle_ai_window import BattleAiWindow

            got = self._battle_ai = BattleAiWindow(self.ai_hub)
        got.refresh()
        got.show()
        # ★★ 画面の中へ収める（RX3-0328 / 依頼者「下が隠れる。少し上に表示させたい」）。
        #   ⚠ `show()` の**あと**に呼びます（★並べ終わるまで大きさが決まらない）。
        layout_mod.fit_on_screen(got)
        got.raise_()

    def _build_buttons(self) -> QWidget:
        """⚠ DQ2 の並びに合わせる（★同じものは同じ場所に）。

        ★★ 2026-09-20（RX3-0325）: **アイコン＋字**にしました。
          依頼者 2026-08-29 の「※のちのちアイコン」がここです。
        ⚠ 鍵は**役割**（`self._buttons["auto"]`）。★表示の字を鍵にしない。
        """
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(icon_button.SPACING)

        #: ★(役割, 画面に出す字, ヒント, 押したとき)
        #   ⚠ 依頼者 2026-08-29「整、A、タ、満、終 の一文字のボタンにする
        #   （縦節約）※のちのちアイコン」
        #   ⚠ 依頼者 2026-09-20「特に以下は文字を残してください: オート / ターボ /
        #     まんたん / 地図 / メモ / 会議 / 聞込 / 管理」
        rows = [
            ("align", "整", "窓を標準の並びへ戻す\n"
                     "  左   : 見た地図\n"
                     "  中央 : FCEUX（ゲーム画面）\n"
                     "  右   : この画面\n"
                     "  下   : 戦闘（モンスターとログ）\n"
                     "★FCEUX は中央へ動かします（⚠ 大きさは変えません）",
             self.arrange_windows),
            ("auto", "オート", AUTO_TIP, lambda: self._send("auto")),
            ("turbo", "ターボ", TURBO_TIP_DISABLED, lambda: self._send("turbo")),
            ("map", "地図", "行った地図を見る" + chr(10)
                   + "★左の一覧から選びます（⚠ 行った地図だけ出ます）" + chr(10)
                   + "⚠ いつもの地図は**現在地に追随**、こちらは**全体**です",
             self.open_map_browser),
            ("monster", "敵", "モンスター図鑑を見る" + chr(10)
                   + "★会った敵の絵・性能・行動・耐性・落とす品が見られます"
                   + chr(10)
                   + "⚠ 倒していない敵は、中身を出しません（★No-Spoiler）",
             self.open_monster_book),
            # ⚠⚠ 「会」（勇者会議）は**左の地図の窓へ移しました**（RX3-0302 / 2026-09-20）。
            #   ★依頼者「勇者会議のボタンは MAP 画面にもっていく」「右側のボタンも一列になるし」
            #   ⚠ `open_council` は残します（★ほかから呼べる / 検査も見ている）。
            ("shop", "店", "お店の品揃えを見る" + chr(10)
                   + "★値段と「いま装備しているものとの差」が出ます"
                   + chr(10)
                   + "⚠ 見せるだけです（★買いません）",
             self.open_shop),
            ("mantan", "まんたん", "全員を回復する\n"
                         "★キーボードの M と同じことをします\n"
                         "⚠ フィールドで押してください",
             lambda: self._send("mantan")),
            ("admin", "管理", "管理画面を開く" + chr(10)
                   + "★状態 / プレイデータの初期化・退避・復元 / 聞き込みテスト / 自動移動の停止" + chr(10)
                   + "★設定: 画面の見え方（フィルタ）/ 詳しいログ / 補充の数",
             self.open_admin),
            ("exit", "終", "終わります\n"
                   "★FCEUX も閉じるか聞きます\n"
                   "⚠ セーブしていない進行は失われます",
             self.quit_all),
        ]
        self._buttons = {}
        made = []
        for role, label, tip, slot in rows:
            # ★★ 2026-09-21（RX3-0328 / 依頼者「文字はいらない。アイコンだけでいい」）。
            #   ⚠ 字は残します（`text()` は「オート」を返す）。★出さないだけです。
            button = icon_button.make(role, label, tip, place=icon_button.ICON,
                                      on_click=slot)
            self._buttons[role] = button
            made.append(button)
        # ★入るだけ 1 段に並べる（⚠ 段数は決め打ちにしない / 上の註）
        # ★押せないボタンでも説明を出す（RX3-0329 / ⚠ Qt は押せない部品にマウスを届けない）
        icon_button.watch_disabled(box)
        for line in icon_button.wrap_rows(made):
            strip = QHBoxLayout()
            strip.setContentsMargins(0, 0, 0, 0)
            strip.setSpacing(icon_button.SPACING)
            for button in line:
                strip.addWidget(button)
            strip.addStretch(1)
            outer.addLayout(strip)
        return box

    def open_map_browser(self) -> None:
        """★行った地図を選んで見る画面を開く（RX3-0024）。

        ⚠ 2 つ開かない（★既に開いていれば前へ出す）。
        """
        got = getattr(self, "_map_browser", None)
        if got is None:
            from .map_browser import Dq3MapBrowser

            got = self._map_browser = Dq3MapBrowser(self.vm)
        got.reload()
        got.show()
        got.raise_()

    def open_monster_book(self) -> None:
        """★モンスター図鑑を開く（RX3-0040）。

        ⚠ 2 つ開かない（★既に開いていれば前へ出す）。
        ⚠ 戦闘のたびに増えるので、★開くたびに作り直します。
        """
        got = getattr(self, "_monster_book", None)
        if got is None:
            from .monster_book_window import Dq3MonsterBookWindow

            got = self._monster_book = Dq3MonsterBookWindow(self.vm)
        got.reload()
        got.show()
        got.raise_()

    def open_council(self) -> None:
        """★勇者会議を開く（RX3-0074）。

        ⚠ 2 つ開かない（★既に開いていれば前へ出す）。
        ★開くたびに評価し直す（⚠ 毎フレームではない / 指示書 §25）。
        """
        got = getattr(self, "_council_window", None)
        if got is None:
            from .council_window import Dq3CouncilWindow

            got = self._council_window = Dq3CouncilWindow(self.vm)
        else:
            got.reload()
        got.show()
        got.raise_()

    def open_shop(self) -> None:
        """★お店の品揃えを見る（RX3-0084）。

        ⚠ 2 つ開かない（★既に開いていれば前へ出す）。★開くたびに読み直す。
        """
        got = getattr(self, "_shop_window", None)
        if got is None:
            from .shop_window import Dq3ShopWindow

            got = self._shop_window = Dq3ShopWindow(self.vm)
        else:
            got.reload()
        got.show()
        got.raise_()

    def _work_area(self):
        """★タスクバーを除いた範囲（**Qt の論理座標**）。

        ⚠⚠ `window_align.work_area()`（物理）を使ってはいけない。
        ★依頼者の画面は 125% / 150% の拡大表示で、物理を渡すと
        窓が 1.5 倍になって画面からはみ出した（2026-08-29 に実際に踏んだ）。
        """
        return layout_mod.qt_area(self)

    def minimize_lua_window(self) -> bool:
        """★FCEUX の「Lua Script」窓を最小化する。

        ⚠⚠ **閉じない。** 閉じると Lua が止まり、自動戦闘もまんたんも死ぬ。
        ★最小化なら処理は続く（DQ2 で確立した扱い）。

        ⚠ Windows 以外や、窓がまだ無いときは何もせず `False`。
        """
        try:
            return bool(window_align.minimize(LUA_WINDOW_TITLE))
        except (OSError, AttributeError):
            # ⚠ 並べられないだけなら遊べる。★例外で画面ごと止めない
            return False

    def _send(self, action: str) -> None:
        """★Lua へ頼む（⚠ 効いたかは `state.json` を見て分かる）。"""
        try:
            seq = self.commands.send(action)
        except (OSError, ValueError) as err:
            self._status.setText("⚠ 頼めませんでした: %s" % err)
            return
        self._status.setText("★%s を頼みました（seq=%d）" % (action, seq))

    # --- ★窓の位置を覚える（RX3-0200） ------------------------------------

    def _windows_to_remember(self) -> dict:
        """★覚える窓（鍵 → 窓）。⚠ FCEUX は別プロセスなので別に扱う。"""
        return {WINDOW_KEYS["main"]: self, WINDOW_KEYS["map"]: self.map_window,
                WINDOW_KEYS["battle"]: self.battle_window}

    def restore_window_positions(self, state=None) -> list[str]:
        """★前回の終了時の位置へ戻す。戻り値: 戻せた窓の鍵。

        ⚠⚠ 2026-09-12 依頼者「終了した時、ウィンドウ位置を保存して再開時にその位置で始めてほしい
          ※今は毎回整列ボタンを押下している」（RX3-0200）。
        ★DQ2 の `WindowState` を使う（★画面の外に保存された窓は画面内へ戻す / 小さすぎる記録は使わない）。
        ⚠ 記録が無い窓は今までどおり（★整列で置く）。
        """
        from retroux.ui.window_state import WindowState

        self._window_state = state if state is not None else WindowState(WINDOW_STATE_PATH)
        done = []
        for key, window in self._windows_to_remember().items():
            if self._window_state.apply_to(key, window, min_width=WINDOW_MIN_W,
                                           min_height=WINDOW_MIN_H):
                done.append(key)
        return done

    def save_window_positions(self) -> bool:
        """★いまの位置を覚える（★閉じる前に呼ぶ）。戻り値: 書けたか。⚠ 書けなくても閉じることは続ける。"""
        state = getattr(self, "_window_state", None)
        if state is None:
            return False                   # ⚠ 位置を戻す仕組みを通っていない窓（★検査の入れ物）
        for key, window in self._windows_to_remember().items():
            if window.isVisible():         # ⚠ 開いていない窓の既定の場所で、覚えた位置を上書きしない
                state.capture_from(key, window)
        self._remember_emulator(state)
        return state.save()

    def _remember_emulator(self, state) -> None:
        """★FCEUX の位置を**論理**で覚える（⚠ 大きさは戻さない: 人が決めた倍率を壊さない）。"""
        try:
            found = window_align.find_windows(FCEUX_WINDOW_TITLE, match="prefix")
        except (OSError, AttributeError):
            found = []
        if not found:
            return                         # ★もう閉じていたら、前に覚えたぶんを残す
        ratio = layout_mod.qt_ratio(self)
        x, y = layout_mod.to_logical(found[0].x, found[0].y, ratio)
        w, h = layout_mod.to_logical(found[0].width, found[0].height, ratio)
        state.put(WINDOW_KEYS["fceux"], {"x": x, "y": y, "w": w, "h": h})

    def restore_emulator_position(self) -> bool:
        """★FCEUX を前回の位置へ（⚠ 記録が無い / 窓がまだ無いなら何もしない / 戻せたら 2 回目はしない）。"""
        state = getattr(self, "_window_state", None)
        at = state.get(WINDOW_KEYS["fceux"]) if state is not None else {}
        if not at or getattr(self, "_emulator_restored", False):
            return False
        try:
            if not window_align.find_windows(FCEUX_WINDOW_TITLE, match="prefix"):
                return False               # ★まだ出ていない（次の合図で）
        except (OSError, AttributeError):
            return False
        from retroux.ui.window_state import clamp_to_screens

        try:
            x, y = int(at["x"]), int(at["y"])
            w, h = int(at.get("w") or 0), int(at.get("h") or 0)
        except (KeyError, TypeError, ValueError):
            return False
        # ★画面の外に保存されていたら主画面へ寄せる（★見えない所へ運ばない）
        x, y, _moved = clamp_to_screens(x, y, max(w, 1), max(h, 1))
        self._emulator_restored = self.move_emulator(layout_mod.Box(x, y, w, h))
        return self._emulator_restored

    def arrange_windows(self) -> None:
        """★DQ2 の「整列」と同じ並びにする。

        ```text
        ┌──────────┬────────────┬──────────┐
        │ 見た地図  │ FCEUX      │ 右パネル  │
        ├──────────┴────────────┴──────────┤
        │ ログ                              │
        └───────────────────────────────────┘
        ```

        ⚠ **FCEUX も動かします**（依頼者 2026-08-29「メイン画面と被る」）。
        ★`retroux/core/window_align.py` を**読むだけ**で使います
        （⚠ `retroux/` は 1 行も変更しません）。
        """
        area = self._work_area()
        if area is None:
            return
        # ★中央は FCEUX の**いまの大きさ**に合わせる（⚠ 決め打ちしない）。
        #   ⚠ FCEUX の実寸は**物理**なので、論理へ直してから使う。
        wide, tall = self._emulator_size()
        plan = layout_mod.compute(
            area, center_w=wide or layout_mod.CENTER_W,
            top_h=tall or layout_mod.TOP_H_FALLBACK)
        self._layout = plan

        # ⚠ 枠の厚みを測るために、先に見えている状態にしておく
        for window in (self.map_window, self.battle_window):
            if not window.isVisible():
                window.show()
        QApplication.processEvents()

        _place(self.map_window, plan.map)
        _place(self, plan.panel)
        _place(self.battle_window, plan.bottom)
        # ★1 度で決まらないことがあるので、確定させてからもう一度当てる
        QApplication.processEvents()
        _place(self.map_window, plan.map)
        _place(self, plan.panel)
        _place(self.battle_window, plan.bottom)
        # ★中央へ FCEUX を動かす（⚠ 動かせなくても、こちらは並んでいる）
        self.move_emulator(plan.center)

        # ★並べ直したら、Lua の窓も引っ込める（⚠ 上に出てくることがある）
        self.minimize_lua_window()

    def _emulator_size(self):
        """★FCEUX の**いまの大きさ**（論理）。⚠ 見つからなければ `(None, None)`。

        依頼者 2026-08-29:「②にタイトルバー、メニューバーがついたやつで。」
        （★② ＝ NES 画面 240×2 = 480px）

        ⚠ 帯の厚みは環境で違う（★拡大率・テーマ）。**決め打ちしない**。
        → ★動いている窓を測るのがいちばん確か。
        """
        try:
            found = window_align.find_windows(FCEUX_WINDOW_TITLE, match="prefix")
        except (OSError, AttributeError):
            found = []
        if not found:
            return (None, None)
        ratio = layout_mod.qt_ratio(self)
        return layout_mod.to_logical(found[0].width, found[0].height, ratio)

    def move_emulator(self, box) -> bool:
        """★FCEUX を中央へ。⚠ 動かせなくても例外にしない。

        ⚠⚠ **論理 → 物理へ直してから渡す。** `SetWindowPos` は物理で効く。
        ★125% / 150% の画面で、直さないと右へずれる（2026-08-29 に踏んだ）。

        ⚠ `align` は**前方一致**で探す（★「含む」だと関係ない窓を動かす）。
        ⚠ 大きさは変えない（★人が決めた倍率をこちらで壊さない）。
        """
        ratio = layout_mod.qt_ratio(self)
        at = layout_mod.to_physical(box, ratio)
        try:
            window_align.align(FCEUX_WINDOW_TITLE, at.x, at.y,
                               None, None, match="prefix")
            return True
        except Exception as err:            # noqa: BLE001 (どの失敗でも続ける)
            # ⚠ 並ばないだけなら遊べる。★理由は状態欄に出す
            # ⚠ 状態欄は短く（★長い文は幅を押し上げる）。詳しくはヒントへ
            self._status.setText("⚠ FCEUX を動かせませんでした")
            self._status.setToolTip(str(err))
            return False

    # --- ★見直し --------------------------------------------------------

    def _progress_watch(self):
        """★「手に入れた品」を数える人（RX3-0298）。⚠ 最初に使うときだけ作る。

        ⚠ 窓を作るたびに `progress.json` を読まないため（★検査でたくさん作る）。
        """
        got = getattr(self, "_progress_watcher", None)
        if got is None:
            from dq3.knowledge import progress as PG

            got = PG.Watcher()
            self._progress_watcher = got
        return got

    def _note_item_memos(self, chests, hidden) -> list:
        """★持ち物が増えたことで気づいた品を勇者メモへ（RX3-0312）。

        ⚠ 数えているのは `_progress_watch()` の `Progress` **1 つだけ**です
        （★ここで別の `Progress` を作ると、⚠ 同じ品を 2 度数えます）。
        """
        if not hasattr(self.vm, "note_item_memos"):
            return []
        try:
            book = self._progress_watch().progress
            fresh = book.take_new_items()
        except Exception:                                  # noqa: BLE001 ★数えられないだけ
            return []
        # ★宝箱・しらべる が名乗り出た品（⚠ 「入手：…」で二重に出さない）
        claimed = [m.item_id for m in list(chests or ()) + list(hidden or ())
                   if getattr(m, "item_id", None) is not None]
        try:
            return self.vm.note_item_memos(fresh, claimed=claimed)
        except Exception:                                  # noqa: BLE001 ★メモにできないだけ
            return []

    def refresh(self) -> None:
        state = self.vm.state()
        # ★DQ3 だけの項目（運のよさ・職業）を足した形で受け取る
        members = self.vm.party()

        # ★★ 2026-09-21（RX3-0328 / 依頼者「frame／フィールド表示は管理画面に移動させていい」）。
        #   ⚠⚠ 「届いていません」だけは**ここに残します**。★これが出ないと、
        #     利用者は「動いていない」ことに気づけません（⚠ 管理画面を開かないと分からない、では遅い）。
        #   ★届いているときは**欄ごと隠して**縦を稼ぎます。
        if state.frame:
            self._status.setText("")
            self._status.setVisible(False)
        else:
            self._status.setText("⚠ FCEUX から届いていません")
            self._status.setVisible(True)

        # ★所持金は $07AC（2 バイト）。⚠ 届いていなければ `None`
        self.party.update_party(members, self.vm.gold())
        # ★オート戦闘サマリー（RX3-0149）。⚠ 落ちても右画面は続ける
        got = getattr(self, "auto_panel", None)
        if got is not None:
            try:
                got.refresh()
            except Exception:                              # noqa: BLE001
                pass
        # ★まんたんの 1 行（RX3-0160）。⚠ 落ちても右画面は続ける
        row = getattr(self, "mantan_row", None)
        if row is not None:
            try:
                row.refresh()
            except Exception:                              # noqa: BLE001
                pass
        # ★パーティが届いた・変わった（入れ替え・呪文を覚えた・転職・攻撃力）ら、役割の提案から
        #   生成物を作り直して Lua へ（⚠ 人が決めた欄は変えない / RX3-0198 §16・§17）。
        #   ★差は `party_digest` で見る（⚠ HP / MP だけの変化では作り直さない）
        hub = getattr(self, "ai_hub", None)
        if members and hub is not None:
            try:
                hub.sync_party()
            except Exception:                              # noqa: BLE001 - ★右画面は続ける
                pass

        # ★Auto / Turbo の状態をボタンに映す（⚠ 状態を持つのは Lua 側 / RX3-0169）
        turbo = getattr(state, "turbo_enabled", None)
        raw = self.vm._raw()
        count = raw.get("speed_normal_count") if isinstance(raw, dict) else None
        self._note_turbo(turbo, count if isinstance(count, int) else None)
        self._apply_battle_buttons(raw)

        # ★★ 手に入れた品・立った旗を、勇者会議を**開かなくても**数える（RX3-0298）。
        #
        #   ⚠⚠ これが無いと、★取ってすぐ使った / 捧げた品は**1 度も記録に残りません**
        #     （★依頼者のオーブ 6 個のうち 3 個がそうだった / RX3-0297）。
        #   ⚠ 書くのは増えたときだけ（`Watcher` が見る）。★落ちても右画面は続ける
        try:
            self._progress_watch().note(raw)
        except Exception:                                  # noqa: BLE001
            pass

        # ★★ いま映っている升を「見た」ことにする（RX3-0023）。
        #
        #   ⚠⚠ **地図が隠れていても呼ぶ。** ★地図の窓を閉じて遊んだぶんが
        #     記録されないと、⚠ 次に開いたとき**歩いた道が黒いまま**になる。
        #   ⚠ 書き出しは `SeenMap` が間隔を守る（★毎回は書かない）。
        self.vm.note_seen()

        # ★★ はじめての場所を「訪れた」ことにする（RX3-0016 V0）★★
        #
        #   ⚠⚠ `visited_locations` は **読む所しかありませんでした**。
        #     ★誰も書かないので、地点情報は永遠に「？」のままでした。
        #   ⚠ ここで呼ばないと、また同じ形に戻ります。
        made = self.vm.note_here() or self.vm.note_conversation()
        # ★★ 手で話した会話も「聞いた」台帳へ（RX3-0282 / ⚠ 自動の聞き込み中は向こうが書く）
        bar_now = getattr(self, "town_bar", None)
        if made is not None and bar_now is not None:
            if getattr(made, "source", None) in ("conversation", "npc_talk"):
                # ★メモをそのまま渡す（⚠ 本文だけ渡すと、相手（npc_id）が落ちる / RX3-0282 の直し）
                bar_now.note_manual_talk(made)
        # ★いま開いた宝箱も勇者メモへ（RX3-0261 / ⚠ 宝箱の記録は上の note_seen が更新する）
        chests = self.vm.note_chest_memos() if hasattr(self.vm, "note_chest_memos") else []
        made = made or (chests[-1] if chests else None)
        # ★「しらべる」で取った隠し道具も同じ形で（RX3-0281 / ⚠ 宝箱とは別の表なので別の呼び出し）
        hidden = self.vm.note_hidden_memos() if hasattr(self.vm, "note_hidden_memos") else []
        made = made or (hidden[-1] if hidden else None)
        # ★★ 宝箱でも「しらべる」でもない道で増えた品（RX3-0312 / ⚠ 竜の女王のひかりのたま など）
        #   ⚠ 宝箱・しらべる が**同じ更新で出した品**は取り消す（★二重に出さない）
        items = self._note_item_memos(chests, hidden)
        made = made or (items[-1] if items else None)
        if made is not None and self.map_window.isVisible():
            # ★増えたぶんをすぐ出す（⚠ 勇者メモは地図の窓の中にある）
            self.map_window.memos.refresh()
        # ★街ナビ（RX3-0058）: Lua の進み具合を見て、聞き込みなら次の相手へ
        bar = getattr(self, "town_bar", None)
        if bar is not None:
            try:
                bar.poll()
            except Exception as err:                         # noqa: BLE001 ★画面は落とさない
                self._status.setText("⚠ 街ナビで落ちました: %s" % err)
        # ★自動戦闘 / まんたんの終わりを Lua のログから拾う（RX3-0110）
        #   ⚠⚠ ログの窓が**閉じていても**読みます（★閉じている間の分を落とさない）。
        watch = getattr(self, "action_watch", None)
        if watch is not None:
            try:
                watch.poll()
            except Exception as err:                         # noqa: BLE001 ★画面は落とさない
                self._status.setText("⚠ 行動履歴で落ちました: %s" % err)
        admin = getattr(self, "_admin", None)
        if admin is not None and admin.isVisible():
            try:
                admin.refresh()
            except Exception as err:                         # noqa: BLE001
                self._status.setText("⚠ 管理画面で落ちました: %s" % err)

        browser = getattr(self, "_map_browser", None)
        if browser is not None and browser.isVisible():
            browser.refresh()

        if self.map_window.isVisible():
            self.map_window.refresh()
        if self.battle_window.isVisible():
            self.battle_window.refresh()

    def quit_all(self) -> None:
        """★終わる。⚠ FCEUX を閉じるかは**必ず聞く**。

        依頼者 2026-08-29:「終了ボタンでは FCEUX が残ってしまう
        （RetroUX だけ落ちる）」

        ⚠⚠ 黙って閉じません。★セーブしていない進行が失われるためです。
        """
        answer = QMessageBox.question(
            self, "RetroUX DQ3",
            "FCEUX も一緒に閉じますか？" + chr(10) + chr(10)
            + "⚠ セーブしていない進行は失われます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Cancel:
            return
        # ★FCEUX を閉じる**前に**位置を覚える（RX3-0200 / ⚠ 閉じた後は測れない）
        self.save_window_positions()
        if answer == QMessageBox.StandardButton.Yes:
            try:
                # ⚠ `close_window` は**閉じてくれと頼む**だけ（★強制終了ではない）。
                #   ★FCEUX 側の後始末（Lua の registerexit）がちゃんと走る。
                window_align.close_window(FCEUX_WINDOW_TITLE, match="prefix")
            except Exception:               # noqa: BLE001
                self._status.setText("⚠ FCEUX を閉じられませんでした")
        self._stop_own_backup()
        self.close()

    #: ⚠ 起動スクリプトが渡す、この起動を見分ける札（★無ければ何も止めない）
    SESSION_ENV = "RETROUX_DQ3_SESSION"

    def _stop_own_backup(self, lock_path=None) -> bool:
        """★セーブステートの世代バックアップに、**そっと**終わってもらう。

        ⚠⚠ **殺しません。** ★合図のファイルを置くだけです
        （`work/savestate_backup.stop`）。⚠ コピーの途中で殺すと、
        **世代のほうが壊れます**（守るために作ったものが壊れては本末転倒）。

        ⚠⚠ **今回の起動で立てたものだけ**を止めます。
          ★DQ2 の起動と同時に使うことがあり、そちらのぶんを止めると
          ⚠ 相手は**気づかないまま控えが残らなくなります**。
          → ロックに書いてある札と、こちらの札を突き合わせます。
          ⚠ 札が無い（手で起動した / 直接 `python -m dq3.ui.app` した）ときは
          **何もしません**。★分からないときは触らない、が安全側です。

        ⚠⚠ **札は「状態ファイル」から読みます。ロックからではありません。**

          ★`savestate_backup.py` は `RecorderLock` を**札なしで**作っており
          （`savestate_backup.py:348`）、⚠ ロックには `session` が入りません。
          ⚠ 最初はロックを見ていたので、**この処理は 1 度も動きませんでした**
          （2026-08-29。★検査は自分で札を書いたロックを渡していたので緑）。
          → ★札が入るのは `work/savestate_backup.status.json` のほう。

        `lock_path` は検査から差し替えるためのものです
        （⚠ 本物へ合図を置くと、★動いている控えを止めてしまいます）。

        ## ⚠⚠ **どの道で抜けたかを記録に 1 行出します**（RX3-0479 / 2026-10-01）

        ★2026-09-30 の実機で控えが止まりませんでした。⚠ そのとき
        **3 つの道すべてが静かに `False` を返す**ので、
        ⚠⚠ 「止めようとして駄目だった」と「止める相手が居なかった」を
        あとから区別できませんでした。→ ★`savestate_backup.note()` に残します。

        戻り値: ★合図を置いたら True。
        """
        import json
        import os

        from dq3 import savestate_backup as SB

        # ★2 つの道（「終」ボタンと窓の ×）から呼ばれるので、⚠ 2 度目は黙って抜ける
        #   （★合図を置き直しても害はありませんが、記録が二重になります）
        if getattr(self, "_backup_stop_signalled", False):
            return True
        mine = os.environ.get(self.SESSION_ENV)
        if not mine:
            # ⚠ 札が無い（★手で `python -m dq3.ui.app` した / 起動スクリプトを通っていない）
            SB.note("★控えの停止: 何もしません（⚠ %s が無い = この起動の札が不明）"
                    % self.SESSION_ENV)
            return False
        try:
            from retroux.core import backup_status

            if lock_path is None:
                from retroux.core.config import user_config as user_config_mod

                cfg, _ = user_config_mod.load()
                lock_path = cfg.path("backup_lock")
            status = backup_status.status_path(lock_path)
            if not status.exists():
                # ⚠ 一度も動いていない。★触らない
                SB.note("★控えの停止: 何もしません（⚠ 状態ファイルが無い: %s）"
                        % status)
                return False
            got = json.loads(status.read_text(encoding="utf-8"))
            if got.get("session") != mine:
                # ⚠ 別の起動が立てたもの（★DQ2 の起動かもしれない）。触らない
                SB.note("★控えの停止: 何もしません"
                        "（⚠ 別の起動のものです: 記録 %r / こちら %r）"
                        % (got.get("session"), mine))
                return False
            stop = lock_path.with_suffix(".stop")
            stop.write_text("stop", encoding="utf-8")
            self._backup_stop_signalled = True
            SB.note("★控えの停止: 合図を置きました（%s / 札 %r）" % (stop, mine))
            return True
        except Exception as exc:           # noqa: BLE001
            # ⚠ 終わるときの後始末で落ちない（★閉じること自体は続ける）
            #   ⚠⚠ ただし**黙りません**（★2026-09-30 はここで消えた可能性も残っていた）
            SB.note("⚠⚠ 控えの停止に失敗しました: %s: %s"
                    % (type(exc).__name__, exc))
            return False

    # --- ★コントローラー（RX3-0486 / 2026-10-02） -------------------------

    def start_gamepad(self, link=None) -> bool:
        """★パッドを読み始める（⚠ `dq3.ui.app` の本物の起動からだけ呼ぶ）。

        ⚠ 止める条件: 環境変数 `RETROUX_NO_GAMEPAD` / 設定 `gamepad.enabled: false` /
          XInput が無い（★どれも理由を状態欄に出す）。
        """
        from . import gamepad_link as GL
        from .command_ack import AckWaiter

        self.pad_settings = GL.PadSettings.from_settings(getattr(self, "settings", None))
        self._pad_force = None
        self._pad_restore = None
        self._pad_wait = None
        self._pad_waiter = AckWaiter(lambda: self.vm.state_path)
        waiter = self._pad_waiter
        self.pad_queue = GL.CommandQueue(
            self.commands, lambda seq, action: waiter.stage_of(seq, action=action),
            on_sent=self._pad_sent)
        if link is None:
            if os.environ.get("RETROUX_NO_GAMEPAD") or not self.pad_settings.enabled:
                self.gamepad = None
                return False
            from dq3 import paths as P3
            from retroux.core import window_align

            logic = GL.PadLogic(
                self.pad_settings, GL.PadFileWriter(P3.runtime(GL.PAD_FILE_NAME)),
                mouse_move=window_align.move_cursor, mouse_button=window_align.mouse_left,
                in_battle=lambda: bool(getattr(self, "_pad_in_battle", False)))
            link = GL.GamepadLink(logic)
        self.gamepad = link
        if not link.start():
            self._status.setText("⚠ コントローラーを読めません（XInput がありません）")
            self.gamepad = None
            return False
        self._pad_timer = QTimer(self)
        self._pad_timer.timeout.connect(self._gamepad_tick)
        self._pad_timer.start(50)
        return True

    def stop_gamepad(self) -> None:
        """★止めて全部離す（⚠ 押したまま終わらない）。⚠ 強制オートで入れたものは開始前へ戻す。

        ★終わるので列は回りません → 戻す頼みは**直に送り、届くまで少し待ちます**
          （★置き場 1 つ = 1 つずつ / 1 つ 1.5 秒まで / ⚠ FCEUX が先に閉じていれば届かない）。
        """
        link = getattr(self, "gamepad", None)
        if link is None:
            return
        self.gamepad = None
        timer = getattr(self, "_pad_timer", None)
        if timer is not None:
            timer.stop()
        link.stop()
        link.drain()
        want = getattr(self, "_pad_restore", None) or (
            self._pad_restore_of(self._pad_force) if getattr(self, "_pad_force", None) else None)
        self._pad_force, self._pad_restore = None, None
        if not want:
            return
        raw = self._pad_raw()
        for action in self._pad_differs(want, raw):
            try:
                seq = self.commands.send(action)
                self._pad_waiter.wait(seq, action, want="received", timeout=1.5)
            except (OSError, ValueError):
                pass

    # ★強制オートの戻し方（★開始前の状態に**揃える** / ⚠ 反転を数えない）
    #   ⚠ state.json は遅れて届くので、離した瞬間の 1 回では決めません（★入れた頼みがまだ映っていないことがある）。
    #   → ★離してから `PAD_RESTORE_SECONDS` の間、「開始前」と食い違っていれば 1 つずつ戻します。
    PAD_RESTORE_SECONDS = 5.0
    PAD_RESTORE_SPACING = 1.0

    @staticmethod
    def _pad_flags(raw: dict) -> dict:
        """★オートと**人の**ターボ（⚠ 戦闘の自動の高速化は含めない = `turbo_manual`）。"""
        turbo = raw.get("turbo_manual")
        if turbo is None:
            turbo = raw.get("turbo_enabled")                 # ⚠ 古い Lua（★欄が無い）
        return {"auto": bool(raw.get("auto_enabled")), "turbo": bool(turbo)}

    @staticmethod
    def _pad_restore_of(force: dict | None) -> dict | None:
        if not force:
            return None
        return {k: v for k, v in force.get("before", {}).items() if force.get(k)}

    def _pad_differs(self, want: dict, raw: dict) -> list:
        now = self._pad_flags(raw)
        return [k for k in ("auto", "turbo") if k in want and now[k] != want[k]]

    def _pad_raw(self) -> dict:
        try:
            return self.vm._raw() or {}
        except Exception:                                    # noqa: BLE001 ★読めなくても続ける
            return {}

    def _pad_sent(self, action: str, seq: int) -> None:
        """★セーブ / ロードの頼みに番号が付いた（★結果を番号で待つ）。"""
        import time as _time

        wait = getattr(self, "_pad_wait", None)
        if wait is not None and wait["action"] == action:
            wait.update(seq=seq, at=_time.monotonic())
        if action in ("auto", "turbo") and getattr(self, "_pad_restore", None) is not None:
            self._pad_restore["last"] = _time.monotonic()

    def _pad_result(self, raw: dict) -> None:
        """★ステート 0 の保存 / 読込の**実際の結果**を出す（⚠ 「頼んだ」を成功と言わない）。"""
        import time as _time

        from . import gamepad_link as GL

        wait = getattr(self, "_pad_wait", None)
        if wait is None:
            return
        verb = "保存" if wait["action"] == "save_state" else "読込"
        got = ((raw.get("pad") or {}).get("saved") if wait["action"] == "save_state"
               else (raw.get("nav") or {}).get("loaded"))
        if wait.get("seq") is not None and isinstance(got, dict) and got.get("seq") == wait["seq"]:
            self._pad_wait = None
            if got.get("ok"):
                self._status.setText("★%s: ステート %d に%sしました" % (
                    "RB" if verb == "保存" else "LB", GL.PAD_STATE_SLOT, "保存" if verb == "保存" else "戻"))
            else:
                self._status.setText("⚠ ステート %d の%sに失敗しました: %s"
                                     % (GL.PAD_STATE_SLOT, verb, got.get("why") or "理由不明"))
            return
        if _time.monotonic() - wait["at"] > 10.0:
            self._pad_wait = None
            self._status.setText("⚠ ステート %d の%sの結果を確かめられませんでした（FCEUX の応答が無い）"
                                 % (GL.PAD_STATE_SLOT, verb))

    def _pad_reconcile(self, raw: dict) -> None:
        """★強制オートを離したあと、開始前の状態へ揃える（★1 秒に 1 つ / 5 秒まで）。"""
        import time as _time

        rest = getattr(self, "_pad_restore", None)
        if rest is None:
            return
        now = _time.monotonic()
        want = {k: v for k, v in rest.items() if k in ("auto", "turbo")}
        diff = self._pad_differs(want, raw)
        if now - rest["since"] > self.PAD_RESTORE_SECONDS:
            self._pad_restore = None
            return
        if not diff:
            return                                           # ⚠ 揃って見えても見張りは続ける（★遅れて映る頼みがある）
        busy = self.pad_queue.inflight is not None or any(
            p["action"] in ("auto", "turbo") for p in self.pad_queue.pending)
        if busy or now - rest.get("last", 0.0) < self.PAD_RESTORE_SPACING:
            return
        self.pad_queue.push(diff[0])
        rest["last"] = now

    def _gamepad_tick(self) -> None:
        """★パッドで出た操作を主スレッドで行い、頼みの列を進める。"""
        link = getattr(self, "gamepad", None)
        if link is None:
            return
        raw = self._pad_raw()
        self._pad_in_battle = bool(raw.get("in_battle"))
        for name in link.drain():
            try:
                self._on_pad(name, raw)
            except Exception as err:                         # noqa: BLE001 ★1 つの失敗で止めない
                self._status.setText("⚠ パッドの操作 %s に失敗: %s" % (name, err))
        self._pad_reconcile(raw)
        self._pad_result(raw)
        self.pad_queue.tick()

    def _on_pad(self, name: str, raw: dict) -> None:
        import time as _time

        from . import gamepad_link as GL

        bar = getattr(self, "town_bar", None)
        ctl = getattr(bar, "ctl", None)
        slot = GL.PAD_STATE_SLOT                             # ⚠ 0 固定（依頼者 2026-10-02 DQ3-000156）
        if name == GL.RELEASED:
            self.pad_queue.clear("パッドが離れた / 対象外の窓")
        elif name == GL.CANCEL:
            if ctl is not None and ctl.busy():
                ctl.stop()
                bar.refresh()
        elif name == GL.INN:
            if raw.get("in_battle"):
                return
            button = (getattr(bar, "move_buttons", None) or {}).get("inn")
            # ★［宿］ボタンが押せるときだけ（★同じ条件 = 面識のある宿屋がある・聞き込み / 補充の間でない）
            if button is not None and button.isEnabled():
                bar._on_move("inn")                          # ★［宿］ボタンと同じ入口
            else:
                self._status.setText("★X: いまは宿屋へ移動できません（★町の中で、知っている宿屋があるときだけ）")
        elif name == GL.FORCE_BEGIN:
            before = self._pad_flags(raw)
            # ★開始前から入っていたものは触らない（⚠ 戻すときも触らない）
            self._pad_force = {"auto": not before["auto"], "turbo": not before["turbo"],
                               "before": before}
            self._pad_restore = None
            for action in ("auto", "turbo"):
                if self._pad_force[action]:
                    self.pad_queue.push(action)
        elif name == GL.FORCE_END:
            want = self._pad_restore_of(getattr(self, "_pad_force", None))
            self._pad_force = None
            if want:
                # ⚠ まだ出していない「入れる」頼みは取り消す（★出していなければ戻す必要もない）
                kept = [p for p in self.pad_queue.pending if p["action"] not in want]
                self.pad_queue.pending.clear()
                self.pad_queue.pending.extend(kept)
                self._pad_restore = dict(want, since=_time.monotonic(), last=0.0)
        elif name in ("load_state", "save_state"):
            if name == "load_state" and ctl is not None and ctl.busy():
                ctl.stop()                                   # ★街の自動を先に止める（依頼者 §4）
                bar.refresh()
            self.pad_queue.push(name, slot=slot)
            self._pad_wait = {"action": name, "seq": None, "at": _time.monotonic()}
            self._status.setText("★%s: ステート %d の%sを頼みました（結果待ち）"
                                 % ("LB" if name == "load_state" else "RB", slot,
                                    "読込" if name == "load_state" else "保存"))
        elif name in ("auto", "turbo", "mantan"):
            self.pad_queue.push(name)

    def keyPressEvent(self, event) -> None:              # noqa: N802 (Qt の名前)
        """★聞き込み・街移動・補充の途中なら D / B で止める（RX3-0170 / 依頼者 §14）。

        ★D はゲームの B と同じキー（⚠ 新しいキーは増やさない）。★FCEUX が前にあるときは
          Lua（`town_speed.lua`）が人の B を見て止める。⚠ 動いていなければ何もしない。
        """
        bar = getattr(self, "town_bar", None)
        ctl = getattr(bar, "ctl", None)
        if (ctl is not None and ctl.busy() and not event.isAutoRepeat()
                and event.key() in (Qt.Key.Key_D, Qt.Key.Key_B)):
            ctl.stop()
            bar.refresh()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:                 # noqa: N802 (Qt の名前)
        # ★★ ⚠⚠ **控えに終わってもらう**（RX3-0479 / 2026-10-01）★★
        #
        #   ⚠ 2026-09-30 の実機で「外から閉じたら控えが止まらなかった」のは、
        #     ★`_stop_own_backup()` を呼んでいたのが **「終」ボタンだけ**だったためです。
        #
        #     ① 「終」ボタン   `_close_all()` → ★呼んでいた
        #     ② 窓の ×        `closeEvent`  → ⚠⚠ **呼んでいなかった**
        #     ③ 外から WM_CLOSE `closeEvent` → ⚠⚠ 同じ（★これが実機で出た症状）
        #     ④ launcher / FCEUX 側         → ⚠ Qt を通らない（★launcher の仕事）
        #
        #   → ★`closeEvent` は 4 つのうち 2 つの**合流点**なので、ここで呼びます。
        #     ⚠ 「終」からは 2 度呼ばれますが、★2 度目は黙って抜けます。
        self._stop_own_backup()
        # ★パッドを止めて全部離す（RX3-0486 / ⚠ 押したまま終わらない）
        self.stop_gamepad()
        # ★窓の位置を覚える（RX3-0200 / ⚠ 別窓を閉じる**前**に）
        self.save_window_positions()
        # ★街の自動操作の途中なら止める（RX3-0170 / ⚠ Turbo・無音のまま FCEUX を残さない）
        bar = getattr(self, "town_bar", None)
        ctl = getattr(bar, "ctl", None)
        if ctl is not None and ctl.busy():
            try:
                ctl.stop()
            except Exception:                              # noqa: BLE001 - ★閉じること自体は続ける
                pass
        # ⚠ 2 倍速のまま FCEUX を残さない（RX3-0059 §6）
        speed = getattr(self, "speed", None)
        if speed is not None and speed.current != 1.0:
            speed.restore()
        admin = getattr(self, "_admin", None)
        if admin is not None:
            admin.close()
        # ★一緒に閉じる（⚠ 残ると次の起動で二重に出る）
        self.map_window.close()
        self.battle_window.close()
        browser = getattr(self, "_map_browser", None)
        if browser is not None:
            browser.close()
        super().closeEvent(event)
