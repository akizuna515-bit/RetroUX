"""止まったことに気づく（RX3-0048 A-4 / ASSERT: no_hang）。

## ⚠⚠ 長時間の無人実行で、いちばん困るのは「止まったのに気づかない」

```text
heartbeat  ★run.jsonl の更新   ★state.json の更新   ★座標   ★frame
```

⚠ **どれか 1 つでも動いていれば生きています。**
★全部が `limit_s` のあいだ変わらなければ `hang_suspected`。

## ⚠⚠ 壁にぶつかっただけは hang ではない（指示書 A-4）

★壁にぶつかると座標は変わりませんが、⚠ `run.jsonl` に `ok:false` の行が**足されます**。
→ ★**ファイルが大きくなる**ので、ここでは「生きている」と見ます。
⚠ 座標だけを見ると、壁で hang と誤って止めます。

⚠⚠ 2026-09-07（RX3-0075）: もとは**更新時刻だけ**を見ていました。
★Windows は追記しても `mtime` をすぐには進めないので、⚠ 間を空けずに書くと
「動いていない」に見えます（★実測 79.4%）。→ ★`st_size` を足しました（`_file_sign`）。

## ★時計は差し替えられる

⚠ 実時間で待つ検査は遅くて不安定なので、★`clock=` を渡せます（指示書 §23）。
"""

from __future__ import annotations

import pathlib
import time

#: ⚠ これだけ何も変わらなければ止まったとみなす（★1 歩 ≒ 0.25 秒。壁でも行は増える）
DEFAULT_LIMIT_S = 30.0

#: ★止まった理由の語（⚠ 指示書 A-4 のまま）
HANG = "hang_suspected"


def _file_sign(path: pathlib.Path):
    """★そのファイルの脈（`(更新時刻, 大きさ)`）。⚠ 無ければ `None`。

    ## ⚠⚠ 2026-09-07（RX3-0075）: **更新時刻だけでは足りません**

      ★Windows は、追記しても `st_mtime_ns` を**すぐには進めません**。
      ⚠ 実測（200 回 × 5 回追記）:

      ```text
      ★書き込みの間隔 0.00 秒 → ⚠ mtime が動かなかった 79.4%（381 / 480）
      ★書き込みの間隔 0.05 秒 → ★0.0%（0 / 480）
      ★書き込みの間隔 0.25 秒 → ★0.0%
      ```

      ⚠ つまり**間を空けずに続けて書くと**、更新時刻は動きません。
      ★実運用の間隔（0.25 秒に 1 歩）なら問題は出ませんが、
      ⚠ **検査は間を空けずに書く**ので、そこで踏みました。

      → ★`st_size` を足します。⚠ **行が足された**ことの直接の証拠で、
        同じ `stat()` から取れるので**ただ**です。
      ⚠ 更新時刻も残します（★同じ大きさで書き直された場合はこちらが拾う）。
    """
    try:
        got = path.stat()
    except OSError:
        return None
    return (got.st_mtime_ns, got.st_size)


class Watchdog:
    """★heartbeat を集めて、止まっていないかを見る。

    ```python
    dog = Watchdog([run.log_path, run.steps_path], limit_s=30)
    ...
    dog.beat()                 # ★見るたびに呼ぶ
    if dog.stalled(): ...      # ⚠ limit_s 以上なにも変わっていない
    ```

    @param files   ★更新時刻を見るファイル（⚠ 無いものは「まだ」として扱う）
    @param extra   ★ほかの脈（関数。★値が変わったら生きている）。例: 座標を返す関数
    @param clock   ⚠ 検査で差し替える時計
    """

    def __init__(self, files, *, limit_s: float = DEFAULT_LIMIT_S,
                 extra=None, clock=None) -> None:
        self.files = [pathlib.Path(p) for p in files]
        self.limit_s = float(limit_s)
        self.extra = list(extra or [])
        self.clock = clock or time.monotonic
        self.last_sign = None
        self.last_change = self.clock()
        self.beats = 0
        self.changes = 0

    def sign(self) -> tuple:
        """★いまの脈（⚠ これが変われば生きている）。"""
        parts = [_file_sign(p) for p in self.files]
        for fn in self.extra:
            try:
                parts.append(fn())
            except Exception as err:                        # noqa: BLE001
                parts.append("⚠ %s" % err)                 # ⚠ 読めないのも 1 つの状態
        return tuple(parts)

    def beat(self) -> bool:
        """★見に行く。⚠ 変わっていれば True。"""
        self.beats += 1
        now = self.sign()
        if now != self.last_sign:
            self.last_sign = now
            self.last_change = self.clock()
            self.changes += 1
            return True
        return False

    def quiet_for(self) -> float:
        """★最後に何か変わってから何秒か。"""
        return self.clock() - self.last_change

    def stalled(self) -> bool:
        """⚠⚠ `limit_s` 以上なにも変わっていないか。"""
        return self.quiet_for() >= self.limit_s

    def report(self) -> dict:
        return {"limit_s": self.limit_s, "quiet_for_s": round(self.quiet_for(), 1),
                "beats": self.beats, "changes": self.changes,
                "stalled": self.stalled()}
