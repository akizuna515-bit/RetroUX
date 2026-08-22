"""ROM から「通れるか」の表を作る（製品版ログ整理 Phase 5 / 指示書 §13〜§15）。

## ★ なぜ作るか

    MapEdge              2,117 行   ← 通常歩行で「通れた」
    MapBlockedDirection    496 行   ← 通常歩行で「進めなかった」

これを**毎回歩いて集め直していました**。⚠ 中身は ROM に最初から入っています。
★静的に作れるものを実行時に集めない（指示書 §12）。

## ⚠⚠ どこまで分かっているか（★ここを読まずに使わないこと）

地形テーブルは 1 件 5 バイト（タイル4枚＋属性1）。
その**5 バイト目の上位ニブル**について、次まで確かめました。

### ★確認できたこと（逆アセンブル）

    $E1F9: A0 04      LDY #$04        ; 5 バイト目（属性）
    $E1FB: B1 10      LDA ($10),Y
    $E1FD: 29 F0      AND #$F0        ; ★上位ニブルだけ取り出す
    $E1FF: 85 3C      STA $3C         ; ゼロページ $3C へ

★写像は3つの既知地点で照合済み（`$DFF1: CMP #$14` 宝箱 /
`$E006: LDA #$00` 開封後 / `$E015: CMP #$18` 扉）。
⚠ 既存コードは `& 3`（パレット）しか見ておらず、上位ニブルは未使用でした。

### ★観測との一致（1,202 件・反例 0）

    進めなかった観測のうち上位ニブルが 0xF : 54
    ★歩けたのに 0xF だった（＝反証）        :  0
    歩けて 0xF でもなかった                : 1,148
    進めなかったが 0xF でもなかった        :  235   ⚠ NPC・演出を含む

### ★★ 因果が確定した（2026-08-21 / RX-0032）★★

⚠ 上の `$3C` は**移動の判定ではない**（移動後の階段・ワープ判定に使う）。
  判定は **`$3B`** で、徒歩の移動処理（固定バンク。日本版 `$D176`〜、
  北米版逆アセンブル `constant.asm` の `$D35E`〜 `B0F_D414`）にある。
  ★日本版 ROM を**命令単位で逆アセンブル**して確かめた（バイト列検索だけで
  決めていない。★2026-08-13 の誤検出の教訓）:

    $D176: A0 04     LDY #$04        ; 目的地タイルの属性（5バイト目）
    $D178: B1 10     LDA ($10),Y
    $D17A: 29 FC     AND #$FC
    $D17C: 85 3B     STA $3B
    ── 徒歩（$CF bit2 = 0）──
    $D1CE: A5 3B / 29 F0 / C9 40 / D0 ..   ; == $40（水）→ その場に船が居れば乗船、無ければ不可
    $D1F7: A5 3B / 29 F0 / C9 A0 / D0 ..   ; == $A0 → 湖の洞窟B1($2C)/B2($2D)/map $40 だけ不可、他は可
    $D20F: C9 B0 / 90 15                    ; >= $B0 → 不可 / < $B0 → 可（$D228）
    $D213: A5 16 / 85 28 / A5 17 / 85 29 / PLA×4 / LDA #0 / STA $03 / STA $3B / JMP $C5C0
                                            ; ★「不可」= 座標(2)を(1)へ戻して移動を捨てる
    ── 船上（$CF bit2 = 1）──
    $D18D: == $40 → 可（航行） / $D198: >= $A0 → 不可 / それ以外 → 下船して可

★つまり規則は「0xF は不可」より広い: **上位ニブル >= 0xB は不可**、0xA は3マップ
  だけ不可、0x4 は水（船のみ）、それ以外は徒歩で可。0xF の観測（反例 0）は
  この規則の特別な場合として**因果で裏付けられた**。
⚠ 日本版には `$D17E` に NOP×9 がある（北米版の `LDA $61AD` 系の検査が外されている）。

## 使い方

    PYTHONUTF8=1 python -m retroux.tools.map_passability
    PYTHONUTF8=1 python -m retroux.tools.map_passability --out work/generated/map_passability.json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from retroux.core.bgmap.dungeon_map import (  # noqa: E402
    BANK2, CHEST_TERRAIN, DOOR_TERRAINS, TABLE_ENTRY, TERRAIN_TABLES,
    DungeonMap, map_kind)

DEFAULT_ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
DEFAULT_OUT = PROJECT_ROOT / "work" / "generated" / "map_passability.json"

#: ★通れない上位ニブルの下限（`$D20F: CMP #$B0 / BCC 可`）。★0xB〜0xF が不可
SOLID_FLOOR = 0xB0
#: ★互換のため残す（旧 0xF だけの見立て）。⚠ 判定には `SOLID_FLOOR` を使う
SOLID_CLASS = 0xF0
#: ★水（`$D1CE: CMP #$40`）。徒歩では船がその場に居るときだけ乗れる
WATER_CLASS = 0x40
#: ★0xA0 は3マップでだけ不可（`$D1FF`〜: 湖の洞窟 B1/B2・map $40）
SWAMP_CLASS = 0xA0
SWAMP_BLOCKED_MAPS = (0x2C, 0x2D, 0x40)

#: ⚠ 実行中に差し替わる地形。★静的な値は「閉じている状態」を指す
DYNAMIC = {**{t: "door" for t in DOOR_TERRAINS}, CHEST_TERRAIN: "chest"}

#: ★世界地図は行ランレングスの別復号（`world_map.py`）。第一版では対象外
WORLD_MAP_ID = 0x01


def attribute(prg: bytes, map_id: int, terrain_id: int) -> int | None:
    """地形IDの属性バイト。⚠ 表の外なら None（★0 と混ぜない）。"""
    kind = map_kind(map_id)
    if kind not in TERRAIN_TABLES or terrain_id is None:
        return None
    base = BANK2 + TERRAIN_TABLES[kind] - 0x8000 + terrain_id * TABLE_ENTRY
    if base + 4 >= len(prg):
        return None
    return prg[base + 4]


def classify(terrain_id: int, attr: int | None, map_id: int | None = None) -> tuple[str, dict]:
    """(種別, 通行可否) を返す。★規則は上の docstring（`$D1CE`〜 の写し）。

    ⚠⚠ **bool へ潰さない**（指示書 §15）。DQ2 には船がある。
      `foot` / `ship` をそれぞれ持つ。`None` は「静的には決まらない」。
    ★2026-08-21（RX-0032）: 因果が確定したので `ship` にも値を入れる。
      船上: 水（0x4）= 航行可 / >= 0xA = 不可 / それ以外 = 下船して可。
    """
    if attr is None:
        return "unknown", {"foot": None, "ship": None}
    if terrain_id in DYNAMIC:
        # ★開けると `OPENED_TERRAIN = 0x00` へ差し替わる。
        #   ⚠ 閉じている間は通れない、開けば通れる。**静的には決まらない**。
        return DYNAMIC[terrain_id], {"foot": None, "ship": None}
    cls = attr & 0xF0
    if cls >= SOLID_FLOOR:
        return "blocked", {"foot": False, "ship": False}
    if cls == SWAMP_CLASS:
        blocked = map_id in SWAMP_BLOCKED_MAPS
        return ("blocked" if blocked else "walk"), {"foot": not blocked, "ship": False}
    if cls == WATER_CLASS:
        # ⚠ 徒歩は「その場に船が居る」ときだけ乗れる（NPC #$13 の位置 = 動的）
        return "water", {"foot": False, "ship": True}
    return "walk", {"foot": True, "ship": True}


def build(prg: bytes, *, rom_hash: str, now: datetime | None = None) -> dict:
    maps = []
    skipped: list[int] = []
    for map_id in range(0x00, 0x6D):
        if map_id == WORLD_MAP_ID:
            skipped.append(map_id)
            continue
        try:
            dm = DungeonMap(prg, map_id)
        except Exception:                              # noqa: BLE001
            skipped.append(map_id)
            continue
        if dm.pointer == 0:
            continue                                   # ★中身のないマップ
        width, height = dm.screen_size
        cells = []
        for y in range(height):
            for x in range(width):
                try:
                    terrain_id = dm.terrain_at(x, y)
                except Exception:                      # noqa: BLE001
                    terrain_id = None
                attr = attribute(prg, map_id, terrain_id)
                kind, passability = classify(terrain_id, attr, map_id)
                cells.append({
                    "x": x, "y": y,
                    "terrain_id": terrain_id,
                    # ★属性の上位ニブル（＝ゲームが $3C へ入れている値）
                    "terrain_class": None if attr is None else (attr & 0xF0),
                    "terrain_type": kind,
                    "passability": passability,
                })
        maps.append({
            "map_id": map_id,
            "kind": map_kind(map_id),
            "width": width, "height": height,
            "cells": cells,
        })

    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "schema_version": "1.0",
        "game_id": "dq2_fc_jp",
        "rom_hash": rom_hash,
        "generated_at": stamp,
        "source": "python -m retroux.tools.map_passability",
        # ⚠⚠ **根拠を一緒に持たせる**（★後から「どこまで確かか」を読めるように）
        "confidence": {
            "rule": "attr high nibble: >=0xB blocked / 0xA blocked only on maps 0x2C,0x2D,0x40 / "
                    "0x4 water (ship only) / else walk. ship: 0x4 sail, >=0xA blocked, else land",
            # ★移動判定の実コード（日本版 ROM を命令単位で逆アセンブルして確認 / RX-0032）
            "disassembly": "$D176: LDY #$04 / LDA ($10),Y / AND #$FC / STA $3B ; "
                           "$D1CE: CMP #$40 ; $D1F7: CMP #$A0 ; $D20F: CMP #$B0 / BCC walk ; "
                           "$D213: blocked (restore $28/$29) ; $D228: move",
            "verified_against_observations": 1202,
            "counterexamples": 0,
            # ★2026-08-21 に因果を特定した（それまでは 0xF の相関だけだった）
            "causal_site_located": True,
            "causal_site": "JP $D176-$D228 (fixed bank) / US constant.asm $D35E-$D429",
            "note": "旧 $E1F9 の $3C は移動後の階段・ワープ判定で、通行判定ではない。"
                    "navigation_mismatch は引き続き裏取りに使う",
        },
        "skipped_maps": skipped,
        "skipped_reason": "世界地図は行ランレングスの別復号（world_map.py）。第一版では対象外",
        "maps": maps,
    }


def summarize(data: dict) -> str:
    total = sum(len(m["cells"]) for m in data["maps"])
    kinds: dict[str, int] = {}
    for m in data["maps"]:
        for c in m["cells"]:
            kinds[c["terrain_type"]] = kinds.get(c["terrain_type"], 0) + 1
    lines = [f"マップ {len(data['maps'])} / マス {total:,}"]
    for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {v:7,}  {k}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", default=str(DEFAULT_ROM))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    rom_path = pathlib.Path(args.rom)
    if not rom_path.exists():
        print(f"✗ ROM がありません: {rom_path}", file=sys.stderr)
        return 2
    raw = rom_path.read_bytes()
    prg = raw[16:]                                     # ★iNES ヘッダを飛ばす

    import hashlib

    rom_hash = hashlib.sha256(prg).hexdigest().upper()
    data = build(prg, rom_hash=rom_hash)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"書き出した: {out}")
    print(summarize(data))
    print("★規則は実コード（JP $D176〜$D228）から確定しています"
          "（confidence.causal_site_located = true / RX-0032）")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
