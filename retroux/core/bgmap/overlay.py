"""地形を層に分ける（2026-08-02 / 依頼者の指示 Phase A・Phase 3）。

★★ **「動くもの」を基礎地形へ混ぜません。** ★★

## なぜ分けるか

依頼者の指摘（2026-08-02）:

  「左上の謎の宝箱と、赤い枠が左上の湖に存在するのがちょっとおかしい」

★ROM の地形IDには**宝箱そのもの**が入っています（`$14`）。
⚠ しかし宝箱は**開けると消えます**。ROM だけで描くと、
  もう開けた宝箱がいつまでも地図に残ります。

## ★★ 3 つに分ける（Phase 3）

| 層 | 何か | 出どころ | 変わるか |
| --- | --- | --- | --- |
| `ObjectDefinition` | ★**そこに宝箱がある** | ROM | ★変わらない |
| `RuntimeState` | ⚠ **いま開いているか** | RAM `$051A`/`$052A` | ⚠ 遊ぶと変わる |
| `KnowledgeState` | ⚠ **見つけたか** | 遊んだ記録 | ⚠ 増える |

⚠⚠ **この 3 つを混ぜないでください。**
「宝箱がある」と「宝箱が開いている」と「宝箱を見つけた」は別のことです。

★`BaseTerrain`（`DungeonMap`）へは**書き込みません**。
合成するときだけ、`composed_terrain()` が状態を反映します。

## ★ 実コードの裏づけ（`$DFEF`-`$E03A`）

```
DFEF: STA $0C
DFF1: CMP #$14 / BNE $E013        ; ★宝箱
DFF5: LDY #$00
DFF7: LDA $12 / CMP $051A,Y       ; ★x を照合
DFFE: INY / LDA $13 / CMP $051A,Y ; ★y を照合
E006: LDA #$00 / STA $0C          ; ★★一致したら「床」に差し替え
E00F: CPY #$10 / BNE $DFF7        ; ★8組（16バイト）ぶん

E015: CMP #$18 / BEQ              ; ★扉（3種）
E019: CMP #$19 / BEQ
E01D: CMP #$1A / BNE
E021: 同じ手順で $052A の8組
```

★初期化は `$E368: TXA / STA $051A,X / CPX #$20`（32バイト＝両方）。

⚠ 初期化は `$00,$01,$02,…` を入れます。★つまり「(0,1) (2,3) (4,5)…」という
**ありえない座標**が並ぶわけではありません。実在の座標と当たる恐れがあるので、
`RuntimeState` は**そのまま**照合します（実機と同じ挙動）。

## ⚠ 名前をつけない

**コードで確定した `$14`（宝箱）と `$18`-`$1A`（扉）だけ**に名前をつけます。
⚠ 他の地形IDは `unknown` のまま保持します。絵を見て
「これは水だろう」と決めることはしません（★推測で埋めない）。
"""

from __future__ import annotations

import dataclasses

from .dungeon_map import CHEST_TERRAIN, DOOR_TERRAINS, OPENED_TERRAIN

#: 動的差分の表（★`$051A` / `$052A`）
CHEST_LIST = 0x051A
DOOR_LIST = 0x052A
#: ★1つの表に入る組の数（`CPY #$10` = 16バイト = 8組）
LIST_PAIRS = 8
#: ★両方あわせた初期化の長さ（`CPX #$20`）
LIST_BYTES = 0x20

#: 出典・確度
FROM_ROM_CODE = "rom_code"
FROM_RAM = "ram"
UNKNOWN = "unknown"

#: 種別（★コードで確定したものだけ）
KIND_CHEST = "chest"
KIND_DOOR = "door"

#: 状態
STATE_CLOSED = "closed"
STATE_OPENED = "opened"

#: ★どの表を見るか
LIST_OF_KIND = {KIND_CHEST: CHEST_LIST, KIND_DOOR: DOOR_LIST}
#: ★根拠（受け渡しに載せる）
ROM_EVIDENCE = {KIND_CHEST: "$DFF1 CMP #$14",
                KIND_DOOR: "$E015/$E019/$E01D CMP #$18/#$19/#$1A"}
RAM_EVIDENCE = {KIND_CHEST: "$051A (8 pairs)", KIND_DOOR: "$052A (8 pairs)"}


# --- 1. どこに何があるか（★ROM だけ。変わらない）--------------------------

@dataclasses.dataclass(frozen=True)
class ObjectDefinition:
    """★**そこに宝箱／扉がある**という事実。ROM 由来で変わりません。

    ⚠ 「開いているか」は持ちません。それは `RuntimeState` の仕事です。
    """

    cell: tuple
    """★論理セル `(x, y)`。照合はこの座標で行われます（`$12`/`$13`）。"""
    kind: str
    """`chest` / `door`。⚠ それ以外は作りません。"""
    terrain_id: int
    source_address: int | None = None
    """★ROM のどこから来たか。⚠ 分からなければ None。"""

    @property
    def rom_evidence(self) -> str:
        return ROM_EVIDENCE[self.kind]

    @property
    def ram_evidence(self) -> str:
        return RAM_EVIDENCE[self.kind]


# --- 2. いまどうなっているか（⚠ RAM だけ。遊ぶと変わる）-------------------

@dataclasses.dataclass(frozen=True)
class RuntimeState:
    """⚠ **いま開いているか**。RAM 由来です。

    ★RAM を渡さずに作ると `has_ram=False` になり、
      すべての状態が `unknown` になります（**`closed` にしません**）。
    """

    opened: dict = dataclasses.field(default_factory=dict)
    """`{種別: {(x, y), ...}}`。"""
    has_ram: bool = False

    @classmethod
    def from_ram(cls, ram) -> "RuntimeState":
        """RAM から 8 組ずつ読む。⚠ 読めなければ `has_ram=False`。"""
        if ram is None:
            return cls()
        opened = {}
        for kind, base in LIST_OF_KIND.items():
            opened[kind] = set(_pairs(ram, base))
        return cls(opened=opened, has_ram=True)

    def state_of(self, definition: ObjectDefinition) -> str:
        """⚠ RAM が無ければ `unknown`。★決めつけません。"""
        if not self.has_ram:
            return UNKNOWN
        found = self.opened.get(definition.kind, set())
        return STATE_OPENED if definition.cell in found else STATE_CLOSED

    def unmatched(self, definitions) -> list:
        """⚠ 表に載っているのに ROM 側の宝箱・扉が無い座標。

        ★**黙って捨てません。** `unknown_dynamic` として持ちます。
        （初期化の `$00,$01,…` がそのまま残っている場合もここに出ます）
        """
        if not self.has_ram:
            return []
        known = {(d.kind, d.cell) for d in definitions}
        out = []
        for kind, cells in self.opened.items():
            for cell in sorted(cells):
                if (kind, cell) not in known:
                    out.append({"object_type": "unknown_dynamic",
                                "listed_as": kind, "logical_x": cell[0],
                                "logical_y": cell[1],
                                "ram_evidence": RAM_EVIDENCE[kind],
                                "confidence": UNKNOWN})
        return out


# --- 3. 見つけたか（⚠ 遊んだ記録）-----------------------------------------

@dataclasses.dataclass
class KnowledgeState:
    """⚠ **プレイヤーが見つけたか**。ROM からも RAM からも作れません。

    ★歩いて見たマスを、呼ぶ側が入れてください（指示書 §2.2）。
    """

    discovered: set = dataclasses.field(default_factory=set)

    def is_discovered(self, definition: ObjectDefinition) -> bool:
        return definition.cell in self.discovered

    def discover(self, cell: tuple) -> None:
        self.discovered.add(tuple(cell))


# --- 合成ビュー（★これまでの使い方を保ちます）-----------------------------

@dataclasses.dataclass(frozen=True)
class Element:
    """★`定義 + 状態` を1つに見せたもの。**読み取り専用**です。"""

    definition: ObjectDefinition
    state: str
    source: str
    confidence: str

    @property
    def cell(self) -> tuple:
        return self.definition.cell

    @property
    def kind(self) -> str:
        return self.definition.kind

    @property
    def terrain_id(self) -> int:
        return self.definition.terrain_id

    @property
    def x(self) -> int:
        """★代表の画面マス（2×2 の左上）。"""
        return self.definition.cell[0] * 2

    @property
    def y(self) -> int:
        return self.definition.cell[1] * 2


@dataclasses.dataclass
class DynamicOverlay:
    """宝箱と扉。★基礎地形からは外してあります。"""

    definitions: list = dataclasses.field(default_factory=list)
    runtime: RuntimeState = dataclasses.field(default_factory=RuntimeState)
    knowledge: KnowledgeState = dataclasses.field(default_factory=KnowledgeState)
    #: ★1 論理セルが画面何マスぶんか（種別2以上は 2）
    span: int = 2

    @property
    def has_ram(self) -> bool:
        return self.runtime.has_ram

    @property
    def elements(self) -> list:
        """★定義と状態を合わせた一覧。"""
        return [Element(definition=d, state=self.runtime.state_of(d),
                        source=FROM_RAM if self.has_ram else FROM_ROM_CODE,
                        confidence=FROM_ROM_CODE)
                for d in self.definitions]

    def at(self, x: int, y: int):
        """そのマスの要素。⚠ 無ければ None。

        ★引数は**画面のマス**です。要素は論理セル単位で持っているので、
        1つの宝箱は 2×2 の 4 マスすべてに当たります（種別2以上）。
        """
        cell = (x // self.span, y // self.span)
        for e in self.elements:
            if e.cell == cell:
                return e
        return None

    def opened(self) -> list:
        return [e for e in self.elements if e.state == STATE_OPENED]

    def unresolved(self) -> list:
        """⚠ 状態が分かっていないもの。**黙って closed にしません**。"""
        return [e for e in self.elements if e.state == UNKNOWN]

    def unknown_dynamic(self) -> list:
        """⚠ 表に載っているが ROM 側に見当たらないもの。"""
        return self.runtime.unmatched(self.definitions)

    def apply_runtime_state(self, ram) -> "DynamicOverlay":
        """★RAM を当てた**新しい**層を返します。

        ⚠⚠ 元の層も `BaseTerrain` も**書き換えません**。
        """
        return dataclasses.replace(self, runtime=RuntimeState.from_ram(ram))

    def summary(self) -> str:
        chest = [d for d in self.definitions if d.kind == KIND_CHEST]
        door = [d for d in self.definitions if d.kind == KIND_DOOR]
        note = "★RAM あり" if self.has_ram else "⚠ RAM 無し（状態は不明のまま）"
        extra = self.unknown_dynamic()
        tail = f" / ⚠ 表にだけある {len(extra)}" if extra else ""
        return (f"宝箱 {len(chest)} / 扉 {len(door)}"
                f" / ★開封済み {len(self.opened())}"
                f" / ⚠ 状態不明 {len(self.unresolved())}{tail}   {note}")


def _pairs(ram, base: int):
    """★表から (x, y) を8組取り出す。⚠ RAM が無ければ空。"""
    if ram is None:
        return []
    out = []
    for i in range(LIST_PAIRS):
        try:
            out.append((ram[base + i * 2], ram[base + i * 2 + 1]))
        except (IndexError, TypeError):
            return out                      # ⚠ 読めなくなったら黙って止める
    return out


def build_dynamic(dmap, ram=None) -> DynamicOverlay:
    """基礎地形から宝箱・扉を抜き出す。

    `dmap` は `DungeonMap`。`ram` があれば**開封済みかどうか**も入れます。
    ⚠ `ram` が無いときは状態を `unknown` にします（`closed` にしません）。

    ★照合は `$12`/`$13` すなわち**論理セル座標**（`$DD9D` で 1/2 済み）です。
    """
    definitions = []
    # ★★論理セル単位で回します。⚠ 画面マスで回すと 1 つの宝箱が
    #   2×2 の 4 個に増えてしまいます。
    for cy in range(dmap.height):
        for cx in range(dmap.width):
            terrain = dmap.cell(cx, cy)
            if terrain == CHEST_TERRAIN:
                kind = KIND_CHEST
            elif terrain in DOOR_TERRAINS:
                kind = KIND_DOOR
            else:
                continue
            definitions.append(ObjectDefinition(
                cell=(cx, cy), kind=kind, terrain_id=terrain,
                source_address=(None if dmap.raw(cx, cy) is None else
                                dmap.pointer + cy * dmap.width + cx)))
    return DynamicOverlay(definitions=definitions,
                          runtime=RuntimeState.from_ram(ram),
                          span=2 if dmap.halved else 1)


def composed_terrain(dmap, x: int, y: int, overlay: DynamicOverlay) -> int:
    """★合成後の地形ID（`$E006` の写し）。

    ⚠ 状態が `unknown` の要素は**差し替えません**。
      分からないものを勝手に「開けた」ことにしないためです。

    ⚠⚠ `dmap`（BaseTerrain）は**書き換えません**。
    """
    element = overlay.at(x, y)
    if element is not None and element.state == STATE_OPENED:
        return OPENED_TERRAIN
    return dmap.terrain_at(x, y)
