"""モンスターの絵の置き場は、作り方が変わったら作り直す（RX3-0223 / 2026-09-12）。

⚠⚠ 前の `ensure()` は「ファイルが在れば作らない」だけでした。
★`monster_gfx` を直しても、**半分に切れた古い絵が置き場に残り続けます**。

```text
置き場の art_version.txt ≠ monster_gfx.ART_VERSION
  → ★全部を作り直し、中身が変わったものだけを置き換える
  ⚠ 中身が同じものは触らない（★動いている画面がこの PNG を読んでいる）
```

⚠ 本物の `work/dq3-monster-art` には書きません（★`tmp_path` だけ）。
"""

from __future__ import annotations

import os

import pytest

from dq3.knowledge import monster_art
from dq3rom import monster_gfx as mg
from dq3rom import profile as dq3


def _rom_ready() -> bool:
    try:
        dq3.load_and_identify(monster_art.ROM_PATH)
    except Exception:
        return False
    return True


needs_rom = pytest.mark.skipif(
    not _rom_ready(),
    reason=f"DQ3 Rev 0A の ROM が読めない（{monster_art.ROM_PATH}）")

#: ⚠ 触っていないことを確かめる印（★作り直しの前に戻しておく古い時刻）
OLD_MTIME = 1_000_000_000


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("dq3-monster-art")
    made = monster_art.ensure(art_dir=base)
    assert made == 139, monster_art.last_error
    return base


@needs_rom
def test_作ったら今の作り方の印を付ける(built):
    assert monster_art.stamp_of(built) == str(mg.ART_VERSION)
    assert (built / monster_art.STAMP_NAME).read_bytes() == \
        b"%d\n" % mg.ART_VERSION
    assert monster_art.ensure(art_dir=built) == 0, "⚠ 印が合っているのに作り直した"


@needs_rom
def test_印が古い置き場は中身が変わった絵だけ置き換える(built):
    """★★ ⚠⚠ ここが本題: 古い半分の絵が**自動で**入れ替わること。 ★★"""
    good = (built / "038.png").read_bytes()
    (built / "038.png").write_bytes(b"old half picture")
    os.utime(built / "000.png", (OLD_MTIME, OLD_MTIME))
    (built / monster_art.STAMP_NAME).unlink()

    assert monster_art.ensure(art_dir=built) == 1, monster_art.last_error
    assert (built / "038.png").read_bytes() == good, "⚠⚠ 古い絵が残った"
    assert os.stat(built / "000.png").st_mtime == OLD_MTIME, (
        "⚠ 中身が同じ絵まで書き直した（★読んでいる画面の邪魔になる）")
    assert monster_art.stamp_of(built) == str(mg.ART_VERSION)
    assert list(built.glob("*.tmp")) == [], "⚠ 一時ファイルが残った"


@needs_rom
def test_印が別の版でも作り直す(built):
    """⚠ 印の中身まで見る（★「在るか」だけ見ると次の版で素通りする）。"""
    (built / "014.png").write_bytes(b"stale")
    (built / monster_art.STAMP_NAME).write_text("1\n", encoding="utf-8")

    assert monster_art.ensure(art_dir=built) == 1, monster_art.last_error
    assert (built / "014.png").read_bytes().startswith(b"\x89PNG")
    assert monster_art.stamp_of(built) == str(mg.ART_VERSION)


def test_ROMが無ければ印を付けない(tmp_path):
    """⚠ 作れなかったのに「今の版」の印を付けない（★次の起動で作り直せなくなる）。"""
    got = monster_art.ensure(art_dir=tmp_path, rom_path=tmp_path / "none.nes")
    assert got == 0
    assert monster_art.last_error and "ROM" in monster_art.last_error
    assert monster_art.stamp_of(tmp_path) is None
