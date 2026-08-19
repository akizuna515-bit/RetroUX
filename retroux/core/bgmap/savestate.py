"""FCEUX のセーブステートを読む（2026-08-02 / Stop 1'）。

★★ **これがあると、FCEUX を起こさずに実機の値を確かめられます。** ★★

  ⚠ これまで「RAM の実際の値」を見るには FCEUX を1つ起こす必要があり、
    遊んでいる最中は測れませんでした。★セーブステートを直接読めば、
    **遊びを止めずに**確かめられます。

## 形式（2026-08-02 に実測）

```
先頭16バイト: "FCSX" + 展開後の大きさ など
17バイト目から: zlib（`zlib.decompress(raw[16:])`）
展開後: [名前4バイト][大きさ4バイト(LE)][中身] の並び
```

主なチャンク:

| 名前 | 大きさ | 中身 |
| --- | --- | --- |
| `RAM` | 2048 | ★CPU の RAM（`$0000`-`$07FF`） |
| `NTAR` | 2048 | ★ネームテーブル（`$2000` と `$2400`） |
| `PRAM` | 32 | パレット（`$3F00`-） |
| `SPRA` | 256 | ★OAM（スプライト。主人公の画面位置） |
| `CHRR` | 8192 | ★CHR-RAM |

⚠ `savestate.persist()` は FCEUX をハングさせるので使えませんが、
  **人が `File > Save State` で保存したものを読む**のは安全です。
"""

from __future__ import annotations

import dataclasses
import pathlib
import zlib

#: zlib のデータが始まる位置（先頭は "FCSX" と大きさ）
COMPRESSED_FROM = 16
#: 署名
MAGIC = b"FCS"


class NotASaveState(ValueError):
    """⚠ セーブステートではない。★推測で読み進めない。"""


@dataclasses.dataclass(frozen=True)
class SaveState:
    """セーブステート1つぶん。"""

    path: pathlib.Path
    chunks: dict

    @property
    def ram(self) -> bytes:
        return self.chunks.get("RAM", b"")

    @property
    def nametable(self) -> bytes:
        return self.chunks.get("NTAR", b"")

    @property
    def palette(self) -> bytes:
        return self.chunks.get("PRAM", b"")

    @property
    def oam(self) -> bytes:
        return self.chunks.get("SPRA", b"")

    @property
    def chr_data(self) -> bytes:
        return self.chunks.get("CHRR", b"")

    def byte(self, addr: int) -> int | None:
        """RAM の1バイト。⚠ 読めなければ None（0 と混ぜない）。"""
        ram = self.ram
        return ram[addr] if 0 <= addr < len(ram) else None

    def word(self, addr: int) -> int | None:
        """RAM の2バイト（下位・上位の順）。⚠ 読めなければ None。"""
        lo, hi = self.byte(addr), self.byte(addr + 1)
        if lo is None or hi is None:
            return None
        return lo | (hi << 8)

    def sprite(self, index: int):
        """OAM の1件を `(x, y, tile, attr)` で返す。⚠ 無ければ None。"""
        oam = self.oam
        base = index * 4
        if base + 4 > len(oam):
            return None
        return (oam[base + 3], oam[base], oam[base + 1], oam[base + 2])

    def hero_screen_cell(self):
        """主人公が画面のどの 16px マスに居るか。⚠ 分からなければ None。

        ★OAM の先頭が主人公の左上（実測 / 2026-08-02）。

        ⚠⚠ **これで「画面中央 (8,7)」を確かめようとして、逆に外しました。**
          スプライトの左上は (128,107) で、素直に割ると (8, 6) になります。
          ★ですが7件のセーブステートで突き合わせると **(8,7) のほうが
            合いました**（矛盾なし 4件 vs 2件）。
          ★キャラの絵は背景のマスより少し上に描かれます。
            **画面上の見た目からマスを決めない**こと。
        """
        s = self.sprite(0)
        if s is None or s[1] >= 0xEF:
            return None
        return (s[0] // 16, s[1] // 16)


def load(path) -> SaveState:
    """セーブステートを読む。⚠ 形式が違えば `NotASaveState`。"""
    path = pathlib.Path(path)
    raw = path.read_bytes()
    if raw[:3] != MAGIC:
        raise NotASaveState(f"FCEUX のセーブステートではありません: {path}")
    try:
        body = zlib.decompress(raw[COMPRESSED_FROM:])
    except zlib.error as exc:            # noqa: PERF203
        raise NotASaveState(f"展開できません: {path}") from exc

    chunks: dict = {}
    pos = 0
    while pos + 8 <= len(body):
        name = body[pos:pos + 4]
        size = int.from_bytes(body[pos + 4:pos + 8], "little")
        printable = all(32 <= c < 127 or c == 0 for c in name)
        if not printable or name[0] == 0 or size <= 0 or \
                pos + 8 + size > len(body):
            # ⚠ 途中で読めなくなっても、そこまでは使う。
            #   ★「全部読めないと何も返さない」は不便すぎる
            pos += 1
            continue
        chunks[name.rstrip(b"\x00").decode("ascii")] = body[pos + 8:pos + 8 + size]
        pos += 8 + size
    if "RAM" not in chunks:
        raise NotASaveState(f"RAM が見つかりません: {path}")
    return SaveState(path=path, chunks=chunks)
