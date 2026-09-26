"""呪文の結果（RX3-0271 / 2026-09-14）― Lua が見たゲーム自身の判定を、戦闘ごとにまとめる。

```text
Lua  dq3/phase0/spell_watch.lua   耐性の判定（$A3EF）の入口と出口 → work/dq3-probe/spell_watch.log
      SPELL_RESULT battle=12 enemy=0 index=6 spell=34 ok=1
Py   ここ                        戦闘が終わったら読む（view_model._note_battle_end）
      → 図鑑の「あなたの記録」へ回数を足す（EnemyBook.tries）
      → 行動履歴へ 1 行（battle.spell / 「ラリホー → スライム：3回中2回 効いた」）
```

## ⚠⚠ 観測だけ（★報告 §10 / 依頼者「S10 は提案通りでOK」）

- ⚠ 1 回の失敗で「耐性がある」と書かない（★段 1 でも 3 割外れる）。★「n回中k回 効いた」とだけ書く。
- ★図鑑のことば（効きにくい など）は、**倒した敵**（図鑑が開いている敵）にだけ添える（★No-Spoiler）。
- ⚠ AI の内部の確率は出さない。⚠ 既にかかっていた敵はゲームが判定しないので、Lua も書かない（★失敗と数えない）。
"""
from __future__ import annotations

import dataclasses
import pathlib
import re

from dq3 import events as EV

from .. import paths
from .log_tail import LogTail

PROBE = paths.lazy_work("dq3-probe")

LINE = re.compile(r"^SPELL_RESULT battle=(?P<battle>\d+) enemy=(?P<enemy>\d+) index=(?P<index>\d+) "
                  r"spell=(?P<spell>-?\d+) ok=(?P<ok>[01])\s*$")


@dataclasses.dataclass(frozen=True)
class Observation:
    """★判定 1 回（⚠ 敵 1 体ぶん。群の呪文は 1 回で何行も来る）。"""

    battle: int
    enemy: int
    index: int
    spell: int
    ok: bool


def parse(line: str) -> Observation | None:
    m = LINE.match((line or "").strip())
    if m is None:
        return None
    return Observation(battle=int(m.group("battle")), enemy=int(m.group("enemy")),
                       index=int(m.group("index")), spell=int(m.group("spell")), ok=m.group("ok") == "1")


def resist_key(index: int) -> str | None:
    """★耐性の番号 → 名前。⚠ 画面の側は ROM を読まない（`test_UIはROMの正解を読まない`）→ 図鑑の知識に聞く。"""
    from dq3.knowledge import monster_book as mb

    return mb.resist_key_of(index)


def summarize(observations) -> list[dict]:
    """★(戦闘, 呪文, 敵) ごとに「試した / 効いた」（★出てきた順）。"""
    out: dict[tuple, dict] = {}
    for o in observations:
        key = (o.battle, o.spell, o.enemy, o.index)
        row = out.setdefault(key, {"battle": o.battle, "spell": o.spell, "enemy": o.enemy,
                                   "index": o.index, "tried": 0, "ok": 0})
        row["tried"] += 1
        row["ok"] += int(o.ok)
    return list(out.values())


def _spell_name(spell_id: int) -> str:
    if int(spell_id) < 0:
        return "道具"
    from dq3.knowledge import rom_names

    return rom_names.spell(int(spell_id)) or ("呪文%d" % int(spell_id))


def _enemy_name(enemy_id: int, book) -> str:
    from dq3.knowledge import rom_names

    names = getattr(book, "names", {}) or {}
    return rom_names.monster(int(enemy_id)) or names.get(int(enemy_id)) or ("敵%d" % int(enemy_id))


def _book_word(enemy_id: int, index: int, book) -> str | None:
    """★図鑑のことば（⚠ 倒した敵だけ / 決めるのは図鑑の知識 `monster_book.book_word`）。"""
    from dq3.knowledge import monster_book as mb

    return mb.book_word(book, enemy_id, index)


class SpellWatcher:
    """★Lua の `spell_watch.log` を読み、戦闘が終わったら 1 回だけまとめる。"""

    def __init__(self, path=None, *, writer=None, from_end: bool = True) -> None:
        self.tail = LogTail(pathlib.Path(path) if path is not None else PROBE / "spell_watch.log",
                            from_end=from_end)
        self.writer = writer
        self.pending: list[Observation] = []

    def poll(self) -> int:
        """★増えた行を読む（⚠ 読めない行は捨てる）。戻り値: 増えた判定の数。"""
        added = 0
        for line in self.tail.read_new():
            got = parse(line)
            if got is not None:
                self.pending.append(got)
                added += 1
        return added

    def take(self) -> list[Observation]:
        self.poll()
        got, self.pending = self.pending, []
        return got

    def flush(self, book) -> list[dict]:
        """★戦闘の終わりに: 図鑑の記録へ足し、行動履歴へ 1 行。戻り値: まとめた行（★無ければ空）。"""
        observations = self.take()
        if not observations:
            return []
        for o in observations:
            key = resist_key(o.index)
            if key is not None and book is not None:
                book.record_spell(o.enemy, key, o.ok)
        if book is not None:
            book.save()
        rows = summarize(observations)
        results = [{"spell": _spell_name(r["spell"]), "enemy": _enemy_name(r["enemy"], book),
                    "tried": r["tried"], "ok": r["ok"], "book": _book_word(r["enemy"], r["index"], book)}
                   for r in rows]
        if self.writer is not None:
            try:
                self.writer.emit(EV.BATTLE_SPELL, EV.SRC_SPELL, {"result": EV.SUCCESS, "results": results})
            except Exception:                                   # noqa: BLE001 ⚠ 記録で画面を止めない
                pass
        return results


__all__ = ["Observation", "SpellWatcher", "parse", "resist_key", "summarize", "LINE"]
