"""モンスターの絵の置き場（RX3-0036 / 2026-09-01）。

★★ **画面の持ち物にしません**（指示書 §22）。 ★★

```text
Monster Image Repository
        ├─ Monster Panel
        └─ EnemyBook / Monster Book
```

⚠ 絵の作り方（ROM の展開）は `dq3rom/monster_gfx.py` にあります。
★ここは「`monster_id` → ファイル」だけを引き受けます。

## ⚠ 同梱しません

★ROM から起こしたものなので `work/dq3-monster-art/` に置きます
（⚠ `data/` ではありません）。無ければ**作ります**（1 度だけ）。
"""
from __future__ import annotations

import os
import pathlib

from dq3 import paths as P3

#: ★★ 置き場（⚠ Git 管理外 / **derived**）★★
#
#   ⚠ 2026-10-01（`RX3-0472`）まで `ROOT / "work" / …`（= program 側）でした。
#     ★配布 Runtime では `program_root == write_root` なので**道は変わりません**が、
#     ⚠⚠ 検査が `RETROUX_WRITE_ROOT` を差し替えても**追いついていませんでした**
#       （★本物の `work/` に 139 枚を書きうる形でした）。
#   ★`lazy_work` なので、⚠ 使う瞬間に書き先を引き直します（RX3-0342）。
ART_DIR = P3.lazy_work("dq3-monster-art")
#: ⚠ 解決は `dq3/paths.py::rom()` の 1 本（RX3-0467）。★任意の場所を指定できます。
ROM_PATH = P3.lazy_rom()
#: ★置き場の絵が**どの作り方で**作られたか（RX3-0223）
#:
#:   ⚠ 前は「ファイルが在れば作らない」だけでした。
#:   ★作り方を直しても、半分に切れた古い絵が**残り続けます**。
#:   → 中身が `monster_gfx.ART_VERSION` と違えば、作り直します。
STAMP_NAME = "art_version.txt"

#: ⚠ 作れなかった理由（★黙って None を返さないため）
last_error: str | None = None


def path_of(monster_id, art_dir=None) -> pathlib.Path | None:
    """★その敵の絵。⚠ 無ければ `None`（★画面は「絵なし」と出す）。"""
    if monster_id is None:
        return None
    base = pathlib.Path(art_dir) if art_dir else ART_DIR
    got = base / ("%03d.png" % int(monster_id))
    return got if got.exists() else None


def stamp_of(art_dir=None) -> str | None:
    """★置き場の絵を作ったときの `ART_VERSION`（⚠ 無ければ None ＝ 古い作り方）。"""
    base = pathlib.Path(art_dir) if art_dir else ART_DIR
    try:
        return (base / STAMP_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_one(mg, write_png, ident, mid: int, out: pathlib.Path) -> bool:
    """★1 枚作る。戻り値は**書き換えたか**。

    ⚠ 動いている画面がこの PNG を読みます。
    ★中身が同じなら**触りません**。違うときも、隣に書いてから
      **1 回で置き換えます**（⚠ 書きかけの PNG を読ませない）。
    """
    got = mg.build(ident, mid)
    pal = (got.bg_palettes or got.sprite_palettes
           or ((0x30, 0x15, 0x1C),))[0]
    px, w, h = mg.to_pixels(got, pal)
    tmp = out.with_name(out.name + ".tmp")
    write_png(tmp, px, w, h)
    try:
        if out.exists() and out.read_bytes() == tmp.read_bytes():
            return False
        os.replace(tmp, out)
        return True
    finally:
        if tmp.exists():
            tmp.unlink()


def ensure(art_dir=None, rom_path=None) -> int:
    """★絵が無ければ ROM から作る。戻り値は**作った（書き換えた）枚数**。

    ★置き場の `STAMP_NAME` が今の `ART_VERSION` と違えば、**全部を作り直し**、
      中身が変わったものだけを置き換えます（RX3-0223）。

    ⚠ ROM が無い環境では 0 を返し、`last_error` に理由を残します
    （★落としません / 黙りません）。
    """
    global last_error

    base = pathlib.Path(art_dir) if art_dir else ART_DIR
    rom = pathlib.Path(rom_path) if rom_path else ROM_PATH
    try:
        from dq3rom import monster_gfx as mg
        from dq3rom import profile as dq3
        from dq3rom.render import write_png
    except ImportError as exc:
        last_error = "⚠ 絵を作る道具が読めません: %s" % exc
        return 0
    if not rom.exists():
        last_error = "⚠ ROM がありません: %s" % rom
        return 0
    try:
        ident = dq3.load_and_identify(rom)
        total = int(ident.table("monster_graphics")["entries"])
    except Exception as exc:                            # noqa: BLE001
        last_error = "⚠ ROM を読めません: %s" % exc
        return 0
    base.mkdir(parents=True, exist_ok=True)
    stale = stamp_of(base) != str(mg.ART_VERSION)
    made = 0
    failed = False
    for mid in range(total):
        out = base / ("%03d.png" % mid)
        if out.exists() and not stale:
            continue
        try:
            made += _write_one(mg, write_png, ident, mid, out)
        except Exception as exc:                        # noqa: BLE001
            failed = True
            last_error = "⚠ id%d を作れません: %s" % (mid, exc)
    if failed:
        # ⚠ 印を付けない（★次の ensure() でもう一度作り直す）
        return made
    if stale:
        (base / STAMP_NAME).write_text(
            "%s\n" % mg.ART_VERSION, encoding="utf-8", newline="")
    last_error = None
    return made
