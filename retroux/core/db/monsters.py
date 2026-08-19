"""モンスター図鑑の集計（MVP2 Phase 4 の土台 / 指示書 5.4 C）。

記録済みの戦闘（`BattleLog`）と、ROM 由来の静的データ（`memory_map` の
`monster_stats`）を突き合わせて、1体ぶんの行を作る。

★2つの出所を混ぜない:

| 列 | 出所 | 性質 |
| --- | --- | --- |
| 最大HP・攻撃・守備・EXP・ゴールド | **ROM**（`monster_stats`） | 動かない事実 |
| 遭遇回数・勝率・平均所要 | **記録**（`BattleLog`） | 遊ぶほど増える観測 |

指示書には「基礎脅威度」「実測脅威度」と両方あるが、
**混ぜて1つの数字にしない**。どちらの話かが分からなくなる。

⚠⚠ **勝敗が記録されていない戦闘がある**（実データで 1563 件中 685 件が NULL）。
  記録プロセスが動いていない間に終わった戦闘などが該当する。

  これを分母に入れると「スライムの勝率 8.7%」のような数字が出る。
  実際に負けているのではなく、**勝敗が分からないだけ**。
  そこで **勝率の分母は「勝敗が分かっている戦闘」**にし、
  分からない件数は別に出す（データの質が見えるように）。

  ★遭遇回数は全部を数える。「出会った」ことは記録の質と関係なく事実。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class MonsterRow:
    """図鑑の1行。"""

    id: int
    name: str
    # --- ROM 由来（動かない事実）---
    max_hp: int | None = None
    attack: int | None = None
    defense: int | None = None
    agility: int | None = None
    exp: int | None = None
    gold: int | None = None
    evade: int | None = None
    resist: dict | None = None
    """耐性6種（0=必ず効く / 7=効かない）。無い敵は None。"""
    drop: dict | None = None
    """{item, denominator}。**落とさない敵はキーごと無い**（None）。"""
    wisdom: int | None = None
    actions: list | None = None
    """8枠の行動（値は memory_map の monster_actions のキー）。"""
    # --- 記録由来（遊ぶほど増える）---
    encounters: int = 0
    decided: int = 0
    """勝敗が記録されている戦闘の数。**勝率の分母はこちら。**"""
    wins: int = 0
    total_ms: int = 0

    @property
    def unknown_results(self) -> int:
        """勝敗が分からない戦闘の数。多いほど勝率の信用が落ちる。"""
        return self.encounters - self.decided

    @property
    def win_rate(self) -> float | None:
        """勝率。**勝敗が分かっている戦闘が無ければ None**（0% ではない）。

        ★0 と「まだ分からない」を混ぜない。分からないものを 0% と出すと、
          勝てない敵に見える（実データで実際にそうなった）。
        """
        return (self.wins / self.decided) if self.decided else None

    @property
    def average_seconds(self) -> float | None:
        return (self.total_ms / self.encounters / 1000.0) if self.encounters else None

    @property
    def known(self) -> bool:
        """一度でも会ったか。"""
        return self.encounters > 0


def build(db, rom_hash: str, names: dict, stats: dict,
          behavior: dict | None = None) -> list[MonsterRow]:
    """図鑑の全行を作る。名前の表（memory_map の monsters）を基準にする。

    `behavior` は memory_map の `monster_behavior`（賢さと8枠の行動）。
    ★渡さなくても動く（古い呼び出しを壊さない）。その場合は行動が空になる。
    """
    rows: dict[int, MonsterRow] = {}
    for mid, name in names.items():
        s = stats.get(mid, {}) if stats else {}
        b = (behavior or {}).get(mid) or {}
        rows[mid] = MonsterRow(
            id=mid, name=str(name),
            max_hp=s.get("max_hp"), attack=s.get("attack"),
            defense=s.get("defense"), agility=s.get("agility"),
            exp=s.get("exp"), gold=s.get("gold"),
            evade=s.get("evade"),
            # ★無いものは None のまま。**空の辞書で埋めない**
            #   （「耐性が全部0」と「耐性が分からない」を混ぜない）
            resist=s.get("resist"), drop=s.get("drop"),
            wisdom=b.get("wisdom"), actions=b.get("actions"),
        )

    # ★1戦闘に同じ敵が複数いても「遭遇1回」と数える。
    #   体数で数えると「6体グループ」の敵ばかり遭遇回数が伸びて、
    #   出会いやすさの指標として使えなくなる。
    for battle in db.recent_battles(rom_hash, limit=100000):
        try:
            ids = json.loads(battle["monster_ids"])
        except (TypeError, ValueError):
            continue
        result = battle["result"]
        won = str(result or "") == "win"
        duration = int(battle["duration_ms"] or 0)
        for mid in set(ids):
            row = rows.get(mid)
            if row is None:
                row = rows[mid] = MonsterRow(id=mid, name=f"未知(0x{mid:02X})")
            row.encounters += 1
            row.total_ms += duration
            if result:
                row.decided += 1
                if won:
                    row.wins += 1

    return [rows[k] for k in sorted(rows)]
