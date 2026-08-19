"""直前戦闘レビュー（2026-08-12 / 依頼者の指示 §7〜§16）。

## ★★ なぜ要るか

    RetroUX ではAUTO戦闘時の進行が速いため、
    «戦闘中に全情報を読むことより、戦闘終了後に
      「今の戦闘でAIがどう判断したか」を確認できること» を重視する。

★戦闘は約35倍で終わります。**読む前に消えます。**
  だから「いま」ではなく「**さっき何を考えていたか**」を残します。

## ★ 何を残すか（指示 §13）

    «UI文字列を履歴として保存するのではなく、可能な限り論理データを
      保存し、表示時にフォーマットする»

だから ここには**数字と英語の値**しか入れません。「ロ:攻3.0」を作るのは
`battle_format.py` の仕事です。⚠ 文字列で貯めると、あとから
短縮の仕方を変えられなくなります。

## ⚠⚠ 1ターン = 1件（指示 §14・§15）

画面は 0.2 秒ごとに見に来ますが、**同じターンを何度も足しません**。
★戦況・戦術・役割はターン単位で固定される、という Layered AI の考え方に
合わせます。

⚠ ただし**同じターンの中で内容が増えることはあります**（判断が先に来て、
  戦況があとから届くなど）。★そのときは**上書き**します（足しません）。

## ⚠ 取りこぼしについて（正直に書きます）

★倍速だと、戦闘まるごと1回が 0.2 秒に収まって**画面が見逃します**。
  そのときはその戦闘の履歴が丸ごと残りません。
  ⚠ `battle_seq`（Lua が数えた通し番号）が飛ぶので、
    「見逃した」ことは分かります。
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class BattleReviewTurn:
    """1ターンぶんの判断（★論理データのまま持つ）。"""

    turn_no: int
    balance: str | None = None
    length: str | None = None
    turns_to_win: float | None = None
    turns_to_lose: float | None = None
    plan: str | None = None
    plan_score: float | None = None
    plan_margin: float | None = None
    plan_reasons: str | None = None
    roles: str | None = None
    tags: str | None = None
    actions: list = dataclasses.field(default_factory=list)
    """★そのターンに誰が何をしたか。要素は `{"name", "action", "reason"}`。

    ⚠ 優先順は 実行された行動 > AI が選んだ行動 > 役割だけ（指示 §16）。
      ★いま取れるのは `ai_decisions`（AI が選んだ行動）です。
      **無いものを推測で埋めません。**
    """

    def signature(self) -> tuple:
        """★中身が変わったかを見るための鍵（⚠ 同じなら書き直さない）。"""
        return (self.balance, self.length, self.turns_to_win,
                self.turns_to_lose, self.plan, self.plan_score,
                self.plan_margin, self.roles, self.tags,
                tuple((a.get("name"), a.get("action")) for a in self.actions))


@dataclasses.dataclass
class BattleReview:
    """1戦闘ぶんの履歴。"""

    battle_seq: int | None = None
    turns: list = dataclasses.field(default_factory=list)
    result_label: str | None = None
    """★勝敗。⚠ **分からなければ None のまま**（推測で「勝利」と書かない）。

    ⚠ `state.json` には勝敗が来ません。DB の `BattleLog.result` から
      あとで埋まることがあります（`ViewModel` が入れます）。
    """

    @property
    def total_turns(self) -> int:
        return len(self.turns)

    def turn(self, turn_no: int):
        for t in self.turns:
            if t.turn_no == turn_no:
                return t
        return None


def _decision_turn(game) -> int | None:
    """いま何ターン目か。★`ai_decisions` の `turn` から取ります。

    ⚠⚠ **推測しません。** 取れなければ None を返し、呼び出し側が
      「まだ分からない」として扱います（★0 で埋めると1ターン目に見えます）。
    """
    turns = [d.get("turn") for d in (getattr(game, "ai_decisions", None) or [])
             if isinstance(d, dict) and d.get("turn") is not None]
    if not turns:
        return None
    try:
        return max(int(t) for t in turns)
    except (TypeError, ValueError):
        return None


def _actions_of(game, turn_no: int) -> list:
    """そのターンの行動（★AI が選んだもの / 指示 §16）。

    ⚠ 別のターンの判断を混ぜません（`turn` が一致するものだけ）。
    ⚠ 行動が決まっていない人は**入れません**（「たたかう」と混ぜない）。
    """
    out = []
    for d in (getattr(game, "ai_decisions", None) or []):
        if not isinstance(d, dict):
            continue
        if d.get("turn") is not None and int(d["turn"]) != turn_no:
            continue
        if not d.get("action"):
            continue
        out.append({"name": d.get("name"), "action": d.get("action"),
                    "reason": d.get("reason")})
    return out


class BattleReviewRecorder:
    """戦況のスナップショットをターン単位で貯める（指示 §14）。

    ★★ **「何も変わっていないときは何もしない」** ★★
      `observe()` は変化があったときだけ True を返します。
      ⚠ 画面はそれを見て、**変わったときだけ**描き直します
        （以前 0.2 秒ごとに全部組み直して、もっさりの原因になりました）。
    """

    def __init__(self) -> None:
        self.current: BattleReview | None = None
        self.previous: BattleReview | None = None

    # --- 参照用 -------------------------------------------------------
    def active(self) -> BattleReview | None:
        """いま画面に出すべき履歴。★戦闘中は今回、終わったら直前。"""
        return self.current if self.current is not None else self.previous

    def revision(self) -> tuple:
        """★中身が変わったかの鍵（ツールチップの作り直しに使う）。"""
        review = self.active()
        if review is None:
            return ()
        return (id(review), review.battle_seq, review.total_turns,
                review.result_label,
                review.turns[-1].signature() if review.turns else ())

    # --- 取り込み -----------------------------------------------------
    def observe(self, game) -> bool:
        """`GameState` を1回ぶん見る。★変化があれば True。"""
        if game is None:
            return False
        in_battle = bool(getattr(game, "in_battle", False))
        seq = getattr(game, "battle_seq", None)

        if not in_battle:
            return self._end_battle()

        changed = False
        # ★★ 新しい戦闘（指示 §11: current を作り直し、previous は残す）★★
        #   ⚠ `battle_seq` は Lua が数えた通し番号です。倍速で戦闘を
        #     見逃しても、番号が変わったことで「別の戦闘」だと分かります。
        if self.current is None or self.current.battle_seq != seq:
            if self.current is not None and self.current.turns:
                self.previous = self.current
            self.current = BattleReview(battle_seq=seq)
            changed = True

        turn_no = _decision_turn(game)
        if turn_no is None:
            # ⚠ ターンが読めないうちは足しません（★0 を1ターン目にしない）。
            return changed

        snap = BattleReviewTurn(
            turn_no=turn_no,
            balance=getattr(game, "battle_balance", None),
            length=getattr(game, "battle_length", None),
            turns_to_win=getattr(game, "battle_turns_to_win", None),
            turns_to_lose=getattr(game, "battle_turns_to_lose", None),
            plan=getattr(game, "battle_plan", None),
            plan_score=getattr(game, "battle_plan_score", None),
            plan_margin=getattr(game, "battle_plan_margin", None),
            plan_reasons=getattr(game, "battle_plan_reasons", None),
            roles=getattr(game, "battle_roles", None),
            tags=getattr(game, "battle_tags", None),
            actions=_actions_of(game, turn_no),
        )

        existing = self.current.turn(turn_no)
        if existing is None:
            # ⚠ ターン番号は増える一方とは限らない（読み取りのぶれ）。
            #   ★並べ替えて、あとで読むときに順番が狂わないようにします。
            self.current.turns.append(snap)
            self.current.turns.sort(key=lambda t: t.turn_no)
            return True
        if existing.signature() != snap.signature():
            # ★同じターンの中身が増えた → **上書き**（足さない / 指示 §15）
            self.current.turns[self.current.turns.index(existing)] = snap
            return True
        return changed

    def _end_battle(self) -> bool:
        """戦闘が終わった。★current を previous へ移し、画面には残す。"""
        if self.current is None:
            return False
        if self.current.turns:
            self.previous = self.current
        self.current = None
        return True

    def set_result(self, label) -> bool:
        """直前戦闘の勝敗を、分かったときだけ入れる（★推測しない）。"""
        review = self.previous
        if review is None or not label or review.result_label == label:
            return False
        review.result_label = label
        return True


#: 勝敗の日本語。
#:
#: ⚠⚠ **2026-08-12 の訂正。** ここには `{"win", "retreat"}` と書いて
#:   いましたが、★`retreat` という値は**存在しません**。
#:   DB スキーマのコメント（`database.py:43`「win / retreat」）を
#:   そのまま信じたのが誤りで、⚠ **実データを見ていませんでした**。
#:
#: ★実際に入っている値（`work/retroux.sqlite3` の 522 件）:
#:
#:     win 500 / flee 13 / lose 6 / enemy_fled 3
#:
#: ★決めているのは `bridge.lua:3189`。
#:
#:     saw_victory            → win         勝利表示を見た
#:     加入者>0 かつ 生存0     → lose        ⚠ 全滅（★読めていないのと区別）
#:     player_had_control      → flee        こちらが逃げた
#:     それ以外                → enemy_fled  ★敵が逃げた
RESULT_LABELS = {
    "win": "勝利", "lose": "全滅", "flee": "逃走", "enemy_fled": "敵が逃走", 
}
