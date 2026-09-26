"""宝箱を取ったかの記録（RX3-0012 / 2026-09-07）。

## ⚠⚠ ビットの並びが**逆**でした

★番地と通し番号は 2026-08-25 に ROM のコードで確定していました。
⚠ ところが「ビット = 番号 & 7」と控えてあり、★**これが誤り**でした。

bank12 の読み出しは `ASL` を (番号 & 7) + 1 回まわして、桁上がりに乗せます。

```text
$9DCE  LSR A x3 → X      ; ★バイト番号 = 番号 >> 3
$9DD3  AND #$07 → Y      ; ★Y = 番号 & 7
$9DD8  LDA $608E,X
$9DDB  ASL A             ; ⚠ 左シフト（★bit7 が桁上がりへ）
$9DDC  DEY
$9DDD  BPL $9DDB         ; ★(Y + 1) 回まわる
$9DE1  RTS               ; ★桁上がり = もとの bit (7 - Y)
```

★立てる側（`$9DE2`）も `SEC / LDA #$00 / ROR` で `$80 >> Y` を作るので、同じ並びです。

    宝箱 n の在り処 = ($608E + (n >> 3)) の bit (7 - (n & 7))     ← ★MSB から

⚠⚠ **同じ ROM の中で、並びが 2 通りあります。**
★フラグ（`dq3rom/flags.py` / bank13 `$BF94`）は表 `01 02 04 08 10 20 40 80` で
**LSB から**です。⚠ 片方を見て他方を決めないでください。

## ★裏取り（2026-09-07 / ⚠ ここが 1 年ぶんの宿題でした）

⚠ 2026-08-25 の時点では、セーブの配列が**全部 0** で確かめられませんでした
（★「0 件は通っていないだけ」の形）。⚠ その後、依頼者が遊んだセーブに値が入りました。

```text
DQ3_J.fc6      ★いま map 45 の中（kind=5）  → 取った宝箱 17, 18      （map 45 は 16..18）
DQ3_J.fc0/fc1  ★map 45 の外                → 取った宝箱 16, 17, 18  （map 45 を全部）
⚠ ほかの宝箱は 1 つも取られていない
```

★map 45 は依頼者の記録で「ナジミの塔への洞窟」（`CONFIRMED`）です。
⚠⚠ **LSB から読むと、同じバイトが map 48 と 52 の宝箱**になります。
★どちらも依頼者が**行っていない場所**で、⚠ 行った map（0 / 45 / 70 / 159）の
ビットは 1 つも立ちません。→ ★MSB から読むほうだけが辻褄が合います。

```text
★合う道が 4 本そろった
  ① ROM のコード（ASL / ROR の回数）
  ② map の区切りにぴったり乗る（16..18 = map 45 の 3 個ちょうど）
  ③ ⚠ 取りかけの状態（fc6 = 3 個中 2 個）が、**その洞窟の中に居るセーブ**
  ④ 依頼者の場所の記録（map 45 = CONFIRMED / map 48・52 は未訪問）
```

## ★★ 2026-09-16: 配列は 25 バイトではなく **26 バイト**でした（RX3-0012）

⚠ ここには長いあいだ「193 ビット = 25 バイト」とだけ書いてありました。
★実際の配列は `$608E`..`$60A7` の 26 バイトで、**最後の 1 バイトが余りではありません**。

```text
0..192    ★個数表の宝箱（`dq3rom/chests.py`）
193..199  ⚠ どこからも使われていない
200..207  ★「しらべる」の隠し道具 8 件（`dq3rom/search_spots.py` / bank12 $9BD5）
$60A8     ⚠ 配列ではない。★「いま見ている通し番号」の置き場
```

⚠⚠ つまり `taken()` だけを見ていると、**隠し道具 8 件を取りこぼします**。
★`hidden_taken()` を併せて読んでください。

## ⚠ ここでは何も断定しません

★取った「個数」は言えますが、⚠ **どの宝箱に何が入っていたか**は
`dq3rom/chests.py` の担当です（★中身の表は同梱しません）。
"""
from __future__ import annotations

#: ★WRAM の中での位置（⚠ `$6000` を 0 とした添字）
BASE = 0x008E
#: ★宝箱の総数（⚠ `chests.read_tables` の合計と一致すること。★検査で見張る）
COUNT = 193
#: ★バイト数（⚠ 193 ビット → 25 バイト）
NBYTES = (COUNT + 7) // 8

#: ★配列そのものは **26 バイト**（⚠ 2026-09-16 / `RX3-0012`）。
#  ⚠⚠ 193 ビットで終わりではありません。26 バイト目（`$60A7`）に
#  「しらべる」の隠し道具 8 件が入ります（`dq3rom/search_spots.py`）。
ARRAY_BYTES = 26
#: ★配列に入る通し番号の上限（26 バイト = 208 ビット）
LIMIT = ARRAY_BYTES * 8
#: ★隠し道具の通し番号（⚠ 193..199 は**どこからも使われていない**）
HIDDEN = range(200, LIMIT)
#: ⚠ 配列のすぐ後ろ。★「いま見ている通し番号」の置き場（bank12 `$9DC7` / `$9BDB`）
CURSOR = 0x00A8


def slot_of(serial: int) -> tuple[int, int]:
    """★通し番号 → `(WRAM の添字, ビットのマスク)`。⚠ 配列ぜんぶ（0..207）。

    ⚠ 宝箱として数えてよいのは 0..192 だけです。★隠し道具（200..207）も
    **同じ配列の同じ並び**なので、計算はここ 1 か所にまとめます。
    """
    if not 0 <= serial < LIMIT:
        raise ValueError("⚠ 通し番号は 0..%d です: %r" % (LIMIT - 1, serial))
    return BASE + (serial >> 3), 1 << (7 - (serial & 7))


def bit_of(index: int) -> tuple[int, int]:
    """★宝箱の通し番号 → `(WRAM の添字, ビットのマスク)`。

    ⚠⚠ ビットは **MSB から**（★`bit (7 - (n & 7))`）。上の註を読んでください。
    ⚠ 隠し道具（200..207）は宝箱ではないので、★ここは通しません。
    """
    if not 0 <= index < COUNT:
        raise ValueError("⚠ 宝箱の通し番号は 0..%d です: %r" % (COUNT - 1, index))
    return slot_of(index)


def is_taken(wram, index: int) -> bool | None:
    """★その宝箱を取ったか。⚠ WRAM が短ければ `None`（★False と混ぜない）。"""
    off, mask = bit_of(index)
    if wram is None or len(wram) <= off:
        return None
    return bool(wram[off] & mask)


def taken(wram) -> list[int] | None:
    """★取った宝箱の通し番号（⚠ 読めなければ `None`）。"""
    if wram is None or len(wram) < BASE + NBYTES:
        return None
    return [n for n in range(COUNT) if wram[BASE + (n >> 3)] & (1 << (7 - (n & 7)))]


def hidden_taken(wram) -> list[int] | None:
    """★「しらべる」で取った隠し道具の通し番号（⚠ 読めなければ `None`）。

    ⚠ 升そのもの（map / x / y / 品番）は `dq3rom/search_spots.py` が持ちます。
    """
    if wram is None or len(wram) < BASE + ARRAY_BYTES:
        return None
    return [n for n in HIDDEN if wram[BASE + (n >> 3)] & (1 << (7 - (n & 7)))]


def raw(wram) -> bytes | None:
    """★配列そのもの（⚠ 一次情報を捨てない / `RX3-0016` の方針）。"""
    if wram is None or len(wram) < BASE + NBYTES:
        return None
    return bytes(wram[BASE:BASE + NBYTES])


def by_map(wram, owner) -> dict:
    """★map ごとの `{取った, 全部}`。`owner` は `{通し番号: map_id}`。"""
    got = taken(wram)
    if got is None:
        return {}
    out: dict[int, dict] = {}
    for n, mid in owner.items():
        row = out.setdefault(mid, {"taken": [], "all": []})
        row["all"].append(n)
        if n in got:
            row["taken"].append(n)
    for row in out.values():
        row["taken"].sort()
        row["all"].sort()
    return {m: r for m, r in out.items() if r["taken"]}


__all__ = ["BASE", "COUNT", "NBYTES", "ARRAY_BYTES", "LIMIT", "HIDDEN", "CURSOR",
           "slot_of", "bit_of", "is_taken", "taken", "hidden_taken", "raw", "by_map"]
