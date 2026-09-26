"""窓の並べ方（RX3-0019 / 2026-08-29）。

依頼者 2026-08-29:

    窓の初期の大きさだが、1920x1080 にピッタリハマるように変更して。
    いまはメイン画面と被ってしまっている

```text
┌──────────────┬────────────────┬──────────────┐
│  見た地図     │  FCEUX（中央）  │  右パネル     │
├──────────────┴────────────────┴──────────────┤
│  ログ（モンスター / 戦闘ログ / System Log）    │
└───────────────────────────────────────────────┘
```

## ⚠⚠ 画面の大きさではなく「作業領域」を使う

★タスクバーを除いた範囲で計算します。
⚠ 画面の高さで並べると、**下端がタスクバーに隠れます**。
⚠ タスクバーは上や左に置いている人もいるので、**上端も 0 とは限りません**。

## ⚠⚠⚠ 論理と物理を混ぜない（2026-08-29 に実際に踏んだ）

依頼者の画面は **125% / 150%** の拡大表示です。そこで 2 つの座標系が出てきます。

```text
Qt（この画面）           論理  1280 x 752   ★availableGeometry()
Win32（FCEUX を動かす）  物理  1920 x 1128  ⚠ window_align.work_area()
                         倍率  1.5          ★devicePixelRatio()
```

⚠ `window_align.work_area()`（物理 1920）を Qt へ渡したところ、
★窓が **1.5 倍**になって画面からはみ出しました（依頼者の画面で確認）。

→ ★**Qt の窓は Qt の値で、FCEUX は物理の値で**。境目で `to_physical` を通します。

## ⚠ Qt を import しません

★画面が無くても数だけ確かめられるようにするためです。
"""

from __future__ import annotations

from dataclasses import dataclass

#: ★NES の画面（★1 倍）
NES_W, NES_H = 256, 240

#: ★★ 上段の高さ ＝ **NES の 2 倍 ＋ タイトルバー ＋ メニューバー**。
#:
#: 依頼者 2026-08-29:「②にタイトルバー、メニューバーがついたやつで。」
#: （★② ＝ NES 画面 240×2 = 480px）
#:
#: ⚠ 帯の厚みは環境で違う（★拡大率・テーマ）。**決め打ちしない**。
#:   → ★FCEUX の窓が動いていれば**その高さを測って**使う。
#:   ⚠ 見つからないときだけ、下の見積もりを使う。
TITLE_BAR_H = 30          #: ★題名の帯（⚠ Qt の実測が 30）
MENU_BAR_H = 24           #: ★メニューの帯（File / NES / Config …）

#: ★見つからないときの上段の高さ（論理）
TOP_H_FALLBACK = NES_H * 2 + TITLE_BAR_H + MENU_BAR_H

#: ★下段（ログ）の高さ（**論理**）。
#:
#: ⚠ 上段が決まったら**残り全部**が下段になる。ここは見つからないときの目安。
#: ⚠⚠ 依頼者「下のログ欄の縦は少し小さくして重ならないようにまずはしたい」
#: ★2026-09-02（RX3-0060）: 札に耐性・特技の 1 行を足した（帯の下限 104 → 120）ぶん 210 → 226
BOTTOM_H = 226

#: ★中央（FCEUX）に空ける幅。
#:
#: ⚠ FCEUX の窓は NES 256x240 の 2 倍（512x480）＋メニューと枠で、
#:   実測 **約 770x730**（依頼者の 1920x1080 の画面 / 2026-08-29）。
#: ★少し余裕を持たせる。⚠ 足りないと右パネルに潜り込む。
CENTER_W = 800

#: ⚠ 左右がこれより狭くなるなら、中央を譲る（★狭い画面で潰れないように）
SIDE_MIN = 360

#: ★★ 下の窓の既定の配分 ― モンスターの帯が取る割合（RX3-0037 / 2026-09-01）。
#:
#:   依頼者 2026-09-01:
#:
#:     > モンスター画面とログ画面のバランスで、
#:     > ★モンスター画面はちゃんと**デフォルトでなるべく表示**させたい
#:
#:   ⚠ もとは「帯は固定 104px / ログが残り全部」で、★伸びるのはログだけでした。
MONSTER_SHARE = 0.62


def bottom_split(total_h: int, strip_min: int, log_min: int,
                 share: float = MONSTER_SHARE) -> tuple[int, int]:
    """下の窓を「モンスターの帯」と「ログ」へ分ける（★既定の配分）。

    @param total_h    分け合える高さ（★余白と仕切りを引いたあと）
    @param strip_min  帯の下限（★`monster_panel.STRIP_HEIGHT`。札が切れる線）
    @param log_min    ログの下限（★`battle_window.LOG_MIN`。0 行にしない線）
    @return `(帯, ログ)`

    ## ⚠⚠ 足りないときは、**帯を優先**します

      ★DQ2 と DQ3 で 2 度踏んだ失敗が「札が切れる」ほうです
      （`test_layout_heights.test_札を切らない` / 2026-08-14、
        `setMaximumHeight(88)` / 2026-09-01）。
      ⚠ ログは 1 行減っても読めますが、★切れた札は**嘘を出します**
        （性能が 3 つ消えていました）。

    ## ★これは「既定」だけです

      ⚠ 人がつまんで変えたぶんは、こちらでは戻しません
      （`docs/design/dq3-ui-v0.md`「★してよい ＝ 人がつまんで変えたとき」）。
    """
    total = max(0, int(total_h))
    strip_min = max(0, int(strip_min))
    log_min = max(0, int(log_min))
    if total <= strip_min + log_min:
        # ⚠ 分け合えない。★帯を先に満たし、残りをログへ（負にはしない）
        strip = min(strip_min, total)
        return (strip, total - strip)
    strip = round(total * float(share))
    # ★どちらの下限も割らない範囲へ寄せる
    strip = max(strip_min, min(strip, total - log_min))
    return (int(strip), int(total - strip))


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class Layout:
    map: Box
    center: Box
    panel: Box
    bottom: Box


def compute(area, *, bottom_h: int = BOTTOM_H, center_w: int = CENTER_W,
            top_h: int | None = None) -> Layout:
    """作業領域から、4 つの置き場所を決める。

    @param area  `(left, top, width, height)`（★**論理**の値）
    @param top_h 上段の高さ。★FCEUX の窓の高さを渡す
                 （⚠ 渡さなければ `bottom_h` から逆算）

    ⚠ 中央（FCEUX）は**こちらの窓ではない**が、場所は空けておく。
      ★空けないと必ず重なる（依頼者「メイン画面と被ってしまっている」）。
    """
    left, top, width, height = area
    if top_h is not None:
        # ★上段を先に決める（⚠ 下段は**残り全部**）
        top_h = max(200, min(int(top_h), height - 120))
        bottom_h = height - top_h
    else:
        bottom_h = max(120, min(int(bottom_h), height // 2))
        top_h = height - bottom_h

    # ⚠ 狭い画面では中央を譲る（★左右が潰れると何も読めない）
    center = min(int(center_w), max(0, width - SIDE_MIN * 2))
    side = (width - center) // 2
    # ★端数は右パネルへ寄せる（⚠ 1px の隙間を残さない）
    right_w = width - center - side

    return Layout(
        map=Box(left, top, side, top_h),
        center=Box(left + side, top, center, top_h),
        panel=Box(left + side + center, top, right_w, top_h),
        bottom=Box(left, top + top_h, width, bottom_h),
    )


#: ★既定に使う画面（⚠ 実際の作業領域が取れないときだけ）。
#:   ⚠ **論理**の値（★1920x1080 を 100% で使っているときの数）。
DEFAULT_AREA = (0, 0, 1920, 1032)


def default_sizes(area=None) -> Layout:
    """★起動直後の大きさ（⚠ 作業領域が取れなければ 1920x1080 を仮定）。"""
    return compute(area or DEFAULT_AREA)


def to_physical(box: Box, ratio: float) -> Box:
    """★Qt の論理座標を、Win32 の物理座標へ直す。

    ⚠⚠ FCEUX は別プロセスで、`SetWindowPos` は**物理**で効きます。
    ★125% なら 1.25、150% なら 1.5（`QScreen.devicePixelRatio()`）。
    ⚠ 1.0 のときは何も変わりません。
    """
    if not ratio or ratio <= 0:
        return box
    return Box(round(box.x * ratio), round(box.y * ratio),
               round(box.w * ratio), round(box.h * ratio))


def to_logical(width: int, height: int, ratio: float) -> tuple[int, int]:
    """★物理の大きさを、Qt の論理へ直す（⚠ FCEUX の実寸を測ったとき）。"""
    if not ratio or ratio <= 0:
        return (int(width), int(height))
    return (round(width / ratio), round(height / ratio))


def qt_area(widget=None):
    """★Qt の作業領域（**論理**）を `(x, y, w, h)` で返す。

    ⚠⚠ `window_align.work_area()`（物理）を Qt へ渡してはいけない。
    ★125% / 150% の画面で、窓がそのぶん大きくなる（実際に踏んだ）。
    """
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return None
    screen = None
    if widget is not None:
        screen = widget.screen()
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    geo = screen.availableGeometry()
    return (geo.x(), geo.y(), geo.width(), geo.height())


def qt_ratio(widget=None) -> float:
    """★拡大率（⚠ 100% なら 1.0 / 150% なら 1.5）。"""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return 1.0
    screen = None
    if widget is not None:
        screen = widget.screen()
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def fit_on_screen(window, *, margin: int = 8) -> tuple:
    """★窓を画面の中へ収める（RX3-0328 / 2026-09-21）。

    依頼者 2026-09-21:

        戦闘AIのウィンドウ初期表示位置が全部表示にならない（下が隠れる）。少し上に表示させたい。

    ⚠⚠ Qt は窓を置くとき、**画面からはみ出すかどうかを見ません**。
      ★背の高い窓（戦闘AI設定）を既定の位置に出すと、下が画面の外へ出ていました。

    ★やること: ①作業領域より大きければ縮める ②はみ出す向きへ寄せ直す。
    ⚠ 縮めるのは**画面より大きいとき**だけです（★勝手に小さくしない）。

    戻り値: `(x, y, w, h)`（★置いた場所 / ⚠ 画面が分からなければ `None`）。
    """
    area = qt_area(window)
    if area is None:
        return None
    ax, ay, aw, ah = area
    geo = window.frameGeometry()
    w, h = geo.width(), geo.height()
    if w <= 0 or h <= 0:                       # ⚠ まだ並べ終わっていない（★画面外の Qt / RX3-0258）
        hint = window.sizeHint()
        w, h = max(w, hint.width()), max(h, hint.height())
    w = min(w, aw - margin * 2)
    h = min(h, ah - margin * 2)
    x, y = geo.x(), geo.y()
    # ★はみ出した側へ寄せ直す（⚠ 下がはみ出すなら上へ）
    x = min(max(x, ax + margin), ax + aw - margin - w)
    y = min(max(y, ay + margin), ay + ah - margin - h)
    if (w, h) != (geo.width(), geo.height()):
        window.resize(w, h)
    window.move(x, y)
    return (x, y, w, h)
