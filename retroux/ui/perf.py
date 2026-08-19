"""画面の更新にかかった時間を測る（2026-07-31 の指示書 §10.3）。

★★ **推測で最適化しない。** ★★
  「たぶんログが重い」で直すと、直っていないのに直った気になる。
  ⚠ このプロジェクトでは、読んで立てた仮説が**繰り返し外れて**いる
    （R-1 のコンソール、スクロール追従、P-3 の保存）。
    どれも実測した瞬間に決着した。ここも同じ手で行く。

## 何を測るか

`refresh()` の中を区間に切り、区間ごとの **回数・合計・最大** を持つ。
平均だけだと「たまに 300ms 掛かる」が消える。⚠ **最大を必ず残す。**

## いつ出すか

⚠⚠ **毎回出すと、出力そのものが重くなる**（それ自体が原因になる）。

  | しきい値 | 扱い |
  | --- | --- |
  | 16ms 超 | 参考（1フレーム）。**出さない**、集計だけ |
  | 50ms 超 | 警告候補。集計だけ |
  | 100ms 超 | **明確な引っ掛かり**。ここだけログへ1行 |

まとめは `summary()` を呼んだときだけ作る（終了時・診断情報）。

## 切り方

    with probe.section("state読込"):
        ...

⚠ 例外が出ても計測は閉じる（`finally`）。閉じないと、
  1回落ちただけで以降の数字が全部でたらめになる。

★既定は**無効**。`RETROUX_PERF=1` か設定で入れる。
  常時有効にすると、計測のために遅くする、という本末転倒になる。
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import time

#: 「明確な引っ掛かり」。この値を超えた区間だけログへ出す（ミリ秒）。
STALL_MS = 100.0
#: 「警告候補」。集計には残すが、その場では出さない。
WARN_MS = 50.0
#: 1フレーム（60fps）。これを超えたら描画が1回飛んでいる。
FRAME_MS = 16.0


@dataclasses.dataclass
class Stat:
    """1区間ぶんの集計。"""

    name: str
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    over_frame: int = 0
    over_warn: int = 0
    over_stall: int = 0

    @property
    def average_ms(self) -> float:
        return (self.total_ms / self.count) if self.count else 0.0

    def add(self, elapsed_ms: float) -> None:
        self.count += 1
        self.total_ms += elapsed_ms
        self.max_ms = max(self.max_ms, elapsed_ms)
        if elapsed_ms > FRAME_MS:
            self.over_frame += 1
        if elapsed_ms > WARN_MS:
            self.over_warn += 1
        if elapsed_ms > STALL_MS:
            self.over_stall += 1


class Probe:
    """区間ごとの所要時間を集める。

    ★無効のときは**何もしない**（`section` が空の context manager を返す）。
      `if probe:` を呼ぶ側に書かせない。書かせると必ず書き忘れる。
    """

    def __init__(self, enabled: bool = False, logger=None,
                 stall_ms: float = STALL_MS) -> None:
        self.enabled = bool(enabled)
        self.logger = logger
        self.stall_ms = stall_ms
        self.stats: dict[str, Stat] = {}

    @classmethod
    def from_env(cls, logger=None) -> "Probe":
        """環境変数 `RETROUX_PERF` で入れる。

        ⚠ 既定は無効。**計測のために遅くしない。**
        """
        flag = (os.environ.get("RETROUX_PERF") or "").strip().lower()
        return cls(enabled=flag in ("1", "true", "on", "yes"), logger=logger)

    @contextlib.contextmanager
    def section(self, name: str):
        if not self.enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            # ⚠ 例外が出ても必ず記録する。ここを try の外に書くと、
            #   1回落ちただけで以降の数字が全部ずれる。
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.record(name, elapsed_ms)

    def record(self, name: str, elapsed_ms: float) -> None:
        stat = self.stats.get(name)
        if stat is None:
            stat = self.stats[name] = Stat(name)
        stat.add(elapsed_ms)
        # ★出すのは**明確な引っ掛かり**だけ（毎回出すと出力が原因になる）
        if elapsed_ms > self.stall_ms and self.logger is not None:
            self.logger.warning("画面更新が引っ掛かりました: %s %.1fms",
                                name, elapsed_ms)

    def summary_lines(self) -> list[str]:
        """人が読む形。★**最大の大きい順**（平均では山が見えない）。"""
        if not self.stats:
            return ["（計測していません）"]
        lines = [f"{'区間':<20}{'回数':>6}{'平均ms':>9}{'最大ms':>9}"
                 f"{'>16':>5}{'>50':>5}{'>100':>6}"]
        for stat in sorted(self.stats.values(),
                           key=lambda s: s.max_ms, reverse=True):
            lines.append(
                f"{stat.name:<20}{stat.count:>6}{stat.average_ms:>9.1f}"
                f"{stat.max_ms:>9.1f}{stat.over_frame:>5}"
                f"{stat.over_warn:>5}{stat.over_stall:>6}")
        return lines

    def reset(self) -> None:
        self.stats.clear()
