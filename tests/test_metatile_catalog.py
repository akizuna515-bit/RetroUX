"""メタタイル辞書と倍率キャッシュ（2026-08-02 / マップ指示書 §18.4・§18.5）。

★★ 守りたい契約 ★★

  1. 4枚の 8×8 を正しい位置に並べて 16×16 にする
  2. 0.5 / 1 / 2 / 4 倍を作れる。⚠ **補間しない**
  3. ★キャッシュを作り直さない（指示書 §10.3）
  4. ⚠⚠ **黒観測を地形として保存しない**（指示書 §11.2）
  5. ⚠⚠ **1回の食い違いで既存の地形を上書きしない**（指示書 §12.2）
  6. FIELD_IDLE 以外では保存しない（指示書 §6.2）
"""

from __future__ import annotations

import json

import pytest

from retroux.core.bgmap import Character, Metatile
from retroux.core.bgmap.catalog import (
    AssetStore, auto_scale, pick_scale, safe_name,
)
from retroux.core.db.database import Database


class _Pal:
    def rgb(self, index):
        return (index, index & 0x3F, 0)


def _char(key: str, value: int = 1) -> Character:
    return Character(
        key=key, tile_id=0, chr_hash=key[:12], palette_signature="AA",
        pattern=tuple(tuple([value] * 8) for _ in range(8)),
        colors=(0x0F, 0x30, 0x16, 0x06))


def _metatile(key: str = "mt1", blank: bool = False) -> Metatile:
    value = 0 if blank else 1
    return Metatile(
        key=key,
        top_left=_char("a:00:AA", value), top_right=_char("b:00:AA", value),
        bottom_left=_char("c:00:AA", value),
        bottom_right=_char("d:00:AA", value),
        map_id=0x3F, x=1, y=2)


# --- 1. 4枚の並び -------------------------------------------------------

def test_4枚を正しい位置に並べる():
    """★左上・右上・左下・右下。⚠ 入れ替わると地形が読めなくなる。"""
    mt = Metatile(
        key="k",
        top_left=_char("tl", 1), top_right=_char("tr", 2),
        bottom_left=_char("bl", 3), bottom_right=_char("br", 0),
        map_id=1, x=0, y=0)
    rows = mt.rgba(_Pal())
    assert len(rows) == 16 and len(rows[0]) == 16
    # ★色番号は colors[n]。1->0x30 / 2->0x16 / 3->0x06 / 0->0x0F
    assert rows[0][0][0] == 0x30      # 左上
    assert rows[0][8][0] == 0x16      # 右上
    assert rows[8][0][0] == 0x06      # 左下
    assert rows[8][8][0] == 0x0F      # 右下


# --- 2. 倍率（指示書 §10）----------------------------------------------

def test_4つの倍率を作る(tmp_path):
    store = AssetStore(tmp_path)
    store.prepare()
    result = store.put_metatile(_metatile(), _Pal())
    assert result.metatiles == 1
    d = store.metatile_dir("mt1")
    for name in ("half", "1x", "2x", "4x"):
        assert (d / f"{name}.png").exists(), name
    assert (d / "meta.json").exists()


def test_倍率ごとの大きさ(tmp_path):
    from retroux.core.bgmap import scale_nearest

    base = _metatile().rgba(_Pal())
    assert len(scale_nearest(base, 0.5)) == 8
    assert len(scale_nearest(base, 1)) == 16
    assert len(scale_nearest(base, 2)) == 32
    assert len(scale_nearest(base, 4)) == 64


def test_倍率の選び方():
    assert pick_scale(1) == "1x"
    assert pick_scale(2) == "2x"
    assert pick_scale(4) == "4x"
    assert pick_scale(0.5) == "half"
    # ⚠ 中途半端な値でも**定義済みの中から**選ぶ（小数倍率を作らない）
    assert pick_scale(3) in ("2x", "4x")


def test_自動倍率は収まる最大を選ぶ():
    """指示書 §10.4「ウィンドウ内に収まる最大の定義済み倍率」。"""
    # 10x10 マス。4倍なら 640px 要る
    assert auto_scale(10, 10, 700, 700) == "4x"
    assert auto_scale(10, 10, 400, 400) == "2x"
    assert auto_scale(10, 10, 200, 200) == "1x"
    # ⚠ どれも収まらないなら一番小さい（勝手に小数を作らない）
    assert auto_scale(100, 100, 100, 100) == "half"


# --- 3. キャッシュ（指示書 §10.3）---------------------------------------

def test_2回目は作り直さない(tmp_path):
    """★表示のたびに拡大縮小しない。"""
    store = AssetStore(tmp_path)
    store.prepare()
    first = store.put_metatile(_metatile(), _Pal())
    assert first.metatiles == 1 and first.reused == 0
    second = store.put_metatile(_metatile(), _Pal())
    assert second.metatiles == 0 and second.reused == 1


def test_倍率が1枚欠けたら作り直す(tmp_path):
    store = AssetStore(tmp_path)
    store.prepare()
    store.put_metatile(_metatile(), _Pal())
    (store.metatile_dir("mt1") / "4x.png").unlink()
    assert store.has_metatile("mt1") is False
    again = store.put_metatile(_metatile(), _Pal())
    assert again.metatiles == 1


def test_鍵にコロンがあってもファイルにできる():
    """⚠ Windows は `:` をファイル名に使えない。"""
    assert ":" not in safe_name("abc:01:0F30")
    assert safe_name("abc:01:0F30") == "abc_01_0F30"


def test_元の鍵はjsonに残る(tmp_path):
    store = AssetStore(tmp_path)
    store.prepare()
    store.put_character(_char("abc123456789:0A:0F30"), _Pal())
    path = store.characters / "abc123456789_0A_0F30.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    # ★ファイル名は置き換えても、中身には元の鍵が入っている
    assert data["character_key"] == "abc123456789:0A:0F30"


# --- 4. 黒観測（指示書 §11.2）-------------------------------------------

def test_全部が地の色なら保存しない(tmp_path):
    """⚠⚠ **ここが落ちると、暗転中の1枚で床や壁が塗りつぶされる。**"""
    store = AssetStore(tmp_path)
    store.prepare()
    result = store.put_metatile(_metatile("black", blank=True), _Pal())
    assert result.metatiles == 0
    assert result.skipped_blank == 1
    assert not store.metatile_dir("black").exists()


def test_黒を見送ったことは数に残る(tmp_path):
    """★黙って捨てない（指示書 §11.2「解析ログへ理由を記録する」）。"""
    store = AssetStore(tmp_path)
    store.prepare()
    result = store.put_metatile(_metatile("black", blank=True), _Pal())
    assert result.skipped_blank == 1


def test_画像が無ければNoneを返す(tmp_path):
    store = AssetStore(tmp_path)
    store.prepare()
    assert store.image_path("ない鍵") is None
    store.put_metatile(_metatile(), _Pal())
    assert store.image_path("mt1", "2x") is not None
    # ⚠ 知らない倍率名は None（勝手に作らない）
    assert store.image_path("mt1", "3x") is None


# --- 5. DB（指示書 §12.2・§12.3）---------------------------------------

@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "t.sqlite3")
    database.register_rom("HASH", "テスト", "JP", mapper=2)
    yield database
    database.close()


def test_初回はprovisional(db):
    got = db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA")
    assert got == "provisional"


def test_同じものを重ねると確度が上がる(db):
    assert db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA") \
        == "provisional"
    assert db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA") == "probable"
    assert db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA") == "confirmed"


def test_1回の食い違いで上書きしない(db):
    """⚠⚠ **ここが今回いちばん大事。**

    暗転・メニュー・移動途中の1枚で、何度も見て確かめた地形を消さない。
    """
    for _ in range(3):
        db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA")
    got = db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyB")
    assert got == "conflict"
    cells = db.visited_metatiles("HASH", 0x3F, 0x8000)
    assert len(cells) == 1
    # ★元の鍵が残っている（上書きされていない）
    assert cells[0][2] == "keyA"
    assert cells[0][4] == "conflict"


def test_食い違いで回数を増やさない(db):
    """⚠ 増やすと「何度も見た」ように見えてしまう。"""
    db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA")
    before = db.visited_metatiles("HASH", 0x3F, 0x8000)[0][3]
    db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyB")
    after = db.visited_metatiles("HASH", 0x3F, 0x8000)[0][3]
    assert after == before


def test_FIELD_IDLE以外では保存しない(db):
    """指示書 §6.2。★移動中・メニュー中の背景を地形にしない。"""
    for state in ("FIELD_MOVING", "FIELD_MENU", "MAP_TRANSITION", "UNKNOWN"):
        got = db.record_metatile("HASH", 0x3F, 0x8000, 5, 5, "keyX",
                                 source_state=state)
        assert got == "ignored", state
    assert db.visited_metatiles("HASH", 0x3F, 0x8000) == []


def test_鍵が空なら何もしない(db):
    assert db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "") == "ignored"
    assert db.visited_metatiles("HASH", 0x3F, 0x8000) == []


def test_マップはidとポインタの両方で見分ける(db):
    """指示書 §18.5「map_idとmap_ptrの両方でマップを識別する」。"""
    db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA")
    db.record_metatile("HASH", 0x3F, 0x9000, 1, 2, "keyB")
    a = db.visited_metatiles("HASH", 0x3F, 0x8000)
    b = db.visited_metatiles("HASH", 0x3F, 0x9000)
    assert a[0][2] == "keyA"
    assert b[0][2] == "keyB"


def test_鍵の無いマスは返さない(db):
    """⚠ 古い記録（色だけ）を混ぜない。★0 と不明を混ぜない。"""
    db.mark_visited("HASH", 0x3F, 0x8000, 9, 9, color="123")
    assert db.visited_metatiles("HASH", 0x3F, 0x8000) == []


def test_既存の歩いた記録を壊さない(db):
    """⚠ 指示書 §19「既存のマップDB…を壊していない」。"""
    db.mark_visited("HASH", 0x3F, 0x8000, 1, 2, color="ABC", tile="B0")
    db.record_metatile("HASH", 0x3F, 0x8000, 1, 2, "keyA")
    tiles = db.visited_tiles("HASH", 0x3F, 0x8000)
    assert len(tiles) == 1
    assert tiles[0][3] == "ABC"        # ★色が消えていない


# --- 6. CHR の正本（指示書 §7.4）---------------------------------------

def test_CHRの生バイトを残せる(tmp_path):
    """⚠ 2026-08-02 に渡し忘れて raw_chr が 0 件だった。

    ★PNG は表示用。**元のバイト**を残しておかないと、
      後からパレットを変えて作り直すことができない（指示書 §7.4「正本」）。
    """
    store = AssetStore(tmp_path)
    store.prepare()
    chr_data = bytes(range(256)) * 4          # 十分な長さ
    store.put_metatile(_metatile(), _Pal(), chr_data=chr_data)
    saved = list(store.raw_chr.glob("*.bin"))
    assert saved, "★CHR の生バイトが残っていない"
    assert all(len(p.read_bytes()) == 16 for p in saved)


def test_CHRを渡さなくても保存はできる(tmp_path):
    """⚠ 渡せない場面（古い採取データ）でも止めない。"""
    store = AssetStore(tmp_path)
    store.prepare()
    result = store.put_metatile(_metatile(), _Pal())
    assert result.metatiles == 1
    assert list(store.raw_chr.glob("*.bin")) == []
