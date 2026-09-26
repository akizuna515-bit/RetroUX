"""省力操作のあと、★ゲームへ操作を返す（RX3-0116 / 2026-09-08）。

依頼者 2026-09-08:

    自動移動や聞き込みが終わったあと、ユーザーが FCEUX をクリックし直さなくても、
    そのままゲーム操作へ戻れるようにする。

## ⚠⚠ 順番が決まっています

```text
自動処理 → 速度・Mute を開始前へ復元 → User Action Summary を 1 行 → ★フォーカス復帰
```

★フォーカス復帰は**いちばん最後**です（⚠ 先に戻すと、まだ動いている処理の
画面が前に出てきます）。

## ★各機能へベタ書きしない

⚠ 依頼者の指示どおり、★既にあるものを使い回します。

```text
★使う  retroux/core/window_align.py の `focus(title)`（SetForegroundWindow）
★置く  ここ 1 か所（⚠ 聞き込み・店移動・リストックに別々に書かない）
```

## ⚠ 戻さない場合

```text
⚠ RetroUX 側に確認ダイアログが開いている
⚠ エラー詳細など、人が読むべきモーダルが残っている
```

★`blockers` に「いま人へ見せている窓」を返す関数を渡してください。

## ⚠ 失敗しても落としません

★FCEUX が見つからない / Windows が前面化を断る、はふつうに起きます
（⚠ `SetForegroundWindow` は前面のプロセスが別だと拒否されます）。
→ ★理由を `last_error` に残し、⚠ **例外にしません**。
"""
from __future__ import annotations

#: ★FCEUX の窓の題名（⚠ 前方一致では**なく**部分一致。★題名に ROM 名が付く）
GAME_TITLE = "FCEUX"

#: ⚠⚠ 戻してはいけない相手（★間違って別のアプリを前面にしない）
#:   ★`focus()` は題名の**部分一致**で探すので、⚠ ここを緩めると事故ります。
FORBIDDEN = ("RetroUX", "Lua Script")


def _default_focus(title: str) -> bool:
    """★既にある窓の道具を使う（⚠ ここで Win32 を直に呼ばない）。"""
    from retroux.core import window_align

    return bool(window_align.focus(title, match="contains"))


class GameFocus:
    """★省力操作の終わりに、ゲームへ操作を返す。

    `focus`    … ⚠ 検査で差し替える（★既定は `window_align.focus`）
    `blockers` … ★いま人へ見せている窓の名前を返す関数（⚠ 空なら戻してよい）
    """

    def __init__(self, focus=None, blockers=None, title: str = GAME_TITLE) -> None:
        self._focus = focus if focus is not None else _default_focus
        self._blockers = blockers if blockers is not None else (lambda: ())
        self.title = title
        self.last_error: str | None = None
        #: ★数えておく（⚠ 「呼ばれていない」と「戻せなかった」を分ける）
        self.tries = 0
        self.restored = 0
        self.skipped = 0

    # ------------------------------------------------------------------
    def blocked_by(self) -> list[str]:
        """⚠ いま人へ見せている窓（★あれば戻さない）。"""
        try:
            got = list(self._blockers() or ())
        except Exception as err:                             # noqa: BLE001
            self.last_error = "⚠ 開いている窓を数えられません: %s" % err
            return []                                         # ⚠ 数えられない＝止めない
        return [str(g) for g in got if g]

    def restore(self) -> bool:
        """★ゲームへ操作を返す。⚠ 戻さなかったときは `False`（★例外にしない）。"""
        self.tries += 1
        self.last_error = None
        blocked = self.blocked_by()
        if blocked:
            self.skipped += 1
            self.last_error = "★人へ見せている窓があるので戻しません: %s" % "、".join(blocked)
            return False
        # ⚠⚠ 別のアプリを前面にしない（★題名の部分一致なので、ここで守る）
        if any(bad in self.title for bad in FORBIDDEN):
            self.last_error = "⚠⚠ 戻してはいけない窓です: %s" % self.title
            return False
        try:
            ok = bool(self._focus(self.title))
        except Exception as err:                             # noqa: BLE001
            self.last_error = "⚠ フォーカスを戻せません: %s" % err
            return False
        if ok:
            self.restored += 1
        else:
            # ★ふつうに起きる（⚠ FCEUX が居ない / Windows が断った）
            self.last_error = "⚠ FCEUX が見つからないか、前面にできませんでした"
        return ok


__all__ = ["GameFocus", "GAME_TITLE", "FORBIDDEN"]
