"""場所の名前と id（Location Naming v1 / RX3-0076 / locations.py）。

```text
挨拶から覚える（濁点の揺れも同じ鍵）/ ROM から地名を引かない
APPROVED だけ結ぶ（DRAFT は結ばない）/ 完全一致だけ / 世界地図では覚えない
```
"""
from __future__ import annotations

import json

import pytest

from dq3.knowledge import locations as LOC


# --- ★挨拶 ------------------------------------------------------------------------

@pytest.mark.parametrize("text, wanted", [
    # ⚠⚠ 入力は**昔の綴り**（★記録に残っているもの）。★出す形はカタカナ（RX3-0093 / 0100）
    ("＊「レーべのむらに ようこそ。", "レーベ"),
    ("＊「アりアハンの おしろにようこそ。", "アリアハン"),   # ★城（⚠ 空白と「お」/ RX3-0100）
    ("＊「ロマリアのまちに ようこそ！", "ロマリア"),
    ("＊「アリアハンのしろに ようこそ。", "アリアハン"),
    ("＊「ここは どうぐやです。", None),
    ("＊「むらに ようこそ。", None),                       # ⚠ 名前が無い
])
def test_挨拶から地名を取る(text, wanted):
    assert LOC.greeting_name(text) == wanted


def test_learnは今の_mapに結び_二度目は触らない():
    names = {}
    assert LOC.learn_from_text(names, "＊「レーべのむらに ようこそ。", 9) == "レーベ"
    assert names == {"L9": "レーベ"}
    # ⚠⚠ 2026-09-05: はじめ「ちがうまちに ようこそ」で試していて、**挨拶の形に合わず**
    #   上書きの検査になっていなかった（壊しても鳴らなかった）。★形に合う文で試す。
    assert LOC.learn_from_text(names, "＊「ベツノのまちに ようこそ。", 9) is None, "⚠ 覚えた名前を上書きした"
    assert names == {"L9": "レーベ"}
    assert LOC.learn_from_text(names, "＊「レーべのむらに ようこそ。", None) is None


# --- ★解く ------------------------------------------------------------------------

def test_覚えた名前は濁点の揺れがあっても解ける():
    cat = LOC.LocationCatalog(learned={"L9": "レーベ"})
    assert cat.resolve("レーベ") == "L9", "⚠ fold で揃わない（RX3-0070 の実測と同じ揺れ）"
    assert cat.resolve("れーべ") == "L9"


def test_部分一致や似た名前は解かない():
    cat = LOC.LocationCatalog(learned={"L9": "レーベ", "L20": "ロマリア"})
    assert cat.resolve("レー") is None and cat.resolve("ロマリアの関所") is None


def test_APPROVEDだけ結ぶ():
    table = {"L0": {"name": "アリアハン", "review_status": "APPROVED", "kind": "town"},
             "L5": {"name": "ナジミの塔", "review_status": "DRAFT", "kind": "tower"}}
    cat = LOC.LocationCatalog(table=table)
    assert cat.resolve("アリアハン") == "L0"
    assert cat.resolve("ナジミの塔") is None, "⚠⚠ DRAFT を結んだ（人の承認前）"
    assert cat.place("L5").name is None and cat.place("L0").source == "approved"


def test_実プレイの名前が表より先():
    cat = LOC.LocationCatalog(learned={"L9": "レーベ"},
                              table={"L9": {"name": "べつのなまえ", "review_status": "APPROVED"}})
    assert cat.place("L9").name == "レーベ" and cat.place("L9").source == "learned"


def test_行ったとルーラの索引が分かる():
    cat = LOC.LocationCatalog(learned={"L9": "レーベ"}, visited={"L9"}, points=[0, 9, 1])
    p = cat.place("L9")
    assert p.visited and p.rura_index == 1 and p.map_id == 9
    assert not cat.place("L1").visited and cat.place("L1").rura_index == 2


def test_名前を知らない場所を作らない():
    cat = LOC.LocationCatalog(visited={"L70"})
    assert cat.place("L70").name is None, "⚠⚠ ROM から地名を引いてはいけない"


def test_ファイルから読める(tmp_path):
    know = tmp_path / "k.json"
    know.write_text(json.dumps({"visited_locations": ["L9"], "location_names": {"L9": "レーベ"}}),
                    encoding="utf-8")
    table = tmp_path / "names.csv"
    table.write_bytes(b"\xef\xbb\xbf" + "location_id,map_id,name,kind,review_status,evidence,notes\r\n"
                      "L0,0,アリアハン,town,APPROVED,,\r\n".encode("utf-8"))
    cat = LOC.LocationCatalog.load(knowledge_path=know, names_path=table, with_rom=False,
                                   conversations_path=tmp_path / "c.json")
    assert cat.resolve("レーベ") == "L9" and cat.resolve("アリアハン") == "L0"
    assert {p.location_id for p in cat.known()} == {"L0", "L9"}


def test_無くても落ちない(tmp_path):
    cat = LOC.LocationCatalog.load(knowledge_path=tmp_path / "x.json", names_path=tmp_path / "y.csv",
                                   with_rom=False, conversations_path=tmp_path / "c.json")
    assert cat.known() == [] and cat.resolve("レーベ") is None


def test_過去の会話の記録からも地名を拾う(tmp_path):
    """★`location_names` を書く仕組みが無かった頃の記録にも挨拶が残っている。"""
    conv = tmp_path / "c.json"
    conv.write_text(json.dumps({
        "9/6": [{"text": "＊「レーべのむらに ようこそ。"}],
        "20/1": [{"text": "＊「ここは どうぐやです。"}],
        "junk": [{"text": "＊「ロマリアのまちに ようこそ。"}],
    }, ensure_ascii=False), encoding="utf-8")
    got = LOC.read_conversation_names(conv)
    assert got == {"L9": "レーベ"}
    know = tmp_path / "k.json"
    know.write_text(json.dumps({"location_names": {"L9": "レーベ"}}), encoding="utf-8")
    cat = LOC.LocationCatalog.load(knowledge_path=know, names_path=tmp_path / "n.csv",
                                   with_rom=False, conversations_path=conv)
    assert cat.place("L9").name == "レーベ", "⚠ player-knowledge の名前が先"


def test_場所の台帳の確かな名前も使う(tmp_path):
    """⚠⚠ RX3-0183（2026-09-12 依頼者「そもそもロマリア到着したのに更新されていない？」）。

    ★場所の台帳は ROM の地名で ロマリア・カザーブ を知っていたのに、勇者会議の名前の表は読んでいなかった。
    """
    know = tmp_path / "player-knowledge.json"
    know.write_text(json.dumps({"visited_locations": ["L9"], "location_names": {"L9": "レーベ"}},
                               ensure_ascii=False), encoding="utf-8")
    (tmp_path / "location-book.json").write_text(json.dumps({"locations": {
        "L1": {"display_name": "ロマリア", "name_source": "rom", "visited": True},
        "L20": {"display_name": "カザーブ", "name_source": "rom", "visited": True},
        "L43": {"display_name": "ロマリア北西の場所", "name_source": "provisional", "visited": True},
        "L9": {"display_name": "べつのなまえ", "name_source": "manual", "visited": True},
    }}, ensure_ascii=False), encoding="utf-8")
    cat = LOC.LocationCatalog.load(knowledge_path=know, names_path=tmp_path / "n.csv", with_rom=False,
                                   conversations_path=tmp_path / "c.json")
    assert cat.resolve("ロマリア") == "L1" and cat.resolve("カザーブ") == "L20", \
        "⚠⚠ 場所の台帳の名前が勇者会議に届いていない"
    assert {"L1", "L20"} <= cat.visited
    assert cat.resolve("ロマリア北西の場所") is None, "⚠ 仮名を話の決まりに当ててはいけない"
    assert cat.place("L9").name == "レーベ", "⚠ 既に知っている名前は変えない（★足すだけ）"


def test_本物の記録からレーベが拾える():
    """★会話の記録か player-knowledge のどちらかに残っている（⚠ 聞き込み履歴を初期化しても消えない）。"""
    cat = LOC.LocationCatalog.load(with_rom=False)
    if not cat.learned:
        pytest.skip("⚠ 地名の記録が無い")
    assert cat.resolve("レーベ") == "L9"


def test_拾った地名はplayer_knowledgeに残る(tmp_path):
    """⚠⚠ RX3-0077: 会話の記録から拾った名前が記憶の中だけで、聞き込み履歴の初期化で消えた。"""
    know = tmp_path / "k.json"
    assert LOC.persist_learned({"L9": "レーべ"}, know) == 1
    saved = json.loads(know.read_text(encoding="utf-8"))
    assert saved["location_names"] == {"L9": "レーべ"} and saved["visited_locations"] == []
    # ★既にある名前は触らない / 何も増えなければ書かない
    assert LOC.persist_learned({"L9": "べつ", "L1": ""}, know) == 0
    assert json.loads(know.read_text(encoding="utf-8"))["location_names"] == {"L9": "レーべ"}
    assert LOC.persist_learned({}, know) == 0
    # ★会話の記録が消えても、catalog は player-knowledge から解ける
    cat = LOC.LocationCatalog.load(knowledge_path=know, names_path=tmp_path / "n.csv", with_rom=False,
                                   conversations_path=tmp_path / "gone.json")
    assert cat.resolve("レーベ") == "L9"


# --- ★正本の表 ----------------------------------------------------------------------

def test_人が承認する表はBOM付きCRLFで名前が空():
    """★2026-09-05 の種: ルーラ表 20 ＋ 行った 3。⚠ AI は名前を入れない。"""
    raw = LOC.NAMES_PATH.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf" and raw.count(b"\n") == raw.count(b"\r\n")
    table = LOC.read_names_table()
    assert len(table) >= 20
    assert all(r.get("review_status") in ("DRAFT", "APPROVED") for r in table.values())


def test_view_modelは挨拶を聞くと地名を覚える(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel(state_path=tmp_path / "state.json", knowledge_path=tmp_path / "k.json")
    vm._raw = lambda: {"loc_kind": 1, "map_id": 9, "map_x": 1, "map_y": 1}
    # ⚠ 入力は昔の綴り（★記録に残っているもの）。⚠⚠ 出す形はカタカナ（RX3-0093 / 0100）
    assert vm._learn_place_name("＊「レーべのむらに ようこそ。") == "レーベ"
    assert vm._names == {"L9": "レーベ"}
    saved = json.loads((tmp_path / "k.json").read_text(encoding="utf-8"))
    assert saved["location_names"] == {"L9": "レーベ"}
    # ⚠ 世界地図では覚えない
    vm._raw = lambda: {"loc_kind": 0, "map_id": 0, "map_x": 1, "map_y": 1}
    assert vm._learn_place_name("＊「アリアハンのしろに ようこそ。") is None


# --- ★城の挨拶から名前と種別を取る（RX3-0100）------------------------------------

def test_城の挨拶から名前と種別を取る():
    """⚠⚠ 2026-09-07 依頼者「map70（アリアハンの城）は和名の類推が不可能？」→ ★可能。

    ★証拠は記録にありました（`npc-conversations.json` / 2026-09-05 / 2 人から）。
    ⚠ 拾えなかった理由は 2 つあり、**両方が効いていました**。

    ```text
    ⚠ ①「の」の直後の空白    ⚠ ② 丁寧の「お」しろ
    ```
    """
    from dq3.knowledge import locations as L

    # ★実際に記録されていた台詞（⚠ 作った文で決めない）
    assert L.greeting_place("＊「アりアハンの おしろにようこそ。") == ("アリアハン", "castle")
    assert L.greeting_name("＊「アりアハンの おしろにようこそ。") == "アリアハン"


def test_今までの挨拶は変わらない():
    """⚠⚠ ここが崩れると、★既に覚えた名前が変わります。"""
    from dq3.knowledge import locations as L

    assert L.greeting_place("＊「レーべのむらに ようこそ。") == ("レーベ", "village")
    assert L.greeting_name("＊「レーべのむらに ようこそ。") == "レーベ"
    # ⚠ 挨拶でない文は拾わない（★作文しない）
    assert L.greeting_place("＊「ここは アりアハンのじょうかまち。") is None
    assert L.greeting_name("＊「おうさまは このうえにおはします。") is None


def test_ほかの形の挨拶からも名前を取る():
    """⚠⚠ RX3-0188（2026-09-12 依頼者「ここはエルフの隠れ村よというが、場所が更新されない」）。

    ★見本は依頼者の記録の文を写したもの（⚠ 記録を名指しで読まない）。
    """
    from dq3.knowledge import locations as L

    # ★語順が逆（ロマリア）
    assert L.greeting_place("＊「ようこそ ロマりアのおしろに！") == ("ロマリア", "castle")
    # ★「ここは X の かくれむら よ」（⚠ 「エルフ」だけでは村の名前にならない）
    assert L.greeting_place("＊「ここは エルフのかくれむらよ。＊「あっ にんげんと はなしちゃママに しかられちゃう。") \
        == ("エルフのかくれむら", "village")
    # ★「ここは X の むら だ」
    assert L.greeting_place("＊「ここは レーべの むらだ。") == ("レーベ", "village")
    # ⚠ 種別の語が無い「ここは X。」は拾わない（★誤爆 / カザーブは ROM の町なので要らない）
    assert L.greeting_place("＊「ここは カザーブ。") is None
    assert L.greeting_place("＊「ここは だいじな ばしょなのよ。") is None
