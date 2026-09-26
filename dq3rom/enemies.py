"""DQ3 の敵データ表（139 体 × 23 bytes）を ROM から読む（RX3-0003 / 2026-08-23）。

## 位置（profile から引く。⚠ ここに数値を直書きしない）

    file 0x003308 〜 0x003F85（exclusive）= 139 × 23 = 3197 bytes
    ★北米版の既知表と **3197/3197 bytes 一致**（調査資料 §5.1）。
      表全体が同一なので、公開されている 23-byte layout を日本版にも当てられる。

## 1 エントリ 23 bytes（調査資料 §5.2 / 北米版逆アセンブル）

    +0      level
    +1..2   exp（little-endian）
    +3      agility
    +4      gold  下位 8 bit
    +5      attack  下位 8 bit
    +6      defense 下位 8 bit
    +7      hp      下位 8 bit
    +8      mp
    +9      item / drop ID
    +10..17 行動候補 8 枠
    +18..21 ★各能力の**上位 2 bit**（⚠ 下位 2 bit だけ使う）＋ 他は未確定
    +22     ⚠ drop odds / threshold 関連（**未確定**）

## ★★ 上位 2 bit は確定した（RX3-0033 / 2026-08-31）

⚠ 以前ここには「どの bit かは公開ソース側にも未確定」と書いてありました。
★北米版の逆アセンブル（`work/dq3-disasm/`）に**名前つきで載っていました**。

```text
_bs_read_enemy_prop_HP:   LDY #7   … LDY #$15  AND #3   → 上位バイト
_bs_load_enemy_prop_ATK:  LDY #5   … LDY #$13  AND #3
_bs_load_enemy_prop_DEF:  LDY #6   … LDY #$14  AND #3
（gold）                  LDY #4   … LDY #$12  AND #3   ★16 bit で足している
```

★つまり **+14 したところの下位 2 bit** が上位バイトです。

```text
gold    = raw[4] + (raw[18] & 3) * 256
attack  = raw[5] + (raw[19] & 3) * 256
defense = raw[6] + (raw[20] & 3) * 256
hp      = raw[7] + (raw[21] & 3) * 256
```

### ★裏づけ（⚠ 実測）

```text
敵 0   HP 8 / gold 2 / atk 9 / def 5 / exp 4    ★スライムの実際の値
敵 133 HP 1023 / atk 550                        ★HP 最大（⚠ 2 bit ぶんが効いている）
★HP が 256 を超える敵が 14 体（⚠ 上位 bit を使わないと出せない）
★HP が 0 の敵は 0 体（⚠ でたらめな bit を拾っていない証拠）
```

⚠ `AND #3` なので、+18〜+21 の**残り 6 bit は別の意味**です（★耐性など。未確定）。
★だから `raw` は**引き続き丸ごと持ちます**。

## round-trip（指示書 §6）

  `Enemy.to_bytes()` が元の 23 bytes を**1 byte も欠かさず**返すこと。
  ⚠ 名前付きの値だけを持つ model は、未確定 byte を落とす。raw を必ず抱える。
"""

from __future__ import annotations

import dataclasses

from .profile import Identified

ENTRY_SIZE = 23
ACTION_SLOTS = 8
#: ⚠ 意味が未確定の領域。名前を付けず raw で持つ
RAW_TAIL_FROM = 18


@dataclasses.dataclass(frozen=True)
class Enemy:
    """敵 1 体。★確定している値と、raw の両方を持つ。"""

    enemy_id: int                     # 0 始まり（表の並び順）
    level: int
    exp: int
    agility: int
    gold_raw: int                     # ★下位 8 bit（⚠ 上位 2 bit は `+14`）
    attack_raw: int                   # 同上
    defense_raw: int                  # 同上
    hp_raw: int                       # 同上
    mp: int
    drop_item: int
    actions: tuple                    # 8 枠（raw）
    raw_18_21: bytes                  # ⚠ 未確定（上位 bit・耐性・効果）
    raw_22: int                       # ⚠ 未確定（drop odds / threshold）
    raw: bytes                        # ★元の 23 bytes そのもの

    @classmethod
    def from_bytes(cls, enemy_id: int, data: bytes) -> "Enemy":
        if len(data) != ENTRY_SIZE:
            raise ValueError(
                f"敵 {enemy_id}: {ENTRY_SIZE} bytes のはずが {len(data)} bytes")
        return cls(
            enemy_id=enemy_id,
            level=data[0],
            exp=int.from_bytes(data[1:3], "little"),
            agility=data[3],
            gold_raw=data[4],
            attack_raw=data[5],
            defense_raw=data[6],
            hp_raw=data[7],
            mp=data[8],
            drop_item=data[9],
            actions=tuple(data[10:18]),
            raw_18_21=bytes(data[18:22]),
            raw_22=data[22],
            raw=bytes(data),
        )

    # --- ★★ 10 bit の値（⚠ 上位 2 bit は `+14` / RX3-0033 で確定）--------
    #
    #   ⚠⚠ 長らく「上位 2 bit の位置は未確定」と書いてありました。
    #     ★2026-08-31 に北米版の逆アセンブルで確定し、実機とも合っています。
    #     ⚠ `*_raw` は**下位 8 bit だけ**なので、表示には下の値を使うこと。

    @property
    def hp(self) -> int:
        """★最大 HP（⚠ 最大 1023）。"""
        return wide(self.raw, 7)

    @property
    def attack(self) -> int:
        return wide(self.raw, 5)

    @property
    def defense(self) -> int:
        return wide(self.raw, 6)

    @property
    def gold(self) -> int:
        return wide(self.raw, 4)

    def to_bytes(self) -> bytes:
        """名前付きの値から 23 bytes を組み立て直す。

        ★`raw` をそのまま返すのではなく**組み立て直す**。⚠ そうしないと
          「名前付きの値が raw と食い違っている」ことに気づけない。
        """
        out = bytes([self.level]) + self.exp.to_bytes(2, "little")
        out += bytes([self.agility, self.gold_raw, self.attack_raw,
                      self.defense_raw, self.hp_raw, self.mp, self.drop_item])
        out += bytes(self.actions)
        out += self.raw_18_21 + bytes([self.raw_22])
        return out

    def to_json(self) -> dict:
        return {
            "id": self.enemy_id,
            "level": self.level,
            "exp": self.exp,
            "agility": self.agility,
            "gold_raw": self.gold_raw,
            "attack_raw": self.attack_raw,
            "defense_raw": self.defense_raw,
            "hp_raw": self.hp_raw,
            "mp": self.mp,
            "drop_item": self.drop_item,
            "actions": list(self.actions),
            # ⚠ 未確定は hex で。名前を付けない
            "raw_18_21": self.raw_18_21.hex(),
            "raw_22": f"{self.raw_22:02x}",
            # ★10 bit にした値（⚠ `*_raw` は下位 8 bit だけ）
            "hp": self.hp,
            "attack": self.attack,
            "defense": self.defense,
            "gold": self.gold,
            "_note": "gold/attack/defense/hp の上位 2 bit は「下位の場所 +14」"
                     "（★RX3-0033 で確定）",
        }


#: ★上位 2 bit は「下位のある場所 +14」に入っている（⚠ 実測 / RX3-0033）
HIGH_OFFSET = 14
#: ⚠ 使うのは下位 2 bit だけ（★`AND #3`）
HIGH_MASK = 0x03


def wide(raw: bytes, low: int) -> int:
    """★下位 8 bit ＋ 上位 2 bit を合わせた値（0..1023）。

    ⚠⚠ ここが唯一の実装。★呼ぶ側で `& 3` と書かないこと。

    ★根拠は北米版の逆アセンブル（`_bs_read_enemy_prop_HP` ほか）。
    """
    hi = raw[low + HIGH_OFFSET] & HIGH_MASK
    return raw[low] + hi * 256


def read_all(ident: Identified) -> list[Enemy]:
    """profile の位置から 139 体を読む。⚠ 範囲が合わなければ断る。"""
    t = ident.table("enemies")
    count = int(t["count"])
    entry = int(t["entry_size"])
    if entry != ENTRY_SIZE:
        raise ValueError(f"profile の entry_size が {entry}（このコードは {ENTRY_SIZE}）")
    start = ident.table_prg("enemies")
    end = start + count * entry
    prg = ident.rom.prg
    if end > len(prg):
        raise ValueError(f"敵表が ROM の外に出ます: 0x{end:X} > 0x{len(prg):X}")
    want_end = ident.table_prg("enemies", "end_file_exclusive")
    if want_end != end:
        raise ValueError(
            f"profile の終端 0x{want_end:X} と count×entry の終端 0x{end:X} が違います")
    return [Enemy.from_bytes(i, prg[start + i * entry:start + (i + 1) * entry])
            for i in range(count)]


def round_trip_ok(ident: Identified, enemies: list[Enemy]) -> bool:
    """★全 3197 bytes を組み立て直して、元と 1 byte も違わないか。"""
    start = ident.table_prg("enemies")
    original = ident.rom.prg[start:start + len(enemies) * ENTRY_SIZE]
    rebuilt = b"".join(e.to_bytes() for e in enemies)
    return rebuilt == original


def to_csv_rows(enemies: list[Enemy]) -> list[list]:
    head = ["id", "level", "exp", "agility", "gold_raw", "attack_raw",
            "defense_raw", "hp_raw", "mp", "drop_item"]
    head += [f"action{i}" for i in range(ACTION_SLOTS)]
    head += ["raw_18_21", "raw_22"]
    rows = [head]
    for e in enemies:
        rows.append([e.enemy_id, e.level, e.exp, e.agility, e.gold_raw,
                     e.attack_raw, e.defense_raw, e.hp_raw, e.mp, e.drop_item,
                     *e.actions, e.raw_18_21.hex(), f"{e.raw_22:02x}"])
    return rows
