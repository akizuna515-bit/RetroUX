"""ユーザー向けの行動履歴 ― Action Summary Log（RX3-0109 / 2026-09-07）。

## ★何のためか（依頼者 2026-09-07）

> 「ユーザーの代わりに RetroUX が何を実行し、どう終わったか」を 1 行で残せるようにする。
> これは将来的にデバッグログではなく、**ユーザーへ常時見せる行動履歴**として利用する。

```text
15:21 [自動移動] 完了：道具屋へ到着 / 37歩
15:23 [リストック] 完了：やくそう×4 / 32G
15:26 [聞き込み] 完了：8人と会話 / 未完1人
15:31 [自動戦闘] 完了：5戦5勝 / 19ターン
```

## ⚠⚠ 2 種類のログを混ぜない

```text
A User Action Log   ★人へ見せる    [聞き込み] 完了：9人と会話 / 未完2人
B Technical Log     ★開発・解析用  npc_id=4 reason=path_deviation x=18 y=22
```

⚠ B を消す必要はありません。★**A に B を混ぜない**のが決まりです。
→ `ActionSummary.message` は人の言葉だけ。⚠ 数字・記号の生値は `detail` へ。

## ★終わりに 1 行だけ（⚠ 2 度出さない）

⚠⚠ 省力 Action は「終わり方」が何通りもあります（★完了 / 到達不能 / 中断 / 例外）。
⚠ 素直に書くと、**同じ 1 回で 2 行出る**か、**1 行も出ない**かのどちらかになります。
→ ★`begin()` が返す `ActionRun` が、`finish()` を **1 回しか通しません**。

## ⚠ 大きな仕組みにはしません

★依頼者の指示どおり、⚠ event sourcing も巨大な永続ログ基盤も作りません。

```text
★ここまで   省力 Action の終わりに、ユーザー向け 1 行を出せる
⚠ ここから先 履歴の検索・集計・保存形式 → ★必要になってから
```

## ⚠ `retroux/` には置きません

★`RX3-0011`: `retroux/` は読むだけ（import 可・変更不可）。
⚠ 「共通化は結果として行う。先に共通化しない」。
→ ★DQ3 の省力 Action で使い倒してから、⚠ 要るなら上げます。
"""
from __future__ import annotations

import dataclasses
import re
import time

#: ★終了状態（⚠ **内部の語**。人には出しません）
SUCCESS = "SUCCESS"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
PARTIAL = "PARTIAL"
STATUSES = (SUCCESS, PARTIAL, FAILED, CANCELLED)

#: ★人向けの終わり方（⚠ `PARTIAL` も「完了」。★未完の件数は本文で言う）
STATUS_LABELS = {
    SUCCESS: "完了",
    PARTIAL: "完了",
    FAILED: "中断",
    CANCELLED: "停止",
}

#: ★Action の名前（⚠ 増えたらここに 1 行。★UI 側に書かない）
ACTION_LABELS = {
    "hearing": "聞き込み",
    "move": "自動移動",
    "battle": "自動戦闘",
    "mantan": "まんたん",
    "restock": "リストック",
    "spell": "呪文の結果",               # ★RX3-0271（⚠ 観測だけ / 戦闘ごとに 1 行）
}

#: ⚠⚠ **人向けの本文に混ぜてはいけない形**（★Technical Log 側の書き方）
#:   ★`npc_id=4` / `0x1F` / `{'a': 1}` / `Traceback` / `reason=path_deviation`
_TECHNICAL = (
    re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*="),      # ★key=value
    re.compile(r"0[xX][0-9A-Fa-f]+"),               # ★hex
    re.compile(r"[{}]"),                            # ★dict / repr
    re.compile(r"Traceback|File \"|line \d+, in "),  # ★traceback
    re.compile(r"<[A-Za-z_][A-Za-z0-9_.]* object at 0x"),
)

#: ★履歴に残す行数（⚠ 青天井にしない）
MAX_ROWS = 500


#: ★理由が分からないときの言い方（⚠ **内部の語をそのまま出さない**）
UNKNOWN_REASON = "うまくいきませんでした"


def is_user_safe(text: str) -> bool:
    """★その文がユーザー向けとして出せるか（⚠ 生の値が混ざっていないか）。"""
    return not any(pat.search(text or "") for pat in _TECHNICAL)


def humanize_reason(table: dict, reason, fallback: str = UNKNOWN_REASON) -> str:
    """★内部の理由 → 人の言葉。⚠ 表に無いものは**推測せず** `fallback`。

    ⚠⚠ `reason` には `cursor_stuck:p1` のように**値がくっついた**ものが来ます。
    ★`:` の前だけで引きます（⚠ 後ろは Technical 側の材料）。
    """
    key = str(reason or "").split(":", 1)[0].strip()
    return table.get(key, fallback)


@dataclasses.dataclass(frozen=True)
class ActionSummary:
    """★1 回ぶんの省力 Action の結末。⚠ 人へ出すのは `action` / `status` / `message` だけ。"""

    action: str
    status: str
    message: str
    at: float = 0.0
    #: ⚠ Technical Log 側の材料（★UI には渡さない）
    detail: dict = dataclasses.field(default_factory=dict)

    @property
    def action_label(self) -> str:
        return ACTION_LABELS.get(self.action, self.action)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def line(self) -> str:
        """★人へ見せる 1 行（⚠ 時刻は付けない。★付けるのは表示側）。"""
        head = "[%s] %s" % (self.action_label, self.status_label)
        return ("%s：%s" % (head, self.message)) if self.message else head

    def stamped(self, fmt: str = "%H:%M") -> str:
        """★時刻つきの 1 行（★行動履歴の見た目）。"""
        return "%s %s" % (time.strftime(fmt, time.localtime(self.at or time.time())),
                          self.line())


class ActionRun:
    """★1 回ぶんの省力 Action。⚠ `finish()` は **1 回しか通しません**。"""

    def __init__(self, log: "ActionLog", action: str) -> None:
        self.log = log
        self.action = action
        self.done = False
        self.started_at = log.clock()

    def finish(self, status: str, message: str, **detail) -> ActionSummary | None:
        """★終わりの 1 行を出す。⚠ 2 回目以降は `None`（★二重に出さない）。"""
        if self.done:
            return None
        self.done = True
        detail.setdefault("elapsed_s", round(self.log.clock() - self.started_at, 2))
        return self.log.record(self.action, status, message, **detail)

    def claim(self) -> bool:
        """★終わりを **1 回だけ** 名乗る（⚠ Event へ移した Action 用 / RX3-0154）。

        ⚠⚠ `finish()` と**同じ歯止め**です。★Event Writer を通す Action は
        ここで押さえてから `emit()` します（⚠ 二重に出さない）。
        """
        if self.done:
            return False
        self.done = True
        return True

    def elapsed(self) -> float:
        """★かかった秒（⚠ `claim()` した側が `data` へ入れる）。"""
        return round(self.log.clock() - self.started_at, 2)

    # ★よく使う終わり方（⚠ 呼ぶ側が `SUCCESS` などの語を書かなくて済むように）
    def completed(self, message: str, **detail):
        return self.finish(SUCCESS, message, **detail)

    def partial(self, message: str, **detail):
        return self.finish(PARTIAL, message, **detail)

    def failed(self, message: str, **detail):
        return self.finish(FAILED, message, **detail)

    def cancelled(self, message: str = "ユーザー操作", **detail):
        return self.finish(CANCELLED, message, **detail)


class ActionLog:
    """★ユーザー向けの行動履歴。⚠ Qt を知りません（★UI から引きに来る）。"""

    def __init__(self, *, clock=time.time, limit: int = MAX_ROWS) -> None:
        self.clock = clock
        self.limit = limit
        self.rows: list[ActionSummary] = []
        self._subscribers: list = []
        #: ★取りこぼしを見つけるための数（⚠ 直した本文の件数）
        self.scrubbed = 0
        #: ★★ これまでに記録した**通し番号**（⚠ 上限で捨てても減りません / RX3-0429）。
        #:
        #:   ⚠⚠ `len(self.rows)` を番号に使ってはいけません。★上限で頭打ちになり、
        #:     500 件を超えた瞬間から `since()` が**何も返さなくなります**（★実際に踏んだ）。
        self.total = 0

    # ------------------------------------------------------------------
    def begin(self, action: str) -> ActionRun:
        return ActionRun(self, action)

    def record(self, action: str, status: str, message: str, **detail) -> ActionSummary:
        """★1 行を残す。⚠ 人向けに出せない本文は**ここで止めます**。"""
        text = (message or "").strip()
        if not is_user_safe(text):
            # ⚠⚠ 生の値を人へ出さない。★中身は Technical 側へ落として、本文は伏せる
            detail = dict(detail, raw_message=text)
            text = "詳しくはログを見てください"
            self.scrubbed += 1
        got = ActionSummary(action=action, status=status, message=text,
                            at=self.clock(), detail=dict(detail))
        self.rows.append(got)
        self.total += 1                  # ★通し番号は捨てても減らさない（RX3-0429）
        del self.rows[:-self.limit]
        for fn in list(self._subscribers):
            try:
                fn(got)
            except Exception:                                # noqa: BLE001
                pass                                          # ⚠ 見る側の失敗で履歴を壊さない
        return got

    # ------------------------------------------------------------------
    def subscribe(self, fn) -> None:
        self._subscribers.append(fn)

    def since(self, seen: int) -> tuple[list[ActionSummary], int]:
        """★`seen` 件目から後の行と、⚠ 次に渡す番号。

        ## ⚠⚠ ここは 2026-09-24 まで壊れていました（RX3-0429 / P-3）

          ★昔は番号に `len(self.rows)` を使っていました。⚠ `rows` は上限
          （`MAX_ROWS` = 500）で頭打ちになるので、★500 件を超えると
          `seen` も 500 のまま動かず、⚠⚠ **`rows[500:]` が永久に空**でした。

          ```text
          500 件目   ★1 行届く   seen=500
          501 件目   ⚠⚠ 0 行     seen=500   ← ★ここから先はもう流れない
          620 件目   ⚠⚠ 0 行     seen=500
          ```

          ⚠ 本体（`rows`）も `subscribe` も無事で、★止まるのは**この道だけ**でした。
          → ★「何件**残すか**」（`limit`）と「どこまで**渡したか**」（`total`）を分けます。

        @param seen ★前回この関数が返した番号（⚠ 記録した通し番号。★残っている件数ではない）
        @return `(新しい行, 次に渡す番号)`
        """
        total = self.total
        seen = max(0, min(int(seen), total))
        # ★上限で捨てたぶん（⚠ 捨てた行はもう渡せません / 追いつけなければ残っている分から）
        dropped = total - len(self.rows)
        start = max(0, seen - dropped)
        return list(self.rows[start:]), total

    def lines(self, fmt: str = "%H:%M") -> list[str]:
        return [r.stamped(fmt) for r in self.rows]


#: ★アプリで 1 本だけ持つ（⚠ 画面ごとに作らない）
_SHARED: ActionLog | None = None


def shared() -> ActionLog:
    global _SHARED
    if _SHARED is None:
        _SHARED = ActionLog()
    return _SHARED


def reset_shared() -> None:
    """⚠ 検査用（★本番では呼びません）。"""
    global _SHARED
    _SHARED = None


__all__ = ["ActionSummary", "ActionRun", "ActionLog", "shared", "reset_shared",
           "is_user_safe", "SUCCESS", "PARTIAL", "FAILED", "CANCELLED",
           "STATUSES", "STATUS_LABELS", "ACTION_LABELS"]
