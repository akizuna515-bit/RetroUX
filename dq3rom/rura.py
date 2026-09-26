"""ルーラの行き先（RX3-0013 ③ / 2026-08-31）。

★ゲームの中で「map 番号」と「地名」が**同時に並ぶ唯一の場所**。
⚠ だから地名を別データに起こさなくても、一覧を 1 度見れば結び付けられる。

## 仕組み（★完全逆アセンブルから）

```text
_b0_s49_set_returnable_locations_bit   （JP: PRG 0x001CDA / $9CDA）
  LDA rura_points,X / CMP $8B     ★いま居る map を表から探す
  BEQ  → INX / SEC / ROL ×3 / DEX ★見つかった索引 X の bit を立てる
  ORA  $0750+人*3 の 3 バイトへ    ⚠ **人ごと**に持つ
```

⚠ 地名の**文字列はここには無い**。★実行時に画面から読む（`docs/00-project-policy.md`）。
"""
from __future__ import annotations

from .profile import Identified


class RuraError(ValueError):
    pass


def read_points(ident: Identified) -> list[int]:
    """一覧の順に並んだ map 番号。"""
    t = ident.table("rura_points")
    n = int(t["entries"])
    start = ident.table_prg("rura_points")
    out = list(ident.rom.prg[start:start + n])
    if len(out) != n or len(set(out)) != n:
        raise RuraError(f"ルーラ表が壊れています: {out}")
    return out


def _cfg(prof) -> dict:
    rt = prof.data.get("runtime") or {}
    if "rura" not in rt:
        raise RuraError("profile に runtime.rura がありません")
    return rt["rura"]


def known_indices(ram: bytes, prof, player: int) -> list[int]:
    """その人が飛べる行き先の**索引**（★`read_points` と同じ並び）。"""
    c = _cfg(prof)
    players, stride, bits = int(c["players"]), int(c["stride"]), int(c["bits"])
    if not 0 <= player < players:
        raise RuraError(f"人の番号が範囲外です: {player}（0..{players - 1}）")
    base = int(str(c["returnable"]), 16) + player * stride
    if base + stride > len(ram):
        raise RuraError(f"RAM が短すぎます: {len(ram)} バイト")
    word = int.from_bytes(ram[base:base + stride], "little")
    return [i for i in range(bits) if word >> i & 1]


def _to_maps(points: list[int], idx: list[int]) -> list[int]:
    """⚠ 表からはみ出す索引は**黙って捨てない**（★並びのずれの目印）。"""
    over = [i for i in idx if i >= len(points)]
    if over:
        raise RuraError(f"表の外を指す索引があります: {over}（表は {len(points)} 件）")
    return [points[i] for i in idx]


def known_maps(ram: bytes, prof, points: list[int], player: int) -> list[int]:
    """その人が飛べる行き先の map 番号。"""
    return _to_maps(points, known_indices(ram, prof, player))


def party_known(ram: bytes, prof, points: list[int]) -> list[int]:
    """★誰か 1 人でも飛べる行き先（⚠ 死んでいた人は落ちるので和を取る）。"""
    c = _cfg(prof)
    seen: set[int] = set()
    for p in range(int(c["players"])):
        seen |= set(known_indices(ram, prof, p))
    return _to_maps(points, sorted(seen))
