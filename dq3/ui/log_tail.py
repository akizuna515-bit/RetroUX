"""Lua が書いたログを、増えたぶんだけ読む（RX3-0019 / 2026-08-29）。

依頼者 2026-08-29:

    戦闘ログ（フレーム表示しかいま画面に出ていない）。じゃなくて、
    全体的なログが出るように DQ2 のログ仕様を参考にして実装して。

★★ なぜ「読む」のか ★★

⚠ 画面は 0.5 秒に 1 回しか見に来ません。★ターボ中は 1 秒に数千フレーム進むので、
**画面が状態を見て組み立てると、ほとんど取りこぼします**（DQ2 の `battle_review`
にも同じ註釈がある: 「倍速だと戦闘まるごと 1 回が 0.2 秒に収まって見逃す」）。

★一方、Lua は**起きたことをその場でファイルへ書いています**。
⚠ そちらを読めば、1 つも取りこぼしません。

    work/dq3-probe/auto_v0.log    戦闘の進行（★ターンごと）
    work/dq3-probe/mantan_v0.log  まんたんの逐条
    work/dq3-probe/dev.log        起動・ターボ・画面からの頼み

## ⚠ 大きくなったファイルを毎回読み直さない

★読んだところまでの位置を覚え、**増えたぶんだけ**読みます
（⚠ `auto_v0.log` は実測で 75KB あり、毎回全部読むと重い）。

## ⚠ 途切れた行を捨てない

★Lua は書いている途中かもしれません。⚠ 最後の行が改行で終わっていなければ
**次まで待ちます**（半端な行を出すと、読む人が混乱する）。
"""

from __future__ import annotations

import pathlib

#: ★1 度に読む上限（⚠ ターボ中は一気に増えるので、青天井にしない）
MAX_BYTES = 256 * 1024


class LogTail:
    """1 つのログファイルの「増えたぶん」を返す。"""

    def __init__(self, path, *, from_end: bool = True) -> None:
        self.path = pathlib.Path(path)
        self._pos = 0
        self._buf = ""
        #: ⚠ 起動時に**過去ぶんを全部出さない**（★今回の分だけ見たい）
        self._from_end = from_end
        self._started = False

    def _open_position(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def read_new(self) -> list[str]:
        """★増えた行を返す（⚠ 無ければ空）。"""
        try:
            size = self.path.stat().st_size
        except OSError:
            return []                      # ⚠ まだ無い（★異常ではない）

        if not self._started:
            self._started = True
            self._pos = self._open_position() if self._from_end else 0

        # ⚠ 小さくなった＝作り直された（★先頭から読み直す）
        if size < self._pos:
            self._pos = 0
            self._buf = ""

        if size == self._pos:
            return []

        try:
            with self.path.open("rb") as handle:
                handle.seek(self._pos)
                raw = handle.read(MAX_BYTES)
        except OSError:
            return []
        self._pos += len(raw)

        text = self._buf + raw.decode("utf-8", errors="replace")
        # ★最後が改行で終わっていなければ、その行は次まで待つ
        if text.endswith("\n"):
            self._buf = ""
        else:
            cut = text.rfind("\n")
            if cut < 0:
                self._buf = text
                return []
            self._buf = text[cut + 1:]
            text = text[:cut + 1]
        return [ln for ln in text.splitlines() if ln.strip()]
