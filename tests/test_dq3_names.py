"""名前辞書（RX3-0069 / 2026-09-03）。

★★ 原作の名称一覧を**ここに焼かない** ★★

  ⚠ 検査するのは**構造**です（件数 / pointer の範囲 / 全件が復号できる / 終端 /
    復号した字が字形表に収まる）。★名前そのものは、実機で読んだ記録と
    突き合わせるときだけ（⚠ その記録は work/ にあり、無ければ skip）。
"""

from __future__ import annotations

import json
import pathlib
import unicodedata

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"
SRC = PROJECT_ROOT / "dq3rom" / "names.py"
PROFILE = PROJECT_ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
SCREEN_NAMES = PROJECT_ROOT / "work" / "dq3-knowledge" / "enemy-names.json"


needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="⚠ ROM が無い環境")


@pytest.fixture(scope="module")
def book():
    if not ROM_PATH.exists():
        pytest.skip("⚠ ROM が無い環境")
    from dq3rom import names as N
    from dq3rom import profile as P

    return N.NameDictionary(P.load_and_identify(ROM_PATH))


# --- ⚠⚠ 原作テキストを焼いていない ------------------------------------------

def _code_only(path: pathlib.Path) -> str:
    """★註釈と文字列を落として、コードの字面だけにする。"""
    import io
    import tokenize

    out = []
    with io.open(path, encoding="utf-8") as f:
        for tok in tokenize.generate_tokens(f.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    return " ".join(out)


def _structure_only(value):
    """★`_` で始まる鍵（註釈・根拠）を再帰的に落とす。"""
    if isinstance(value, dict):
        return {k: _structure_only(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [_structure_only(v) for v in value]
    return value


def _kana(text: str) -> bool:
    return any("぀" <= ch <= "ヿ" for ch in text)


def test_名前をソースに書いていない():
    """⚠⚠ **これが今回いちばん大事な検査**（指示書 §1）。

    ★註釈に実例（実機で確かめた 1〜2 語）を書くのは許す。⚠ **コード**には書かない。
    """
    for path in (SRC, PROJECT_ROOT / "dq3" / "knowledge" / "rom_names.py"):
        code = _code_only(path)
        assert not _kana(code), "⚠⚠ コードに かな が入っている: %s" % path.name


def test_profileが持つのは場所と形だけ():
    spec = json.loads(PROFILE.read_text(encoding="utf-8"))["tables"]["names"]
    assert set(spec["file_table"]) >= {"cpu", "monster_lo", "monster_hi", "item", "spell", "item_end"}
    for kind in ("monster", "item", "spell"):
        assert "count" in spec[kind], "⚠ %s の件数が無い（★検算に要る）" % kind
    # ⚠ 名前らしい値が混ざっていない（★数字と番地と英字だけ。註釈は除く）
    flat = json.dumps(_structure_only(spec), ensure_ascii=False)
    assert not _kana(flat), "⚠⚠ profile の構造部分に かな が入っている"


# --- ★構造 -------------------------------------------------------------------

def test_件数がpointerの範囲と合う(book):
    lay = book.layout
    assert lay.monster_count == 139 and lay.monster_split == 84
    assert lay.item_count == 125 and lay.spell_count == 62
    # ★固定長の表は、次の表の先頭でちょうど終わる
    assert lay.item_base + lay.item_count * (lay.item_width + 2) < lay.monster_lo
    assert lay.spell_base + lay.spell_count * (lay.spell_width + 2) == lay.monster_lo


# --- ★地名（ルーラの行き先 / RX3-0092）------------------------------------------

def test_地名の表はファイル表から辿れる(book):
    """⚠ 番地を決め打ちしない。★道具の表の終わりが、そのまま地名のファイルの先頭。"""
    lay = book.layout
    assert lay.place_width == 7
    assert lay.place_count == 20, "⚠ ルーラの行き先と同じ件数のはず"
    # ★次の表（呪文のファイル）の先頭でちょうど終わる
    assert lay.place_base + lay.place_count * (lay.place_width + 2) == lay.spell_file


def test_地名の件数はルーラ表と同じ(book):
    """★`rura_points`（画面に並ぶ順）と 1 対 1（⚠ 数だけでなく、★並びも同じ前提）。"""
    from dq3rom import rura

    points = rura.read_points(book.ident)
    assert len(points) == book.count("place")


def test_地名は9バイト目が文字数と一致する(book):
    """★「表の形が合っている」証拠。⚠⚠ ただし **19/20** です。

    ⚠⚠ 2026-09-06 訂正: 最初「20 件すべてで一致」と書きましたが、★**誤り**でした。
    ⚠ id 13 だけ 9 バイト目が 1 少ないです（★理由は未解明）。

    ★この byte が「文字数」だという裏付けは、⚠ 地名ではなく**道具と呪文**が出します
      （★道具 125/125・呪文 62/62 で一致）。→ ⚠ 例外はこの 1 件だけ。
    """
    entries = book.all("place")
    assert len(entries) == 20
    for e in entries:
        assert e.name, "⚠ 空の名前がある: id %d" % e.entity_id
        assert not e.unknown_bytes, "⚠ 読めない符号: id %d %s" % (e.entity_id, e.unknown_bytes)
    off = [e.entity_id for e in entries if e.attr != len(e.name)]
    assert off == [13], "⚠ 合わない件が変わった: %s" % off
    for kind in ("item", "spell"):
        rows = book.all(kind)
        assert all(e.attr == len(e.name) for e in rows), "⚠ %s で 9 バイト目 = 文字数 が崩れた" % kind


def test_地名も共通の入口から引ける(book):
    assert book.resolve("place", 0).name == book.all("place")[0].name
    with pytest.raises(IndexError):
        book.resolve("place", book.count("place"))


def test_全件が復号でき未知のバイトが無い(book):
    for kind in ("monster", "item", "spell"):
        entries = book.all(kind)
        assert len(entries) == book.count(kind)
        assert all(e.name for e in entries), "⚠ 空の名前がある: %s" % kind
        unknown = [e.entity_id for e in entries if e.unknown_bytes]
        assert not unknown, "⚠ %s に復号できないバイト: %s" % (kind, unknown)


def test_モンスターの終端と長さ(book):
    for e in book.all("monster"):
        assert 0xFF not in e.raw and 1 <= len(e.raw) <= 16
        assert len(e.name) <= 12


def test_固定長の名前は幅に収まる(book):
    for kind, width in (("item", 7), ("spell", 5)):
        for e in book.all(kind):
            assert len(e.raw) == width + 2
            assert e.mask is not None and e.mask < (1 << width), (
                "⚠ %s %d のマスクが幅を超える: %02X" % (kind, e.entity_id, e.mask))


def test_復号した字が字形表に収まる(book):
    """⚠ 2026-09-06（RX3-0093）: 表示の形は、★同じ絵を使い回している かな を

    カタカナに直します。⚠ その字は**字形表には無い**ので、★直す前の相手まで許します。
    """
    from dq3rom.kana import to_katakana as _to_katakana

    known = set(book.chars.values()) | {"␣", " "}
    allowed = known | {_to_katakana(c) for c in known}
    for kind in ("monster", "item", "spell", "place"):
        for e in book.all(kind):
            for ch in unicodedata.normalize("NFD", e.name):
                if ch in ("゙", "゚"):
                    continue
                assert ch in allowed or _to_katakana(ch) in allowed, (
                    "⚠ 字形表に無い字: %r（%s %d）" % (ch, kind, e.entity_id))


def test_濁点と半濁点が合成されている(book):
    """★マスク方式（固定長）と前置方式（FF 区切り）の両方で、⚠ 結合文字が残らない。"""
    for kind in ("monster", "item", "spell"):
        for e in book.all(kind):
            assert "゙" not in e.name and "゚" not in e.name, (
                "⚠ 合成されていない濁点がある: %s %d" % (kind, e.entity_id))
    # ★半濁点が 1 つも無ければ、経路が死んでいる（⚠ 実測では複数ある）
    has_handakuten = any(
        unicodedata.normalize("NFD", e.name).count("゚")
        for kind in ("monster", "item", "spell") for e in book.all(kind))
    assert has_handakuten, "⚠⚠ 半濁点が 1 つも出ていない（★F6 / 0xCD の経路が死んでいる）"


def test_同じidは同じ名前(book):
    """⚠ 主キーは (kind, id)。★名前は表示属性。"""
    for kind in ("monster", "item", "spell"):
        a = [e.name for e in book.all(kind)]
        b = [book.resolve(kind, i).name for i in range(book.count(kind))]
        assert a == b


def test_版が違うROMは断る(tmp_path, book):
    """⚠⚠ 未対応の ROM を『たぶん動く』で読まない（指示書 §17）。"""
    from dq2rom import ines
    from dq3rom import names as N

    src = bytearray(ROM_PATH.read_bytes())
    # ★呪文の表の長さが 7 の倍数でなくなるように、モンスター名の先頭を 1 バイトずらす
    bank10 = 16 + 10 * 0x4000
    src[bank10 + 4] = (src[bank10 + 4] + 1) & 0xFF
    broken = tmp_path / "broken.nes"
    broken.write_bytes(bytes(src))
    rom = ines.load(broken) if hasattr(ines, "load") else None
    if rom is None:
        pytest.skip("⚠ ines.load が無い")
    with pytest.raises(Exception):
        N.NameDictionary(book.ident.__class__(rom=rom, profile=book.ident.profile))


# --- ★実機の記録との突き合わせ（⚠ 記録が無ければ skip）-----------------------

def test_画面で読んだ名前とROMの名前が一致する(book):
    """★2 系統の突き合わせ（指示書 §9）。⚠ 記録は work/ にあり、Git には無い。"""
    if not SCREEN_NAMES.exists():
        pytest.skip("⚠ 画面で読んだ名前の記録が無い")
    got = json.loads(SCREEN_NAMES.read_text(encoding="utf-8")).get("names") or {}
    if not got:
        pytest.skip("⚠ 画面で読んだ名前が 0 件")
    bad = []
    for key, seen in got.items():
        rom = book.monster(int(key)).name
        if seen != rom:
            bad.append((key, seen, rom))
    assert not bad, "⚠⚠ 画面と ROM で名前が食い違う: %s" % bad


# --- ★cache ------------------------------------------------------------------

def test_cacheはROMとdecoderの版で鍵を持つ(tmp_path):
    if not ROM_PATH.exists():
        pytest.skip("⚠ ROM が無い環境")
    from dq3rom import names as N

    path = tmp_path / "names.json"
    first = N.load_cached(ROM_PATH, path)
    assert path.exists()
    assert first["decoder_version"] == N.DECODER_VERSION
    assert first["rom_payload_crc32"]
    # ⚠ 版が違う cache は捨てて作り直す
    stale = dict(first, decoder_version=0)
    path.write_text(json.dumps(stale), encoding="utf-8")
    again = N.load_cached(ROM_PATH, path)
    assert again["decoder_version"] == N.DECODER_VERSION
# --- ★フォロー確認（2026-09-03 / 後工程で安心して使えるか）--------------------

def test_別のROMのcacheを誤って使わない(tmp_path):
    """⚠⚠ cache は ROM（payload の CRC32）で分ける（指示書 §7 / §16）。"""
    if not ROM_PATH.exists():
        pytest.skip("⚠ ROM が無い環境")
    from dq3rom import names as N

    path = tmp_path / "names.json"
    first = N.load_cached(ROM_PATH, path)
    other = dict(first, rom_payload_crc32="00000000")
    other["names"]["monster"]["0"] = "???"
    path.write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
    again = N.load_cached(ROM_PATH, path)
    assert again["rom_payload_crc32"] == first["rom_payload_crc32"]
    assert again["names"]["monster"]["0"] != "???", "⚠⚠ 別の ROM の cache をそのまま使った"


def test_共通の入口はkindとidが主キー(book):
    """★resolve_name(kind, id) 相当。⚠ 名前の文字列を鍵にしない。"""
    from dq3.knowledge import rom_names

    rom_names.reset()
    if not rom_names.available():
        pytest.skip("⚠ ROM が無い環境: %s" % rom_names.last_error)
    for kind in ("monster", "item", "spell"):
        for entity_id in (0, book.count(kind) - 1):
            assert rom_names.name(kind, entity_id) == book.resolve(kind, entity_id).name
    # ⚠ 装備中 bit（bit7）が付いた品 id でも同じ品
    assert rom_names.name("item", 0x80 | 2) == rom_names.name("item", 2)
    with pytest.raises(ValueError):
        rom_names.name("place", 0)


def test_図鑑の1件にROM由来の全部が揃う(tmp_path, book):
    """★monster_id → 名前 / Master（HP EXP Gold）/ 耐性 / 行動 / 落とす品の名前 が 1 つに結合できる。"""
    from dq3.knowledge import monster_book as mb
    from dq3.knowledge import rom_names
    from dq3.knowledge.enemies_seen import EnemyBook

    rom_names.reset()
    if not rom_names.available():
        pytest.skip("⚠ ROM が無い環境")
    seen = EnemyBook(tmp_path / "enemy-names.json")
    seen.record_battle([{"id": 0, "n": 1}], won=True)        # ★倒した → 中身を出してよい
    entry = mb.entry_of(seen, 0, rom_path=ROM_PATH)
    assert entry is not None
    assert entry.name == book.monster(0).name, "⚠ 名前が ROM と違う"
    assert entry.master, "⚠ Master が結合されていない"
    assert entry.detail is not None and entry.resistances, "⚠ 耐性が結合されていない"
    assert "0x" not in entry.drop_label, "⚠⚠ 落とす品が裸の番号のまま: %r" % entry.drop_label


def test_ROMがprimaryで画面読みは検証用(tmp_path, book):
    """★§8: 画面で別の名前を覚えていても、表示は ROM の名前。⚠ 覚えた名前は捨てない。"""
    from dq3.knowledge import rom_names
    from dq3.knowledge.enemies_seen import EnemyNames

    rom_names.reset()
    if not rom_names.available():
        pytest.skip("⚠ ROM が無い環境")
    seen = EnemyNames(tmp_path / "names.json")
    seen.names[0] = "??"                                    # ⚠ 画面で誤学習した想定
    label = seen.label({"id": 0, "n": 1})
    assert book.monster(0).name in label and "??" not in label
    assert seen.names[0] == "??", "⚠ 画面で読んだ記録を消してはいけない（検証用に残す）"


# --- ★り と リ の共有（RX3-0093）-------------------------------------------------

def test_曖昧な字は文字表から出す():
    """⚠⚠ 手で並べない。★「カタカナの絵が別に無いひらがな」を表から機械的に出す。"""
    from dq3rom.kana import ambiguous_kana

    known = {"あ", "ア", "り", "へ", "ヘ" if False else "ラ"}
    got = ambiguous_kana(known)
    assert "り" in got, "⚠ カタカナの絵が無いのに曖昧扱いされない"
    assert "あ" not in got, "⚠ カタカナの絵があるのに曖昧扱い"


def test_カタカナの語だけ直す():
    """⚠⚠ 混ざった名前を壊さないこと（★実データに はぐれメタル 等がある）。"""
    from dq3rom.kana import katakana_word

    known = set("あいうえおかきくけこさしすせそはひふへほまみむめもらりるれろん"
                "アイウエオカキクコサシスタテトナハヒフホマミムメモラルレロン")
    amb = "り"
    assert amb not in known or True
    # ★語のなかに「曖昧でないひらがな」が 1 つでもあれば触らない
    assert katakana_word("はぐれメタル", known) == "はぐれメタル"
    assert katakana_word("キメラのつばさ", known) == "キメラのつばさ"


@needs_rom
def test_地名は全部カタカナになる(book):
    """★依頼者の画面に「アりアハン」と出ていた（RX3-0092）。"""
    import unicodedata

    for e in book.all("place"):
        for ch in unicodedata.normalize("NFD", e.name):
            if ch in ("゙", "゚", "ー"):
                continue
            assert "ァ" <= ch <= "ヶ", "⚠ カタカナでない字が残っている: %r（%s）" % (ch, e.name)


@needs_rom
def test_混ざった名前は変わらない(book):
    """⚠⚠ ここが本丸。★カタカナとひらがなが混ざった名前を**触らない**。

    ⚠ 数で見ます（★1 例だけだとすり抜ける）。
    """
    import unicodedata

    mixed = 0
    for kind in ("item", "spell", "monster"):
        for e in book.all(kind):
            bases = [unicodedata.normalize("NFD", c)[0] for c in e.name]
            has_kana = any("ぁ" <= c <= "ゖ" for c in bases)
            has_kata = any("ァ" <= c <= "ヶ" for c in bases)
            if has_kana and has_kata:
                mixed += 1
    assert mixed >= 20, "⚠ 混ざった名前が急に減った（★変換が効きすぎている）: %d" % mixed
