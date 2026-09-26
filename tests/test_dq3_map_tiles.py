"""地図データ → ゲーム内のタイル（RX3-0032 / 2026-08-31）。

## ★★ 何を固定するのか

    地図バッファ（$7400）の 1 バイト
      → & 0x1F で地形
      → tileset（$7200）+ 地形*4 の 4 バイト
      → ★**実機のネームテーブルと同じパターン番号**

⚠⚠ **絵を見比べません。** ★同じ形のデータどうしを升で突き合わせます
（`docs/50-playbook.md` の「絵を経由した突き合わせはノイズだらけ」）。

## ⚠ 窓が重なる升は外す

★会話や状態の窓は地図ではありません。⚠ 外さないと 74.8% にしかなりません
（★外した内訳は全部が窓の文字でした）。
"""

from __future__ import annotations

import pathlib

import pytest

from dq3_states import FIELD, pick

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★カートリッジ RAM は $6000 から
TILESET = 0x1200          #: ★$7200（⚠ 4 バイト × **64** タイル）
MAP_BUF = 0x1400          #: ★$7400（⚠ 1 升 1 バイト）
TERRAIN_MASK = 0x1F
#: ⚠⚠ **bit5 が立っている升は、地形にかかわらず索引 32 で描かれる**
#:
#:   ★2026-08-31 実測: 外れた 30 升は**全部** bit5 つきで、
#:     実機は必ず `FB FB FC FC`（＝索引 32）だった。
#:   ⚠ 索引 32 が何かは未確認（★暗闇／未踏か）。
DARK_BIT, DARK_INDEX = 0x20, 32
LOC_KIND, LOCAL = 0x2F, 1
#: ★洞窟（⚠ 以前は町のセーブだけで確かめていた → 洞窟で白黒が逆でも緑だった / RX3-0191）
CAVE = 5
MAP_W, MAP_H = 0x88, 0x89
HERO_X, HERO_Y = 0x30, 0x31


def _index(w, ram, raw):
    """★製品と同じ決まりで索引を出す（★勇者の升の層と比べる / `tile_art.index_of`）。"""
    from dq3.knowledge.tile_art import index_of

    hero = w[MAP_BUF + ram[HERO_Y] * ram[MAP_W] + ram[HERO_X]]
    return index_of(raw, hero)


def _local_states():
    """★ローカル地図（町・洞窟）のセーブ。⚠ 世界地図は別経路。"""
    from retroux.core.bgmap import savestate as ss

    got = []
    for path in pick(FIELD):
        ch = ss.load(path).chunks
        if ch["RAM"][LOC_KIND] in (LOCAL, CAVE) and "WRAM" in ch:
            got.append((path, ch))
    if not got:
        pytest.fail("⚠⚠ ローカル地図のセーブが 1 本もありません")
    return got


def _compare(ch):
    """★生成したパターン番号と、実機のネームテーブルを升で比べる。"""
    from dq3rom import ppu, viewport, window

    w, ram = ch["WRAM"], ch["RAM"]
    W, H = ram[MAP_W], ram[MAP_H]
    real = ppu.compose(ch["NTAR"], ppu.scroll_of(ch), ppu.mirroring_of(ch))
    covered = set()
    for box in window.find_windows(real):
        for yy in range(box.y, box.y + box.height + 1):
            for xx in range(box.x, box.x + box.width + 1):
                covered.add((xx, yy))
    vp = viewport.of_state(ch, W, H)
    hit = miss = 0
    for cy in range(H):
        for cx in range(W):
            at = vp.screen_at(cx, cy)
            if at is None:
                continue
            sx, sy = at
            if not (0 <= sx < 31 and 0 <= sy < 29):
                continue
            if any((sx + dx, sy + dy) in covered for dx in (0, 1) for dy in (0, 1)):
                continue
            raw = w[MAP_BUF + cy * W + cx]
            idx = _index(w, ram, raw)
            want = tuple(w[TILESET + idx * 4: TILESET + idx * 4 + 4])
            if len(want) < 4:
                continue
            got = (real[sy * 32 + sx], real[sy * 32 + sx + 1],
                   real[(sy + 1) * 32 + sx], real[(sy + 1) * 32 + sx + 1])
            if want == got:
                hit += 1
            else:
                miss += 1
    return hit, miss


def test_地図データから実機と同じタイルが出る():
    """★★ ⚠⚠ **これが今回いちばん大事な検査**。

    ⚠ 1 升でもずれていれば、★経路の読みがどこか違います。
    """
    total_hit = total = 0
    for path, ch in _local_states():
        hit, miss = _compare(ch)
        assert hit + miss > 20, "⚠ 比べた升が %d しかない（%s）" % (hit + miss, path.name)
        total_hit += hit
        total += hit + miss
        rate = hit / (hit + miss)
        assert rate == 1.0, (
            "⚠⚠ %s で %d/%d（%.1f%%）しか合わない" % (path.name, hit, hit + miss,
                                                  100 * rate))
    assert total_hit == total, (
        "⚠⚠ 全体で %d/%d（★経路を疑うこと）" % (total_hit, total))
    assert total > 300, "⚠ 比べた升が %d しかない（★材料不足）" % total


def test_窓を外さないと合わないことも確かめる():
    """⚠ 「外して合った」だけでは、★外し方が効いているか分からない。

    ★窓を**外さない**と落ちることを、ここで見ます（⚠ 検査の空回り防止）。
    """
    from dq3rom import ppu, viewport

    for path, ch in _local_states():
        w, ram = ch["WRAM"], ch["RAM"]
        W, H = ram[MAP_W], ram[MAP_H]
        real = ppu.compose(ch["NTAR"], ppu.scroll_of(ch), ppu.mirroring_of(ch))
        vp = viewport.of_state(ch, W, H)
        hit = miss = 0
        for cy in range(H):
            for cx in range(W):
                at = vp.screen_at(cx, cy)
                if at is None:
                    continue
                sx, sy = at
                if not (0 <= sx < 31 and 0 <= sy < 29):
                    continue
                raw = w[MAP_BUF + cy * W + cx]
                idx = _index(w, ram, raw)
                want = tuple(w[TILESET + idx * 4: TILESET + idx * 4 + 4])
                got = (real[sy * 32 + sx], real[sy * 32 + sx + 1],
                       real[(sy + 1) * 32 + sx], real[(sy + 1) * 32 + sx + 1])
                if want == got:
                    hit += 1
                else:
                    miss += 1
        if miss:
            return          # ★窓のぶんズレた ＝ 外し方が効いている
    pytest.fail("⚠⚠ 窓を外さなくても全部合ってしまう（★検査が空回り）")


def test_壁の2通りは別の地形番号だった():
    """★以前「同じ地形が 2 通りの見た目」と書いていたものの正体。

    ⚠ 自動つなぎではなく、**地形番号そのものが違う**。
    """
    for path, ch in _local_states():
        w = ch["WRAM"]
        a = tuple(w[TILESET + 11 * 4: TILESET + 11 * 4 + 4])
        b = tuple(w[TILESET + 27 * 4: TILESET + 27 * 4 + 4])
        if a == b:
            continue
        assert a[0] == b[0] and a[1] == b[1], (
            "⚠ 上半分が違う（%s）: %s / %s" % (path.name, a, b))
        assert a[2] != b[2], "⚠ 下半分が同じ（★2 通りでない）"
        return
    pytest.skip("⚠ 壁の 2 通りが出ているセーブが無い")


def test_勇者と層が違う升は索引32で描かれる():
    """⚠⚠ **これが最後の 1 升を埋めた規則**（★2026-08-31 / ★2026-09-12 に訂正）。

    ★外れていた 30 升は**全部** bit5 つきで、実機は必ず索引 32 だった（2026-08-31 / ⚠ 町のセーブだけ）。
    ⚠⚠ 2026-09-12（RX3-0191）: 本当の決まりは「升の層（& 0xE0）が**勇者の升の層**と違えば索引 32」。
      ★町では勇者が層 0 なので bit5 と一致していた。⚠ 洞窟（勇者が層 0x20）では白黒が逆になっていた。
      → ★洞窟のセーブも入れ、製品と同じ `_index` で確かめる。
    """
    from dq3rom import ppu, viewport, window

    seen = 0
    for path, ch in _local_states():
        w, ram = ch["WRAM"], ch["RAM"]
        W, H = ram[MAP_W], ram[MAP_H]
        real = ppu.compose(ch["NTAR"], ppu.scroll_of(ch), ppu.mirroring_of(ch))
        covered = set()
        for box in window.find_windows(real):
            for yy in range(box.y, box.y + box.height + 1):
                for xx in range(box.x, box.x + box.width + 1):
                    covered.add((xx, yy))
        vp = viewport.of_state(ch, W, H)
        dark = tuple(w[TILESET + DARK_INDEX * 4: TILESET + DARK_INDEX * 4 + 4])
        for cy in range(H):
            for cx in range(W):
                raw = w[MAP_BUF + cy * W + cx]
                if _index(w, ram, raw) != DARK_INDEX:
                    continue
                at = vp.screen_at(cx, cy)
                if at is None:
                    continue
                sx, sy = at
                if not (0 <= sx < 31 and 0 <= sy < 29):
                    continue
                if any((sx + dx, sy + dy) in covered
                       for dx in (0, 1) for dy in (0, 1)):
                    continue
                got = (real[sy * 32 + sx], real[sy * 32 + sx + 1],
                       real[(sy + 1) * 32 + sx], real[(sy + 1) * 32 + sx + 1])
                assert got == dark, (
                    "⚠⚠ bit5 の升なのに索引 32 で描かれていない（%s / %d,%d）: "
                    "%s ではなく %s" % (path.name, cx, cy, dark, got))
                seen += 1
    assert seen > 10, "⚠⚠ bit5 の升が %d しか無い（★検査が空回り）" % seen


#: ★★ 升ごとのパレット組（⚠ `$7300`。★2026-08-31 実測）
PALETTE_OFF = 0x1300


def test_パレット組も実機と一致する():
    """★★ ⚠⚠ **色の根拠**（RX3-0032 / 2026-08-31）。

    ⚠ WRAM 8192 バイトを総当たりして、★`$7300` **1 か所だけ**が
    実機の属性表と合いました（⚠ 1 バイト 1 索引）。

    ★634 升すべてで一致します。
    """
    from dq3rom import ppu, viewport, window

    total_hit = total = 0
    for path, ch in _local_states():
        w, ram = ch["WRAM"], ch["RAM"]
        W, H = ram[MAP_W], ram[MAP_H]
        sc = ppu.scroll_of(ch)
        mir = ppu.mirroring_of(ch)
        real = ppu.compose(ch["NTAR"], sc, mir)
        attr = ppu.compose_attributes(ch["NTAR"], sc, mir)
        covered = set()
        for box in window.find_windows(real):
            for yy in range(box.y, box.y + box.height + 1):
                for xx in range(box.x, box.x + box.width + 1):
                    covered.add((xx, yy))
        vp = viewport.of_state(ch, W, H)
        for cy in range(H):
            for cx in range(W):
                at = vp.screen_at(cx, cy)
                if at is None:
                    continue
                sx, sy = at
                if not (0 <= sx < 31 and 0 <= sy < 29):
                    continue
                if any((sx + dx, sy + dy) in covered
                       for dx in (0, 1) for dy in (0, 1)):
                    continue
                raw = w[MAP_BUF + cy * W + cx]
                idx = _index(w, ram, raw)
                total += 1
                if w[PALETTE_OFF + idx] == attr[sy * 32 + sx]:
                    total_hit += 1
    assert total > 300, "⚠ 比べた升が %d しかない" % total
    assert total_hit == total, (
        "⚠⚠ パレット組が %d/%d しか合わない（★$7300 を疑うこと）"
        % (total_hit, total))


def test_パレット組は1つに決まる():
    """⚠ 同じ索引が 2 つの組で描かれていたら、★表 1 本では足りない。"""
    import collections

    from dq3rom import ppu, viewport, window

    seen = collections.defaultdict(set)
    for path, ch in _local_states():
        w, ram = ch["WRAM"], ch["RAM"]
        W, H = ram[MAP_W], ram[MAP_H]
        sc = ppu.scroll_of(ch)
        mir = ppu.mirroring_of(ch)
        real = ppu.compose(ch["NTAR"], sc, mir)
        attr = ppu.compose_attributes(ch["NTAR"], sc, mir)
        covered = set()
        for box in window.find_windows(real):
            for yy in range(box.y, box.y + box.height + 1):
                for xx in range(box.x, box.x + box.width + 1):
                    covered.add((xx, yy))
        vp = viewport.of_state(ch, W, H)
        for cy in range(H):
            for cx in range(W):
                at = vp.screen_at(cx, cy)
                if at is None:
                    continue
                sx, sy = at
                if not (0 <= sx < 31 and 0 <= sy < 29):
                    continue
                if any((sx + dx, sy + dy) in covered
                       for dx in (0, 1) for dy in (0, 1)):
                    continue
                raw = w[MAP_BUF + cy * W + cx]
                idx = _index(w, ram, raw)
                # ⚠ パレット組の表（$7300）は**地図ごと**（★洞窟は町と tileset が違う / RX3-0191 で洞窟を足した）
                seen[(path.name, idx)].add(attr[sy * 32 + sx])
    assert seen, "⚠ 1 つも集まっていない"
    bad = {i: sorted(g) for i, g in seen.items() if len(g) > 1}
    assert not bad, "⚠⚠ 索引が 2 つの組で描かれている: %s" % bad
