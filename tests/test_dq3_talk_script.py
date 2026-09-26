"""talk_id の振り分け（RX3-0056）。★$B3CC / $B3F0 の写しを、実機で確かめた 4 体で固定する。"""
from __future__ import annotations

import pathlib

import pytest

from dq3.testing import talk_script as TS


def test_実機の4体はROMの処理でroleが付く():
    # ★2026-09-02 アリアハン: 宿屋 0x00B / 道具屋 0x1FF / 武器防具屋 0x1EB / 教会 0x006（会話の文と一致）
    assert TS.classify(0x00B)["role"] == "inn" and TS.classify(0x00B)["facility_index"] == 1
    assert TS.classify(0x1FF)["role"] == "item_shop" and TS.classify(0x1FF)["routine"] == "$A296"
    assert TS.classify(0x1EB)["role"] == "weapon_armor_shop" and TS.classify(0x1EB)["routine"] == "$A1CE"
    assert TS.classify(0x006)["role"] == "church" and TS.classify(0x006)["handler"] == "$A60E"
    assert all(TS.classify(t)["role_status"] == "CONFIRMED" for t in (0x00B, 0x1FF, 0x1EB, 0x006))


def test_ふつうの会話はメッセージ番号でroleは無い():
    c = TS.classify(0x247)
    assert (c["class"], c["role"], c["message_id"]) == ("message", None, 0x0F7 + (0x247 - 0x226))
    assert TS.classify(0x05C)["message_id"] == 0x00C
    assert TS.classify(0x000)["class"] == "none"
    assert TS.classify(0x3C2)["class"] == "event_script" and TS.classify(0x3C2)["script_index"] == 0x4D + 2


def test_範囲の境目():
    # ★下限そのもの / 直前で処理が変わる
    assert TS.classify(0x00A)["class"] == "inn" and TS.classify(0x009)["class"] == "church"
    assert TS.classify(0x1FE)["class"] == "item_shop" and TS.classify(0x1FD)["class"] == "weapon_armor_shop"
    assert TS.classify(0x001)["class"] == "special_1" and TS.classify(0x001)["role"] is None


def test_特別な表の相手は印が付く():
    c = TS.classify(0x227)
    assert c["special_table_B34E"] is True and c["class"] == "message"


def test_台帳にroleを足しても元は変えない():
    master = {"maps": [{"map_id": 9, "npcs": [{"npc_id": 1, "talk_id": 0x00B, "initial_x": 8, "initial_y": 16,
                                                "appearance_id": 28, "movement": "fixed"}]}]}
    got = TS.annotate(master)
    assert got["maps"][0]["npcs"][0]["role"] == "inn" and "role" not in master["maps"][0]["npcs"][0]
    goals = TS.facility_goals(got["maps"][0])
    assert goals == [{"role": "inn", "npc_id": 1, "x": 8, "y": 16, "movement": "fixed", "talk_id": 11, "facility_index": 1}]


def test_script_analysisは範囲が途切れない():
    sa = TS.script_analysis()
    rs = sa["ranges"]
    assert rs[0]["from"] == 1 and rs[-1]["to"] == 0x3FF
    for a, b in zip(rs, rs[1:]):
        assert a["to"] + 1 == b["from"]
    assert sa["talk_id_meaning"].startswith("script id")


# --- ★RX3-0089: 店番号（$06FF）の出どころ ---------------------------------------

ROM = pathlib.Path(__file__).resolve().parents[1] / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")


def _prg():
    from dq3.testing import npc_rom as R

    return R._prg(None)


def _cpu(bank, addr):
    return bank * 0x4000 + (addr - (0xC000 if bank == 15 else 0x8000))


@needs_rom
def test_施設の振り分けの定数をROMから取り直す():
    """⚠⚠ `CLASSES` の `index_add` は写しです。★写し間違いを ROM 側から見つけます。

    ```text
    $B4BD  A9 00 / F0 02 / A9 15   ★宿   低い帯 +$00 / 高い帯 +$15
    $B4CC  A9 00 / F0 02 / A9 02   ★武器 低い帯 +$00 / 高い帯 +$02
    $B4DB  A9 14 / D0 02 / A9 17   ★道具 低い帯 +$14 / 高い帯 +$17
           18 65 5C（★+ $5C）→ 8D FF 06（★$06FF へ）→ 4C ..（★処理へ）
    ```
    """
    prg = _prg()
    got = {}
    for at in (0xB4BD, 0xB4CC, 0xB4DB):
        o = _cpu(13, at)
        assert prg[o] == 0xA9 and prg[o + 2] in (0xF0, 0xD0) and prg[o + 4] == 0xA9
        assert prg[o + 6:o + 9] == bytes((0x18, 0x65, 0x5C)), "⚠ $5C を足していない"
        assert prg[o + 9:o + 12] == bytes((0x8D, 0xFF, 0x06)), "⚠ $06FF へ書いていない"
        assert prg[o + 12] == 0x4C
        routine = prg[o + 13] | (prg[o + 14] << 8)
        got[routine] = (prg[o + 1], prg[o + 5])            # ★(低い帯, 高い帯)

    want = {}
    for _bound, _handler, _klass, _role, extra in TS.CLASSES:
        if "routine" not in extra or "index_add" not in extra:
            continue
        want.setdefault(int(extra["routine"]), []).append(extra["index_add"])
    for routine, (lo, hi) in got.items():
        adds = sorted(want[routine])
        assert adds == sorted((lo, hi)), (
            "⚠ $%04X の足す数が ROM と違う: 表 %s / ROM %s" % (routine, adds, sorted((lo, hi))))


@needs_rom
def test_宿屋の泊まるかの問いのはいいいえは1か所だけ():
    """★RX3-0241: `nav_v0.lua` は `$A55C`（bank 13）を見張って はい を押す。★ROM がその形であることを見る。

    ```text
    $A51F  AD DF 06        ★宿屋の処理の頭（LDA $06DF / 昼か夜か）
    $A556  00 19 87        ★問い（メッセージ $19）
    $A559  00 12 D7
    $A55C  00 20 17        ★はい／いいえ（bank 14 $8743）
    $A55F  D0 BA           ⚠ いいえ / B → $A51B
    $A51B  00 1D 87 / 60   ★またどうぞ / RTS
    ```
    """
    prg = _prg()

    def at(cpu, n):
        return bytes(prg[_cpu(13, cpu):_cpu(13, cpu) + n])

    assert all(extra.get("routine") == TS.INN_ROUTINE for _b, _h, _k, role, extra in TS.CLASSES if role == "inn")
    assert at(TS.INN_ROUTINE, 3) == bytes.fromhex("ADDF06")
    assert at(0xA556, 11) == bytes.fromhex("0019870012D7002017D0BA"), "⚠⚠ 宿屋の問いの形が違う"
    assert TS.INN_QUESTION == 0xA55C and at(TS.INN_QUESTION, 3) == bytes.fromhex("002017")
    assert at(0xA51B, 4) == bytes.fromhex("001D8760"), "⚠ いいえ の行き先が「またどうぞ → RTS」でない"
    body = at(TS.INN_ROUTINE, 0xA60E - TS.INN_ROUTINE)          # ★$A60E から教会の処理
    hits = [TS.INN_ROUTINE + k for k in range(len(body) - 2) if body[k:k + 3] == bytes.fromhex("002017")]
    assert hits == [TS.INN_QUESTION], "⚠⚠ 宿屋の処理に はい／いいえ が別にもある: %s" % [hex(h) for h in hits]


@needs_rom
def test_店番号を直に書くのは5か所だけ():
    """★`$06FF`（店番号）に直に書く命令を ROM 全体から数えます。

    ```text
    $B4C6 宿 / $B4D5 武器 / $B4E4 道具   ★会話の振り分け（talk_id から）
    $A2BB                                ★LDA #$2D → 店 45（⚠ 店 41 の差し替え）
    $AF6B                                ★special_5 が $04 を 2 倍した値
    ```
    ⚠⚠ 索引つき（`STA abs,X`）で届く可能性までは否定できません
    （★base $0600〜$06FF への書き込みは 79 か所あり、⚠ そこまで大きな索引は
    使わないはずですが、**証明はしていません**）。
    """
    prg = _prg()
    want = bytes((0x8D, 0xFF, 0x06))
    hits = []
    i = 0
    while True:
        i = prg.find(want, i)
        if i < 0:
            break
        bank = i // 0x4000
        hits.append((bank, (0xC000 if bank == 15 else 0x8000) + (i % 0x4000)))
        i += 1
    assert hits == [(13, 0xA2BB), (13, 0xAF6B), (13, 0xB4C6), (13, 0xB4D5), (13, 0xB4E4)]


@needs_rom
def test_店45は店41の差し替え():
    """★`$A296`（道具屋）の頭で、店 41 のときだけ条件を見て 45 に差し替えます。

    ```text
    $A296  LDA $06FF / CMP #$1E / BNE     ⚠ 店 30 は $A478 へ
    $A2A0  CMP #$29                       ★店 41 のとき
    $A2A4  LDA $60B9 / AND #$20 / BEQ     ★条件 1
    $A2AB  LDA $60B7 / BMI                ★条件 2（⚠ 意味は未確認）
    $A2B0  LDA #$1C / STA $CE / BRK       ★問いかけ
    $A2B7  BCS                            ⚠ 断ったら差し替えない
    $A2B9  LDA #$2D / STA $06FF           ★店 45 へ
    ```
    """
    prg = _prg()
    o = _cpu(13, 0xA296)
    assert prg[o:o + 3] == bytes((0xAD, 0xFF, 0x06))
    assert prg[o + 3:o + 5] == bytes((0xC9, 0x1E)), "⚠ 店 30 の分岐が無い"
    assert prg[o + 10:o + 12] == bytes((0xC9, 0x29)), "⚠ 店 41 の分岐が無い"
    assert prg[_cpu(13, 0xA2B9):_cpu(13, 0xA2BE)] == bytes((0xA9, 0x2D, 0x8D, 0xFF, 0x06))
    # ★武器屋の頭も同じ形（⚠ 店 7 が同じ $A478 へ飛ぶ）
    w = _cpu(13, 0xA1CE)
    assert prg[w + 3:w + 5] == bytes((0xC9, 0x07))
    assert prg[w + 5:w + 7] == bytes((0xD0, 0x03))
    assert prg[w + 7:w + 10] == bytes((0x4C, 0x78, 0xA4)), "⚠ $A478 へ飛んでいない"
    assert prg[o + 7:o + 10] == bytes((0x4C, 0x78, 0xA4)), "⚠ 店 30 も $A478 のはず"


@needs_rom
def test_店の処理へ飛ぶのは会話の振り分けだけ():
    """★★ ⚠ これで「残りの店番号は作られない」が言えます（RX3-0089）。

    ```text
    $B4C9 → 宿 $A51F   /  $B4D8 → 武器 $A1CE  /  $B4E7 → 道具 $A296   ★会話の振り分け
    $A1D5 / $A29D → $A478                                            ★店の中の特別処理
    ```
    ⚠ `special_5`（$AF51）は `$06FF` に値を入れますが、★店の処理へは**飛びません**。
    """
    prg = _prg()
    got = []
    for addr in (0xA1CE, 0xA296, 0xA51F, 0xA478):
        for op in (0x4C, 0x20):
            pat = bytes((op, addr & 0xFF, addr >> 8))
            i = 0
            while True:
                i = prg.find(pat, i)
                if i < 0:
                    break
                bank = i // 0x4000
                got.append((addr, bank, (0xC000 if bank == 15 else 0x8000) + (i % 0x4000)))
                i += 1
    assert sorted(got) == [
        (0xA1CE, 13, 0xB4D8),
        (0xA296, 13, 0xB4E7),
        (0xA478, 13, 0xA1D5),
        (0xA478, 13, 0xA29D),
        (0xA51F, 13, 0xB4C9),
    ], "⚠ 店の処理への入口が変わった: %s" % [(hex(a), b, hex(c)) for a, b, c in sorted(got)]
