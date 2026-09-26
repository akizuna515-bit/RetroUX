"""アイコンのボタン（RX3-0325 / 2026-09-20）。

依頼者 2026-09-20:

    「アイコンで認識しやすくし、文字で意味を確定する」
    原則として主要機能は `アイコン + ラベル` で表示してください。

## ★ここが「見た目」の正本

⚠⚠ Normal / Hover / Active（ON）/ Disabled の 4 つは**この 1 ファイルだけ**が決めます。
★画面ごとに `setStyleSheet` を書かないでください（⚠ 同じ状態が 2 通りに見えます）。

## ★並べ方は 2 つだけ

```text
BESIDE  アイコンの右に字   右パネル（★「オート」「まんたん」など字が長い）
UNDER   アイコンの下に字   街の行（⚠ 横に 8 個並ぶので、字は 1 つぶんの幅しか取れない）
```

⚠ 街の行を `BESIDE` にすると、★状態の文（「★道具屋 1/2 へ」）の場所が無くなります
（実測: 42px × 7 ＋ ［…］で 340px の右パネルがほぼ埋まる）。

## ⚠⚠ 色は増やしません

★`theme.ACCENT` から `theme.mix()` でその場で作ります（依頼者「新しいテーマ色を勝手に増やさない」）。
⚠ 以前の ON は明るい緑（`main_window.ON_STYLE`）でしたが、★白地では薄く、
`theme.MAX_LUMA` の方針とも合わないため **`ACCENT` に寄せました**。

## ⚠⚠ 字を後から書き戻さないこと

★DQ2 で実際に起きました（`tests/test_icon_buttons_have_tooltips.py:126-163`）:
`setText("AUTO ON")` と書き戻した結果、⚠ 幅の狭いボタンから**字がはみ出て**いました。
→ ★字を変えたいときは `set_label()` を使ってください（⚠ 幅も一緒に合わせ直します）。
"""
from __future__ import annotations

from . import icons, theme

#: ★アイコンの大きさ（⚠ 依頼者「アイコン単体 16〜20px程度」）
ICON_PX = 16

#: ★字の置き場所
BESIDE = "beside"
UNDER = "under"
#: ★★ 字を**出さない**（RX3-0328 / 2026-09-21 依頼者「アイコンだけでいい」）。
#:
#:   ⚠⚠ 字（`setText`）は**消しません**。★`text()` は「宿」「オート」を返し続けます。
#:     理由: ★字は**そのボタンが何かを表す名前**でもあり、記録・検査・ツールチップが使います。
#:     ⚠ 空にすると `self._buttons` の鍵や検査の手がかりまで消えます。
#:   → ★出すか出さないかだけを変えます（Qt の `ToolButtonIconOnly`）。
ICON = "icon"

#: ★ボタンの高さ（⚠ 依頼者「縦を稼ぎたい」/ RX3-0328）
HEIGHT = {BESIDE: 32, UNDER: 36, ICON: 28}

#: ★アイコンと字のあいだ／左右の余白
GAP = 5
PAD = 6

#: ★字の下に置くときの字の大きさ（⚠ 小さくしないと 1 文字ぶんの幅に収まらない）
UNDER_PX = 10

#: ★右パネルで使える幅（⚠ `layout.SIDE_MIN` 360 から左右の余白 10 ずつを引いた値）
PANEL_WIDTH = 340

#: ★ボタンどうしの隙間（⚠ `main_window` のグリッドと同じ）
SPACING = 4


# ----------------------------------------------------------------------
# ★色（⚠ ここ 1 か所だけ）
# ----------------------------------------------------------------------
def colours() -> dict:
    """★4 つの状態の色。⚠ すべて `theme` の色から作ります（新しい色を増やさない）。"""
    return {
        # ★ふつう
        "bg": theme.CARD,
        "border": theme.BORDER,
        "ink": theme.INK,
        # ★ふれたとき（⚠ ごく薄く）
        "hover_bg": theme.mix(theme.CARD, theme.ACCENT, 0.08),
        "hover_border": theme.mix(theme.BORDER, theme.ACCENT, 0.45),
        "press_bg": theme.mix(theme.CARD, theme.ACCENT, 0.18),
        # ★入っているとき（⚠ 一目で分かること）
        "on_bg": theme.mix(theme.CARD, theme.ACCENT, 0.15),
        "on_border": theme.ACCENT,
        "on_ink": theme.ACCENT,
        # ★押せないとき（⚠ 押せないと分かること）
        "off_bg": theme.PAPER,
        "off_border": theme.mix(theme.BORDER, theme.PAPER, 0.55),
        "off_ink": theme.mix(theme.INK, theme.PAPER, 0.62),
    }


def style_sheet(place: str = BESIDE) -> str:
    """★ボタン 1 つぶんの見た目。⚠ ON は `on` という印（プロパティ）で切り替えます。"""
    c = colours()
    font = ("font-size: %dpx;" % UNDER_PX) if place == UNDER else ""
    if place == ICON:
        font = ""
    return (
        "QToolButton {"
        " background: %(bg)s; border: 1px solid %(border)s; border-radius: 6px;"
        " color: %(ink)s; padding: 0px; %(font)s }"
        "QToolButton:hover { background: %(hover_bg)s; border-color: %(hover_border)s; }"
        "QToolButton:pressed { background: %(press_bg)s; }"
        "QToolButton[on=\"true\"] { background: %(on_bg)s; border-color: %(on_border)s;"
        " color: %(on_ink)s; font-weight: bold; }"
        "QToolButton:disabled { background: %(off_bg)s; border-color: %(off_border)s;"
        " color: %(off_ink)s; }"
        % dict(c, font=font)
    )


# ----------------------------------------------------------------------
# ★大きさ
# ----------------------------------------------------------------------
def width_for(button, label: str, place: str) -> int:
    """★そのボタンに要る幅。

    ⚠⚠ 字の幅は**実際のフォントで測ります**（★決め打ちの px にしない）。
      画面外（offscreen）には日本語のフォントが 1 つも無く、⚠ 実機とは字の幅が違うためです
      （`docs/50-playbook.md` 2026-09-08）。★実機で組み立てるときに実機の字で測れば合います。
    """
    if place == ICON:
        return ICON_PX + PAD * 2          # ★字は出さないので絵のぶんだけ
    text_px = button.fontMetrics().horizontalAdvance(label or "")
    if place == UNDER:
        return max(ICON_PX, text_px) + PAD * 2
    return ICON_PX + (GAP + text_px if label else 0) + PAD * 2


def fit(button) -> None:
    """★いまの字に合わせて幅を決め直す（⚠ 字が変わったら必ず呼ぶ）。"""
    place = button.property("place") or BESIDE
    want = width_for(button, button.text(), place)
    if button.width() != want or button.minimumWidth() != want:
        button.setFixedWidth(want)


# ----------------------------------------------------------------------
# ★作る
# ----------------------------------------------------------------------
def make(role: str, label: str, tip: str, *, place: str = BESIDE, on_click=None,
         parent=None):
    """★アイコン＋字のボタンを 1 つ作る。

    `role`  … `icons.ICONS` の鍵（⚠ 画面に出す字ではありません）
    `label` … 画面に出す字（★空にしないでください / 依頼者 §4）
    `tip`   … ツールチップ（⚠ 1 行目に**何のボタンか**を書くこと）
    """
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtWidgets import QSizePolicy, QToolButton

    c = colours()
    button = QToolButton(parent)
    button.setText(label)
    button.setToolTip(tip)
    button.setIcon(icons.icon(role, c["ink"], ICON_PX, disabled=c["off_ink"]))
    button.setIconSize(QSize(ICON_PX, ICON_PX))
    button.setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly if place == ICON
        else Qt.ToolButtonStyle.ToolButtonTextUnderIcon if place == UNDER
        else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setAutoRaise(False)
    # ★役割と並べ方を覚えておく（⚠ 色を塗り替えるときに要る）
    button.setProperty("role", role)
    button.setProperty("place", place)
    button.setProperty("on", False)
    button.setStyleSheet(style_sheet(place))
    button.setFixedHeight(HEIGHT[place])
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    fit(button)
    if on_click is not None:
        button.clicked.connect(on_click)
    return button


def set_label(button, label: str, tip: str | None = None) -> None:
    """★字を変える（⚠ 幅も合わせ直す / 字がはみ出さないように）。"""
    if button.text() != label:
        button.setText(label)
        fit(button)
    if tip is not None and button.toolTip() != tip:
        button.setToolTip(tip)


def set_role(button, role: str) -> None:
    """★絵を差し替える（例: 聞き込み → 止める）。"""
    if button.property("role") == role:
        return
    from PySide6.QtCore import QSize

    c = colours()
    on = bool(button.property("on"))
    button.setProperty("role", role)
    button.setIcon(icons.icon(role, c["on_ink"] if on else c["ink"], ICON_PX,
                              disabled=c["off_ink"]))
    button.setIconSize(QSize(ICON_PX, ICON_PX))


def set_on(button, on: bool) -> None:
    """★ON / OFF の見た目（⚠ 押した瞬間ではなく、**実際の状態**で呼ぶこと）。

    ⚠⚠ `main_window` の AUTO / TURBO は、★UI 側に真偽値を持っていません。
      `state.json` に Lua が書いた値の鏡です（`_apply_battle_buttons`）。
      → ★押した瞬間にここを呼ばないでください（嘘の表示になります）。
    """
    on = bool(on)
    if bool(button.property("on")) == on:
        return
    from PySide6.QtCore import QSize

    c = colours()
    button.setProperty("on", on)
    role = button.property("role")
    if role:
        button.setIcon(icons.icon(role, c["on_ink"] if on else c["ink"], ICON_PX,
                                  disabled=c["off_ink"]))
        button.setIconSize(QSize(ICON_PX, ICON_PX))
    # ⚠ 印（プロパティ）で切り替えた見た目は、★磨き直さないと反映されません
    button.style().unpolish(button)
    button.style().polish(button)


def is_on(button) -> bool:
    """★いま ON の見た目か（⚠ 検査と画面の両方がここを見る）。"""
    return bool(button.property("on"))


# ----------------------------------------------------------------------
# ★並べる
# ----------------------------------------------------------------------
def wrap_rows(buttons, max_width: int = PANEL_WIDTH, spacing: int = SPACING) -> list:
    """★入るだけ 1 段に並べ、あふれたら次の段へ（★段の数は字の幅しだい）。

    ⚠⚠ 段数を決め打ちにしないでください。★画面外（offscreen）と実機で字の幅が違うため、
      決め打ちだと**実機でだけ右パネルからはみ出します**（RX3-0074 / RX3-0084 と同じ事故）。
    """
    rows: list = []
    row: list = []
    used = 0
    for button in buttons:
        want = button.width() or button.sizeHint().width()
        need = want if not row else used + spacing + want
        if row and need > max_width:
            rows.append(row)
            row, used = [button], want
        else:
            row.append(button)
            used = need
    if row:
        rows.append(row)
    return rows


__all__ = ["ICON_PX", "BESIDE", "UNDER", "HEIGHT", "PANEL_WIDTH", "SPACING",
           "colours", "style_sheet", "width_for", "fit", "make", "set_label",
           "set_role", "set_on", "is_on", "wrap_rows"]


# ----------------------------------------------------------------------
# ★押せないボタンの説明（RX3-0329 / 2026-09-21）
# ----------------------------------------------------------------------
def watch_disabled(container) -> None:
    """★押せない（`setEnabled(False)`）ボタンでも説明を出す。

    依頼者 2026-09-21: 「ツールチップはだしてほしい」

    ⚠⚠ **Qt は押せない部品にマウスの出来事を届けません。**
      ★だから `setToolTip` を入れてあっても、押せない間は**出ません**。
      ⚠ ところが「なぜ押せないのか」を知りたいのは、まさに押せないときです
        （★「面識のある宿屋がまだありません」「Turboは戦闘中に使えます」）。

    → ★**入れ物**が代わりに受け取り、その場所にある子の説明を出します
      （⚠ `childAt` は押せない子も返します）。

    ⚠ 押せるときは今までどおり Qt が出します（★ここは何もしません）。
    """
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QToolTip

    class _Filter(QObject):
        def eventFilter(self, obj, event):      # noqa: N802 - ★Qt の名前
            if event.type() == QEvent.Type.ToolTip:
                child = obj.childAt(event.pos())
                if child is not None and not child.isEnabled():
                    tip = (child.toolTip() or "").strip()
                    if tip:
                        QToolTip.showText(event.globalPos(), tip, obj)
                        return True
            return False

    # ⚠⚠ **親を `container` にします。** ★これが見張りを生かし続けます。
    #   ⚠ 親を付けずに作ると、その場で回収されて**黙って効かなくなります**
    #     （★2026-09-21 の壊す実験で、別に控えを持つ行は無意味だと分かった）。
    container.installEventFilter(_Filter(container))
