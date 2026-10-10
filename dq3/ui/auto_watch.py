"""Lua が書いたログを、★共通 Event に変える bridge（RX3-0110 → RX3-0154）。

## ⚠⚠ 自動戦闘とまんたんは、Python 側に「終わり」が来ません

★聞き込みと自動移動は Python の `TownNavController` が段取りを持っています。
⚠ 自動戦闘（`auto_v0.lua`）とまんたん（`mantan_v0.lua`）は違います。

```text
画面 → dq3-command.json → Lua が最後まで自分でやる → ★結果はログファイルだけ
```

⚠ 画面は 0.5 秒に 1 回しか見に来ないので、★状態から組み立てると取りこぼします
（`dq3/ui/log_tail.py` の註と同じ理由）。

## ★2026-09-10（RX3-0154）: ここは**文章を作りません**

⚠ 以前はここで `[自動戦闘] 完了：…` を組み立てていました。
★いまは「何が起きたか」を Event にして流すだけです（依頼者 §9 / §16 / §18）。

```text
AUTO_V0_DONE … rounds=5 actions=18
   → battle.end {result: win, rounds: 5, actions: 18}
        ├─► Product Log      自動戦闘：勝利 5ターン（18行動）
        ├─► Action Summary   [自動戦闘] 完了：1戦 / 5ターン（18行動）
        └─► Diagnostic       {"ts": …, "type": "battle.end", …}

AUTO_V0_DONE … turns=18   ⚠ 旧。★ターンが分からないので rounds は None
AUTO_V0_STOP reason=screen_frozen  → battle.end {result: stopped, reason: …}
MANTAN_V0_DONE 全員 80% 以上 casts=0 → mantan.end {result: success, members_healed: 0}
```

⚠ 内部の語（`reason=screen_frozen`）は Event の `data` に**そのまま**入れます。
★人の言葉に直すのは `events/formatter.py` の仕事です。

## ⚠ 1 回に 1 行

★`AUTO_V0_DONE` と `AUTO_V0 OFF` は続けて出ます。⚠ 素直に書くと 2 行出ます。
→ ★`_Session` を閉じたら 2 度目は出しません（**先に来たほうが勝ち**）。
"""
from __future__ import annotations

import pathlib
import re

from dq3 import action_log as AL
from dq3 import battle_count as BC
from dq3 import events as EV
from dq3.events import reasons as RS

from .log_tail import LogTail

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROBE = paths.lazy_work("runtime", "dq3-probe")

#: ★止まった理由の表は `dq3/events/reasons.py` に 1 本（⚠ ここへ写さない）
BATTLE_REASONS = RS.BATTLE
MANTAN_REASONS = RS.MANTAN

_RE_BATTLE_ON = re.compile(r"^AUTO_V0 (ON|OFF)\b")
#: ★数え方は `dq3/battle_count.py` の 1 か所だけ（⚠ ここへ写さない / RX3-0153）
_RE_BATTLE_TURN = BC.TURN
_RE_BATTLE_DONE = BC.DONE
_RE_BATTLE_STOP = BC.STOP

_RE_MANTAN_ON = re.compile(r"^MANTAN_V0 (ON|OFF)\b")
_RE_MANTAN_DONE = re.compile(r"^MANTAN_V0_DONE (?P<why>.*?) casts=(?P<casts>\d+)\s*$")
_RE_MANTAN_STOP = re.compile(r"^MANTAN_V0_STOP reason=(?P<why>.+?)\s*$")
#: ★`  ★回復した p1 22 → 29（1 回目）`
_RE_MANTAN_HEAL = re.compile(r"★回復した (?P<slot>\S+) (?P<before>\d+) → (?P<after>\d+)")


class _Session:
    """★1 回ぶんの Lua 側の処理（⚠ ON から DONE / STOP まで）。"""

    def __init__(self) -> None:
        #: ★行動（1 人 1 回）と ターン（全員が 1 回）を、走りながら数える
        self.live = BC.Live()
        self.heals: list[tuple[str, int, int]] = []

    def healed(self) -> dict:
        """★回復の結果（⚠ 取れない値は入れません / 依頼者 §23）。"""
        if not self.heals:
            return {"members_healed": 0}
        return {"members_healed": len({slot for slot, _b, _a in self.heals}),
                "hp_gained": sum(after - before for _s, before, after in self.heals)}


class LuaActionWatcher:
    """★Lua のログを読み、⚠ 終わりに 1 件だけ Event を出す。"""

    def __init__(self, action_log: AL.ActionLog | None = None, *,
                 battle_log=None, mantan_log=None, from_end: bool = True,
                 writer=None) -> None:
        self.log = action_log if action_log is not None else AL.shared()
        # ⚠⚠ 行動履歴を名指しされたら、★その履歴へ書く Writer を持ちます。
        #   ★`EV.shared()` の sink は `AL.shared()` を見るので、⚠ 名指しが素通りします。
        if writer is not None:
            self.writer = writer
        elif action_log is not None:
            self.writer = EV.EventWriter(action_log=action_log)
        else:
            self.writer = EV.shared()
        self.tails = {
            "battle": LogTail(battle_log or (PROBE / "auto_v0.log"), from_end=from_end),
            "mantan": LogTail(mantan_log or (PROBE / "mantan_v0.log"), from_end=from_end),
        }
        self.open: dict[str, _Session | None] = {"battle": None, "mantan": None}

    # ------------------------------------------------------------------
    def poll(self) -> list[AL.ActionSummary]:
        """★増えた行を読み、⚠ 行動履歴に増えた行を返す（★無ければ空）。"""
        out: list[AL.ActionSummary] = []
        for kind, tail in self.tails.items():
            handler = self._battle if kind == "battle" else self._mantan
            for line in tail.read_new():
                out.extend(self._recorded(handler, line.strip()))
        return out

    def feed(self, kind: str, lines) -> list[AL.ActionSummary]:
        """⚠ 検査用（★ファイルを介さずに同じ道を通す）。"""
        handler = self._battle if kind == "battle" else self._mantan
        out: list[AL.ActionSummary] = []
        for line in lines:
            out.extend(self._recorded(handler, line.strip()))
        return out

    def _recorded(self, handler, line: str) -> list:
        """★1 行流して、⚠ **行動履歴に増えたぶん**を拾う。

        ⚠ Event を出しても履歴に出ない種別（`*.start`）があるので、
        ★戻り値は「Event が出たか」ではなく「履歴が増えたか」で数えます。
        """
        before = len(self.log.rows)
        handler(line)
        return list(self.log.rows[before:])

    # ------------------------------------------------------------------
    def _emit(self, type: str, source: str, data: dict, *, level: str = EV.INFO):
        try:
            return self.writer.emit(type, source, data, level=level)
        except Exception:                                        # noqa: BLE001
            return None                                           # ⚠ 見張りで本体を壊さない

    def _begin(self, kind: str) -> _Session:
        got = self.open.get(kind)
        if got is None:
            got = self.open[kind] = _Session()
        return got

    def _close(self, kind: str):
        got = self.open.get(kind)
        self.open[kind] = None
        return got

    # ------------------------------------------------------------------
    # ★自動戦闘
    # ------------------------------------------------------------------
    def _battle(self, line: str):
        m = _RE_BATTLE_TURN.match(line)
        if m:
            self._begin("battle").live.feed(m.group("slot"))
            return None
        done = BC.parse_done(line)
        if done is not None:
            got = self._begin("battle")
            self._close("battle")
            #: ⚠ 旧い記録は `rounds` が無いので、★走りながら数えたほうを使う
            rounds = done["rounds"]
            if rounds is None and got.live.actions == done["actions"]:
                rounds = got.live.rounds
            from dq3.events import reasons as _RS

            # ⚠⚠ RX3-0233: 窓の色・劣勢で人へ返した終わり（「…（ここから手で戦う）」）を「勝利」と数えていた
            result = EV.HANDED if _RS.is_handback(done["why"]) else EV.WIN
            data = {"result": result, "rounds": rounds, "actions": done["actions"],
                    "level_up": "レベル" in done["why"], "reason": done["why"]}
            # ★RX3-0198: 作戦・行動の内訳・MP 消費（⚠ 旧い行には無いので足さない / 形は battle_count が決める）
            data.update(BC.event_fields(done.get("summary")))
            return self._emit(EV.BATTLE_END, EV.SRC_BATTLE, data)
        m = _RE_BATTLE_STOP.match(line)
        if m:
            got = self._begin("battle")
            self._close("battle")
            return self._emit(EV.BATTLE_END, EV.SRC_BATTLE, {
                "result": EV.STOPPED, "rounds": got.live.rounds,
                "actions": got.live.actions, "reason": m.group("why")},
                level=EV.WARNING)
        m = _RE_BATTLE_ON.match(line)
        if m:
            if m.group(1) == "ON":
                self._begin("battle")
                return self._emit(EV.BATTLE_START, EV.SRC_BATTLE, {})
            # ⚠ DONE / STOP を見ずに OFF ＝ 人が切った（★閉じ済みなら何も出さない）
            got = self._close("battle")
            if got is None:
                return None
            return self._emit(EV.BATTLE_END, EV.SRC_BATTLE, {
                "result": EV.CANCELLED, "rounds": got.live.rounds,
                "actions": got.live.actions})
        return None

    # ------------------------------------------------------------------
    # ★まんたん
    # ------------------------------------------------------------------
    def _mantan(self, line: str):
        m = _RE_MANTAN_HEAL.search(line)
        if m:
            self._begin("mantan").heals.append(
                (m.group("slot"), int(m.group("before")), int(m.group("after"))))
            return None
        m = _RE_MANTAN_DONE.match(line)
        if m:
            got = self._begin("mantan")
            self._close("mantan")
            data = dict(got.healed(), result=EV.SUCCESS,
                        casts=int(m.group("casts")), reason=m.group("why"))
            return self._emit(EV.MANTAN_END, EV.SRC_MANTAN, data)
        m = _RE_MANTAN_STOP.match(line)
        if m:
            got = self._begin("mantan")
            self._close("mantan")
            data = dict(got.healed(), result=EV.STOPPED, reason=m.group("why"))
            return self._emit(EV.MANTAN_END, EV.SRC_MANTAN, data, level=EV.WARNING)
        m = _RE_MANTAN_ON.match(line)
        if m:
            if m.group(1) == "ON":
                self._begin("mantan")
                return self._emit(EV.MANTAN_START, EV.SRC_MANTAN, {})
            got = self._close("mantan")
            if got is None:
                return None
            return self._emit(EV.MANTAN_END, EV.SRC_MANTAN,
                              dict(got.healed(), result=EV.CANCELLED))
        return None


__all__ = ["LuaActionWatcher", "BATTLE_REASONS", "MANTAN_REASONS"]
