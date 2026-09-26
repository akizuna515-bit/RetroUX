"""戦闘 AI の設定（RX3-0127 / RX3-0198）— ★作戦は右画面と窓の両方、役割と MP 制約は窓。

```text
右画面（毎日触る）   戦略 [最短撃破 ▼] [AI設定]                                   ★`StrategyRow`
別の窓（たまに触る） 作戦 ＋「この作戦では」/ 第1・第2 行動傾向 / MP制約（作戦より優先）  ★`BattleAiWindow`
```

## ★流れ（指示書 §14 / §17）

  触る → `settings` に保存 → `work/generated/dq3_ai.lua` を作り直す → Lua に `ai_reload`
  ⚠ 反映は**次のターンから**（★同じターンの途中で作戦が変わると説明できない）
  ★右画面と窓の作戦は `AiSettingsHub` 1 つを見る（⚠ 片方だけ変わらない / RX3-0198 §7）

## ★画面と Lua は同じ行動傾向を見る（RX3-0198 §16・§17）

  ★生成に使ったパーティ（`hub.members_used`）を覚え、窓の行動傾向もそのパーティで計算する。
  ★パーティが変わったら（入れ替え・呪文を覚えた・転職・攻撃力）`sync_party` が作り直して `ai_reload`。

## ⚠⚠ 数値は置かない（§16）

  ★閾値は生成側（`dq3/battle_ai/generate.py`）の内部の値。画面には出しません。

## ⚠ 行動傾向の提案は、人が触った欄を**上書きしない**（§15・§17）

  ★第1・第2 を別々に覚える。欄の横の「人が設定 ↺」を押すと、その欄だけ AI の提案に戻る。
"""
from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QPushButton, QRadioButton, QVBoxLayout, QWidget)

from dq3.battle_ai import settings as S

#: ★パーティの要約に入れる欄（⚠ HP / MP は戦うたびに変わるので入れない / RX3-0198 §16）
PARTY_KEYS = ("name", "class_gender", "attack", "spells")

TOUCHED_TEXT = "人が設定 ↺"
SUGGEST_TEXT = "提案"
NOTE = "★変えると次のターンから効きます"

#: ★★ 戦闘開始時（RX3-0237 / 依頼者「戦闘開始時の振る舞いは設定画面へ分離する」）。
#:   ★保存は今までと同じ `automation.battle_auto_known`（true = 自動 / false = 手動 / 無ければ自動）→ 前の設定を引き継ぐ。
#:   ⚠ 2026-09-13 まで管理画面の「倒したことのある敵とは自動で戦う」だった（★置き場を 1 つにした）
START_AUTO, START_MANUAL = "auto", "manual"
START_LABELS = {START_AUTO: "自動", START_MANUAL: "手動"}
START_NOTES = {
    START_AUTO: ("戦闘が始まったら AUTO と TURBO を入れます。\n"
                 "倒したことのある敵だけ・ボス候補でない・窓の色が危険でないときです（それ以外は手動で始まります）。"),
    START_MANUAL: ("戦闘は AUTO・TURBO とも OFF で始まります。\n"
                   "初手を手で指示して、準備ができたら A（AUTO）で AUTO＋TURBO に移ります。"),
}


def party_digest(members) -> tuple:
    """★役割の提案と生成に効くものだけの要約（★差が出たら作り直す）。"""
    out = []
    for m in members or ():
        if not isinstance(m, dict):
            continue
        row = [m.get("slot")]
        for key in PARTY_KEYS:
            got = m.get(key)
            row.append(tuple(got) if isinstance(got, (list, tuple)) else got)
        out.append(tuple(row))
    return tuple(out)


class AiSettingsHub:
    """★設定の読み書き・生成・Lua への通知を 1 か所に（⚠ 右画面と窓で共有する）。"""

    def __init__(self, vm, commands, settings, *, out_dir=None, rom_path=None) -> None:
        self.vm = vm
        self.commands = commands
        self.settings = settings
        self.out_dir = out_dir
        self.rom_path = rom_path
        self.value = S.load(settings)
        self.last_error: str | None = None
        #: ★最後に生成したときのパーティ（⚠ 窓の役割もこれで計算 = Lua と同じ / §17）
        self.members_used: list | None = None
        self._digest: tuple | None = None
        self._listeners: list = []

    def members(self) -> list:
        got = getattr(self.vm, "ai_members", None)
        try:
            rows = got() if callable(got) else []
        except Exception:                                  # noqa: BLE001 - ★画面は落とさない
            rows = []
        return rows if isinstance(rows, list) else []

    def names(self) -> dict:
        """★`p1` → 画面の名前（★まんたんの窓と同じ `party_names` / ⚠ state.json の name は `p1` のまま）。"""
        got = getattr(self.vm, "party_names", None)
        try:
            rows = got() if callable(got) else []
        except Exception:                                  # noqa: BLE001 - ★画面は落とさない
            rows = []
        return {"p%d" % (i + 1): str(n) for i, n in enumerate(rows or []) if n}

    def members_for_view(self) -> list:
        """★窓に出すパーティ（★生成に使ったもの。まだ生成していなければ今のもの）。"""
        return self.members_used if self.members_used is not None else self.members()

    def listen(self, fn) -> None:
        self._listeners.append(fn)

    def effective_roles(self) -> dict:
        """★Lua に渡した役割（⚠ 生成に使ったパーティで計算する / §17）。"""
        return S.effective_roles(self.value, self.members_for_view(), self.rom_path)

    def suggested_roles(self) -> dict:
        """★AI の提案だけ（★人が決めた欄を戻したらこうなる）。"""
        return S.effective_roles(self.value.without_roles(), self.members_for_view(), self.rom_path)

    def update(self, value: S.BattleAiSettings, *, notify: bool = True) -> dict:
        """★保存 → 生成 → `ai_reload`。戻り値は生成した中身（⚠ 失敗しても画面は続ける）。"""
        self.value = value
        S.save(self.settings, value)
        return self._apply(notify)

    def sync_party(self) -> bool:
        """★パーティが変わったら作り直して Lua へ（RX3-0198 §16）。戻り値: 作り直したか。

        ⚠ パーティが届いていない（空）ときは作り直さない（★起動直後や読み込み中に空で上書きしない）。
        """
        members = self.members()
        if not members or party_digest(members) == self._digest:
            return False
        self._apply(True)
        return True

    def _apply(self, notify: bool) -> dict:
        data = self.regenerate()
        if notify:
            try:
                self.commands.send("ai_reload")
            except (OSError, ValueError) as err:
                self.last_error = "Lua に頼めませんでした: %s" % err
        for fn in list(self._listeners):
            fn()
        return data

    def regenerate(self) -> dict:
        from dq3.battle_ai import generate as G

        members = self.members()
        # ★試したパーティを覚える（⚠ 失敗しても毎回やり直さない = 右画面を重くしない）
        self._digest = party_digest(members)
        kwargs = {"out_dir": self.out_dir} if self.out_dir is not None else {}
        try:
            data = G.regenerate(self.value, members, self.rom_path, **kwargs)
        except Exception as err:                           # noqa: BLE001 - ★理由を残す
            self.last_error = "生成できませんでした: %s" % err
            return {"ok": False, "error": self.last_error}
        self.members_used = members
        self.last_error = None if data.get("ok") else str(data.get("error"))
        return data


def _strategy_combo() -> QComboBox:
    combo = QComboBox()
    for value in S.STRATEGIES:
        combo.addItem(S.STRATEGY_LABELS[value], value)
        combo.setItemData(combo.count() - 1, S.STRATEGY_NOTES[value], Qt.ItemDataRole.ToolTipRole)
    return combo


def _show_strategy(combo: QComboBox, value: str) -> None:
    i = combo.findData(value)
    if i >= 0 and i != combo.currentIndex():
        combo.blockSignals(True)
        combo.setCurrentIndex(i)
        combo.blockSignals(False)


class StrategyRow(QWidget):
    """★右画面の 1 行: `戦略 [作戦 ▼] [AI設定]`（⚠ DQ2 の `_build_strategy_row` と同じ場所）。"""

    def __init__(self, hub: AiSettingsHub, *, open_window=None, parent=None) -> None:
        super().__init__(parent)
        self.hub = hub
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("戦略"))
        self.picker = _strategy_combo()
        self.picker.setToolTip(
            "どう戦うかを 1 つだけ選びます。★中の細かい判断は AI に任せます。\n"
            "⚠ 反映は次のターンからです（いま入力済みの行動は変わりません）。")
        self.picker.activated.connect(lambda i: self.pick(self.picker.itemData(i)))
        row.addWidget(self.picker, stretch=1)
        self.button = QPushButton("AI設定")
        self.button.setToolTip("作戦の意味・各キャラの行動傾向（第1 / 第2）・MP制約を見て決めます")
        if open_window is not None:
            self.button.clicked.connect(open_window)
        row.addWidget(self.button)
        self.hub.listen(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        _show_strategy(self.picker, self.hub.value.strategy)

    def pick(self, value: str) -> None:
        if value == self.hub.value.strategy:
            return
        self.hub.update(self.hub.value.with_strategy(value))


class RoleRow(NamedTuple):
    """★1 人ぶんの欄（名前 / 欄ごとのコンボ / 欄ごとの印）。"""

    name: QLabel
    combos: dict      #: tier -> QComboBox
    marks: dict       #: tier -> QPushButton（★提案 / 人が設定 ↺）


class BattleAiWindow(QWidget):
    """★作戦・役割（第1 / 第2）・MP 制約の窓。⚠ 2 つ開かない（★管理画面と同じ開き方）。"""

    def __init__(self, hub: AiSettingsHub, parent=None) -> None:
        super().__init__(parent)
        self.hub = hub
        self.setWindowTitle("戦闘AI設定")
        root = QVBoxLayout(self)
        root.addWidget(self._build_strategy_box())
        root.addWidget(self._build_roles_box())
        root.addWidget(self._build_mp_box())
        root.addWidget(self._build_spell_box())
        root.addWidget(self._build_start_box())
        self.note = QLabel(NOTE)
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        root.addStretch(1)
        self.hub.listen(self.refresh)
        self.refresh()

    # --- ★組み立て ----------------------------------------------------------

    def _build_strategy_box(self) -> QGroupBox:
        """★作戦を選ぶ ＋「この作戦では」を常に出す（RX3-0198 §6・§7）。"""
        box = QGroupBox("作戦")
        lay = QVBoxLayout(box)
        self.strategy_picker = _strategy_combo()
        self.strategy_picker.setToolTip("★右画面の「戦略」と同じものです（どちらで変えても揃います）")
        self.strategy_picker.activated.connect(
            lambda i: self._strategy_picked(self.strategy_picker.itemData(i)))
        lay.addWidget(self.strategy_picker)
        self.strategy_note = QLabel()
        self.strategy_note.setWordWrap(True)
        lay.addWidget(self.strategy_note)
        panel = QGroupBox("この作戦では")
        grid = QGridLayout(panel)
        self.behavior: dict = {}
        for i, key in enumerate(S.BEHAVIOR_ROWS):
            grid.addWidget(QLabel(key), i, 0)
            got = self.behavior[key] = QLabel()
            grid.addWidget(got, i, 1)
        grid.setColumnStretch(1, 1)
        lay.addWidget(panel)
        self.override_note = QLabel()
        self.override_note.setWordWrap(True)
        self.override_note.setStyleSheet("color: #8a5a00;")
        lay.addWidget(self.override_note)
        return box

    def _build_roles_box(self) -> QGroupBox:
        # ★★ 2026-09-20（RX3-0327）: 「役割」→「**行動傾向**」（依頼者 §12-3）。
        #   ⚠ 保存の形（`roles` / `touched` / `first` / `second`）は**そのまま**です。
        box = QGroupBox("行動傾向（★第1 → 第2 の順に優先します）")
        self.roles_box = box
        grid = QGridLayout(box)
        for col, text in enumerate(("キャラ", "第1", "", "第2", "")):
            grid.addWidget(QLabel(text), 0, col)
        self.rows: dict = {}
        for i, slot in enumerate(S.SLOTS):
            name = QLabel(slot)
            grid.addWidget(name, i + 1, 0)
            combos, marks = {}, {}
            for j, tier in enumerate(S.TIERS):
                combo = QComboBox()
                for role in S.ROLES:
                    combo.addItem(S.ROLE_LABELS[role], role)
                combo.setToolTip(
                    "★職業ではなく、覚えている呪文と数字で「できるか」を見ます。\n"
                    "⚠ 行動傾向は制限ではなく優先度です（できなければ他の人が代行）\n"
                    "★最短撃破では、より早く戦闘を終了できる行動を優先し、\n"
                    "  行動傾向は候補が同程度の場合に参照します")
                combo.activated.connect(lambda _i, s=slot, t=tier: self._picked(s, t))
                mark = QPushButton(SUGGEST_TEXT)
                mark.setFlat(True)
                mark.clicked.connect(lambda _c=False, s=slot, t=tier: self.revert_tier(s, t))
                grid.addWidget(combo, i + 1, 1 + 2 * j)
                grid.addWidget(mark, i + 1, 2 + 2 * j)
                combos[tier], marks[tier] = combo, mark
            self.rows[slot] = RoleRow(name, combos, marks)
        self.reset_button = QPushButton("全員を AI の提案に戻す")
        self.reset_button.setToolTip("★人が決めた行動傾向を全部忘れて、覚えている呪文からの提案に戻します")
        self.reset_button.clicked.connect(self.reset_roles)
        grid.addWidget(self.reset_button, len(S.SLOTS) + 1, 1, 1, 4)
        return box

    def _build_mp_box(self) -> QGroupBox:
        # ⚠ 題は「作戦より優先」のまま（★最短撃破では欄ごと灰色になるので矛盾しません）
        box = QGroupBox("MP制約（作戦より優先）")
        self.mp_box = box
        row = QHBoxLayout(box)
        self.mp_group = QButtonGroup(self)
        self.mp_buttons: dict = {}
        for policy in S.MP_POLICIES:
            button = QRadioButton(S.MP_LABELS[policy])
            button.setToolTip(S.MP_NOTES[policy])
            button.clicked.connect(lambda _c=False, p=policy: self._mp_picked(p))
            self.mp_group.addButton(button)
            row.addWidget(button)
            self.mp_buttons[policy] = button
        return box

    def _build_spell_box(self) -> QGroupBox:
        """★使わない呪文を作戦ごとに選ぶ（RX3-0370 / ⚠ 別の窓で選ぶ）。

        ⚠⚠ 依頼者「勇者がギガデインを使いすぎる。★使わない呪文をモード毎に設定する」。
        """
        box = QGroupBox("使う呪文")
        row = QHBoxLayout(box)
        self.spell_summary = QLabel("")
        self.spell_summary.setWordWrap(True)
        row.addWidget(self.spell_summary, 1)
        self.spell_button = QPushButton("選ぶ…")
        self.spell_button.setToolTip("★作戦ごとに、AI に使わせない呪文を選びます")
        self.spell_button.clicked.connect(self.open_spell_window)
        row.addWidget(self.spell_button)
        return box

    def open_spell_window(self) -> None:
        """★窓を 1 つだけ開く（⚠ 2 つ開かない / 管理画面と同じ開き方）。"""
        from .spell_ban_window import SpellBanWindow

        got = getattr(self, "_spell_window", None)
        if got is None:
            got = SpellBanWindow(self.hub, self)
            self._spell_window = got
        got.refresh()
        got.show()
        got.raise_()

    def _refresh_spells(self, value: S.BattleAiSettings) -> None:
        n = len(value.bans_of(value.strategy))
        self.spell_summary.setText(
            "★全部使います" if not n else "⚠ %d 件を使いません（%s）"
            % (n, S.STRATEGY_LABELS.get(value.strategy, value.strategy)))

    def _build_start_box(self) -> QGroupBox:
        """★戦闘開始時 自動 / 手動（RX3-0237 仕様 §5 / ⚠ メイン画面には置かない）。"""
        box = QGroupBox("戦闘開始時")
        row = QHBoxLayout(box)
        self.start_group = QButtonGroup(self)
        self.start_buttons: dict = {}
        for how in (START_AUTO, START_MANUAL):
            button = QRadioButton(START_LABELS[how])
            button.setToolTip(START_NOTES[how])
            button.clicked.connect(lambda _c=False, h=how: self.set_battle_start(h))
            self.start_group.addButton(button)
            row.addWidget(button)
            self.start_buttons[how] = button
        return box

    def battle_start(self) -> str:
        """★いまの「戦闘開始時」（⚠ 画面で決めていなければ 自動 = YAML の既定と同じ）。"""
        from ..phase0 import battle_auto_overlay as BA

        return START_MANUAL if BA.enabled(self.hub.settings) is False else START_AUTO

    def set_battle_start(self, how: str) -> None:
        """★保存して、Lua が次の戦闘で読むファイルを書き直す（⚠ 書けなくても画面は止めない）。"""
        from ..phase0 import battle_auto_overlay as BA

        if self.hub.settings is None:
            return
        self.hub.settings.set(BA.SECTION, BA.KEY, how == START_AUTO)
        try:
            BA.write_overlay(self.hub.settings)
        except OSError as err:
            self.note.setText("⚠ 戦闘開始時の設定を Lua へ渡せませんでした: %s" % err)

    # --- ★表示 ------------------------------------------------------------

    def refresh(self) -> None:
        value = self.hub.value
        self._refresh_strategy(value)
        self._refresh_roles(value)
        self.start_buttons[self.battle_start()].setChecked(True)
        used = S.mp_is_used(value.strategy)
        for policy, button in self.mp_buttons.items():
            # ⚠ `setChecked` は使わない作戦でも続けます（★戻したときに人の選択が見える）
            button.setChecked(policy == value.mp_policy)
            button.setEnabled(used)
        self.mp_box.setEnabled(used)
        self._refresh_spells(value)
        self.note.setText("⚠ " + self.hub.last_error if self.hub.last_error else NOTE)

    def _refresh_strategy(self, value: S.BattleAiSettings) -> None:
        _show_strategy(self.strategy_picker, value.strategy)
        self.strategy_note.setText(S.STRATEGY_NOTES.get(value.strategy, ""))
        for key, text in zip(S.BEHAVIOR_ROWS, S.STRATEGY_BEHAVIOR.get(value.strategy, ())):
            self.behavior[key].setText(text)
        # ★★ 注記は 3 通り（RX3-0327）
        #   ⚠ 使わない作戦   → 「使いません」（★保存は残っていることも言う）
        #   ⚠ おまかせ以外   → 「作戦より優先されます」
        #   ★おまかせ       → 何も出さない
        if not S.mp_is_used(value.strategy):
            self.override_note.setText(S.MP_UNUSED_NOTE)
        elif value.mp_policy == S.MP_AUTO:
            self.override_note.setText("")
        else:
            self.override_note.setText("⚠ MP制約「%s」が作戦より優先されます"
                                       % S.MP_LABELS.get(value.mp_policy, "?"))

    def _refresh_roles(self, value: S.BattleAiSettings) -> None:
        names = {m["slot"]: m.get("name") or m["slot"]
                 for m in self.hub.members_for_view() if isinstance(m, dict) and m.get("slot")}
        names.update(self.hub.names())
        roles = self.hub.effective_roles()
        suggested = self.hub.suggested_roles()
        for slot, row in self.rows.items():
            row.name.setText(str(names.get(slot, slot)))
            pref = roles.get(slot, S.RolePref())
            for tier in S.TIERS:
                self._set_combo(row.combos[tier], pref.tier(tier))
                self._set_mark(row.marks[tier], value.is_touched(slot, tier),
                               suggested.get(slot, S.RolePref()).tier(tier))

    @staticmethod
    def _set_mark(mark: QPushButton, touched: bool, suggestion) -> None:
        mark.setText(TOUCHED_TEXT if touched else SUGGEST_TEXT)
        mark.setEnabled(touched)
        mark.setStyleSheet("color: #1f6f3f;" if touched else "color: #8a93a5;")
        label = S.ROLE_LABELS.get(suggestion, "?")
        mark.setToolTip("★押すと AI の提案（%s）に戻します" % label if touched
                        else "★AI の提案です（覚えている呪文と数字から）")

    @staticmethod
    def _set_combo(combo: QComboBox, role) -> None:
        i = combo.findData(role) if role else -1
        combo.blockSignals(True)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    # --- ★操作 ------------------------------------------------------------

    def _strategy_picked(self, value: str) -> None:
        if value != self.hub.value.strategy:
            self.hub.update(self.hub.value.with_strategy(value))

    def _picked(self, slot: str, tier: str) -> None:
        """★1 つの欄だけ人が決める（⚠ もう片方の欄は提案のまま / §15）。"""
        role = self.rows[slot].combos[tier].currentData()
        self.hub.update(self.hub.value.with_tier(slot, tier, role))

    def _mp_picked(self, policy: str) -> None:
        if policy != self.hub.value.mp_policy:
            self.hub.update(self.hub.value.with_mp(policy))

    def revert_tier(self, slot: str, tier: str) -> None:
        """★1 つの欄だけ AI の提案に戻す（§15）。"""
        if self.hub.value.is_touched(slot, tier):
            self.hub.update(self.hub.value.without_tier(slot, tier))

    def reset_roles(self) -> None:
        self.hub.update(self.hub.value.without_roles())


__all__ = ["AiSettingsHub", "StrategyRow", "BattleAiWindow", "RoleRow", "party_digest"]
