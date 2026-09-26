"""頼みが**どこまで**通ったかを見る（RX3-0130 / 2026-09-08）。

```text
Python が書く         work/dq3-command.json  {"seq": 42, "action": "ai_reload"}
   ↓ 30 フレームに 1 回
Lua が読む            state.json  command.received = 42     ★受け取った
   ↓ 担当の機能が取り出す
Lua が処理する        state.json  command.applied  = 42     ★やった
   ↓ 次の書き出し
Python が見る         ★ここで初めて分かる（⚠ state.json は 0.5 秒に 1 回）
```

## ⚠⚠ なぜ要るのか

★`ai_reload` の直後に `load_state` を送ったら、Lua が読む前に**上書きされて消え**、
⚠ 前の作戦のまま戦いました（2026-09-08 / RX3-0126）。
★頼みの置き場は 1 つしかないので、**次を書く前に前の頼みが通ったことを確かめます**。

## ★段階（どこで止まったか言えること）

```text
unsent     ⚠ まだ Lua が読んでいない（★待つか、同じ番号で書き直す）
lost       ⚠⚠ 読まれる前に次の頼みで上書きされた（★その番号はもう通らない）
received   ★読んだ。⚠ まだ処理していない
applied    ★処理した（担当の機能が取り出した）
frozen     ⚠⚠ state.json が進んでいない（★FCEUX が落ちた / 長く止まっている）
           ⚠ 戦闘の後に地図の材料を書くと**十数秒**止まります（★死んだのではない）
```

## ★再送の決まり（⚠ めくら撃ちにしない）

```text
unsent     ★**同じ seq のまま**書き直す（⚠ Lua は seq <= 読んだ番号 を捨てるので二重実行しない）
received   ⚠ 再送しない（★処理待ち。待つだけ）
frozen     ⚠⚠ 再送しない（★FCEUX が死んでいる。理由をつけて失敗にする）
上限       ★3 回まで。⚠ それでも駄目なら失敗（★永遠に待たない）
```
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import time

#: ★同じ頼みを書き直す上限（⚠ 新しい seq にはしない）
MAX_RESEND = 3
#: ★1 回の待ちの上限（秒）
#:   ⚠ 短くしないこと。★戦闘のあとや 2 回目のセーブ読み込みでは、
#:     FCEUX が**数十秒**フレームを進めないことがあります（2026-09-08 実測 / 地図の材料と CHR の書き出し）。
DEFAULT_TIMEOUT = 30.0
#: ⚠⚠ これだけフレームが進まなければ「止まっている」とみなす。
#:   ★実測: 2 回目の `load_state` で **36 秒**止まってから動き出した例がある。
#:   ⚠ 「止まっている」と「死んだ」は別。★死んだかどうかは `alive`（プロセス）で見ます。
FROZEN_AFTER = 60.0

UNSENT, RECEIVED, APPLIED, FROZEN = "unsent", "received", "applied", "frozen"
#: ⚠⚠ 追い越された（★読まれる前に次の頼みで上書きされた ＝ この seq は永久に実行されない）
LOST = "lost"

#: ★順番が大事な頼み（⚠ 前のが applied になるまで次を送らない）
ORDERED = ("ai_reload", "load_state", "auto", "walk", "walk_stop", "navigate", "nav_stop",
           "restock", "restock_stop", "mantan", "use_item")


@dataclasses.dataclass(frozen=True)
class AckResult:
    seq: int
    action: str
    stage: str
    seconds: float
    resends: int
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.stage == APPLIED

    def line(self) -> str:
        """★Technical Log の 1 行（⚠ どこで止まったかが読めること）。"""
        return "seq=%d action=%s %s（%.1f 秒 / 再送 %d 回）%s" % (
            self.seq, self.action, self.stage, self.seconds, self.resends,
            (" " + self.detail) if self.detail else "")


class AckWaiter:
    """★`state.json` を見て、頼みがどこまで進んだかを言う。

    `state_path` は**呼ぶたび**に引ける形（関数）でも渡せます
    （⚠ 隔離先の env は import の後に立つため / RX3-0128）。
    """

    def __init__(self, state_path, *, log=None, sleep: float = 0.2) -> None:
        self._state_path = state_path
        self.log = log or (lambda _line: None)
        self.sleep = sleep

    # --- ★いまの状態 ----------------------------------------------------

    def path(self) -> pathlib.Path:
        got = self._state_path() if callable(self._state_path) else self._state_path
        return pathlib.Path(got)

    def state(self) -> dict:
        try:
            got = json.loads(self.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}

    @staticmethod
    def _ack(state: dict) -> dict:
        got = state.get("command")
        if isinstance(got, dict):
            return got
        # ⚠ 古い Lua（★`command_seq` しか返さない）とも話せるようにする
        seq = int(state.get("command_seq") or 0)
        return {"received": seq, "applied": 0, "action": None}

    def stage_of(self, seq: int, state: dict | None = None, action: str | None = None) -> str:
        """★その seq がどこまで進んだか。

        ⚠⚠ **番号が進んでいる ＝ その頼みが通った、ではありません。**
          ★頼みの置き場は 1 つなので、読まれる前に次を書くと前のは**消えます**。
          そのとき Lua の番号は次の頼みで**追い越して**いるので、
          ⚠ `applied >= seq` だけで見ると「通った」と誤読します（★2026-09-08 に実際に踏んだ形）。
          → ★`== seq` のときだけ「通った」と言い、追い越されていたら `lost` と言います。
        """
        ack = self._ack(state if state is not None else self.state())
        applied = int(ack.get("applied") or 0)
        received = int(ack.get("received") or 0)
        got_action = ack.get("action")
        if applied == seq and (action is None or got_action in (None, action)):
            return APPLIED
        if received == seq:
            return RECEIVED
        if received > seq:
            return LOST
        return UNSENT

    # --- ★待つ ----------------------------------------------------------

    def wait(self, seq: int, action: str, *, want: str = APPLIED,
             timeout: float = DEFAULT_TIMEOUT, resend=None,
             alive=None) -> AckResult:
        """★`want` の段階まで待つ。⚠ 届いていなければ**同じ seq で**書き直す。

        `resend` … ★もう一度書く関数（⚠ 同じ seq / 同じ action にすること）
        `alive`  … ★FCEUX が生きているかを返す関数（⚠ 死んでいたら即やめる）
        """
        started = time.time()
        resends = 0
        last_frame, last_move = None, started
        rank = {UNSENT: 0, LOST: 0, RECEIVED: 1, APPLIED: 2}
        want_rank = rank[want]
        while True:
            state = self.state()
            frame = state.get("frame")
            now = time.time()
            if frame != last_frame:
                last_frame, last_move = frame, now
            stage = self.stage_of(seq, state, action)
            if stage == LOST:
                # ⚠⚠ 追い越された。★同じ番号で書き直しても Lua は捨てるので、待たずに返す
                return AckResult(seq, action, LOST, now - started, resends,
                                 "⚠⚠ 読まれる前に次の頼みで上書きされました")
            if rank[stage] >= want_rank:
                return AckResult(seq, action, stage, now - started, resends)
            if alive is not None and not alive():
                return AckResult(seq, action, FROZEN, now - started, resends,
                                 "⚠⚠ FCEUX が居なくなりました")
            if now - last_move > FROZEN_AFTER:
                return AckResult(seq, action, FROZEN, now - started, resends,
                                 "⚠⚠ state.json が %.1f 秒進んでいません（frame=%s）"
                                 % (now - last_move, frame))
            if now - started > timeout:
                # ⚠ 受け取られてすらいないときだけ、★同じ seq で書き直す
                if stage == UNSENT and resend is not None and resends < MAX_RESEND:
                    resends += 1
                    resend()
                    self.log("seq=%d action=%s ⚠ 届いていないので同じ番号で書き直す（%d 回目）"
                             % (seq, action, resends))
                    started = time.time()
                    continue
                return AckResult(seq, action, stage, now - started, resends,
                                 "⚠ %s まで %.1f 秒待ちました" % (want, timeout))
            time.sleep(self.sleep)


def send_and_wait(writer, waiter: AckWaiter, action: str, *, want: str = APPLIED,
                  timeout: float = DEFAULT_TIMEOUT, alive=None, **params) -> AckResult:
    """★書いて、通るまで待つ（⚠ 順番が大事な頼みはこれで送る）。

    ★再送の決まり（⚠ 2 通りあるので混ぜない）:

    ```text
    unsent  ★同じ番号で書き直す（⚠ Lua は seq <= 読んだ番号 を捨てる ＝ 二重実行しない）
    lost    ⚠⚠ 追い越された ＝ その番号はもう通らない → ★**新しい番号**で出し直す
            （★実行されていないことが分かっているので、二重実行にならない）
    ```
    """
    for attempt in range(MAX_RESEND + 1):
        seq = writer.send(action, **params)
        waiter.log("seq=%d action=%s requested" % (seq, action))
        got = waiter.wait(seq, action, want=want, timeout=timeout,
                          resend=lambda: writer.resend(), alive=alive)
        waiter.log(got.line())
        if got.stage != LOST or attempt >= MAX_RESEND:
            return got
        waiter.log("seq=%d action=%s ⚠ 追い越されたので新しい番号で出し直す（%d 回目）"
                   % (seq, action, attempt + 1))
    return got


__all__ = ["AckWaiter", "AckResult", "send_and_wait", "UNSENT", "RECEIVED", "APPLIED", "FROZEN",
           "LOST",
           "ORDERED", "MAX_RESEND", "DEFAULT_TIMEOUT", "FROZEN_AFTER"]
