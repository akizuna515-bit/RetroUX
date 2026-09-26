"""ボタンのアイコン（RX3-0325 / 2026-09-20）。

依頼者 2026-09-20:

    公開前のUI仕上げとして主要ボタンをアイコン化します。
    シンプル / フラット / 現代的 / 視認性重視 / 過度にゲーム風・レトロ風にしない

## ★アイコンの名前と機能の対応は、この表 1 つだけ

⚠⚠ **画面ごとにアイコンを持たせません。** 同じ「検索」が 2 つの実装になるのを防ぎます。
★絵は `assets/icons/dq3/*.svg`（24x24 / 線幅 2 / 丸い端 / 単色 / 塗りつぶし最小）。

## ⚠ なぜ SVG なのか（★DQ2 の判断との違い）

★DQ2 側（`retroux/ui/main_window.py` の `_button_icon`）は **`QPainter` で手描き**しています。
理由は「⚠ 文字・絵文字は実機で字形が化けた」（RX-0071）。

→ ★SVG は**フォントではなくリポジトリ同梱のファイル**なので、その心配には当たりません。
★実測（2026-09-20）: PySide6 6.11.1 で `QtSvg` が読め、`QImageReader` が `svg` を認識し、
`QIcon(svg).pixmap(32)` が中身のある絵を返します。⚠ 配布は PyInstaller で固めていない
（ソース配布＋利用者の `.venv`）ので、★`qsvg.dll` は PySide6 の wheel に必ず付いてきます。

⚠ `.svg` を増やしたら `release/public-manifest.yaml` の許可リストも足すこと
（★素のファイルパス読みで、`.qrc` は使っていません）。

## ⚠⚠ 色は QIcon では変えられません

★SVG の本文の `STROKE` を**塗り替えてから**描きます。
⚠ だから SVG の線の色は**必ず `STROKE` の 1 色**で書いてください（検査が見ます）。
"""
from __future__ import annotations

import pathlib

#: ★絵の置き場（⚠ `dq3/ui/` から 2 つ上がリポジトリの根）
DIR = pathlib.Path(__file__).resolve().parents[2] / "assets" / "icons" / "dq3"

#: ⚠⚠ SVG の中で使う**唯一の色**。★ここを塗り替えて色を出します。
STROKE = "#5a6270"

#: ★描く大きさの既定（⚠ 依頼者「アイコン単体 16〜20px程度」）
SIZE = 16

#: ★★ 役割 → 絵（⚠ **この表が正本**。画面はここだけを見ます）
#:
#:   ⚠ 鍵は「画面に出す字」ではなく**役割**です（★字は変わっても鍵は変わらない）。
ICONS = {
    # --- 戦闘系 ---
    "auto": "auto.svg",              # ★自動戦闘（再生の三角＋歯車）
    "turbo": "turbo.svg",            # ★高速化（>>）
    "stop": "stop.svg",              # ★止める（四角）
    "mantan": "mantan.svg",          # ★まんたん（ハート＋＋）
    # --- 探索・情報系 ---
    "map": "map.svg",                # ★地図（折りたたみ地図）
    "memo": "memo.svg",              # ★勇者メモ（ノート）
    "council": "council.svg",        # ★勇者会議（2 つの吹き出し）
    "hear": "hear.svg",              # ★聞き込み（耳＋吹き出し）
    "search": "search.svg",          # ★検索（虫眼鏡）
    # --- 街移動系 ---
    "inn": "inn.svg",                # ★宿屋（ベッド）
    "item_shop": "item_shop.svg",    # ★道具屋（道具袋）
    "weapon": "weapon.svg",          # ★武器防具屋（剣＋盾）
    "church": "church.svg",          # ★教会（⚠ 十字だけにしない / 建物として分かること）
    # --- 管理系 ---
    "admin": "admin.svg",            # ★管理（3 本のつまみ）
    # --- ★同じ行の見た目を揃えるための残り（⚠ 依頼者の「第2弾」より先に要る） ---
    "align": "align.svg",            # ★窓を並べる
    "monster": "monster.svg",        # ★モンスター図鑑
    "shop": "shop.svg",              # ★お店の品揃え
    "exit": "exit.svg",              # ★終わる
    "entrance": "entrance.svg",      # ★街の入口
    "restock": "restock.svg",        # ★補充
    "rehear": "rehear.svg",          # ★再聞き込み
}

#: ★読んだ絵をとっておく（⚠ 500ms ごとの描き直しで毎回ファイルを読まない）
_CACHE: dict = {}


def path(role: str) -> pathlib.Path:
    """★その役割の SVG の場所。⚠ 知らない役割は**黙って無視しない**。"""
    name = ICONS.get(role)
    if name is None:
        raise KeyError("⚠⚠ 知らないアイコンの役割です: %r（★`ICONS` に足してください）" % (role,))
    return DIR / name


def source(role: str, colour: str) -> bytes:
    """★SVG の本文を、その色に塗り替えて返す。"""
    text = path(role).read_text(encoding="utf-8")
    if STROKE not in text:
        raise ValueError("⚠⚠ %s に %s がありません（★線の色は 1 色だけにしてください）"
                         % (path(role).name, STROKE))
    return text.replace(STROKE, colour).encode("utf-8")


def pixmap(role: str, colour: str, px: int = SIZE):
    """★その役割・その色・その大きさの絵。

    ⚠ 画面の拡大率（DPI）に合わせて大きめに描いてから縮めます（★ぼやけないように）。
    """
    key = (role, colour, int(px))
    got = _CACHE.get(key)
    if got is not None:
        return got

    from PySide6.QtCore import QByteArray, QSize
    from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    ratio = 1.0
    screen = QGuiApplication.primaryScreen() if QGuiApplication.instance() else None
    if screen is not None:
        ratio = max(1.0, float(screen.devicePixelRatio() or 1.0))

    side = max(1, int(round(px * ratio)))
    renderer = QSvgRenderer(QByteArray(source(role, colour)))
    if not renderer.isValid():
        raise ValueError("⚠⚠ %s が SVG として読めません" % path(role).name)
    image = QImage(QSize(side, side), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    got = QPixmap.fromImage(image)
    got.setDevicePixelRatio(ratio)
    _CACHE[key] = got
    return got


def icon(role: str, colour: str, px: int = SIZE, disabled: str | None = None):
    """★ボタンに付ける絵。

    ⚠ 押せないときの色も**同じ `QIcon` に入れて**おきます
    （★Qt が自動で切り替えるので、呼ぶ側が押せるかどうかを気にしなくて済む）。
    """
    from PySide6.QtGui import QIcon

    got = QIcon()
    got.addPixmap(pixmap(role, colour, px), QIcon.Mode.Normal)
    if disabled is not None:
        got.addPixmap(pixmap(role, disabled, px), QIcon.Mode.Disabled)
    return got


def roles() -> tuple:
    """★表にある役割ぜんぶ（⚠ 検査が使う）。"""
    return tuple(sorted(ICONS))


def missing() -> tuple:
    """⚠ 表にあるのにファイルが無いもの（★起動時や検査で気づけるように）。"""
    return tuple(sorted(r for r in ICONS if not path(r).exists()))


__all__ = ["DIR", "STROKE", "SIZE", "ICONS", "path", "source", "pixmap", "icon",
           "roles", "missing"]
