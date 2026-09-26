"""呪文の表・習得ビット・状態を ROM から読む（RX3-0125 / 2026-09-08）。

★北米版の逆アセンブルを**教師**にし、⚠ 日本版 ROM では**署名**で表を探して裏を取る。
⚠ 番地の直書きはしない（★見つからなければ空で返す）。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3rom import spell_flags as SF
from dq3rom import spells as SP

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "input" / "Dragon Quest 3 (J).nes"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が読めない環境")


@pytest.fixture(scope="module")
def prg():
    if not ROM.exists():
        pytest.skip("⚠ ROM が読めない環境")
    return ROM.read_bytes()[16:]


# ======================================================================
# ★1. 呪文の表（★ROM の署名で探す）
# ======================================================================
def test_署名で表が見つかる(prg):
    t = SP.find_tables(prg)
    assert t is not None
    # ★bank 4 の中にある（⚠ 北米版と同じ bank。★番地は直書きしない）
    assert t.table // 0x4000 == 4 and t.damage // 0x4000 == 4 and t.heal // 0x4000 == 4
    assert t.targets == t.table + SP.COUNT


def test_62件を読める(prg):
    rows = SP.read_all(prg)
    assert len(rows) == 62
    assert [r.spell_id for r in rows] == list(range(62))


def test_消費MPは知っている値と一致する(prg):
    """★攻略で知られている消費 MP と一致（⚠ ここは ROM の裏付けなので正解を書いてよい）。"""
    mp = {r.spell_id: r.mp for r in SP.read_all(prg)}
    assert (mp[26], mp[27], mp[28]) == (3, 5, 7)        # ホイミ / ベホイミ / ベホマ
    assert (mp[0], mp[3], mp[6]) == (2, 4, 5)           # メラ / ギラ / イオ
    assert (mp[32], mp[33]) == (10, 20)                 # ザオラル / ザオリク
    assert (mp[46], mp[43]) == (4, 3)                   # スクルト / ルカニ
    assert mp[31] == 62                                 # ベホマズン


def test_対象は上位2ビット(prg):
    by = {r.spell_id: r for r in SP.read_all(prg)}
    assert by[26].target == SP.ALLY_SINGLE                # ホイミ
    assert by[0].target == SP.ENEMY_GROUP                 # メラ
    assert by[6].target == SP.ENEMIES_ALL                 # イオ
    assert by[46].target == SP.SELF_PARTY                 # スクルト


def test_単体と群は対象の表から(prg):
    got = SP.read_targets(prg, SP.find_tables(prg))
    assert got["attack_single"] == (0, 1, 2, 9)          # メラ系 + ヒャド
    assert got["attack_group"] == (3, 4, 8, 10, 11, 13, 14, 15)
    assert got["heal_single"] == (26, 27, 28)
    assert got["heal_all"] == (30, 31)
    by = {r.spell_id: r for r in SP.read_all(prg)}
    assert by[0].scope == "single" and by[3].scope == "group" and by[6].scope == "all"


def test_攻撃の範囲は対象欄と辻褄が合う(prg):
    """⚠⚠ **3 件ずれていました**（RX3-0429 / P-2 / 2026-09-24）。

    ```text
    ★`target` 欄は「プレイヤーに何を選ばせるか」。
    ⚠ 群を選ばせる呪文（`enemy_group`）が「敵全体」であることはありえない。
    ⚠ 選ばせない呪文（`enemies_all`）が「1 群だけ」であることもありえない。
    ```
    ★昔は 8 バイトの表から決めていて、⚠ ベギラゴン=all / イオナズン=group だった。
    """
    rows = [r for r in SP.read_all(prg) if r.kind == SP.ATTACK]
    assert rows, "⚠ 攻撃呪文が 1 件も読めていません"
    bad = []
    for r in rows:
        if r.target == SP.ENEMIES_ALL and r.scope != "all":
            bad.append("id=%d 選ばせないのに scope=%s" % (r.spell_id, r.scope))
        if r.target == SP.ENEMY_GROUP and r.scope == "all":
            bad.append("id=%d 群を選ばせるのに scope=all" % r.spell_id)
    assert not bad, "⚠⚠ 対象欄と範囲が矛盾: %s" % bad

    by = {r.spell_id: r for r in rows}
    # ★実測で確定した 3 件（⚠ ここが戻ったら赤くする）
    assert by[5].scope == "group", "⚠⚠ ベギラゴンが群でない"
    assert by[16].scope == "group", "⚠⚠ ライデインが群でない"
    assert by[8].scope == "all", "⚠⚠ イオナズンが全体でない"
    # ⚠ 巻き込んでいないこと（★もともと合っていたもの）
    assert by[0].scope == "single" and by[3].scope == "group" and by[17].scope == "all"


def test_範囲の決め方は対象欄から(prg):
    """★純関数として固定する（⚠ 8 バイトの表は使わない）。"""
    single = {0, 1, 2, 9}
    assert SP.attack_scope(SP.ENEMIES_ALL, 8, single) == "all"
    assert SP.attack_scope(SP.ENEMY_GROUP, 0, single) == "single"
    assert SP.attack_scope(SP.ENEMY_GROUP, 5, single) == "group"


def test_威力は表から(prg):
    by = {r.spell_id: r for r in SP.read_all(prg)}
    assert (by[0].base, by[0].delta) == (8, 6)          # メラ 8〜14
    assert (by[26].base, by[26].delta) == (30, 10)      # ホイミ 30〜40
    assert by[28].base == 0xFF and by[28].avg is None   # ベホマ = 全快
    assert by[27].avg == 75 + 10                        # ベホイミ 75 + 20/2


def test_種別の割り当て(prg):
    by = {r.spell_id: r for r in SP.read_all(prg)}
    assert by[46].kind == SP.BUFF and by[43].kind == SP.DEBUFF
    assert by[32].kind == SP.REVIVE and by[34].kind == SP.INSTANT
    assert by[52].kind == SP.CURE and by[38].kind == SP.FIELD
    assert by[34].resist == "sleep" and by[36].resist == "stopspell"


def test_名前はIDで日本版と揃う(prg):
    """★北米版の ID と日本版の名前が**同じ順**（⚠ ここが崩れると全部ずれる）。"""
    from dq3.knowledge import rom_names as RN

    if not RN.available():
        pytest.skip("⚠ 名前辞書が使えない環境")
    for sid, name in ((0, "メラ"), (26, "ホイミ"), (46, "スクルト"), (43, "ルカニ"),
                      (32, "ザオラル"), (61, "トラマナ")):
        assert RN.spell(sid) == name, (sid, RN.spell(sid))


def test_表が無ければ空(prg):
    assert SP.read_all(b"\x00" * 0x1000) == []
    assert SP.find_tables(b"") is None


# ======================================================================
# ★2. 誰が何を覚えているか（★固定セーブで突き合わせ）
# ======================================================================
def test_勇者と魔法使いと僧侶で読む場所が違う(prg):
    blocks = SF.blocks(prg)
    # ★勇者 Lv6: bytes 0-3 の bit → ブロック 0（メラ ホイミ ニフラム = bit 0,1,2）
    assert SF.learned_ids(bytes([0x07, 0, 0, 0, 0, 0, 0, 0]), 0, blocks) == [0, 26, 21]
    # ★魔法使い: bytes 0-3 → ブロック 4（メラ ヒャド ギラ = bit 0,2,4）
    assert SF.learned_ids(bytes([0x15, 0, 0, 0, 0, 0, 0, 0]), 1, blocks) == [0, 9, 3]
    # ★僧侶: bytes 4-7 → ブロック 8（ホイミ ニフラム ピオリム マヌーサ = bit 1,2,5,6）
    assert SF.learned_ids(bytes([0, 0, 0, 0, 0x66, 0, 0, 0]), 2, blocks) == [26, 21, 25, 37]
    # ★戦闘のページだけ（⚠ bytes 3 の移動呪文は落ちる）
    assert SF.learned_ids(bytes([0, 0, 0, 0x01, 0, 0, 0, 0]), 0, blocks) == []
    assert SF.learned_ids(bytes([0, 0, 0, 0x01, 0, 0, 0, 0]), 0, blocks,
                          battle_only=False) == [26]


def test_ページ2の戦闘呪文も読む(prg):
    """⚠⚠ 2026-09-20（RX3-0326）: ★**ページ 2 を読んでいませんでした**。

    ```text
    block  2 勇p2  ★全部 $FF（⚠ **勇者だけ**が空 → ここから全職へ一般化したのが誤りの元）
    block  6 魔p2  メラゾーマ メダパニ マヒャド … ベギラゴン … イオナズン
    block 10 僧p2  フバーハ ベホマ ★ザラキ ベホマラー バギクロス ザオラル メガンテ ザオリク
    ```

    → ⚠ ザラキ・イオナズン・ベギラゴン等が AI からも呪文一覧からも**見えていません**でした。
    """
    blocks = SF.blocks(prg)
    assert SF.BATTLE_PAGES == (0, 1, 2), "⚠ 戦闘のページが 3 枚でない"
    # ★僧侶のページ 2（bytes 6）… bit2 = ザラキ / bit1 = ベホマ / bit7 = ザオリク
    assert SF.learned_ids(bytes([0, 0, 0, 0, 0, 0, 0x04, 0]), 2, blocks) == [19]
    assert SF.learned_ids(bytes([0, 0, 0, 0, 0, 0, 0x86, 0]), 2, blocks) == [28, 19, 33]
    # ★魔法使いのページ 2（bytes 2）… bit1 = メダパニ / bit6 = イオナズン
    assert SF.learned_ids(bytes([0, 0, 0x42, 0, 0, 0, 0, 0]), 1, blocks) == [39, 8]
    # ⚠ ページ 3（移動・メニュー用）は今までどおり落とす
    assert SF.learned_ids(bytes([0, 0, 0, 0, 0, 0, 0, 0x01]), 2, blocks) == []
    assert SF.learned_ids(bytes([0, 0, 0, 0, 0, 0, 0, 0x01]), 2, blocks,
                          battle_only=False) == [26]


def test_即死の範囲はカーソルの対象とは別(prg):
    """⚠⚠ `target` は**カーソルが何を選ぶか**で、効果の範囲ではありません。

    ★ザキもザラキも `enemy_group`（FC の DQ は「群を選んでから 1 体に当たる」形）。
    → ⚠ `target` を範囲の正本にすると、★ザキまで群全体になります。
    """
    rows = SP.read_all(prg)
    zaki, zaraki = rows[18], rows[19]
    assert zaki.target == zaraki.target == SP.ENEMY_GROUP, "⚠ 前提が変わった"
    assert zaki.scope == "single", "⚠ ザキは 1 体"
    assert zaraki.scope == "group", "⚠⚠ ザラキは 1 群（★体数ぶん見込みが上がる）"


def test_転職しても覚えた呪文は残る(prg):
    """★元僧侶の戦士（class 4）でも bytes 4-7 の bit をそのまま読む。"""
    blocks = SF.blocks(prg)
    assert SF.learned_ids(bytes([0, 0, 0, 0, 0x02, 0, 0, 0]), 4, blocks) == [26]   # ホイミ


def test_固定セーブと一致する(prg):
    """★★ ⚠⚠ 実機のセーブ 20 本で、★Lv と習得の関係が崩れていないこと。"""
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from retroux.core.bgmap import savestate as ss
    from savestate_dir import states_dir

    paths = sorted(states_dir().glob("DQ3_J*.fc*"))
    if not paths:
        pytest.skip("⚠ DQ3 のセーブが無い環境")
    blocks = SF.blocks(prg)
    checked = 0
    for p in paths:
        st = ss.load(p)
        b = st.byte
        for c in range(4):
            if (b(0x0724 + 2 * c) | b(0x0725 + 2 * c) << 8) == 0:
                continue
            cls = b(0x0718 + c) & 7
            lv = b(0x0700 + c)
            raw = bytes(b(0x078C + 8 * c + k) for k in range(8))
            if raw == b"\xff" * 4 + b"\x00" * 4:
                continue                              # ⚠ 空のセーブ
            got = SF.learned_ids(raw, cls, blocks)
            if cls == 0:
                # ★勇者: Lv2 メラ / Lv4 ホイミ / Lv6 ニフラム（★攻略で知られている順）
                want = [sid for sid, at in ((0, 2), (26, 4), (21, 6)) if lv >= at]
                assert got == want, (p.name, c, lv, got)
            elif cls == 4:
                assert got == [], (p.name, c, got)    # ⚠ 戦士は何も覚えない
            checked += 1
    assert checked >= 20, "⚠ 突き合わせた人が少なすぎます: %d" % checked


# ======================================================================
# ★3. 状態（★生存の bit だけ日本版で観測できた）
# ======================================================================
def test_生存のbitが立っている():
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from retroux.core.bgmap import savestate as ss
    from savestate_dir import states_dir

    paths = sorted(states_dir().glob("DQ3_J*.fc*"))
    if not paths:
        pytest.skip("⚠ DQ3 のセーブが無い環境")
    seen = 0
    for p in paths:
        b = ss.load(p).byte
        for c in range(4):
            hp = b(0x071C + 2 * c) | b(0x071D + 2 * c) << 8
            if hp == 0 or hp == 0xFFFF:
                continue
            assert b(0x073C + 2 * c) & 0x80, (p.name, c)   # ★生きていれば bit7
            seen += 1
    assert seen > 0
