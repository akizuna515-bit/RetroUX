"""窓の色（`$06E0`）の決まり（RX3-0225 → RX3-0412 / 2026-09-23）。

★Auto を人へ返す合図は、ゲーム自身が決めた窓の色です
（`$27` オレンジ / `$2A` 緑 / `dq3/phase0/battle_speed.lua`）。
⚠ RetroUX は実行時に色を**計算しません**（★1 バイト読むだけ）。

## ⚠⚠ なぜ検査から出したか

★ここは長らく `tests/test_dq3_window_color.py` の中だけにありました。
⚠ ところが `scripts/dq3_make_fixture.py` が **HP を書き換えても色を直さない**ため、
派生 savestate が**自己矛盾**しました（2026-09-23 / `survival_wait_heal` ほか 1 本）:

```text
⚠ p2 HP 68/378  → 68 < 378/4 = 94 なので緑（$2A）のはず
⚠ しかし $06E0 は $21 のまま（★元のセーブの値）
```

→ ★決まりは**1 か所**に置き、⚠ 検査と fixture 作りの**両方が同じものを使います**
（★2 か所に書くと片方だけ直る / この repo が何度も踏んだ形）。

## ★決まり（⚠ ROM: JP bank 13 `$959B-$961C`）

```text
順  条件（4 枠のうち 1 人でも）                                      値
1   死んでいる（$073C+2i bit7 XOR $073D+2i bit7）                     $27 オレンジ
2   生きている人の HP < floor(最大 HP / 4)（16 bit）                  $2A 緑
3   夜（$06DF >= $78）かつ $60B7 bit5 が立っていない                  $21 薄い青
4   それ以外                                                          $30 白
⚠   最後に $6A58 == 0 なら $30（★意味は未確認 / bank 13 $9610）
```

⚠ 毒（`$073D` bit5）では変わりません。⚠ 赤はありません。
"""
from __future__ import annotations

import json
import pathlib
from typing import Callable

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"

#: ⚠ 意味は未確認（★ROM の分岐だけ: 0 なら白に倒す / bank 13 `$9610`）
GATE = 0x6A58

#: ★`$06E0` の写し（⚠ ROM は**両方**へ書く）
MIRROR = 0x03E8


def _hex(value) -> int:
    """★`"0x06E0"` でも `1760` でも受ける（⚠ 10 進を 16 進で読む事故を防ぐ）。"""
    return value if isinstance(value, int) else int(str(value), 16)


def runtime(profile_path: pathlib.Path | None = None) -> dict:
    path = profile_path or PROFILE
    return json.loads(path.read_text(encoding="utf-8"))["runtime"]


def window_color(read: Callable[[int], int], rt: dict) -> int:
    """★ROM の決まりを上から順に。`read(addr) -> int`（⚠ 内蔵 RAM も WRAM も）。"""
    party, win, flags = rt["party"], rt["window_color"], rt["in_battle"]
    status, size = _hex(party["status"]), int(party.get("status_size", 2))
    hp, hp_max = _hex(party["hp_current"]), _hex(party["hp_max"])
    entry, slots = int(party.get("entry_size", 2)), int(party.get("slots", 4))

    def w16(base: int, i: int) -> int:
        return read(base + i * entry) + read(base + i * entry + 1) * 256

    lo = [read(status + i * size) for i in range(slots)]
    hi = [read(status + i * size + 1) for i in range(slots)]
    if any((a ^ b) & 0x80 for a, b in zip(lo, hi)):
        color = _hex(win["dead"])
    elif any(lo[i] & hi[i] & 0x80 and w16(hp, i) < w16(hp_max, i) // 4 for i in range(slots)):
        color = _hex(win["low_hp"])
    elif (not read(_hex(flags["flags"])) & _hex(flags["flag_bit"])
          and read(_hex(win["time"])) >= _hex(win["night_from"])):
        color = _hex(win["night"])
    else:
        color = _hex(win["normal"])
    if read(GATE) == 0:
        color = _hex(win["normal"])
    return color


def reader(ram, wram=b"") -> Callable[[int], int]:
    """★セーブの塊から 1 バイト読む（⚠ 無い番地は 0 にしない = 白に化ける）。"""
    def read(addr: int) -> int:
        if 0 <= addr < len(ram):
            return ram[addr]
        if 0x6000 <= addr < 0x6000 + len(wram):
            return wram[addr - 0x6000]
        raise AssertionError("⚠ セーブに無い番地 $%04X（★0 と見なすと白に化ける）" % addr)
    return read


def apply(ram: bytearray, wram=b"", profile_path: pathlib.Path | None = None) -> int:
    """★いまの HP・状態から色を計算し、`$06E0` と写しの `$03E8` へ書く。

    ⚠⚠ **`ram` を書き換えます**（★派生 savestate を作るときだけ使ってください）。
    戻り値: 書いた色。
    """
    rt = runtime(profile_path)
    color = window_color(reader(ram, wram), rt)
    ram[_hex(rt["window_color"]["address"])] = color
    ram[MIRROR] = color
    return color
