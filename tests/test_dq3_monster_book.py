"""モンスター図鑑（RX3-0040 / 2026-09-01）。

★`RX3-0035`（絵）・`RX3-0036`（性能）・`RX3-0039`（行動・耐性・ドロップ）を
1 か所で見られるようにしました。

## ⚠⚠ ここで守ること

```text
会っていない敵   ⚠ 一覧に出さない（★存在も伏せる）
会った           ★名前・絵・基本性能
倒した           ★＋ 行動・耐性・ドロップ
```

⚠ 「会った」で基本性能まで出すのは、★戦闘中の帯が既に出しているためです。
⚠⚠ ここだけ隠しても**戦えば見えて**しまい、隠したことになりません。
"""

from __future__ import annotations

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
UI = ROOT / "dq3" / "ui"


def _rom_ready() -> bool:
    try:
        from dq3rom import profile as dq3

        dq3.load_and_identify(ROM_PATH)
    except Exception:
        return False
    return True


needs_rom = pytest.mark.skipif(not _rom_ready(), reason="DQ3 の ROM が読めない")


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                # pragma: no cover
        pytest.skip("Qt が無い環境")
    got = QApplication.instance()
    yield got if got is not None else QApplication([])


def _book(met=(0, 1), defeated=(0,), names=None):
    """★使い捨ての図鑑（⚠ 本物のセーブは触りません）。"""
    from dq3.knowledge.enemies_seen import EnemyBook

    got = EnemyBook(path=pathlib.Path(os.devnull))
    got.met = set(met)
    got.defeated = set(defeated)
    got.names = dict(names or {0: "スライム", 1: "おおがらす", 2: "まほうつかい"})
    return got


class _VM:
    def __init__(self, book):
        self.enemy_book = book


# --- ★★ No-Spoiler（⚠ ここが本体）------------------------------------------


@needs_rom
def test_会っていない敵は一覧に出ない():
    """★★★ ⚠⚠ **存在ごと伏せる**（指示書 §10）★★★"""
    from dq3.knowledge import monster_book as mb

    book = _book(met=(0, 1), defeated=(0,))
    ids = [e.enemy_id for e in mb.entries(book)]
    assert ids == [0, 1], ids
    assert mb.entry_of(book, 2) is None, "⚠⚠ 会っていない敵が出た"
    assert mb.entry_of(book, 138) is None


@needs_rom
def test_倒していない敵は中身を出さない():
    """★★★ ⚠⚠ **これが No-Spoiler の本体** ★★★"""
    from dq3.knowledge import monster_book as mb

    book = _book(met=(0, 1), defeated=(0,))
    open_one = mb.entry_of(book, 0)
    locked = mb.entry_of(book, 1)

    assert open_one.defeated and not open_one.locked
    assert open_one.actions, "⚠ 倒した敵の行動が出ていない"
    assert open_one.resistances, "⚠ 倒した敵の耐性が出ていない"
    assert open_one.drop, "⚠ 倒した敵のドロップが出ていない"

    assert locked.locked, "⚠⚠ 倒していないのに開いている"
    assert locked.actions == (), "⚠⚠ 倒していない敵の行動が漏れた"
    assert locked.resistances == (), "⚠⚠ 倒していない敵の耐性が漏れた"
    assert locked.drop == {}, "⚠⚠ 倒していない敵のドロップが漏れた"
    assert locked.detail is None, "⚠⚠ raw ごと漏れている"


@needs_rom
def test_会っただけでも基本性能は出す():
    """⚠ ここだけ隠しても、★戦闘中の帯が既に出しています。

    ⚠⚠ 「隠したつもり」を作らない。
    """
    from dq3.knowledge import monster_book as mb

    locked = mb.entry_of(_book(met=(1,), defeated=()), 1)
    assert locked.master, "⚠ 基本性能まで隠している（★帯と食い違う）"
    assert locked.name


@needs_rom
def test_件数に全体数を出さない():
    """⚠⚠ 「139 体中 12 体」と出すと、★**残りの数が分かります**。"""
    from dq3.knowledge import monster_book as mb

    got = mb.counts(_book(met=(0, 1, 5), defeated=(0,)))
    assert got == {"met": 3, "defeated": 1}
    assert "total" not in got and "all" not in got

    src = (UI / "monster_book_window.py").read_text(encoding="utf-8")
    assert "139" not in src, "⚠⚠ 画面に全体数が書いてある"


# --- ★確度を崩さない --------------------------------------------------------


@needs_rom
def test_確度の低い耐性を図鑑に出さない():
    """⚠⚠ `unresolved` / `inferred` を出すと、★「そう決まっている」と読まれる。

    ★`RX3-0039` で確度を分けたので、⚠ 画面でそれを崩さないこと。
    """
    from dq3.knowledge import monster_book as mb
    from dq3rom import enemy_detail as det

    shown = {key for key, _ in mb.SHOWN_RESISTANCES}
    good = {name for _, _, _, name, conf in det.RESISTANCES
            if conf == "confirmed"}
    assert shown <= good, "⚠⚠ 確度の低い耐性を出している: %s" % (shown - good)
    weak = {name for _, _, _, name, conf in det.RESISTANCES
            if conf in ("unresolved", "inferred")}
    assert not (shown & weak), "⚠⚠ %s" % (shown & weak)


@needs_rom
def test_行動を確率として出さない():
    """⚠⚠ 8 枠の重複は、★そのまま `n/8` にはなりません（`RX3-0039`）。

    ⚠ 選択は重み表 `off_68406` を使うため、**確率とは書かない**。
    """
    from dq3.knowledge import monster_book as mb
    from dq3.ui import monster_book_window as win

    entry = mb.entry_of(_book(met=(0,), defeated=(0,)), 0)
    rows = dict(win.summary_lines(entry))
    assert "行動" in rows
    text = rows["行動"]
    assert "/8" not in text and "%" not in text, (
        "⚠⚠ 確率のように見える書き方をしている: %s" % text)
    assert " x" in text or len(entry.actions) == 8


@needs_rom
def test_倒していない敵には見出しごと出さない():
    """⚠ 空欄にすると「行動が無い敵」に見えます。★理由を書きます。"""
    from dq3.knowledge import monster_book as mb
    from dq3.ui import monster_book_window as win

    rows = dict(win.summary_lines(mb.entry_of(_book(met=(1,), defeated=()), 1)))
    assert "行動" not in rows and "耐性" not in rows and "落とす" not in rows
    assert "中身" in rows and "倒して" in rows["中身"]


def test_共有しているIDに勝手な名前を付けない():
    """★★★ ⚠⚠ **どれがどれか分からないものに、名前を付けない** ★★★

    ⚠ `breath_0A`〜`0F` と `spell_single_13`〜 は、★複数の ID が
      **同じ関数**を指しています（`RX3-0039`）。
      ⚠⚠ 「0x0F は こごえるふぶき」のように断定すると、
        **調べていないことを調べたように**見せてしまいます。

    ★分類 ＋ 番号（`ブレス(0F)`）で出します。
    ★攻撃呪文だけは ROM の表で呪文が決まる（RX3-0224）→ ⚠ それでも `MOVE_LABEL` には書かない（名前は ROM から実行時に）。
    """
    from dq3.knowledge import monster_book as mb
    from dq3rom import enemy_detail as det

    shared = [name for name in det.MOVE_NAMES
              if name.startswith(("breath_", "spell_single_", "spell_party_",
                                  "heal_single_", "heal_multi_",
                                  "reinforce_specific_"))]
    assert shared, "⚠ 共有している ID が無い（★前提が変わった）"
    for name in shared:
        assert name not in mb.MOVE_LABEL, (
            "⚠⚠ 共有 ID に名前を付けている: %s" % name)

    # ★ブレスは ROM の表で種類と幅になる（RX3-0278）。⚠ ROM が無ければ番号のまま
    assert mb.move_label("breath_0F", 0x0F, "breath", ROOT / "missing.nes") == "ブレス(0F)"
    assert mb.move_label("chant_sleep", 0x22, "spell_status") == "ラリホー"


@needs_rom
def test_ブレスはROMの表で種類とダメージの幅():
    """★RX3-0278 依頼者「特技のブレスの後の１６進数を解析して表示したい」。

    ★JP bank 4 `$B56A` の (基数, 幅) を `$BF58` が読む（索引 = 行動 + $15 - $13）。
    ★炎 / 冷気は `$8E7B` の `CMP #$0D`。⚠ 名前（原作の技の名前）は付けない。
    """
    from dq3.knowledge import monster_book as mb
    from dq3rom import enemy_detail as det
    from dq3rom import profile as dq3

    ident = dq3.load_and_identify(ROM_PATH)
    got = {m: det.breath_damage(ident, m) for m in range(0x0A, 0x10)}
    assert got == {0x0A: ("fire", 6, 9), 0x0B: ("fire", 30, 39), 0x0C: ("fire", 80, 99),
                   0x0D: ("cold", 9, 20), 0x0E: ("cold", 40, 59), 0x0F: ("cold", 100, 139)}, got
    assert det.breath_damage(ident, 0x09) is None and det.breath_damage(ident, 0x10) is None
    # ★依頼者 2026-09-16「炎と冷気は、弱中強とかでいいや」→ 札は強さ、ヒントだけ幅
    assert [mb.move_label("breath_%02X" % m, m, "breath") for m in range(0x0A, 0x10)] == [
        "炎ブレス(弱)", "炎ブレス(中)", "炎ブレス(強)", "冷気ブレス(弱)", "冷気ブレス(中)", "冷気ブレス(強)"]
    assert mb.breath_label(0x0B, with_range=True) == "炎ブレス(中) 30〜39"
    for kind in (range(0x0A, 0x0D), range(0x0D, 0x10)):          # ★弱中強が表の幅の順と合う
        lows = [got[m][1] for m in kind]
        assert lows == sorted(lows) and len(set(lows)) == 3, lows
    # ★いちばん強い冷気（0F）を持つのは HP 1023 の 2 体だけ（★表の並びが強さと合う）
    zoma = [i for i in range(140) if (d := mb._detail_of(i)) is not None
            and any(a["move_id"] == 0x0F for a in d.actions)]
    assert zoma == [133, 134], zoma


@needs_rom
def test_ブレスの表を読む命令が合わなければ番号に戻す():
    """⚠ 黙って別の場所を読まない（★読む命令・分かれ目の命令・表の頭のどれを壊しても None）。"""
    from dq3rom import enemy_detail as det
    from dq3rom import profile as dq3

    prg = bytes(dq3.load_and_identify(ROM_PATH).rom.prg)
    assert det.breath_damage(prg, 0x0B) == ("fire", 30, 39)
    for needle in (det._DAMAGE_READER, det._BREATH_KIND):
        at = prg.find(needle)
        assert at > 0
        broken = prg[:at + 4] + bytes([prg[at + 4] ^ 0xFF]) + prg[at + 5:]
        assert det.breath_damage(broken, 0x0B) is None, "⚠⚠ 命令が違うのに表を信じた"
    assert det.breath_damage(prg[:det.DAMAGE_RANGE_TABLE["file"] + 3], 0x0B) is None


@needs_rom
def test_回復と即死と仲間を呼ぶはROMの表で中身を出す():
    """★RX3-0278 依頼者「お願い」（かいふく(33) などの番号も解析）。

    ★回復 $94D7 / $9516 → $B541 / $B544、即死 $8FE4 / $907F → $90AE、仲間 $8E0F → $8E4B（★敵 ID）。
    """
    from dq3.knowledge import monster_book as mb
    from dq3.knowledge import rom_names
    from dq3rom import enemy_detail as det
    from dq3rom import profile as dq3

    ident = dq3.load_and_identify(ROM_PATH)
    spells = {m: det.shared_move_target(ident, m) for m in (0x1F, 0x20, *range(0x31, 0x3B))}
    assert all(v is not None and v[0] == "spell" for v in spells.values()), spells
    names = {m: rom_names.spell(v[1]) for m, v in spells.items()}
    assert names[0x1F] == "ザキ" and names[0x20] == "ザラキ"
    assert [names[m] for m in range(0x31, 0x36)] == ["ホイミ", "ベホイミ", "ベホマ", "ベホマラー", "ベホマズン"]
    assert [names[m] for m in range(0x36, 0x3B)] == [names[m] for m in range(0x31, 0x36)], "★31〜35 と 36〜3A は同じ呪文"
    calls = [det.shared_move_target(ident, m) for m in range(0x3B, 0x40)]
    assert all(c is not None and c[0] == "monster" for c in calls), calls
    # ★有名な組で裏を取る（さまようよろい → ホイミスライム / マドハンド → だいまじん / ⚠ 敵 ID は ROM の名前で確かめる）
    assert rom_names.monster(27) == "さまようよろい" and rom_names.monster(105) == "マドハンド"
    assert "なかまをよぶ(ホイミスライム)" in mb.card_extras(mb._detail_of(27))["special"].split()
    assert "なかまをよぶ(だいまじん)" in mb.card_extras(mb._detail_of(105))["special"].split()
    assert mb.move_label("heal_single_33", 0x33, "heal") == "ベホマ"
    assert mb.move_label("heal_single_33", 0x33, "heal", ROOT / "missing.nes") == "かいふく(33)"


@needs_rom
def test_回復と即死と仲間を呼ぶの命令が合わなければ番号に戻す():
    """⚠ 読む命令を 1 バイト壊したら None（★黙って別の場所を読まない）。"""
    from dq3rom import enemy_detail as det
    from dq3rom import profile as dq3

    prg = bytes(dq3.load_and_identify(ROM_PATH).rom.prg)
    cases = [(det.SHARED_MOVE_CODE["heal_single"][2], 0x33), (det.SHARED_MOVE_CODE["heal_multi"][2], 0x39),
             (det.SHARED_MOVE_CODE["reinforce"][2], 0x3C), (det.BEAT_CODE[0][1], 0x1F), (det.BEAT_CODE[1][1], 0x20)]
    for needle, move in cases:
        assert det.shared_move_target(prg, move) is not None
        at = prg.find(needle)
        broken = prg[:at + 1] + bytes([prg[at + 1] ^ 0xFF]) + prg[at + 2:]
        assert det.shared_move_target(broken, move) is None, "⚠⚠ 命令が違うのに表を信じた: %02X" % move


def test_札のヒントは耐性を全部と特技を出す():
    """★RX3-0278: 札の 1 行は「…」で切れても、ヒントには全部（⚠ 長い 1 行にしない）。"""
    import types

    from dq3.knowledge import monster_book as mb

    keys = [key for _g, rows in mb.RESIST_GROUPS for key, _l, _c in rows]
    detail = types.SimpleNamespace(
        resistances={k: {"level": 3 if i % 2 == 0 else 2} for i, k in enumerate(keys)},
        actions=[{"name": "chant_sleep", "move_id": 0x22, "category": "spell_status"}])
    got = mb.card_extras(detail, ROOT / "missing.nes")
    tip = got["tip"]
    for _g, rows in mb.RESIST_GROUPS:
        for _k, label, char in rows:
            assert "%s（%s）" % (char, label) in tip, "⚠ ヒントに %s が無い" % label
    assert "ラリホー" in tip and "ダメージ 0" in tip
    assert max(len(line) for line in tip.split(chr(10))) < 60, "⚠ 長い 1 行に並べた"
    assert "なし（どれも 7 割以上効く）" in mb.card_extras(
        types.SimpleNamespace(resistances={}, actions=[]))["tip"]


@needs_rom
def test_ハンターフライの特技は呪文の名前():
    """★RX3-0224 依頼者 2026-09-12「特技 こうげき呪文(17)」→ ★ROM の表で引いた呪文の、ROM の名前。"""
    from dq3.knowledge import monster_book as mb
    from dq3.knowledge import rom_names
    from dq3rom import enemy_detail as det
    from dq3rom import profile as dq3

    assert rom_names.monster(38) == "ハンターフライ", "⚠ 前提（敵 38）が変わった"
    detail = mb._detail_of(38)
    moves = [a["move_id"] for a in detail.actions]
    assert moves.count(0x17) == 4, moves
    spell = rom_names.spell(det.spell_of_move(dq3.load_and_identify(ROM_PATH), 0x17))
    assert spell == "ギラ"
    special = mb.card_extras(detail)["special"]
    assert "こうげき呪文" not in special, special
    assert special.split() == [spell], special
    # ★枠の数え方は今までどおり（⚠ 呪文名になっても 4 枠が 1 行にまとまる）
    assert (spell, 4) in mb.action_summary(detail)


@needs_rom
def test_呪文の行動と耐性の名前はROMの呪文名と合う():
    """⚠⚠ RX3-0245（2026-09-13 依頼者「ヘルコンドルがニフラムを使うと言っているが、バシルーラを使った」）。

    ★行動の名前（`chant_limbo` など）は北米版の呪文の語。★どの呪文かは `dq3rom/spells.py` の表（呪文 ID → 語）で決まり、
      名前は ROM の名前辞書で引ける → 手で書いた日本語が ROM の呪文名と合うかを見る（⚠ limbo を「ニフラム」と書いていた）。
    """
    from dq3.knowledge import monster_book as mb
    from dq3.knowledge import rom_names
    from dq3rom import spells as sp

    word_to_id: dict[str, set] = {}
    for spell_id, word in sp._INSTANT.items():
        word_to_id.setdefault(word, set()).add(spell_id)
    checked = 0
    for move, label in mb.MOVE_LABEL.items():
        word = move[len("chant_"):] if move.startswith("chant_") else None
        ids = word_to_id.get(word or "")
        if not ids or len(ids) != 1:
            continue                                     # ★呪文 1 つに決まる語だけ（beat は 2 つ）
        want = rom_names.spell(next(iter(ids)))
        assert label == want, "⚠⚠ %s を「%s」と書いているが ROM では「%s」" % (move, label, want)
        checked += 1
    assert checked >= 5, "⚠ 突き合わせた行動が少なすぎる: %d" % checked
    # ★ヘルコンドル（敵 69）: 8 枠中 3 枠が chant_limbo = バシルーラ
    assert rom_names.monster(69) == "ヘルコンドル", "⚠ 前提（敵 69）が変わった"
    labels = [mb.move_label(a["name"], a["move_id"], a["category"]) for a in mb._detail_of(69).actions]
    assert labels.count(rom_names.spell(22)) == 3 and rom_names.spell(21) not in labels, labels
    # ★耐性の組: limbo_slow = 呪文 22・24 / expel_fairywater = 呪文 21（★`spells.py` の耐性の表）
    #   ★RX3-0269: 並びと区切りは依頼者の表（「ボミオス・バシルーラ」「ニフラム・せいすい」）。⚠ 名前は ROM の呪文名のまま
    shown = dict(mb.SHOWN_RESISTANCES)
    assert shown["limbo_slow"] == "%s・%s" % (rom_names.spell(24), rom_names.spell(22)), shown["limbo_slow"]
    assert shown["expel_fairywater"].startswith(rom_names.spell(21)), shown["expel_fairywater"]


def test_攻撃呪文が引けなければ今までどおり番号で出す(tmp_path, monkeypatch):
    """⚠ ROM が無い / 名前辞書が作れない → 「こうげき呪文(17)」（★ROM は要らない）。"""
    import types

    from dq3.knowledge import monster_book as mb
    from dq3.knowledge import rom_names

    missing = tmp_path / "missing.nes"
    detail = types.SimpleNamespace(resistances={}, actions=[
        {"name": "spell_party_17", "move_id": 0x17, "category": "spell_damage"},
        {"name": "spell_party_17", "move_id": 0x17, "category": "spell_damage"},
        {"name": "regular_attack", "move_id": 0x02, "category": "attack"}])
    assert mb.attack_spell_name(0x17, missing) is None
    assert mb.move_label("spell_party_17", 0x17, "spell_damage", missing) == "こうげき呪文(17)"
    assert mb.card_extras(detail, missing)["special"] == "こうげき呪文(17)"
    assert ("こうげき呪文(17)", 2) in mb.action_summary(detail, missing)
    # ★表は引けても名前が引けないとき（⚠ ROM の名前辞書が作れない）も同じ
    monkeypatch.setattr(rom_names, "spell", lambda *_a, **_k: None)
    assert mb.move_label("spell_party_17", 0x17, "spell_damage") == "こうげき呪文(17)"
    assert mb.card_extras(detail)["special"] == "こうげき呪文(17)"


def test_名前をつけた行動は1つのIDに対応している():
    """⚠ 逆向き。★`MOVE_LABEL` の鍵が実在し、**重複していない**こと。"""
    from dq3.knowledge import monster_book as mb
    from dq3rom import enemy_detail as det

    known = set(det.MOVE_NAMES)
    for name in mb.MOVE_LABEL:
        assert name in known, "⚠ 実在しない行動名: %s" % name
    assert len(set(mb.MOVE_LABEL.values())) == len(mb.MOVE_LABEL), (
        "⚠ 日本語名が重複している")


# --- ★★ 窓を実際に組む（⚠ 足場だけで緑にしない）-----------------------------


@needs_rom
def test_窓を組んで一覧と中身が出る(app):
    """★★★ ⚠⚠ **本当に組んで見る** ★★★"""
    from dq3.ui.monster_book_window import Dq3MonsterBookWindow

    win = Dq3MonsterBookWindow(_VM(_book(met=(0, 1), defeated=(0,))))
    win.show()
    app.processEvents()

    assert win.list.count() == 2, "⚠ 一覧が %d 件" % win.list.count()
    assert "会った 2 体" in win.count_label.text()
    assert "倒した 1 体" in win.count_label.text()

    # ★倒した敵を選ぶと、行動・耐性・ドロップが出る
    win.list.setCurrentRow(0)
    app.processEvents()
    texts = [w.text() for w in win._body.findChildren(type(win.count_label))
             if hasattr(w, "text")]
    joined = " ".join(texts)
    assert "行動" in joined and "耐性" in joined and "落とす" in joined, joined

    # ⚠ 倒していない敵を選ぶと、中身が消える
    win.list.setCurrentRow(1)
    app.processEvents()
    texts = [w.text() for w in win._body.findChildren(type(win.count_label))
             if hasattr(w, "text")]
    joined = " ".join(texts)
    assert "まだ倒していない" in joined, joined
    # ⚠⚠ 見出し（「行動 / 耐性 / 落とすもの」）は出してよい。
    #   ★出してはいけないのは**中身**です（⚠ 語で見ると見出しに当たる）。
    assert "1/" not in joined, "⚠⚠ ドロップ率が画面に出た"
    assert "こうげき" not in joined, "⚠⚠ 行動が画面に出た"
    assert "ラリホー" not in joined, "⚠⚠ 耐性が画面に出た"
    assert "品 0x" not in joined, "⚠⚠ 落とす品が画面に出た"
    win.close()


@needs_rom
def test_1体も会っていなくても落ちない(app):
    from dq3.ui.monster_book_window import Dq3MonsterBookWindow

    win = Dq3MonsterBookWindow(_VM(_book(met=(), defeated=())))
    win.show()
    app.processEvents()
    assert win.list.count() == 0
    assert "会った 0 体" in win.count_label.text()
    win.close()


def test_図鑑が無くても落ちない(app):
    """⚠ `view_model` が図鑑を持たない場合（★起動直後など）。"""
    from dq3.ui.monster_book_window import Dq3MonsterBookWindow

    class _Empty:
        pass

    win = Dq3MonsterBookWindow(_Empty())
    win.show()
    app.processEvents()
    assert win.list.count() == 0
    win.close()


@needs_rom
def test_中身が増えても窓は大きくならない(app):
    """⚠⚠ `docs/design/dq3-ui-v0.md`「窓の大きさを中身で変えない」。"""
    from dq3.ui.monster_book_window import Dq3MonsterBookWindow

    win = Dq3MonsterBookWindow(_VM(_book(met=(0,), defeated=(0,))))
    win.show()
    app.processEvents()
    before = (win.width(), win.height())

    win.vm.enemy_book.met = set(range(40))
    win.vm.enemy_book.defeated = set(range(40))
    win.reload()
    app.processEvents()
    assert win.list.count() == 40
    assert (win.width(), win.height()) == before, (
        "⚠⚠ 40 体入れたら窓が %s → %s になった"
        % (before, (win.width(), win.height())))


@needs_rom
def test_選んでいた敵を作り直しても保つ(app):
    """⚠ 戦闘のたびに `reload()` します。★選び直しで飛ばされない。"""
    from dq3.ui.monster_book_window import Dq3MonsterBookWindow

    win = Dq3MonsterBookWindow(_VM(_book(met=(0, 1), defeated=(0,))))
    win.show()
    app.processEvents()
    win.list.setCurrentRow(1)
    assert win.current_id() == 1

    win.vm.enemy_book.met = {0, 1, 5}
    win.reload()
    app.processEvents()
    assert win.current_id() == 1, "⚠ 選んでいた敵が変わった"


# --- ⚠ 結線 ----------------------------------------------------------------


def test_ボタンから開ける():
    """⚠⚠ **窓を作っただけでは、誰も開けません**。"""
    src = (UI / "main_window.py").read_text(encoding="utf-8")
    assert '("monster", "敵", ' in src, "⚠ 図鑑のボタンが無い"
    assert "def open_monster_book" in src
    assert "Dq3MonsterBookWindow" in src
    # ⚠ 2 つ開かない（★他の窓と同じ作法）
    assert "_monster_book" in src


def test_retrouxを変えずにDQ3側で作っている():
    """⚠⚠ `RX3-0011`: `retroux/` は変更しません。"""
    assert (UI / "monster_book_window.py").exists()
    src = (UI / "monster_book_window.py").read_text(encoding="utf-8")
    assert "from retroux" not in src, (
        "⚠ DQ2 の図鑑を持ち込んでいる（★中身の作りが違う）")


# --- ★★ RX3-0042 見え方（⚠ 画面を撮って見つけた）---------------------------


@needs_rom
def test_詳細で部品が重ならない(app):
    """★★★ ⚠⚠ **入りきらないと部品が重なって描かれた** ★★★

    ## ⚠⚠ 2026-09-01 に踏んだこと

      ★中身に 520px 要るのに、⚠ 窓が 433px のままでした。
      `QScrollArea(widgetResizable=True)` は、中身を作り直しても
      **窓の高さのまま**にします。
      → ⚠ 絵（192px）が潰され、★行動の行が**絵の上に**描かれました。

      ⚠ 検査は全部緑でした。★**画面を撮って初めて**分かりました。
    """
    from dq3.ui.monster_book_window import Dq3MonsterBookWindow

    win = Dq3MonsterBookWindow(_VM(_book(met=(0, 133), defeated=(0, 133),
                                         names={0: "ス", 133: "ゾ"})))
    win.show()
    app.processEvents()
    win.list.setCurrentRow(1)
    app.processEvents()

    need = win._body_box.sizeHint().height()
    assert win._body.height() >= need - 20, (
        "⚠⚠ 中身に %d 要るのに %d しかない（★重なります）"
        % (need, win._body.height()))
    # ★入りきらないぶんはスクロールで見える
    assert (win._body.height() <= win.detail.viewport().height()
            or win.detail.verticalScrollBar().maximum() > 0), (
        "⚠⚠ はみ出しているのにスクロールできない")
    win.close()


@needs_rom
def test_絵が枠いっぱいに拡大される(app):
    """⚠⚠ **枠は 3 倍なのに、倍率を 1 倍の箱で計算していました**。

    ★いちばん大きい敵（80x64）が `240x192` にちょうど収まります。
    ⚠ 小さい敵は小さいまま（★引き伸ばして同じ大きさにしない）。
    """
    from PySide6.QtGui import QPixmap

    from dq3.knowledge import monster_art
    from dq3.ui.monster_book_window import DETAIL_H, DETAIL_W, art_scale

    # ★★ ⚠⚠ 絵は**この検査が作る**（RX3-0472 / 2026-10-01）★★
    #
    #   ⚠ 以前は `monster_art.path_of()` を直に呼び、無ければ skip していました。
    #     ⚠⚠ そのころ `ART_DIR` は `program_root` 基準で、★**依頼者の本物の
    #       `work/dq3-monster-art/` を読んでいました**（= 隔離をすり抜けていた）。
    #   ★`lazy_work` に寄せたので、いまは隔離先を見ます。⚠ そこには絵が無いので、
    #     そのままだと**この検査は永久に skip** になります（★「まっさらな環境の緑」）。
    #   → ★だから作ります。⚠ 実測 **139 枚 / 0.42 秒**なので待ち時間になりません。
    made = monster_art.ensure()
    big = monster_art.path_of(133)          # ★80x64 の大物
    assert big is not None, (
        "⚠⚠ 絵を作れませんでした（作った枚数 %d / 理由 %s）"
        % (made, monster_art.last_error))
    pix = QPixmap(str(big))
    scale = art_scale(pix)
    assert pix.width() * scale == DETAIL_W, (
        "⚠⚠ 大物が枠いっぱいにならない: %d（★%d のはず）"
        % (pix.width() * scale, DETAIL_W))
    assert pix.height() * scale == DETAIL_H

    small = monster_art.path_of(0)          # ★16x16 のスライム
    small_pix = QPixmap(str(small))
    if not small_pix.isNull():
        assert small_pix.width() * art_scale(small_pix) < DETAIL_W, (
            "⚠ 小さい敵まで枠いっぱいにしている（★大小が消える）")
