"""会話の選択肢に「押してよいか」を決める（RX3-0121 / 2026-09-08）。

## ⚠⚠ この検査がいちばん守りたいこと

```text
⚠ 「通常 NPC はとりあえず全部はい」を、★あとから誰かが書けないようにする
```

★調べた結果（`docs/research/dq3-conversation-choice-analysis.md`）:

```text
1 ふつうの情報 NPC（message 系）は、⚠ **そもそも選択肢を出さない**
2 選択肢を出すのは 施設 と event_script / special
3 event_script は ⚠⚠ 何が起きるか未確認（道具・お金・フラグ・戦闘・仲間）
```

→ ★自動で「はい」を押してよい相手は、⚠ **根拠付きでは 1 件もありません**。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.knowledge import choice as CH
from dq3.testing import talk_script as TS

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★実機で会話の文と一致させた talk_id（2026-09-02 / RX3-0056 の記録）
REAL = {"church": 0x006, "inn": 0x00B, "weapon_armor_shop": 0x1EB, "item_shop": 0x1FF}


# ======================================================================
# ⚠⚠ ここが本丸 — **「はい」は誰にも押さない**
# ======================================================================
def test_はいを自動で押す相手は1件も無い():
    """⚠⚠ 根拠のある相手が見つかるまで、★`AUTO_YES` は返しません。"""
    got = [t for t in range(0x400) if CH.decide(t).presses_yes]
    assert got == [], "⚠⚠ 自動で「はい」を押す talk_id が %d 件あります: %s" % (len(got), got[:8])


def test_施設は答えずに閉じる():
    for role, talk_id in REAL.items():
        d = CH.decide(talk_id)
        assert d.kind == CH.SERVICE, (role, d)
        assert d.action == CH.AUTO_NO, (role, d)
        assert d.confidence == CH.CONFIRMED, (role, d)


def test_何が起きるか分からない相手は止める():
    for talk_id in (0x001, 0x002, 0x003, 0x004, 0x005, 0x168, 0x3C0):
        d = CH.decide(talk_id)
        assert d.kind in (CH.EVENT, CH.UNKNOWN), (hex(talk_id), d)
        assert d.action == CH.STOP, (hex(talk_id), d)


def test_ふつうの会話は情報だが押さない():
    """★`message` 系は選択肢を出さないはず。⚠ 出たら**止まる**（★推測で押さない）。"""
    for talk_id in (0x050, 0x226, 0x03C):
        d = CH.decide(talk_id)
        assert d.kind == CH.INFORMATION, (hex(talk_id), d)
        assert d.action == CH.STOP, (hex(talk_id), d)


def test_物語の相手は分類を信じない():
    """⚠⚠ 表 `$B34E` の相手は、★範囲の処理**より先に**選ばれる。"""
    special = sorted(TS.SPECIAL_TABLE_IDS)
    assert special, "⚠ この検査の前提が消えている"
    for talk_id in special[:6]:
        assert CH.kind_of(talk_id)[0] == CH.UNKNOWN, hex(talk_id)


def test_読めない相手は分からないと言う():
    for bad in (None, -1, "x", 0):
        assert CH.decide(bad).kind == CH.UNKNOWN, bad
        assert CH.decide(bad).action == CH.STOP, bad


# ======================================================================
# ★人へ出す言葉（⚠ 内部の語を混ぜない / RX3-0109）
# ======================================================================
def test_サマリーに内部の値を出さない():
    from dq3 import action_log as AL

    rows = [CH.decide(REAL["inn"]), CH.decide(0x168)]
    assert CH.summary(rows) == "選択肢 1 件処理 / 未確認 1 件"
    for d in rows:
        assert AL.is_user_safe(d.text), d.text
        assert "talk_id" not in d.text and "SERVICE" not in d.text


def test_件数が0なら何も言わない():
    assert CH.summary([]) == ""
    assert CH.summary(None) == ""


# ======================================================================
# ★ROM で裏を取る（⚠ 推測だけで分類しない / 依頼者 §2）
# ======================================================================
@pytest.fixture(scope="module")
def prg():
    rom = ROOT / "input" / "Dragon Quest 3 (J).nes"
    if not rom.exists():
        pytest.skip("⚠ ROM が読めない環境")
    return rom.read_bytes()[16:]


#: ★窓の定義への 16bit ポインタ表（bank 14 / CPU $9BDC = PRG 0x39BDC）
TABLE = 0x39BDC


def _entry(prg, index):
    off = TABLE + index * 2
    return prg[off] | (prg[off + 1] << 8)


def _prg_of(cpu, bank=14):
    return bank * 0x4000 + (cpu - 0x8000)


def test_窓を開く処理が窓番号を書いている(prg):
    """★`$87F3: STA $77` → `$9BDC,X`（⚠ これが「窓の番号」の出どころ）。"""
    at = _prg_of(0x87F3)
    assert prg[at:at + 2] == bytes([0x85, 0x77]), "⚠ STA $77 ではない"
    got = prg[_prg_of(0x8802):_prg_of(0x8802) + 3]
    assert got == bytes([0xBD, 0xDC, 0x9B]), "⚠ LDA $9BDC,X ではない: %s" % got.hex()


def test_キャンセルはFFで返る(prg):
    """⚠⚠ `$8756 CMP #$FF` … ★B を押したときの返り値。"""
    at = _prg_of(0x8753)
    assert prg[at:at + 3] == bytes([0x20, 0x5B, 0x87]), "⚠ JSR $875B ではない"
    assert prg[at + 3:at + 5] == bytes([0xC9, 0xFF]), "⚠ CMP #$FF ではない"


def test_はいといいえの窓が表にある(prg):
    """★窓 0x1D の定義に「はい」「いいえ」の並びがある（⚠ 索引 = 番号）。"""
    cpu = _entry(prg, 0x1D)
    assert 0x8000 <= cpu < 0xC000, hex(cpu)
    body = prg[_prg_of(cpu):_prg_of(cpu) + 16]
    # ★「はい」= 24 0C / 区切り F2 / 「いいえ」= 0C 0C 0E / 終わり FF
    assert body[6:8] == bytes([0x24, 0x0C]), body.hex()
    assert body[8] == 0xF2 and body[9:12] == bytes([0x0C, 0x0C, 0x0E]), body.hex()
    assert body[12] == 0xFF, body.hex()


def test_店と教会の窓も同じ表から出る(prg):
    """⚠ 「はい／いいえ」だけの表ではない（★同じ表に施設の窓もある）。"""
    for index, head in ((0x16, bytes([0x10, 0x0C, 0x20, 0x11, 0x1A])),     # かいにきた
                        (0x17, bytes([0xFE, 0x1E, 0x12, 0x23, 0x1B]))):    # どくのちりょう
        cpu = _entry(prg, index)
        body = prg[_prg_of(cpu):_prg_of(cpu) + 12]
        assert body[6:6 + len(head)] == head, (hex(index), body.hex())


# ======================================================================
# ★台本のどれが「はい／いいえ」を聞くか（RX3-0124 ④ / 2026-09-19）
# ======================================================================
#
# ⚠⚠ **素直な逆アセンブルでは数を外します。** ★台本は呼び出しの直後に
#   **引数の 1 バイト**を置きます（`$B08C` が戻り番地を 1 つ進めて読む）。
#
#   ```text
#   $B835  JSR $B0BE      ★helper
#   $B838  71             ⚠⚠ これは命令ではなく**引数**
#   $B839  JSR $B84E      ← ここから先がずれる
#   ```
#
# ★2 通りで数えて一致したので採った（⚠ 片方だけでは信じない）:
#
#   ```text
#   素直に読む        未定義の命令が出た台本 21 本 / 選択肢を持つ台本 17 本  ⚠ ずれている
#   引数を知って読む  未定義の命令が出た台本  8 本 / 選択肢を持つ台本 19 本
#   バイトを探す                                  / 選択肢を持つ台本 19 本  ★一致
#   ```

@pytest.fixture(scope="module")
def rom_path():
    got = ROOT / "input" / "Dragon Quest 3 (J).nes"
    if not got.exists():
        pytest.skip("⚠ ROM が読めない環境")
    return got


def test_選択肢を聞く相手をROMから出せる(rom_path):
    """★台本が自分の中に `BRK $20 cmd=$17` を持つ talk_id。"""
    got = TS.choice_talk_ids(rom_path)
    assert len(got) == 65, "⚠ 件数が変わりました: %d" % len(got)
    # ★施設は共通処理へ**飛んでから**聞くので、ここには入らない（⚠ 宿屋 = 0x00B）
    assert 0x00B not in got and 0x1FF not in got


def test_はいでお金が動く相手が分かる(rom_path):
    """⚠⚠ ここは**自動で「はい」を押してはいけない**相手（★所持金を見る `$A073`）。"""
    got = TS.money_choice_talk_ids(rom_path)
    assert sorted(got) == list(range(411, 422)), sorted(got)
    assert got <= TS.choice_talk_ids(rom_path), "⚠ 選択肢を聞く側に入っていない"


def test_文を出すBRKの基数(rom_path):
    """★メッセージ番号 = `arg + 基数[Y]`（`$B0B4` の 5 つ）。"""
    got = TS.message_bases(rom_path)
    assert got == (0x0000, 0x00F7, 0x01F7, 0x02B5, 0x03B5), got


def test_基数はふつうの会話の番号と一致する(rom_path):
    """★裏取り: `Y=2` の基数は、⚠ **別の道で出した**「ふつうの会話」の base と同じ数。

    ⚠ 同じ表から 2 度読んだのではありません（★`CLASSES` は逆アセンブルの写し）。
    """
    base = next(extra["message_base"] for _b, _h, k, _r, extra in TS.CLASSES
                if k == "message" and extra.get("message_base"))
    assert TS.message_bases(rom_path)[1] == base == 0x0F7


def test_ROMが無ければ空(tmp_path):
    """⚠ 落とさない（★呼ぶ側は今までどおり）。"""
    assert TS.choice_talk_ids(tmp_path / "ない.nes") == frozenset()
    assert TS.money_choice_talk_ids(tmp_path / "ない.nes") == frozenset()
    assert TS.message_bases(tmp_path / "ない.nes") == ()


def test_版が違えば読まない(rom_path, tmp_path):
    """⚠⚠ 番地が同じとは限らない版で、★**黙って違う数を返さない**。

    ⚠ 今の ROM で見張りを外しても何も起きません（★版が合っているため）。
    → ★ここでは**違う版を作って**確かめます（⚠ 壊す実験が空振りしないように）。
    """
    raw = bytearray(rom_path.read_bytes())
    at = 0x10 + 13 * 0x4000 + (0xB414 - 0x8000)
    assert raw[at] == 0xA9, "⚠ 見張りの見本が変わった: %02X" % raw[at]
    raw[at] ^= 0xFF                                  # ★$B414 の 1 バイトを変える
    other = tmp_path / "別の版.nes"
    other.write_bytes(bytes(raw))
    assert TS.choice_talk_ids(other) == frozenset()
    assert TS.message_bases(other) == ()


def test_お金が動く相手は押してよい側に入らない(rom_path):
    """⚠⚠ ★この WI が終わるまで、自動で「はい」は押しません（`choice.py`）。"""
    for tid in TS.money_choice_talk_ids(rom_path):
        got = CH.decide(TS.classify(tid))
        assert got.presses_yes is False, (tid, got)


def test_ふつうの会話はメッセージを出すだけ(prg):
    """★`message` の処理は far call 1 本（⚠ 窓を開く処理を通らない）。"""
    at = 13 * 0x4000 + (0xB51B - 0x8000)
    got = prg[at:at + 10]
    # $B51B: LDX $5D / LDA $5C / INX ×3 / BRK $04 cmd=$07
    assert got[:4] == bytes([0xA6, 0x5D, 0xA5, 0x5C]), got.hex()
    assert got[7:10] == bytes([0x00, 0x04, 0x07]), "⚠ BRK $04 cmd=$07 ではない: %s" % got.hex()
