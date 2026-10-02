"""場所の名前を**読み（かな）**で照合する（RX3-0292 / 2026-09-18）。

⚠⚠ 依頼者「オリビアの岬の情報を得たら、オリビアの岬を表示させたい。ここ仕様甘い気がする」
→ ★レポートのあと「まずは A（名簿に読みを足して、かな同士で照合）を対応しよう」

```text
名簿   岬の洞窟 / ナジミの塔 / 幽霊船 …        ★人が書いた漢字まじり
会話   ＊「みさきのどうくつには …           ★ゲームの本文は全部かな（⚠ 文は架空）
照合   `fold` はカタカナ → ひらがなだけ       ⚠⚠ 漢字は**永久に当たらない**
```

★だから「行ってみる？」の `BY_TALK`（会話で聞いた場所）は、⚠ 20 件の町にしか効いていなかった。
"""
from __future__ import annotations

import io
import pathlib

import pytest

from dq3.knowledge import place_readings as PR
from dq3.knowledge import reachable as RE

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★ゲームの会話と**同じ形**の架空の文（★全部かな / ⚠ 原作の会話は公開物に入れません / RX3-0433）。
#:   ⚠⚠ 地名と、★名前のすぐ後ろの助詞（`に`）だけは本物と同じにしてあります
#:   （★`reachable.spoken` は後ろの 1 字を見るので、ここを変えると検査の意味が変わります）。
TALK = ("＊「みさきのどうくつには ぬけみちが あるらしい。"
        "＊「ナジミのとうに のぼると とおくまで みえるぞ。"
        "＊「きたのやまおくに だーまのしんでんが あるそうだ。")


def _table(tmp_path, rows) -> pathlib.Path:
    path = tmp_path / "place-readings.csv"
    io.open(path, "w", encoding="utf-8", newline="").write(
        "name,reading\n" + "\n".join("%s,%s" % (n, r) for n, r in rows) + "\n")
    return path


# --- ★読みの表 ---------------------------------------------------------------

def test_読みを読める(tmp_path):
    got = PR.load(_table(tmp_path, [("岬の洞窟", "みさきのどうくつ")]))
    assert got == {"岬の洞窟": "みさきのどうくつ"}


def test_空の読みは入れない(tmp_path):
    """⚠ 「まだ分からない」を入れない（★推測で埋めない）。"""
    got = PR.load(_table(tmp_path, [("竜の女王の城", ""), ("火山", "かざん")]))
    assert got == {"火山": "かざん"}


def test_かなでない読みは読まずに理由を残す(tmp_path):
    """⚠⚠ 漢字まじりの「読み」は効かない → ★黙って受けずに、直す手がかりを残す。"""
    got = PR.load(_table(tmp_path, [("岬の洞窟", "岬のどうくつ")]))
    assert got == {}
    assert PR.problems and "岬の洞窟" in PR.problems[0]


def test_表が無くても落ちない(tmp_path):
    assert PR.load(tmp_path / "ない.csv") == {}


def test_正本が下書きより先(tmp_path, monkeypatch):
    """★`input/` に置かれたらそちらを使う（⚠ `work/` は下書き）。"""
    master = _table(tmp_path, [("火山", "かざん")])
    draft = _table(tmp_path / "d", [("火山", "ひやま")]) if (tmp_path / "d").mkdir() is None else None
    monkeypatch.setattr(PR, "MASTER_PATH", master)
    monkeypatch.setattr(PR, "DRAFT_PATH", draft)
    assert PR.load() == {"火山": "かざん"}
    monkeypatch.setattr(PR, "MASTER_PATH", tmp_path / "ない.csv")
    assert PR.load() == {"火山": "ひやま"}


# --- ★照合 -------------------------------------------------------------------

def test_漢字の名前は読みでだけ当たる():
    assert not RE.spoken("岬の洞窟", TALK), "⚠ 漢字のまま当たった（★この検査が何も見ていない）"
    assert RE.spoken("岬の洞窟", TALK, "みさきのどうくつ")


def test_読みが無ければ今までどおり():
    """★カタカナの名前は前から当たる（⚠ 読みは要らない）。"""
    assert RE.spoken("ナジミの塔", TALK, "ナジミのとう")
    assert RE.spoken("アリアハン", "＊「アりアハンから きました。")


def test_会話に無ければ当たらない():
    assert not RE.spoken("幽霊船", TALK, "ゆうれいせん")


def test_助詞の見張りは効いたまま():
    """⚠ RX3-0178: 「まいられた」が「マイラ」に当たるのを止める決まりを壊さない。"""
    assert not RE.spoken("マイラ", "＊「とおくから まいられた おかたですね?")
    assert RE.spoken("マイラ", "＊「まいらへ いきました。")


def test_短すぎる読みは見ない():
    """⚠ 2 文字以下は誤って当たる（★`MIN_NAME`）。"""
    assert not RE.spoken("火山", "かざんへ", "かざ")


# --- ★「行ってみる？」まで ----------------------------------------------------

class _Master:
    """★名簿の代わり（⚠ 1 つの話が 2 か所を指す）。"""

    class _Topic:
        topic_id = "T1"
        related_location_names = ("岬の洞窟", "幽霊船")

    topics = {"T1": _Topic()}


class _Book:
    locations: dict = {}

    def state(self, _topic_id):
        raise KeyError


def test_塔や洞窟も会話で聞けば出る(tmp_path, monkeypatch):
    """★これが直したかったこと（⚠ 以前は `BY_TOPIC` の場所しか出なかった）。"""
    monkeypatch.setattr(PR, "MASTER_PATH", _table(tmp_path, [("岬の洞窟", "みさきのどうくつ")]))
    monkeypatch.setattr(PR, "DRAFT_PATH", tmp_path / "ない.csv")
    got = RE.collect(_Book(), None, _Master(), conversations={"9/1": [{"text": TALK}]},
                     rom_path=tmp_path / "ない.nes")
    names = {r.name: r.why for r in got}
    assert "岬の洞窟" in names and RE.BY_TALK in names["岬の洞窟"], names
    # ⚠ 会話に出ていない場所は出さない（★ネタバレにしない）
    assert "幽霊船" not in names, names


def test_読みが無い名前は出ない(tmp_path, monkeypatch):
    """⚠ 読みを入れるまでは今までどおり（★勝手に当てない）。"""
    monkeypatch.setattr(PR, "MASTER_PATH", tmp_path / "ない.csv")
    monkeypatch.setattr(PR, "DRAFT_PATH", tmp_path / "ない2.csv")
    # ⚠⚠ 2026-09-27（RX3-0432）: `all_place_names` が**本物の記録**
    #   （`player-knowledge.json` の 57 件）も語彙に入れるようになりました。
    #   ★空の master だけでは語彙が空にならないので、⚠ 記録の側も隔離します。
    got = RE.collect(_Book(), None, _Master(), conversations={"9/1": [{"text": TALK}]},
                     rom_path=tmp_path / "ない.nes",
                     knowledge_path=tmp_path / "ない.json")
    # ⚠⚠ 2026-09-27: もとは `== []` でした。★それは**たまたま**真だっただけで、
    #   ⚠ かなの名前が語彙に入ると破れます（★`location-names.csv` に
    #     `ナジミのとう` を足したら実際に破れた）。
    #   → ★見たいのは「**読みが無い漢字の名前**が当たらないこと」だけ。
    names = [r.name for r in got]
    assert "岬の洞窟" not in names, "⚠⚠ 読みが無いのに漢字の名前が当たった: %s" % names
    assert "幽霊船" not in names, names


def test_下書きが用意されている():
    """★`work/` の下書き（⚠ Git の外）に、漢字を含む名前が並んでいること。"""
    path = ROOT / "work" / "dq3-knowledge" / "place-readings.csv"
    if not path.exists():
        pytest.skip("⚠ 下書きがまだ無い（★`work/` は Git の外）")
    text = io.open(path, encoding="utf-8-sig").read()
    assert "岬の洞窟,みさきのどうくつ" in text
    assert "name,reading" in text.splitlines()[0]
