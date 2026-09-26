"""まんたんの設定の窓と、右画面の 1 行（RX3-0160 / 2026-09-11）。

★調査（RX3-0158 §11 / §14）の推奨案です。

```text
┌─ まんたん設定 ───────────────────────────┐
│ 回復役   [ 3 エルシド ★ホイミ ▼ ]           │
│ 回復を始める HP ───────●── 90% 未満         │
│ 残す MP  ──●────────── 4 MP 未満で終わる    │
│ [✓] まんたんの間だけ速くする                 │
│ 呪文 ホイミ（⚠ 変えるときは設定ファイル）     │
│ [ まんたんを実行 ]   [ 既定に戻す ] [ 閉じる ]│
│ 前回: [まんたん] 完了：2人回復 / HP +83      │
└──────────────────────────────────────────┘
```

★変えたらすぐ保存します（★戦闘 AI 設定の窓と同じ）。⚠ 効くのは**次に始めたとき**から。
⚠ 数値の直接入力は使いません（★スライダー / 選ぶだけ）。
⚠ 設定ファイル（YAML）は書き換えません（★`mantan_settings` の註）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from ..phase0 import mantan_settings as MS

#: ★戦闘中の回復は別の窓（⚠ 「回復役」が 2 か所にあることを言葉にする / RX3-0158 §13）
BATTLE_NOTE = "★戦闘中の回復は [AI設定] の役割で決めます（⚠ ここはフィールドだけ）"


def _names(vm) -> dict:
    """★`p1` → 名前（⚠ 繋がっていなければ空 / 推測で埋めない）。"""
    try:
        got = vm.party_names() if vm is not None else []
    except Exception:                                        # noqa: BLE001
        got = []
    return {"p%d" % (i + 1): str(n) for i, n in enumerate(got or []) if n}


def _spell_marks(vm, spell: str) -> dict:
    """★`p1` → その呪文を覚えているか（⚠ 分からなければ入れない）。"""
    from ..knowledge import spell_info as SI

    wanted = next((s.spell_id for s in SI.all_spells() if s and s.name == spell), None)
    if wanted is None or vm is None:
        return {}
    out = {}
    try:
        for m in vm.ai_members() or []:
            learned = SI.learned_for(m)
            if learned:
                out[m.get("slot")] = wanted in learned
    except Exception:                                        # noqa: BLE001
        return {}
    return out


def _class_marks(vm) -> dict:
    """★`p1` → 職業名 1 文字（RX3-0214 / 依頼者「今のパーティの並び順で職業名1文字で良い」）。⚠ 分からなければ入れない。"""
    from ..knowledge import item_info as II

    out = {}
    try:
        for m in vm.ai_members() or []:
            cls, _female = II.split_class_gender(m.get("class_gender"))
            name = II.CLASS_NAMES.get(cls) if cls is not None else None
            if name and m.get("slot"):
                out[m["slot"]] = (II.CLASS_LABEL.get(name, name), name == "hero")
    except Exception:                                        # noqa: BLE001
        return {}
    return out


def _spell_cost(spell: str) -> int | None:
    from ..knowledge import spell_info as SI

    got = next((s for s in SI.all_spells() if s and s.name == spell), None)
    return got.mp if got is not None else None


class MantanWindow(QWidget):
    """★まんたんの設定の窓。⚠ 2 つ開かない（★開き方は main_window が持つ）。"""

    def __init__(self, settings, vm=None, commands=None, action_log=None,
                 parent=None, config_path=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.vm = vm
        self.commands = commands
        self.action_log = action_log
        self.config_path = config_path or MS.CONFIG
        self.last_error: str | None = None
        self._loading = False
        self.setWindowTitle("まんたん設定")
        root = QVBoxLayout(self)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #c0392b;")
        root.addWidget(self.problems)

        form = QFormLayout()
        # ⚠ 「回復役（p1〜p4）」の欄は消した（RX3-0221 / 2026-09-12 依頼者「GUIのｐ１～４を選ぶ画面と被ってるので、不要なら消したい」）。
        #   ★設定ファイルの `healer` は、呪文の表が読めないとき（v0）の控えとして残る
        # ★唱えてよい人（RX3-0214）: 今の並び順で職業名 1 文字のチェック。★勇者は ほかに唱えられる人が居ない時だけ
        self.casters: dict = {}
        caster_row = QWidget()
        caster_lay = QHBoxLayout(caster_row)
        caster_lay.setContentsMargins(0, 0, 0, 0)
        for slot in MS.HEALERS:
            box = QCheckBox(slot[1:])
            box.toggled.connect(self._on_casters)
            caster_lay.addWidget(box)
            self.casters[slot] = box
        caster_lay.addStretch(1)
        form.addRow(MS.LABELS["casters"], caster_row)
        # ★回復のしかた（RX3-0174 / 2026-09-11 依頼者「道具を優先するか、呪文を優先するか、道具を使わないか」）
        self.heal_order = QComboBox()
        for key in MS.HEAL_ORDERS:
            self.heal_order.addItem(MS.HEAL_ORDER_UI[key], key)
        self.heal_order.setToolTip("呪文を優先: MPが足りないときは やくそう を使います。\n"
                                   "道具を優先: やくそう が無くなったら呪文を使います。\n"
                                   "道具を使わない: 呪文だけで回復します。\n"
                                   "毒は、道具を使うときだけ どくけしそう で治します。\n"
                                   "まひ は毒より先に キアリク / まんげつそう で治します（★まんげつそうは道具を使うときだけ）。")
        self.heal_order.currentIndexChanged.connect(self._on_heal_order)
        form.addRow(MS.LABELS["heal_order"], self.heal_order)

        self.hp = QSlider(Qt.Orientation.Horizontal)
        self.hp.setRange(MS.HP_MIN, MS.HP_MAX)
        self.hp.setSingleStep(MS.HP_STEP)
        self.hp.setPageStep(MS.HP_STEP)
        self.hp.setTickInterval(MS.HP_STEP)
        self.hp.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.hp.valueChanged.connect(self._on_hp)
        self.hp_label = QLabel()
        form.addRow(MS.LABELS["hp_below"], self._pair(self.hp, self.hp_label))

        self.mp = QSlider(Qt.Orientation.Horizontal)
        self.mp.setRange(MS.MP_MIN, MS.MP_MAX)
        self.mp.valueChanged.connect(self._on_mp)
        self.mp_label = QLabel()
        form.addRow(MS.LABELS["min_mp"], self._pair(self.mp, self.mp_label))

        self.turbo = QCheckBox(MS.LABELS["turbo"])
        self.turbo.toggled.connect(self._on_turbo)
        form.addRow("", self.turbo)

        self.spell = QLabel()
        form.addRow("呪文", self.spell)
        root.addLayout(form)

        self.file_note = QLabel()
        self.file_note.setWordWrap(True)
        self.file_note.setStyleSheet("color: #8a93a5;")
        root.addWidget(self.file_note)
        note = QLabel(BATTLE_NOTE + "\n★変えた値は、次に まんたん を始めたときから効きます")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8a93a5;")
        root.addWidget(note)

        buttons = QHBoxLayout()
        self.run_button = QPushButton("まんたんを実行")
        self.run_button.setToolTip("★右画面の「満」と同じです（⚠ フィールドで押してください）")
        self.run_button.clicked.connect(self.run_now)
        self.reset_button = QPushButton("既定に戻す")
        self.reset_button.setToolTip("★画面で変えた値を消し、設定ファイルの値に戻します")
        self.reset_button.clicked.connect(self.reset_all)
        close = QPushButton("閉じる")
        close.clicked.connect(self.close)
        buttons.addWidget(self.run_button)
        buttons.addStretch(1)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.last = QLabel()
        self.last.setWordWrap(True)
        root.addWidget(self.last)
        self.refresh()

    @staticmethod
    def _pair(slider, label) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(slider, 1)
        label.setMinimumWidth(150)
        row.addWidget(label)
        return box

    # ------------------------------------------------------------------
    def effective(self) -> MS.Effective:
        return MS.effective(self.settings, self.config_path)

    def refresh(self) -> None:
        """★いま効いている値を並べ直す（⚠ 並べ直しで保存を走らせない）。"""
        eff = self.effective()
        v = eff.value
        spell = MS.file_spell(self.config_path)
        names = _names(self.vm)
        self._loading = True
        try:
            classes = _class_marks(self.vm)
            for slot, box in self.casters.items():
                mark, hero = classes.get(slot, (slot[1:], False))
                box.setText(mark)
                box.setChecked(slot in v.casters)
                who = names.get(slot, slot)
                box.setToolTip("%s%s" % (who, "（★勇者は ほかに唱えられる人が居ない時だけ唱えます）" if hero else ""))
            self.hp.setValue(v.hp_below)
            self.mp.setValue(v.min_mp)
            self.turbo.setChecked(v.turbo)
            self.heal_order.setCurrentIndex(MS.HEAL_ORDERS.index(v.heal_order))
        finally:
            self._loading = False
        self.hp_label.setText("%d%% 未満で回復" % v.hp_below)
        cost = _spell_cost(spell)
        # ★まんたん v1（RX3-0161 / 2026-09-12 依頼者の判断）: 残す MP は「唱えた**後**」
        self.mp_label.setText("唱えた後に %d MP 残す%s" % (
            v.min_mp, ("（★%sは %d MP）" % (spell, cost)) if cost is not None else ""))
        # ★まひ（RX3-0252）: キアリク / まんげつそう
        self.spell.setText("★覚えている呪文から選ぶ（ホイミ / ベホイミ / ベホマ / 毒にキアリー / まひにキアリク）")
        changed = [MS.LABELS[f] for f in MS.FIELDS if eff.source.get(f) == "screen"]
        self.file_note.setText(
            ("★画面で変えている: %s（[既定に戻す] で設定ファイルの値へ）" % "・".join(changed))
            if changed else "★いまは設定ファイルの値で動いています")
        problems = list(eff.problems) + ([self.last_error] if self.last_error else [])
        self.problems.setText("\n".join(problems))
        self.problems.setVisible(bool(problems))
        self.last.setText(self._last_text())

    def _last_text(self) -> str:
        rows = getattr(self.action_log, "rows", None) or []
        got = [r for r in rows if getattr(r, "action", None) == "mantan"]
        return ("前回: " + got[-1].line()) if got else "前回: まだ記録がありません"

    # ------------------------------------------------------------------
    def _save(self, field: str, value) -> None:
        if self._loading:
            return
        why = MS.set_value(self.settings, field, value)
        if why is None:
            try:
                MS.write_overlay(self.settings)
                self.last_error = None
            except OSError as err:
                self.last_error = "⚠ まんたんへ渡せませんでした: %s" % err
        else:
            self.last_error = "⚠ " + why
        self.refresh()

    def _on_casters(self, _on: bool = False) -> None:
        """★チェックした人だけ唱える（⚠ 全員を外すことはできない → 理由を出して元に戻す）。"""
        if self._loading:
            return
        self._save("casters", tuple(s for s in MS.HEALERS if self.casters[s].isChecked()))

    def _on_hp(self, value: int) -> None:
        # ★5 刻みにそろえる（⚠ ドラッグの途中で 87 などにならない）
        snapped = int(round(value / MS.HP_STEP) * MS.HP_STEP)
        if snapped != value and not self._loading:
            self.hp.setValue(snapped)
            return
        self._save("hp_below", snapped)

    def _on_mp(self, value: int) -> None:
        self._save("min_mp", value)

    def _on_turbo(self, on: bool) -> None:
        self._save("turbo", bool(on))

    def _on_heal_order(self, index: int) -> None:
        self._save("heal_order", self.heal_order.itemData(index))

    def reset_all(self) -> None:
        MS.reset(self.settings)
        try:
            MS.write_overlay(self.settings)
            self.last_error = None
        except OSError as err:
            self.last_error = "⚠ まんたんへ渡せませんでした: %s" % err
        self.refresh()

    def run_now(self) -> None:
        """★「満」と同じ頼み（⚠ 新しい押し方は作らない）。"""
        if self.commands is None:
            return
        try:
            self.commands.send("mantan")
            self.last_error = None
        except (OSError, ValueError) as err:
            self.last_error = "⚠ 頼めませんでした: %s" % err
        self.refresh()


class MantanRow(QWidget):
    """★右画面の 1 行: `まんたん  エルシド・HP 90% 未満 [設定]`（★戦略の行と同じ置き方）。"""

    def __init__(self, settings, vm=None, open_window=None, parent=None,
                 config_path=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.vm = vm
        self.config_path = config_path or MS.CONFIG
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("まんたん"))
        self.summary = QLabel()
        # ⚠ 長い名前で右パネルの幅を広げない（★360px / RX3-0102）
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.summary, 1)
        self.button = QPushButton("設定")
        self.button.setToolTip("まんたんの設定を開く\n"
                               "★回復役 / 回復を始める HP / 残す MP / ターボ")
        if open_window is not None:
            self.button.clicked.connect(open_window)
        row.addWidget(self.button)
        self._last = None
        self.refresh()

    def refresh(self) -> None:
        text = MS.summary(MS.effective(self.settings, self.config_path), _names(self.vm))
        if text != self._last:
            self.summary.setText(text)
            self._last = text


__all__ = ["MantanWindow", "MantanRow", "BATTLE_NOTE"]
