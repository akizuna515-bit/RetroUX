"""戦闘中の敵を RAM から読む（RX3-0033 / 2026-08-31）。

## ★★ 何が読めるか

```text
$056D  敵の種類（★ROM の敵の表の索引）   ⚠ 4 群 / $FF は空
$0571  その群の数
$0500  ★個体ごとの**現在 HP**（⚠ 16 bit × 8）
$0510  ⚠ MP（8）        $0518  ⚠ すばやさ（8）
$0520  ⚠ しゅび力（16 bit × 8。★種類ごとに一定）
$0530  ★個体ごとの状態（⚠ 2 バイト × 8。**2 バイト目**の $80 が「生きている」）
```

## ⚠⚠ 2026-08-31 訂正: `$0520` を HP と書いていました

★実機のセーブ 6 本が否定しました。`$0520` は **しゅび力**で、
⚠ ROM の offset 6（`_bs_load_enemy_prop_DEF`）と**6 体すべてで一致**します。

```text
⚠ 気づけなかった理由: しゅび力も「0 < 値 <= ROM の HP」を満たしていた。
★決め手: **4 匹のスライムの値が全部同じ**だった（7,6,7,8 にならない）。
  → ★同じ種類でも個体ごとに違う、が HP の見分け方。
```

★正しい番地は `ram.inc` を最後まで数えれば出ます。

```text
$0480 _attr_ram_buf 128 バイト → $0500 _enemy_HP（WORD×8）
$0510 _enemy_MP 8 → $0518 _enemy_AGI 8 → $0520 _enemy_DEF（WORD×8）
$0530 status
```

## ⚠⚠ HP は 16 bit（★ここを間違えていた）

`RX3-0021`（2026-08-29）には「HP は探したが RAM に見つからなかった」と
書いてありました。⚠ **8 bit で探していた**のが原因です
（★「8 が 4 つ並ぶ場所は 0 件」という観測そのものは正しかった）。

★手がかりは北米版の逆アセンブル（`work/research/dq3-disasm/disassembly/ram.inc`）:

```text
_enemy_HP:  .WORD 0,0,0,0,0,0,0,0     ; enemy current HP during battle
（status）  struct { u8 one, two } enemystat[8]   ; L - alive?
```

## ⚠ 体数より後ろは読まない

★`counts` の合計ぶんだけ読みます（⚠ 後ろに何が残っていても見ない）。

## ⚠ HP はゆらぐ

★ROM の値は**上限**で、実際はそれ以下です（⚠ スライム 8 →実機 6/7/7/8）。
⚠ だから「ROM の値と一致するか」では確かめられません。
★★ そして `0 < いま <= ROM` **だけでは足りません**（しゅび力も満たす）。
  ⚠ 「同じ種類でも個体ごとに違いうる」まで見ること。
"""

from __future__ import annotations

import dataclasses

#: ★4 群まで
GROUPS = 4
#: ★個体は 8 体まで
SLOTS = 8
#: ⚠ 空の群
EMPTY = 0xFF
#: ★状態の「生きている」ビット
ALIVE_BIT = 0x80
#: ⚠⚠ 状態は 2 バイト。★**2 バイト目**が「いまの状態」
#:   （1 バイト目は手番の初めの控えらしく、⚠ 全滅しても $80 のまま残る）
ALIVE_BYTE = 1


class BattleRuntimeError(ValueError):
    """⚠ 読めなかった。★黙って空を返さない。"""


@dataclasses.dataclass(frozen=True)
class Foe:
    """★1 体ぶん。"""

    slot: int
    enemy_id: int
    hp: int
    alive: bool
    status: tuple


@dataclasses.dataclass(frozen=True)
class Battle:
    """★いまの戦闘。"""

    groups: tuple          #: ★`({"id":…, "n":…}, …)`
    foes: tuple            #: ★個体ごと（⚠ 体数ぶんだけ）

    @property
    def total(self) -> int:
        return len(self.foes)

    @property
    def alive(self) -> int:
        return sum(1 for f in self.foes if f.alive)


def _addr(profile: dict, key: str, fallback: int) -> int:
    """⚠ 番地は profile から（★ここに数値を直書きしない）。"""
    got = ((profile.get("runtime") or {}).get("battle_enemies") or {}).get(key)
    return int(str(got), 16) if got is not None else fallback


def read(ram, profile: dict) -> Battle:
    """★RAM から、いまの戦闘の敵を読む。

    ⚠ 戦闘中かどうかは**呼ぶ側が見る**（★`in_battle`）。
      ここは「RAM に何が書いてあるか」だけを返します。
    """
    if len(ram) < 0x0800:
        raise BattleRuntimeError("⚠ RAM が %d バイトしかありません" % len(ram))
    ids_at = _addr(profile, "ids", 0x056D)
    cnt_at = _addr(profile, "counts", 0x0571)
    hp_at = _addr(profile, "hp_current", 0x0500)
    st_at = _addr(profile, "status", 0x0530)

    groups = []
    for i in range(GROUPS):
        eid = ram[ids_at + i]
        if eid == EMPTY:
            continue
        groups.append({"id": eid, "n": ram[cnt_at + i]})

    foes = []
    slot = 0
    for g in groups:
        for _ in range(g["n"]):
            if slot >= SLOTS:
                break                      # ⚠ 表からはみ出さない
            hp = ram[hp_at + slot * 2] | (ram[hp_at + slot * 2 + 1] << 8)
            st = (ram[st_at + slot * 2], ram[st_at + slot * 2 + 1])
            foes.append(Foe(slot=slot, enemy_id=g["id"], hp=hp,
                            alive=bool(st[ALIVE_BYTE] & ALIVE_BIT),
                            status=st))
            slot += 1
    return Battle(groups=tuple(groups), foes=tuple(foes))
