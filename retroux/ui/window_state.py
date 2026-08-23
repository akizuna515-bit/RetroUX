"""ウィンドウの位置とサイズを覚える（2026-07-30 / リリース調整 仕様書 8章）。

★★ **⚠ いちばん大事なのは「画面外に保存されたものを復旧できる」こと** ★★

  仕様書 8章:
    > ディスプレイ構成が変わり画面外に出る場合は、主画面内へ戻す。

  これが無いと、外付けモニタを外したときに
  **窓が見えない場所に開き、利用者からは「起動しない」ように見える**。
  しかも本人には直しようがない（窓が見えないので動かせない）。

## 保存するもの

    位置・サイズ / スプリッターの配分 / チェックの状態

★保存先は `work/window-state.json`。設定（`user_config.yaml`）とは分ける。
  ⚠ 混ぜると、窓を動かすたびに利用者の設定ファイルが書き換わる。

## 落ちないこと

⚠ 読めない・書けない・中身が変でも**必ず既定へ落ちる**。
  窓の位置を思い出せないだけで、ゲームは遊べる。
"""

from __future__ import annotations

import json
import os
import pathlib

#: 既定の保存先
DEFAULT_PATH = pathlib.Path("work/window-state.json")

#: 窓の最小の大きさ（これ未満で保存されていたら使わない）。
#   ⚠ 0×0 や 1×1 が保存されると、開いても何も見えない
#     ＝「起動しない」に見える。
MIN_WIDTH = 320
MIN_HEIGHT = 240

#: ★「ただ開いただけ」の場所。⚠ 利用者が決めた配置と混ぜないこと（RX-0104）
PLACED_DEFAULT = "default"
#: ★利用者の配置（自分で動かした / 整列で置いた / 前回の記録を戻した）
PLACED_USER = "user"


def usable(values, *, min_width: int = MIN_WIDTH,
           min_height: int = MIN_HEIGHT) -> bool:
    """その記録で窓を置けるか（RX-0101）。

    ⚠ 小さすぎる記録は使わない（開いても何も見えない）。
    ★`apply_to` と `remembers` の**両方がここを呼ぶ**。
    """
    if not values:
        return False
    try:
        return (int(values.get("w") or 0) >= min_width
                and int(values.get("h") or 0) >= min_height)
    except (TypeError, ValueError):
        return False

#: 画面内と認めるために必要な重なり（画素）。
#   ★角が1画素かかっているだけでは掴めないので、これだけは要る。
VISIBLE_MARGIN = 80


class WindowState:
    """窓の状態を読み書きする入れ物。

    ⚠ Qt に依存する処理（`geometry` の適用）は `apply_to` / `capture_from`
      に閉じてある。読み書きだけなら Qt 無しで試せる。
    """

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path or DEFAULT_PATH)
        self.data: dict = {}
        self.problems: list = []
        self.load()

    # --- 読み書き ---------------------------------------------------

    def load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = raw if isinstance(raw, dict) else {}
                if not isinstance(raw, dict):
                    self.problems.append("窓の位置の記録が読めません（既定で開きます）")
        except (OSError, ValueError):
            # ⚠ 壊れていても落ちない（位置を思い出せないだけ）
            self.data = {}
            self.problems.append("窓の位置の記録が壊れています（既定で開きます）")

    def forget(self) -> None:
        """覚えている位置を全部捨てる（2026-08-01 の指示書 §7.1）。

        ★「標準レイアウトに戻す」で使う。
          ⚠ 捨てないと、次の整列が「覚えているから動かさない」と判断して
            **押しても何も起きない**ことになる。

        ⚠ ファイルは消さずに中身を空にする（次の保存で普通に書けるように）。
        """
        self.data = {}
        self.save()

    def save(self) -> bool:
        """書く。戻り値は**書けたか**（書けなくても本体は止めない）。

        ★一時ファイル経由。終了時に書くので、途中で落ちると
          **次回に半端な内容を読む**ことになる。
        """
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(self.data, ensure_ascii=False,
                                       indent=1, sort_keys=True),
                            encoding="utf-8")
            os.replace(temp, self.path)
            return True
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    # --- 1つの窓 ----------------------------------------------------

    def get(self, key: str) -> dict:
        found = self.data.get(key)
        return found if isinstance(found, dict) else {}

    def put(self, key: str, values: dict) -> None:
        self.data[key] = values

    def capture_from(self, key: str, widget, *, splitter=None,
                     extra: dict | None = None) -> None:
        """窓から状態を取る（終了時に呼ぶ）。"""
        try:
            geometry = widget.geometry()
            values = {
                "x": int(geometry.x()), "y": int(geometry.y()),
                "w": int(geometry.width()), "h": int(geometry.height()),
                "maximized": bool(widget.isMaximized()),
            }
            if splitter is not None:
                values["splitter"] = [int(v) for v in splitter.sizes()]
            if extra:
                values.update(extra)
            self.put(key, values)
        except Exception:                              # noqa: BLE001
            # ⚠ 取れなくても終了処理を止めない
            pass

    def remembers(self, key: str, *, min_width: int = MIN_WIDTH,
                  min_height: int = MIN_HEIGHT) -> bool:
        """その窓の配置を**使える形で**覚えているか（RX-0101 / 2026-08-23）。

        ★★ 「記録がある」と「その記録で置けた」は別。 ★★

          ⚠⚠ ここを `get(key)` の真偽で代用していて、実害が出た:
            小さすぎる記録は `apply_to` が弾き、窓は **Qt の既定**
            （画面中央・大きめ）で開く。ところが自動整列のほうは
            「覚えているから動かさない」と判断して**手を出さない**。
            ★結果、起動するたびに窓が重なったまま誰も直さない。

          ★判定は `apply_to` と**同じ条件**を使うこと（下の `usable`）。
            2か所に書くと、片方だけ直したときに静かにずれる。
        """
        values = self.get(key)
        if values.get("placed") == PLACED_DEFAULT:
            # ★★ **ただ開いただけの場所は「覚えている」ではない**（RX-0104）★★
            #   ⚠⚠ 起動から約2秒で、画面は**自分の既定の配置**を書きます。
            #     そのあと自動整列が読むと「覚えているから動かさない」と判断し、
            #     ★既定の大きな窓が並べられないまま残ります。しかも一度書かれると
            #     **毎回そうなる**（実測: 14:03:39 起動 → 14:03:41.089 保存 →
            #     14:03:41 整列が全部飛ばす）。
            return False
        return usable(values, min_width=min_width, min_height=min_height)

    def apply_to(self, key: str, widget, *, splitter=None,
                 min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT) -> bool:
        """窓へ状態を戻す（起動時に呼ぶ）。戻り値は**戻せたか**。

        ★★ **画面外なら主画面へ寄せる**（仕様書 8章）★★

        ⚠ 最小サイズは窓ごとに違ってよい（2026-08-11）。★下段のログ窓は
          横長で**背が低い**（150px 前後）ため、主画面向けの下限（240px）だと
          **毎回はじかれて既定位置（左上）に開いて**いた（依頼者の報告）。
          ★そういう窓は `min_height` を下げて渡す。
        """
        values = self.get(key)
        if not values:
            return False
        try:
            width = int(values.get("w") or 0)
            height = int(values.get("h") or 0)
            if not usable(values, min_width=min_width, min_height=min_height):
                # ⚠ 小さすぎる記録は使わない（開いても何も見えない）
                self.problems.append(
                    f"{key} の保存サイズが小さすぎるため既定で開きます"
                    f"（{width}×{height}）")
                return False
            x = int(values.get("x") or 0)
            y = int(values.get("y") or 0)
            x, y, moved = clamp_to_screens(x, y, width, height)
            if moved:
                self.problems.append(
                    f"{key} が画面の外に保存されていたため、画面内へ戻しました")
            widget.setGeometry(x, y, width, height)
            if values.get("maximized"):
                # ⚠⚠ `showMaximized()` は**窓を開いてしまいます**
                #   （2026-08-09 に発覚 / `test_closed_separate_window_is_not_touched`）。
                #   ★遅延生成の窓は「作るだけ」で開かないことがあるので、
                #     ここで開くと閉じているはずの窓が出ます。
                #   → 状態だけ立てる。開くのは呼ぶ側の判断です。
                from PySide6.QtCore import Qt as _Qt

                widget.setWindowState(
                    widget.windowState() | _Qt.WindowState.WindowMaximized)
            if splitter is not None:
                sizes = values.get("splitter")
                if isinstance(sizes, list) and sizes and all(
                        isinstance(v, int) for v in sizes):
                    # ⚠ 段の数が変わっていたら使わない（Qt が黙って詰める）
                    if len(sizes) == splitter.count() and sum(sizes) > 0:
                        splitter.setSizes(sizes)
            return True
        except Exception:                              # noqa: BLE001
            return False


def screen_rects() -> list:
    """いまつながっている画面の矩形 `[(x, y, w, h), ...]`。

    ⚠ Qt が無い／画面が取れない環境では**空**を返す。
      そのときは「画面外かどうか」を判断しない（推測で動かさない）。
    """
    try:
        from PySide6.QtGui import QGuiApplication

        made = []
        for screen in QGuiApplication.screens() or []:
            r = screen.availableGeometry()
            made.append((r.x(), r.y(), r.width(), r.height()))
        return made
    except Exception:                                  # noqa: BLE001
        return []


def primary_rect():
    """主画面の矩形。取れなければ None。"""
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        r = screen.availableGeometry()
        return (r.x(), r.y(), r.width(), r.height())
    except Exception:                                  # noqa: BLE001
        return None


def overlaps(x: int, y: int, w: int, h: int, rect) -> bool:
    """その矩形と**掴める程度に**重なっているか。"""
    rx, ry, rw, rh = rect
    left = max(x, rx)
    top = max(y, ry)
    right = min(x + w, rx + rw)
    bottom = min(y + h, ry + rh)
    return (right - left) >= VISIBLE_MARGIN and (bottom - top) >= VISIBLE_MARGIN


def clamp_to_screens(x: int, y: int, w: int, h: int,
                     screens=None, primary=None) -> tuple:
    """画面外なら主画面へ寄せる。戻り: `(x, y, 動かしたか)`。

    ★★ 判断は「どれか1つの画面と**掴める程度に**重なっているか」。 ★★
      ⚠ 「完全に収まっているか」で判断すると、画面をまたいで置いている
        窓を毎回動かしてしまう（利用者が意図して置いた配置を壊す）。

    ⚠ 画面の情報が取れないときは**動かさない**（推測で動かさない）。
    """
    rects = screen_rects() if screens is None else screens
    if not rects:
        return x, y, False
    if any(overlaps(x, y, w, h, r) for r in rects):
        return x, y, False

    base = primary_rect() if primary is None else primary
    if base is None:
        base = rects[0]
    bx, by, bw, bh = base
    # ★主画面の中に収める。入りきらなければ左上に寄せる
    new_x = bx + max(0, (bw - w) // 2)
    new_y = by + max(0, (bh - h) // 2)
    return int(new_x), int(new_y), True


def center_on_screen(widget) -> bool:
    """窓を、いま乗っている画面の**作業領域の真ん中**へ置く（RX-0105）。

    ★★ **題名の帯が画面の外へ出ないこと**が本題です。 ★★

      ⚠ 置き場所を決めないと、Qt は親を基準に置きます。親（本体の窓）が
        画面の上端にあると、子の窓は**上へはみ出して題名の帯が掴めません**
        （依頼者「ウィンドウツールバーが表示されていない」/ 2026-08-23）。

    ⚠ 画面の情報が取れないときは**何もしない**（推測で動かさない）。
    戻り値は**動かしたか**。
    """
    try:
        from PySide6.QtGui import QGuiApplication
    except Exception:                                  # noqa: BLE001
        return False
    try:
        screen = (QGuiApplication.screenAt(widget.pos())
                  or QGuiApplication.primaryScreen())
        if screen is None:
            return False
        area = screen.availableGeometry()
        size = widget.frameGeometry().size()
        if size.width() <= 0 or size.height() <= 0:
            size = widget.size()
        # ★はみ出すときは作業領域の左上に寄せる（負にはしない）
        x = area.x() + max(0, (area.width() - size.width()) // 2)
        y = area.y() + max(0, (area.height() - size.height()) // 2)
        widget.move(x, y)
        return True
    except Exception:                                  # noqa: BLE001
        return False
