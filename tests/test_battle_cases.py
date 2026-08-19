"""戦闘ログの資産化（2026-08-08 / 指示書 §18 Phase 1「ログSurvey」）。

指示書: `input/RetroUX_戦闘ログ_AIシナリオテスト資産化_実装指示_20260807.md`

## ★★★ Phase 1 の成果物は **報告**です

    > 既存ログを読み、何件あるか / 何が取れるか / **何が不足か** を報告。
    > コード変更は最小。

⚠⚠ **「1,204件作れます」だけ言わないこと。** ★何が取れていないのかが
分からないと、次に何をすればよいか決められません。

## ⚠ 実データで分かったこと（2026-08-08）

    action events 523 … ★**全部が回復**
    物理攻撃 0 / 攻撃呪文 0 / 道具 0

★`battle_action` を出しているのは `bridge.lua` の**回復の1か所だけ**でした。
→ ⚠ 2026-08-08 に `_record_action` へ集約し、**攻撃呪文・物理攻撃・道具**も
  記録するようになりました。上の523件は**それより前**に貯めたデータです。
"""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"

from retroux.tools import battle_cases  # noqa: E402


def _make_db(path: pathlib.Path, events: list[dict]) -> None:
    """★本物と同じ列で作る（⚠ 偽の形で試すと本番で落ちます）。"""
    con = sqlite3.connect(str(path))
    con.execute("""
        create table BattleLog (
            id integer primary key, rom_hash text, started_at text,
            ended_at text, duration_ms integer, duration_frames integer,
            monster_ids text, is_first_encounter integer, is_boss integer,
            result text, exp_gained integer, gold_gained integer,
            speed_applied real, auto_input_used integer)""")
    con.execute("""
        create table BattleEvent (
            id integer primary key, battle_id integer, turn_no integer,
            sequence_no integer, frame_no integer, kind text, actor text,
            target text, action_name text, value_before integer,
            value_after integer, delta integer, selected_by text,
            reason text, created_at text)""")
    con.execute("insert into BattleLog (id, rom_hash) values (1, 'H')")
    for i, e in enumerate(events, 1):
        con.execute(
            "insert into BattleEvent (id, battle_id, turn_no, sequence_no,"
            " kind, actor, target, action_name, selected_by, reason,"
            " value_before, value_after)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, e.get("battle_id", 1), e.get("turn_no", 1),
             e.get("sequence_no", i), e["kind"], e.get("actor"),
             e.get("target"), e.get("action_name"),
             e.get("selected_by"), e.get("reason"),
             e.get("before"), e.get("after")))
    con.commit()
    con.close()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "t.sqlite3"


def test_DBが無ければ落ちずに知らせる(tmp_path, capsys):
    """⚠ 表示のための道具で例外を投げない（★理由を出して終わる）。"""
    assert battle_cases.survey(tmp_path / "無い.sqlite3") == 1
    assert "DB がありません" in capsys.readouterr().out


def test_件数を数える(db, capsys):
    _make_db(db, [
        {"kind": "party_hp"},
        {"kind": "action", "action_name": "ホイミ", "selected_by": "ai"},
    ])
    assert battle_cases.survey(db) == 0
    out = capsys.readouterr().out
    assert "BattleLog" in out
    assert "action events" in out


# --- ★★★ 分類（⚠ 推測で埋めない）---------------------------------------


def test_知っている回復呪文だけを回復と数える():
    assert battle_cases._classify("ホイミ") == "heal"
    assert battle_cases._classify("Healmore") == "heal"


def test_知らない行動は種類不明にする():
    """⚠⚠ **推測で分類しない。**

    ★「ギラ っぽいから攻撃呪文だろう」と決めると、⚠ 分類が間違ったまま
      ケースが作られます。★分からないものは分からないと数えます。
    """
    assert battle_cases._classify("なぞの行動") == "unknown"
    assert battle_cases._classify(None) == "unknown"
    assert battle_cases._classify("") == "unknown"


def test_不明を0と混ぜない(db, capsys):
    """★「⚠ 種類不明」の欄が**必ず出る**こと。"""
    _make_db(db, [{"kind": "action", "action_name": "なぞの行動"}])
    battle_cases.survey(db)
    out = capsys.readouterr().out
    assert "⚠ 種類不明" in out


# --- ⚠⚠ 足りないものを必ず出す ------------------------------------------


def test_物理攻撃が0件なら足りないと言う(db, capsys):
    """★★★ **これが 2026-08-08 の実データそのもの**。

    ⚠ 523件すべてが回復で、物理攻撃・攻撃呪文・道具は**0件**でした。
    """
    _make_db(db, [{"kind": "action", "action_name": "ホイミ",
                   "selected_by": "ai"}])
    battle_cases.survey(db)
    out = capsys.readouterr().out
    assert "物理攻撃（たたかう）が **1件も記録されていません**" in out
    assert "攻撃呪文が **1件も記録されていません**" in out
    assert "道具の使用が **1件も記録されていません**" in out


def test_手動入力が無いことを言う(db, capsys):
    """⚠ `selected_by` が `ai` だけなら、★人の操作は資産にできません。"""
    _make_db(db, [{"kind": "action", "action_name": "ホイミ",
                   "selected_by": "ai"}])
    battle_cases.survey(db)
    assert "手動入力が記録されていません" in capsys.readouterr().out


def test_戦術と大目的が無いことを言う(db, capsys):
    _make_db(db, [{"kind": "action", "action_name": "ホイミ"}])
    out = capsys.readouterr()  # noqa: F841
    battle_cases.survey(db)
    text = capsys.readouterr().out
    assert "戦術（作戦プロフィール）がログに残っていません" in text
    assert "大目的（mission）がログに残っていません" in text


# --- ★ どこまで状態を戻せるか --------------------------------------------


def test_直前に観測があれば戻せると数える(db, capsys):
    """★行動より**前**に観測があれば、その値は戻せます。"""
    _make_db(db, [
        {"kind": "party_hp", "sequence_no": 1},
        {"kind": "party_mp", "sequence_no": 2},
        {"kind": "enemy_hp", "sequence_no": 3},
        {"kind": "action", "sequence_no": 4, "action_name": "ホイミ"},
    ])
    battle_cases.survey(db)
    out = capsys.readouterr().out
    assert "完全に戻せる" in out
    line = next(l for l in out.splitlines() if "完全に戻せる" in l)
    assert line.strip().endswith("1"), line


def test_観測が足りなければ甘く数えない(db, capsys):
    """⚠⚠ **味方HPだけ戻せても、敵のHPが分からなければ同じ判断はしません。**

    ★「一部だけ戻せる」に落とします（⚠ 「完全」に混ぜない）。
    """
    _make_db(db, [
        {"kind": "party_hp", "sequence_no": 1},
        {"kind": "action", "sequence_no": 2, "action_name": "ホイミ"},
    ])
    battle_cases.survey(db)
    out = capsys.readouterr().out
    full = next(l for l in out.splitlines() if "完全に戻せる" in l)
    partial = next(l for l in out.splitlines() if "一部だけ戻せる" in l)
    assert full.strip().endswith("0"), full
    assert partial.strip().endswith("1"), partial


def test_行動より後の観測は数えない(db, capsys):
    """⚠ 行動の**後**に観測しても、判断の材料にはなりません。"""
    _make_db(db, [
        {"kind": "action", "sequence_no": 1, "action_name": "ホイミ"},
        {"kind": "party_hp", "sequence_no": 2},
        {"kind": "party_mp", "sequence_no": 3},
        {"kind": "enemy_hp", "sequence_no": 4},
    ])
    battle_cases.survey(db)
    out = capsys.readouterr().out
    none = next(l for l in out.splitlines() if "観測のみ" in l)
    assert none.strip().endswith("1"), none


# --- ★★★ 原則1: observed を自動で正解にしない ---------------------------


def test_正解を自動で作らない():
    """★★★ **指示書 §1・原則1**。

        > 実戦ログに残っている行動を、自動的に「正解」として golden 化しない

    ⚠⚠ 旧AIの不適切行動やバグまで正解として固定してしまうためです。

    ## ⚠ 字面で見ないこと（★2回も踏みました）

      1回目: 「`expected` という語がコードに無い」を見た
             -> ★説明文に書いてあるだけで赤くなった
      2回目: 説明文を除いて同じことを見た
             -> ⚠⚠ `"expected": None` と**書くのが正解**なのに赤くなった

      → ★いま見るのは「`expected` に入れている値が**必ず None**」です。
    """
    import ast

    source = (PROJECT_ROOT / "retroux" / "tools" / "battle_cases.py"
              ).read_bytes().decode("utf-8")
    tree = ast.parse(source)

    found = 0
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant)
                    and key.value == "expected"):
                found += 1
                if not (isinstance(value, ast.Constant)
                        and value.value is None):
                    bad.append(ast.dump(value)[:80])

    assert found > 0, (
        "⚠ `expected` の欄がありません（★ケースの形が変わりましたか）")
    assert not bad, (
        "⚠⚠ 実戦の行動を正解にしています（★原則1に反します）: " + repr(bad))


def test_期待値を外から入れる口を作っていない():
    """⚠ `--expected` のような口を作ると、★機械的に golden 化できてしまいます。

    ★人がレビューして `tests/data/battle_cases/` に置く、が正しい道です。
    """
    source = (PROJECT_ROOT / "retroux" / "tools" / "battle_cases.py"
              ).read_bytes().decode("utf-8")
    assert "--expected" not in source


# --- ⚠ 実装が「回復だけ」なのはログ側の問題だと固定する -------------------


def _bridge_code() -> str:
    """⚠ 注釈は数えない（★説明で名前を出すのは構わない）。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    return "\n".join(line for line in source.splitlines()
                      if not line.strip().startswith("--"))


def test_行動の記録は1つの形にまとめてある():
    """★★★ **2026-08-08 に「回復だけ」から全種類へ広げました**。

    ## ⚠⚠ もとの状態

        action events 523 … ★全部が回復
        物理攻撃 0 / 攻撃呪文 0 / 道具 0

    ★`emit("battle_action"` が**回復の1か所**にしか無かったためです。
    ⚠ ログを貯めても、再生できるケースは回復しか作れませんでした。

    ## ★ いまの形

      `emit` は **1か所**（`_record_action`）のまま。
      ⚠ そこを4つの経路から呼びます（★測り方を2か所に書かない）。
    """
    code = _bridge_code()
    assert code.count('emit("battle_action"') == 1, (
        "⚠⚠ 記録の形が2つになりました（★`_record_action` に寄せてください）")
    assert "function Bridge:_record_action" in code


def test_4種類すべてを記録している():
    """⚠⚠ **これが survey の「0件」3項目を埋めるもの**。"""
    code = _bridge_code()
    # ★回復 / 攻撃呪文 / 道具 の3経路 ＋ 物理（`_flush_physical` 経由）
    assert code.count("self:_record_action(") >= 4, code.count(
        "self:_record_action(")
    assert "function Bridge:_flush_physical" in code, (
        "⚠ 物理攻撃を確定させる仕掛けがありません")
    # ⚠ 4種類が実際に別々の場所から呼ばれていること
    for marker in ("plan.caster, plan.name",      # ★回復
                   "self:_record_action(m, plan.name",  # ★攻撃呪文
                   "tostring(item_name)",         # ★道具
                   'prev, "たたかう"'):            # ★物理
        assert marker in code, f"⚠ {marker} の記録がありません"


def test_番が終わってから物理攻撃を確定する():
    """★★★ **2026-08-08 の実機データで作り直しました**。

    ## ⚠⚠ もとの形（`_claim_battle_item` の中で記録）は届きませんでした

      ★あそこには**早期 return が多い**（道具が無効・上限・メニュー違い・
        既に試した…）ので、⚠ **たどり着かない道**がありました。

      実機ログ: ⚠ **判断はあるが行動が無い 25件**

    → ★**入力を求められる人が変わった時点**で、前の人ぶんを確定します。
      ⚠ 戦闘終了時にも流します（★最後の人が落ちるため）。
    """
    code = _bridge_code()
    assert "function Bridge:_flush_physical" in code
    assert "function Bridge:_track_turn_actor" in code
    # ★戦闘コマンドメニューの毎ポーリングで呼ぶこと
    at = code.index("function Bridge:_claim_manual_character")
    body = code[at:at + 2500]
    assert "self:_track_turn_actor(m)" in body, (
        "⚠ 誰の番かを追っていません（★前の人ぶんが落ちます）")
    # ⚠ 戦闘の終わりでも流すこと
    source = BRIDGE.read_bytes().decode("utf-8")
    at_end = source.index("function Bridge:_on_battle_end")
    assert "self:_flush_physical()" in source[at_end:at_end + 1200], (
        "⚠⚠ 戦闘終了で流していません（★最後の人の行動が落ちます）")


def test_判断IDを必ず付ける():
    """⚠⚠ 実機で **35件の行動に `decision_id` が付いていません**でした。

    ★判断IDの無い行動は**再生ケースになりません**（⚠ 対にできない）。
    → ★記録が無ければ、その場で作ります（1人1ターン1件なので二重に出ません）。
    """
    code = _bridge_code()
    at = code.index("function Bridge:_record_action")
    body = code[at:at + 2000]
    assert "self:_emit_decision_snapshot(member)" in body, (
        "⚠ 判断の記録が無いときに作っていません（★IDが付きません）")


def _unused_test_物理攻撃は道具を見送ってから記録する():
    """★★★ **順番が命です**（⚠ heal -> attack -> item -> target）。

    ⚠⚠ 攻撃呪文を見送った時点で「たたかう」と記録すると、
      ★このあと**道具を使っても記録されません**
      （`_record_action` は1人1ターン1件なので、先に立ったほうが勝ちます）。

    → ★記録するのは **道具も見送ったとき**（`_claim_battle_item` の中）。
    """
    code = _bridge_code()
    at_item = code.index("function Bridge:_claim_battle_item")
    body = code[at_item:at_item + 4000]
    assert "self:_record_physical(m)" in body, (
        "⚠ 「たたかう」を道具の判定より前で記録しています")

    # ⚠ 攻撃呪文の見送りでは記録しないこと
    at_attack = code.index("function Bridge:_claim_battle_attack")
    attack_body = code[at_attack:at_attack + 3000]
    assert "_record_physical" not in attack_body, (
        "⚠⚠ 攻撃呪文を見送った時点で「たたかう」と記録しています"
        "（★道具が記録されなくなります）")


def test_1人1ターン1件にする門がある():
    """⚠ 押下の道は**毎ポーリング**通ります。★門が無いと何十件も並びます。"""
    code = _bridge_code()
    at = code.index("function Bridge:_record_action")
    body = code[at:at + 1500]
    assert "self.action_logged" in body, "⚠ 1人1ターン1件の門がありません"


def test_戦闘ごとに記録の印を消す():
    """⚠ 消し忘れると、★**次の戦闘で1件も記録されません**。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    at = source.index("function Bridge:_on_battle_end")
    head = source[at:at + 1000]
    assert "self.action_logged = nil" in head


def test_手動入力を記録しない():
    """⚠ 何を押したか分からないので、★「AI が決めた」とは書けません。"""
    code = _bridge_code()
    at = code.index("function Bridge:_record_action")
    body = code[at:at + 1500]
    assert 'selected_by = "ai"' in body

# --- ★★ Phase 2・3: 書き出し ---------------------------------------------


def test_書き出せる(db, tmp_path, capsys):
    _make_db(db, [
        {"kind": "party_hp", "sequence_no": 1, "actor": "lorasia",
         "after": 31},
        {"kind": "enemy_hp", "sequence_no": 2, "actor": "スライム",
         "after": 12},
        {"kind": "action", "sequence_no": 3, "actor": "samaltria",
         "target": "lorasia", "action_name": "ホイミ", "selected_by": "ai",
         "reason": "lorasia のHPが低い"},
    ])
    out = tmp_path / "cases.jsonl"
    assert battle_cases.export(db, out) == 0
    import json

    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    case = rows[0]
    assert case["observed"]["action_name"] == "ホイミ"
    assert case["observed"]["target"] == "lorasia"
    assert case["provenance"]["source"] == "real_emulator"


def test_書き出しでも正解を作らない(db, tmp_path):
    """★★★ **原則1**。⚠ 実戦の行動を自動で「正解」にしません。"""
    _make_db(db, [{"kind": "action", "action_name": "ホイミ",
                   "actor": "samaltria", "target": "lorasia"}])
    out = tmp_path / "cases.jsonl"
    battle_cases.export(db, out)
    import json

    case = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert case["expected"] is None, (
        "⚠⚠ 実戦の行動を正解にしています（★旧AIのバグまで固定されます）")


def test_直前の状態を復元する(db, tmp_path):
    """★行動より**前**の観測を積み直します（Phase 3）。"""
    _make_db(db, [
        {"kind": "party_hp", "sequence_no": 1, "actor": "lorasia",
         "after": 31},
        {"kind": "action", "sequence_no": 2, "action_name": "ホイミ",
         "actor": "samaltria", "target": "lorasia"},
        {"kind": "party_hp", "sequence_no": 3, "actor": "lorasia",
         "after": 81},
    ])
    out = tmp_path / "cases.jsonl"
    battle_cases.export(db, out)
    import json

    case = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert case["case_type"] == "reconstructed"
    assert "lorasia" in case["state"]["party"]


def test_推定値と確定値を混ぜない(db, tmp_path):
    """⚠⚠ **原則4**。★項目ごとに confidence を持ちます。"""
    _make_db(db, [
        {"kind": "party_hp", "sequence_no": 1, "actor": "lorasia",
         "after": 31},
        {"kind": "action", "sequence_no": 2, "action_name": "ホイミ",
         "actor": "samaltria"},
    ])
    out = tmp_path / "cases.jsonl"
    battle_cases.export(db, out)
    import json

    case = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    c = case["confidence"]
    assert c["party_hp"] == "event_reconstructed"
    # ⚠ 一度も観測していないものは unknown（★0 や exact にしない）
    assert c["party_mp"] == "unknown"
    assert c["status"] == "unknown"


def test_絞り込みで何件外したか出す(db, tmp_path, capsys):
    """★「黙って捨てない」。⚠ 0件になった理由が分からないと困ります。"""
    _make_db(db, [
        {"kind": "action", "sequence_no": 1, "action_name": "ホイミ",
         "actor": "samaltria"},
        {"kind": "action", "sequence_no": 2, "action_name": "ホイミ",
         "actor": "moonbrooke"},
    ])
    battle_cases.export(db, tmp_path / "c.jsonl", actor="samaltria")
    out = capsys.readouterr().out
    assert "1 件を書きました" in out
    assert "1 件を外しました" in out


def test_帯に分ける():
    assert battle_cases.bucket(10, 100) == "0-25%"
    assert battle_cases.bucket(60, 100) == "50-75%"
    assert battle_cases.bucket(100, 100) == "75-100%"


def test_分からない割合を0パーセントにしない():
    """⚠ 「0-25%」と「分からない」は別物です。"""
    assert battle_cases.bucket(None, 100) == "unknown"
    assert battle_cases.bucket(10, 0) == "unknown"


def test_自分への回復と仲間への回復を分ける():
    assert "self_heal" in battle_cases.categories(
        {"action_name": "ホイミ", "actor": "a", "target": "a"})
    assert "ally_heal" in battle_cases.categories(
        {"action_name": "ホイミ", "actor": "a", "target": "b"})


# --- ★★★ Phase 4: 判断の記録から再生できるケースを作る -------------------


def _events(path: pathlib.Path, rows: list) -> None:
    import json

    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")


def test_判断の記録から再生ケースを作る(tmp_path, capsys):
    """★★★ **これが Phase 4 の受け取り側**。

    ⚠ `Recorder` は知らない種類のイベントを捨てるので、
      ★生のログ（`events.jsonl`）をそのまま読みます。
    """
    import json

    src = tmp_path / "events.jsonl"
    _events(src, [
        {"type": "battle_start", "enemy_ids": [69, 69]},
        {"type": "battle_decision_snapshot", "decision_id": "b7_t2_samaltria",
         "turn": 2, "actor": "samaltria", "rom_hash": "ABC",
         "party": [{"id": "samaltria", "hp": 40, "max_hp": 152, "mp": 60}],
         "enemies": [{"slot": 0, "monster_id": 69, "hp": 90}],
         "strategy": {"engine": "layered", "profile": "省資源"}},
        {"type": "battle_action", "decision_id": "b7_t2_samaltria",
         "actor": "samaltria", "action": "ホイミ", "target": "lorasia",
         "selected_by": "ai", "reason": "…"},
    ])
    out = tmp_path / "replay.jsonl"
    assert battle_cases.replayable(src, out) == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1, capsys.readouterr().out
    case = rows[0]
    assert case["case_type"] == "replayable"
    assert case["state"]["party"][0]["hp"] == 40
    assert case["state"]["enemies"][0]["monster_id"] == 69
    assert case["state"]["monster_ids"] == [69, 69]
    # ★★ 戦術がケースに載る（⚠ survey で「無い」と言っていたもの）
    assert case["strategy"]["engine"] == "layered"
    assert case["strategy"]["profile"] == "省資源"
    # ★判断の直前に読んだ値なので exact
    assert case["confidence"]["party_hp"] == "exact"
    # ★★★ 原則1
    assert case["expected"] is None


def test_行動が結び付かない判断を黙って捨てない(tmp_path, capsys):
    """⚠⚠ 「たたかう」はまだ記録していません。★何件あるかを出します。"""
    src = tmp_path / "events.jsonl"
    _events(src, [
        {"type": "battle_decision_snapshot", "decision_id": "b1_t1_lorasia",
         "turn": 1, "actor": "lorasia", "party": [], "enemies": []},
    ])
    battle_cases.replayable(src, tmp_path / "r.jsonl")
    out = capsys.readouterr().out
    assert "行動と対にならなかった判断が 1 件" in out


def test_記録がまだ無いことを言う(tmp_path, capsys):
    """⚠ 0件のとき、★理由が分からないと「壊れている」と思われます。"""
    src = tmp_path / "events.jsonl"
    src.write_text("", encoding="utf-8")
    battle_cases.replayable(src, tmp_path / "r.jsonl")
    assert "判断の記録がまだありません" in capsys.readouterr().out


def test_壊れた行で落ちない(tmp_path):
    """⚠ Lua は手書きで JSON を組むので、★書き込み途中の行が混ざります。"""
    src = tmp_path / "events.jsonl"
    src.write_text('{"type": "batt\n{}\nnot json\n', encoding="utf-8")
    assert battle_cases.replayable(src, tmp_path / "r.jsonl") == 0


def test_ログが無ければ落ちずに知らせる(tmp_path, capsys):
    assert battle_cases.replayable(tmp_path / "無い.jsonl",
                                   tmp_path / "r.jsonl") == 1
    assert "ログがありません" in capsys.readouterr().out

# --- ★★★ Phase 4: 判断の記録そのもの（⚠ 本物の bridge を通す）----------

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
SNAPSHOT_HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
                    / "decision_snapshot_test.lua")


@pytest.fixture(scope="module")
def snapshot_result():
    if not (RUNNER.exists() and SNAPSHOT_HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(SNAPSHOT_HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8",
                                                              "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in out and "OK" not in out:
        pytest.skip("Lua を動かせない環境")
    return out


def _snap_ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_判断の記録のハーネスが全部通る(snapshot_result):
    assert "NG 0 件" in snapshot_result, snapshot_result


def test_毎フレーム出さない(snapshot_result):
    """★★★ **指示書 §8・§20 の性能要件そのもの**。

        > 毎フレーム出さない。1 actor の判断直前に1件のみ。

    ⚠⚠ 判断の道は**毎ポーリング**通ります。★印を置いて1回に絞ります。
    """
    assert _snap_ok(snapshot_result, "★★★ 20回呼んでも1件"), snapshot_result


def test_人とターンが変われば出る(snapshot_result):
    assert _snap_ok(snapshot_result, "★人が違えば出す"), snapshot_result
    assert _snap_ok(snapshot_result, "★次のターンでも出す"), snapshot_result


def test_戦闘ごとに印を消す(snapshot_result):
    """⚠ 消し忘れると、★**次の戦闘で1件も出ません**。"""
    assert _snap_ok(snapshot_result, "★★ 戦闘が終わったら印を消す"), snapshot_result


def test_AIが見ている値が入っている(snapshot_result):
    for label in ("★HP が入っている", "★最大HP も", "★MP も",
                  "★敵のIDが入っている", "★戦術の欄がある"):
        assert _snap_ok(snapshot_result, label), snapshot_result


def test_図鑑から引けるものは入れない(snapshot_result):
    """⚠ 指示書 §11.4「圧縮可能なROM静的情報は monster_id 等だけ保存」。"""
    assert _snap_ok(snapshot_result,
                    "⚠ 図鑑から引けるものは入れない（★ログを太らせない）"), \
        snapshot_result
    assert _snap_ok(snapshot_result, "★★ ROM を特定できる（§11.4）"), \
        snapshot_result


def test_落ちても本体を止めないが黙らない(snapshot_result):
    """⚠⚠ **`pcall` が握りつぶして「0件」になった**のが Phase 6 の原因。"""
    assert _snap_ok(snapshot_result, "★★ 何に失敗したか分かる"), snapshot_result
    assert _snap_ok(snapshot_result, "⚠ 同じ失敗を繰り返し出さない"), \
        snapshot_result


def test_行動と結び付けられる():
    """★受け入れ条件「decision_id で action と対応可能」。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    at = source.index('self:emit("battle_action"')
    body = source[at:at + 700]
    assert "decision_id" in body, (
        "⚠⚠ 行動に判断IDが付いていません（★再生ケースが作れません）")



# --- ⚠⚠⚠ 実機で「出たのに中身が空」だった件（2026-08-08）-----------------

def test_JSON化のハーネスが通る():
    """★★★ **実機の判断の記録が `"party": [[],[],[]]` でした。**

    ⚠ 出てはいたので「動いている」と見えましたが、**中身がありません**でした。
      `json_value` が `ipairs` だけで回していたため、
      ★キー付きのテーブルが `[]` に潰れていました。

    ⚠⚠ **「出た／出ない」だけでなく中身を見ること。**

    ★このハーネスは `Bridge.new` を通しません（⚠ 人が遊んでいる最中でも安全）。
    """
    harness = (PROJECT_ROOT / "research" / "probes" / "active"
               / "json_value_test.lua")
    if not (RUNNER.exists() and harness.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(harness)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8",
                                                              "replace")
    if done.returncode != 0 and "lua5.1" in out and "OK" not in out:
        pytest.skip("Lua を動かせない環境")
    assert "NG 0 件" in out, out


def test_キー付きのテーブルを潰さない():
    """⚠ 配列と連想配列を見分けていること（★字面ではなく仕組みを見る）。"""
    code = _bridge_code()
    at = code.index("local function json_value")
    body = code[at:at + 1200]
    assert "for k, x in pairs(v) do" in body, (
        "⚠⚠ キー付きのテーブルを配列として扱っています"
        "（★中身が `[]` に潰れます）")


def test_ハーネスから試せるように出してある():
    """⚠ `Bridge.new` はログを**開いて追記**します。

    ★人が遊んでいる最中でも試せるよう、`json_value` だけ外へ出してあります。
    """
    code = _bridge_code()
    assert "Bridge.json_value = json_value" in code


# --- ★ 分類は**設定から引く**（⚠ 手で並べない）--------------------------

def test_4種類すべてを分類できる():
    """⚠⚠ 実機の再生ケースが `categories: ["unknown"]` でした。

    ★`_classify` が回復呪文しか知らなかったためです。
    ⚠ 分類できないケースは、絞り込みにも代表抽出にも使えません。
    """
    assert battle_cases._classify("たたかう") == "physical"
    assert battle_cases._classify("ホイミ") == "heal"
    assert battle_cases._classify("Healmore") == "heal"
    assert battle_cases._classify("いかづちのつえ") == "item"
    assert battle_cases._classify("Firebane") == "attack_spell"


def test_分類の元を手で並べていない():
    """★★ **推測で分類しない**（指示書 §6 の注意）。

    ⚠ 名前の表をコードに書くと、★設定を足したときに黙って `unknown` に
      なります。→ `config.yaml` と `memory_map.yaml` から引きます。
    """
    source = (PROJECT_ROOT / "retroux" / "tools" / "battle_cases.py"
              ).read_bytes().decode("utf-8")
    assert "CONFIG_PATH" in source and "MEMORY_MAP_PATH" in source
    # ⚠ 呪文名を並べた定数が残っていないこと
    assert "HEAL_SPELLS" not in source, (
        "⚠ 名前の表が残っています（★設定から引いてください）")


def test_知らない行動は種類不明のまま():
    """⚠ 「たぶん攻撃呪文だろう」と決めない。"""
    assert battle_cases._classify("なぞの行動") == "unknown"



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の検査は
#       assert code.count('emit("battle_action"') == 1
#       assert "self.action_logged" in code
#   のように、**書き方**しか見ていません。
#   ★「1か所にまとめた」ことは分かりますが、⚠ **その門が効いているか**は
#     分かりません。鍵をひとつ間違えれば同じ人に2件残ります。
#
# ★ここは実機で2回こけています:
#     判断はあるのに行動が無い 25件 / 行動に decision_id が無い 35件
# =====================================================================

_HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
            / "record_action_test.lua")
_RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"


@pytest.fixture(scope="module")
def lua_result():
    if not (_RUNNER.exists() and _HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(_RUNNER), str(_HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeで記録の門が全部通る(lua_result):
    assert "すべて合格" in lua_result, lua_result


def test_検査の数が足りている(lua_result):
    count = sum(1 for line in lua_result.splitlines()
                if line.startswith("OK "))
    assert count >= 24, f"OK が {count} 件しかありません\n{lua_result}"


def test_1人1ターン1件の門が効いている(lua_result):
    """⚠ 鍵を間違えると、同じ人の同じターンに2件残ります。"""
    assert _ok(lua_result, "★同じ人・同じターンの2件目は記録しない"), lua_result
    assert _ok(lua_result, "★イベントも1件のまま"), lua_result
    assert _ok(lua_result, "同じ人でもターンが違えば記録する"), lua_result


def test_判断IDが必ず付く(lua_result):
    """⚠⚠ 実機で **35件**が欠けていました。★無いと再生ケースにできません。"""
    assert _ok(lua_result, "★判断IDが無ければ、その場で作って付ける"), lua_result
    assert _ok(lua_result, "既にある判断IDを使い回す"), lua_result


def test_判断の記録が落ちても行動は残る(lua_result):
    """★記録の付帯機能が壊れても、本体の記録は失わないこと。"""
    assert _ok(lua_result, "⚠ 判断の記録が落ちても行動は残す"), lua_result


def test_番が変わったら前の人を確定する(lua_result):
    """⚠⚠ ここが「物理攻撃 0件」だった原因。"""
    assert _ok(lua_result, "★番が変わったら前の人ぶんを確定する"), lua_result
    assert _ok(lua_result, "何も記録が無ければ「たたかう」"), lua_result


def test_道具を使ったのにたたかうと記録しない(lua_result):
    """⚠⚠ 早く確定させると、道具の記録が「たたかう」で潰れます。"""
    assert _ok(lua_result, "★既に記録があれば「たたかう」を足さない"), lua_result
    assert _ok(lua_result, "⚠ 道具の記録が残っている"), lua_result


def test_素のたたかうに他人の理由を付けない(lua_result):
    """★2026-08-11 の依頼者の指摘（ログを読んで見つかった）。"""
    assert _ok(lua_result, "⚠⚠ 他人の理由を付けない"), lua_result
    assert _ok(lua_result, "★自分の理由なら使う"), lua_result
    assert _ok(lua_result, "★ターンが違う理由は使わない"), lua_result
