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

### ⚠⚠ まだ確定していないこと

**移動処理のどこで 0xF を見ているのか、位置を特定できていません。**
⚠ 一度 `CPX #$F0` を見つけたと思いましたが誤検出でした
（`29 E0` `F0 09` = `AND #$E0` + `BEQ` を命令境界をまたいで拾った）。

★したがってこの表は **相関にもとづく見立て**です。
  `confidence.causal_site_located` に `false` と入れてあります。
  ⚠ 裏取りは `navigation_mismatch`（§17）で実プレイと突き合わせて行います。

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

#: ★通れないと見立てる上位ニブル（§ 上の説明を参照）
SOLID_CLASS = 0xF0

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


def classify(terrain_id: int, attr: int | None) -> tuple[str, dict]:
    """(種別, 通行可否) を返す。

    ⚠⚠ **bool へ潰さない**（指示書 §15）。DQ2 には船がある。
      ★`ship` は **`None`（調べていない）**。`False`（通れない）ではない。
    """
    if attr is None:
        return "unknown", {"foot": None, "ship": None}
    if terrain_id in DYNAMIC:
        # ★開けると `OPENED_TERRAIN = 0x00` へ差し替わる。
        #   ⚠ 閉じている間は通れない、開けば通れる。**静的には決まらない**。
        return DYNAMIC[terrain_id], {"foot": None, "ship": None}
    if (attr & 0xF0) == SOLID_CLASS:
        return "blocked", {"foot": False, "ship": None}
    return "walk", {"foot": True, "ship": None}


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
                kind, passability = classify(terrain_id, attr)
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
            "rule": "terrain attribute high nibble == 0xF0 -> blocked",
            "disassembly": "$E1F9-$E1FF: LDY #$04 / LDA ($10),Y / AND #$F0 / STA $3C",
            "verified_against_observations": 1202,
            "counterexamples": 0,
            # ★ここが false の間は「相関」であって「因果」ではない
            "causal_site_located": False,
            "note": "移動処理のどこで 0xF を見ているかは未特定。"
                    "navigation_mismatch で実プレイと突き合わせて裏を取る",
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
    print("⚠ この表は**相関にもとづく見立て**です"
          "（confidence.causal_site_located = false）")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
