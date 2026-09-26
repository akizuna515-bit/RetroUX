"""見た升を貯める（RX3-0023 / 2026-08-29）。

⚠⚠ ここが崩れると、★「見ていないのに描く」か「見たのに黒いまま」になります。
どちらも**遊びを壊す**ので、字面ではなく**動かして**見ます。
"""

from __future__ import annotations

import json
import pathlib

from dq3.knowledge.seen_map import (KIND_ALEFGARD, KIND_LOCAL,
                                    KIND_WORLD, WIDTH_STEP, SeenMap,
                                    map_key)
from dq3rom import viewport

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- ★映っている升をまとめて記録する ----------------------------------------

def test_画面ぶんの升をまとめて見たことにする():
    """★16x15 = 240 升（⚠ `dq3rom/viewport.py` の実測値）。"""
    seen = SeenMap(pathlib.Path("使わない"))
    added = seen.mark_view("L9", 100, 100, width=256, height=256)

    assert added == viewport.CELLS_ACROSS * viewport.CELLS_DOWN == 240
    assert seen.count("L9") == 240


def test_主人公は画面の中央に居る():
    """⚠ 主人公がいつも升 (8,7) に描かれるのが前提（★実測で確かめた）。

    ⚠⚠ ここが変わると、記録する範囲が**まるごとずれる**。
    """
    seen = SeenMap(pathlib.Path("使わない"))
    seen.mark_view("L9", 100, 100, width=256, height=256)

    assert seen.is_seen("L9", 100, 100), "⚠ 主人公の足元を見ていない"
    # ★左へ 8 / 右へ 7、上へ 7 / 下へ 7
    assert seen.is_seen("L9", 100 - viewport.HERO_CELL_X, 100)
    assert seen.is_seen("L9", 100 + 7, 100)
    assert seen.is_seen("L9", 100, 100 - viewport.HERO_CELL_Y)
    assert seen.is_seen("L9", 100, 100 + 7)
    # ⚠ その外は見ていない
    assert not seen.is_seen("L9", 100 - viewport.HERO_CELL_X - 1, 100)
    assert not seen.is_seen("L9", 100 + 8, 100)


def test_歩くと見た升が増える():
    seen = SeenMap(pathlib.Path("使わない"))
    seen.mark_view("L9", 100, 100, width=256, height=256)
    before = seen.count("L9")

    # ★右へ 1 歩 → ⚠ 増えるのは新しく入った 1 列（15 升）だけ
    added = seen.mark_view("L9", 101, 100, width=256, height=256)

    assert added == viewport.CELLS_DOWN == 15, (
        "⚠ 1 歩で増える升が %d（★1 列 15 升のはず）" % added)
    assert seen.count("L9") == before + 15


def test_同じ場所に居ても増えない():
    """⚠ 増えないことを見ないと、★保存が延々と走る。"""
    seen = SeenMap(pathlib.Path("使わない"))
    seen.mark_view("L9", 100, 100, width=256, height=256)

    assert seen.mark_view("L9", 100, 100, width=256, height=256) == 0


def test_地図の外は記録しない():
    """⚠ 端に寄ると、★地図の外まで画面に映る（実測で見ている）。

    ⚠⚠ そこを「見た」にすると、地図の外に地形が生えたように描いてしまう。
    """
    seen = SeenMap(pathlib.Path("使わない"))
    # ★左上の隅（⚠ 左と上に地図が無い）
    seen.mark_view("L9", 0, 0, width=26, height=26)

    assert not seen.is_seen("L9", -1, 0), "⚠⚠ 負の座標を記録した"
    assert seen.is_seen("L9", 0, 0)
    # ⚠ 右端の外（★幅 26 の地図で 26 列目は無い）
    seen.mark_view("L9", 25, 25, width=26, height=26)
    assert not seen.is_seen("L9", 26, 25), "⚠⚠ 地図の外を記録した"


def test_升を直に渡しても負は捨てる():
    """⚠⚠ **歯止めが 2 か所ある**（★`Viewport.contains` と `_Map.mark`）。

    ⚠ `mark_view` 経由だと `Viewport` が先に落とすので、
      ★入れ物側の歯止めは**試されない**（2026-08-29 にわざと壊して気づいた）。
    ⚠ `mark()` は外から直接呼べるので、こちらにも歯止めが要る。
    """
    seen = SeenMap(pathlib.Path("使わない"))

    assert seen.mark("L9", -1, 0) is False, "⚠⚠ 負の x を記録した"
    assert seen.mark("L9", 0, -1) is False, "⚠⚠ 負の y を記録した"
    assert seen.count("L9") == 0
    assert seen.mark("L9", 0, 0) is True


def test_大きさが分からなくても負だけは捨てる():
    """★実機では地図の大きさがまだ分からないことがある。

    ⚠ そのときも「地図の外」の最低限（負の座標）は捨てる。
    """
    seen = SeenMap(pathlib.Path("使わない"))
    seen.mark_view("L9", 2, 2)

    assert not seen.is_seen("L9", -1, 2)
    assert seen.is_seen("L9", 0, 0)


def test_地図ごとに別々に貯める():
    """⚠ ダンジョンは複数の map で 1 つの場所（★混ぜない）。"""
    seen = SeenMap(pathlib.Path("使わない"))
    seen.mark_view("L9", 100, 100, width=256, height=256)

    assert seen.count("L9") == 240
    assert seen.count("L10") == 0
    assert not seen.is_seen("L10", 100, 100)


# --- ⚠ しまう・戻す ---------------------------------------------------------

def test_閉じても記録が残る(tmp_path):
    """依頼者の確認項目: ★画面を閉じて開き直しても開けた所が残ること。"""
    path = tmp_path / "seen.json"
    seen = SeenMap(path)
    seen.mark_view("L9", 100, 100, width=256, height=256)
    seen.mark_view("L3", 5, 5, width=26, height=26)
    assert seen.save(force=True) is True

    again = SeenMap.load(path)
    assert again.cells("L9") == seen.cells("L9"), "⚠⚠ 世界地図の記録が変わった"
    assert again.cells("L3") == seen.cells("L3"), "⚠⚠ 街の記録が変わった"


def test_ビットで詰める(tmp_path):
    """⚠ 座標の一覧にすると、★世界地図を歩き回って数万件になる。"""
    path = tmp_path / "seen.json"
    seen = SeenMap(path)
    # ★世界地図をひととおり歩いたくらい（⚠ 1 万升）
    for y in range(100):
        for x in range(100):
            seen.mark("w", x, y)
    seen.save(force=True)

    size = path.stat().st_size
    assert size < 4000, "⚠⚠ 1 万升で %d バイト（★ビットなら 2KB 程度）" % size
    assert SeenMap.load(path).count("w") == 10000


def test_保存を毎回はしない(tmp_path):
    """⚠ DQ2 で地図の描き直しが 1 回 137.8 ms 掛かった。★間隔を守る。"""
    path = tmp_path / "seen.json"
    seen = SeenMap(path)
    seen.mark("L9", 1, 1)
    assert seen.save() is True          # ★1 回目は書く

    seen.mark("L9", 2, 2)
    assert seen.save() is False, "⚠⚠ 間隔を守っていない"
    assert seen.save(force=True) is True


def test_増えていなければ書かない(tmp_path):
    path = tmp_path / "seen.json"
    seen = SeenMap(path)
    seen.mark("L9", 1, 1)
    seen.save(force=True)

    assert seen.save() is False, "⚠ 増えていないのに書いた"


def test_書けなければ理由を残す(tmp_path):
    """⚠⚠ **黙って捨てない**（★`work/` は Git の外で、消えたら戻らない）。"""
    blocked = tmp_path / "ふさがれている"
    blocked.write_text("★これはフォルダではない", encoding="utf-8")
    seen = SeenMap(blocked / "seen.json")
    seen.mark("L9", 1, 1)

    assert seen.save(force=True) is False
    assert seen.failed == 1
    assert seen.last_error, "⚠ 理由が残っていない"


def test_壊れた記録でも読める(tmp_path):
    """⚠ 1 つ壊れていても、★残りは読めること。"""
    path = tmp_path / "seen.json"
    path.write_text(json.dumps({
        "version": 1,
        "maps": {"L9": {"w": 8, "h": 1, "bits": "AQ=="},
                 "L10": {"w": 16}},          # ⚠ bits が無い
    }), encoding="utf-8")

    seen = SeenMap.load(path)
    assert seen.is_seen("L9", 0, 0), "★読めるほうまで捨てている"
    assert seen.count("L10") == 0
    assert seen.failed == 1 and seen.last_error


def test_記録が無ければ空から始める(tmp_path):
    """★新しい冒険（⚠ 落ちない）。"""
    seen = SeenMap.load(tmp_path / "まだ無い.json")

    assert seen.count() == 0
    assert not seen.is_seen("L9", 0, 0)


def test_壊れた記録を消さない(tmp_path):
    """⚠⚠ 読めないからといって**消さない**（★人が見て直せるように）。"""
    path = tmp_path / "seen.json"
    path.write_text("これは JSON ではない", encoding="utf-8")

    SeenMap.load(path)

    assert path.exists(), "⚠⚠ 読めない記録を消してしまった"


def test_幅は丸めて持つ(tmp_path):
    """⚠ 1 升増えるたびに詰め直すと、★世界地図で毎回 8KB 書き直すことになる。"""
    seen = SeenMap(tmp_path / "seen.json")
    seen.mark("L9", 0, 0)
    assert seen.maps["L9"].width == WIDTH_STEP

    seen.mark("L9", WIDTH_STEP, 0)
    assert seen.maps["L9"].width == WIDTH_STEP * 2


# --- ⚠⚠ No-Spoiler ---------------------------------------------------------

def test_見ていない升は誰にも渡さない():
    """⚠⚠ **指示書 §10 / DQ2 の決定**「出すのは自分が見た所だけ」。

    ★この入れ物は「見た」以外を持たない。⚠ 持ってしまうと、
    描く側がうっかり出せてしまう。
    """
    seen = SeenMap(pathlib.Path("使わない"))
    seen.mark_view("L9", 100, 100, width=256, height=256)

    for x, y in seen.cells("L9"):
        assert 100 - 8 <= x <= 100 + 7
        assert 100 - 7 <= y <= 100 + 7


def test_ROMから地形を先に取り込んでいない():
    """⚠⚠ 貯める側が ROM を読み始めると、★「見ていないのに知っている」になる。"""
    src = (ROOT / "dq3" / "knowledge" / "seen_map.py").read_text(
        encoding="utf-8")
    body = "\n".join(L for L in src.splitlines()
                     if not L.lstrip().startswith("#"))
    for bad in ("world_map", "area_maps", "read_directory", "decode_all",
                "decode_entry", "dq3rom.profile", "DQ3_J.nes"):
        assert bad not in body, (
            "⚠⚠ 貯める側が ROM を読んでいる（%s）" % bad)
    # ⚠ 使ってよいのは升の勘定だけ（★`viewport` は座標の計算しかしない）
    assert "from dq3rom import viewport" in src


# --- ★画面とつながっていること ---------------------------------------------

def test_画面の定期処理から呼ばれている():
    """⚠⚠ 入れ物があっても**呼ばれなければ**、地図は永遠に真っ黒。"""
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    i = src.index("def refresh(self)")
    j = src.index("def ", i + 10)
    assert "self.vm.note_seen()" in src[i:j], (
        "⚠⚠ 定期処理から呼んでいない")


def test_地図を閉じていても記録する():
    """⚠ 地図の窓を閉じて遊んだぶんが飛ぶと、★次に開いて道が黒いまま。"""
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    i = src.index("self.vm.note_seen()")
    j = src.index("if self.map_window.isVisible():", i)
    assert i < j, "⚠⚠ 地図が見えているときしか記録していない"


def test_場所が届いていなければ何もしない(tmp_path, monkeypatch):
    """⚠ FCEUX がまだ書いていないとき、★(0,0) を「見た」にしない。"""
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel.__new__(Dq3ViewModel)
    vm._seen = SeenMap(tmp_path / "seen.json")
    monkeypatch.setattr(type(vm), "position", lambda self: None)

    assert vm.note_seen() == 0
    assert vm._seen.count() == 0


def test_届いた場所を見たことにする(tmp_path, monkeypatch):
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel.__new__(Dq3ViewModel)
    vm._seen = SeenMap(tmp_path / "seen.json")
    monkeypatch.setattr(type(vm), "position", lambda self: (KIND_LOCAL, 9, 50, 40))

    assert vm.note_seen() == 240
    assert vm._seen.is_seen("L9", 50, 40)
    # ⚠ 2 回目は増えない（★保存が延々と走らない）
    assert vm.note_seen() == 0


# --- ⚠⚠ 世界地図と街を混ぜない ---------------------------------------------

def test_地図の鍵は種別と番号で決まる():
    """⚠⚠ **番号だけで混ぜてはいけない。**

    ★`map_no`（`$8B`）は**ローカルのときだけ**意味がある。
    ⚠ 世界地図に出ても**前のローカルの値が残ったまま**
    （2026-08-29 実測: セーブ 10 個中 8 個が世界地図なのに `map_no=9`）。

    ⚠ ここを混ぜると、★世界地図を歩いた記録が**街の地図に化ける**。
    """
    assert map_key(KIND_WORLD) == "w"
    assert map_key(KIND_ALEFGARD) == "a"
    assert map_key(KIND_LOCAL, 9) == "L9"
    # ⚠ 世界地図で番号を渡されても、★番号を使わない
    assert map_key(KIND_WORLD, 9) == "w"
    assert map_key(KIND_ALEFGARD, 9) == "a"


def test_番号が分からないローカルは別枠():
    """⚠ 番号が無いのに `L0` などへ入れると、★別の街と混ざる。"""
    assert map_key(KIND_LOCAL, None) == "L?"
    assert map_key(KIND_LOCAL) == "L?"


def test_知らない種別も混ぜない():
    """⚠ 3 以上の種別が出てきても、★既存の地図へ流し込まない。"""
    got = map_key(7)
    assert got not in ("w", "a", "L?"), "⚠⚠ 知らない種別を既存へ混ぜた"


def test_世界と街は別々に貯まる():
    seen = SeenMap(pathlib.Path("使わない"))
    seen.mark_view(map_key(KIND_WORLD), 159, 195)
    seen.mark_view(map_key(KIND_LOCAL, 9), 19, 13)

    assert seen.count("w") == 240
    assert seen.count("L9") == 240
    # ⚠⚠ 同じ座標でも別の地図（★混ざっていないこと）
    assert not seen.is_seen("L9", 159, 195)
    assert not seen.is_seen("w", 19, 13)


# --- ★state.json から居場所を読む -------------------------------------------

def _vm(tmp_path, body):
    """★`state.json` を 1 つ置いた画面の中身を作る。"""
    from dq3.ui.view_model import Dq3ViewModel

    path = tmp_path / "state.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    vm = Dq3ViewModel.__new__(Dq3ViewModel)
    vm.state_path = path
    vm._seen = SeenMap(tmp_path / "seen.json")
    return vm


def test_世界地図の記録は世界の鍵へ(tmp_path):
    """⚠⚠ `map_id` が来ていても、★世界地図なら使わない（前の値の残り）。"""
    vm = _vm(tmp_path, {"loc_kind": 0, "map_id": 9, "map_x": 159, "map_y": 195})

    assert vm.position() == (0, 9, 159, 195)
    assert vm.note_seen() == 240
    assert vm._seen.count("w") == 240
    assert vm._seen.count("L9") == 0, "⚠⚠ 世界の記録が街に化けた"


def test_ローカルの記録は番号つきの鍵へ(tmp_path):
    vm = _vm(tmp_path, {"loc_kind": 1, "map_id": 9, "map_x": 19, "map_y": 13})

    assert vm.note_seen() == 240
    assert vm._seen.count("L9") == 240
    assert vm._seen.count("w") == 0


def test_アレフガルドも別枠(tmp_path):
    vm = _vm(tmp_path, {"loc_kind": 2, "map_x": 80, "map_y": 70})

    assert vm.note_seen() == 240
    assert vm._seen.count("a") == 240
    assert vm._seen.count("w") == 0, "⚠ 世界地図と混ざった"


def test_種別が届いていなければ何もしない(tmp_path):
    """⚠ 古い `state.json`（★種別を送る前のもの）でも落ちない。"""
    vm = _vm(tmp_path, {"map_id": 9, "map_x": 19, "map_y": 13})

    assert vm.position() is None
    assert vm.note_seen() == 0


def test_state_jsonが無くても落ちない(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel.__new__(Dq3ViewModel)
    vm.state_path = tmp_path / "まだ無い.json"
    vm._seen = SeenMap(tmp_path / "seen.json")

    assert vm.position() is None
    assert vm.note_seen() == 0


# --- ★居場所の種別（RX3-0103）----------------------------------------------------

def test_世界でない種別はローカルとして扱う():
    """⚠⚠ 2026-09-07 依頼者「save6 の洞窟で MAP が黒、名前も付けられない」。

    ★実測（`tools/fceux/fcs/DQ3_J.fc6`）:

    ```text
    kind($2F) = 5   map_no($8B) = 45   寸法($88/$89) = 58x40
    ★ROM の area map 45 も **58x40**（⚠ 完全に一致 → 番号も寸法も正しい）
    ```

    ⚠ それなのに `kind == 1` だけを「ローカル」としていたので、
    ★記録は `k5` という別枠へ行き、⚠ 場所の台帳にも入りませんでした。
    """
    from dq3.knowledge import seen_map as S

    assert S.is_local(S.KIND_LOCAL) is True
    assert S.is_local(5) is True, "⚠ 知らない種別を世界扱いしている"
    assert S.is_local(S.KIND_WORLD) is False
    assert S.is_local(S.KIND_ALEFGARD) is False
    assert S.is_local(None) is False


def test_知らない種別でも地図の鍵は番号で決まる():
    """★`k5` に落とさない（⚠ 落ちると MAP も名前も付かない）。"""
    from dq3.knowledge import seen_map as S

    assert S.map_key(5, 45) == "L45"
    assert S.map_key(S.KIND_LOCAL, 45) == "L45"
    assert S.map_key(S.KIND_WORLD, 45) == "w"
    assert S.map_key(S.KIND_ALEFGARD, 45) == "a"
    # ⚠⚠ 番号が無ければ**混ぜない**（★既存の地図へ流し込まない / 既存の決まり）
    assert S.map_key(5, None) == "k5"
    assert S.map_key(S.KIND_LOCAL, None) == "L?"
