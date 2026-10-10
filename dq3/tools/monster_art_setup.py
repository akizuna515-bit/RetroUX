"""モンスターの絵を初回起動で作る（RX3-0431 / 2026-09-25）。

★★ **公開版に絵は同梱しません**（ROM から復元した絵＝ゲームコンテンツそのもの）。 ★★

```text
利用者の DQ3 ROM
        ↓
初回起動（start-dq3.ps1）
        ↓
monster_art.ensure()
        ↓
work/cache/dq3-monster-art/*.png
        ↓
図鑑・戦闘画面
```

⚠⚠ **なぜ要るのか**（2026-09-25 / RX3-0431）

★`dq3/knowledge/monster_art.ensure()` は前からありましたが、
⚠ **どこからも呼んでいませんでした**（使われていたのは `path_of()` だけ）。
→ clone しただけの人は、図鑑と戦闘画面で「絵がありません」のままになります。
★DQ2 は同じ問題を RX-0086 で解決済みなので、**同じ形**にします。

## ⚠ 守ること

- **失敗しても起動を止めません**（★絵は表示だけの機能）。`main()` は常に 0 を返します。
- ★2 回目以降は数 ms で抜けます（`ensure()` が版の印と中身で判断します）。
- ⚠ 途中で失敗したら印を付けないので、★次の起動でもう一度作り直します。
"""
from __future__ import annotations

from dq3.knowledge import monster_art

#: ★何をするか（⚠ 純ロジックにして検査できる形にする / DQ2 RX-0086 と同じ）
SKIP, NO_ROM, INSTALL = "skip", "no-rom", "install"


def plan(rom_exists: bool, art_count: int, stamp_ok: bool) -> str:
    """★何をするかだけ決める（⚠ ファイルも ROM も触りません）。

    @param rom_exists  利用者の ROM があるか
    @param art_count   置き場にある PNG の枚数
    @param stamp_ok    ★版の印が今の作り方と一致しているか（⚠ 違えば作り直し）
    """
    if art_count > 0 and stamp_ok:
        return SKIP
    if not rom_exists:
        return NO_ROM
    return INSTALL


def _count(art_dir) -> int:
    return len(list(art_dir.glob("*.png"))) if art_dir.is_dir() else 0


def main() -> int:
    """★起動スクリプトから呼ぶ。⚠ **常に 0**（起動を止めない）。"""
    art_dir = monster_art.ART_DIR
    rom = monster_art.ROM_PATH

    try:
        from dq3rom import monster_gfx as mg
        want = str(mg.ART_VERSION)
    except ImportError:
        # ⚠ 道具が読めないなら ensure() も同じ所で止まる。★印は「違う」扱いにする
        want = None

    count = _count(art_dir)
    stamp_ok = want is not None and monster_art.stamp_of(art_dir) == want
    what = plan(rom.exists(), count, stamp_ok)

    if what == SKIP:
        print("モンスターの絵: そろっています（%d 枚）" % count)
        return 0
    if what == NO_ROM:
        print("モンスターの絵: ROM が見つからないため作れません（%s）" % rom)
        print("  ★ROM を置けば、次の起動で自動的に作ります")
        return 0

    if count:
        print("モンスターの絵: 作り方が変わったので作り直します（%d 枚あり）..." % count)
    else:
        print("モンスターの絵: 初回なので ROM から作ります...")
    made = monster_art.ensure()
    if monster_art.last_error:
        # ⚠ 絵は表示だけの機能。★止めない（次の起動でもう一度試します）
        print("モンスターの絵: 作れませんでした（起動は続けます）: %s"
              % monster_art.last_error)
        return 0
    print("モンスターの絵: 作りました（%d 枚 / 置き場 %d 枚）" % (made, _count(art_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
