"""戦闘ログを「AIを育てるためのテスト資産」にする（2026-08-08）。

指示書: `input/RetroUX_戦闘ログ_AIシナリオテスト資産化_実装指示_20260807.md`

    > 通常プレイやモンキーテストを実行するだけで、
    > AI回帰試験用のシナリオ資産が自動的に蓄積される

## ★★★ いちばん大事な約束（指示書 §1・原則1）

    observed  … **実際に選んだ行動**
    expected  … **正しいと認定した行動**

⚠⚠ **この2つを混ぜません。** 実戦ログに残っている行動を、自動的に
「正解」として固定してはいけません。★旧AIの不適切な行動やバグまで
正解にしてしまうためです。

    observed:
      action: ionazun
    expected: null      ← ★これが基本

## ★ いまできること

    survey … ⚠ **まず何が取れるかを数える**（指示書 §18 Phase 1）
    export … ★ケースを書き出す（指示書 §18 Phase 2・3）
    replayable … ★判断の記録から**再生できる**ケースを作る（Phase 4）

## ★★ どこへ書き出すか（指示書 §5.2 の3案から選びました）

    観測ケース（大量） … **JSONL** / `work/battle-cases/`
      ⚠ Git 管理外です。★いつでも作り直せるので、貯める必要がありません。

    golden 候補（少数） … YAML/JSON / `tests/data/battle_cases/`
      ★人がレビューして**残すと決めたもの**だけを置きます。

⚠⚠ 1ケース1ファイルは選びませんでした（★523件でも扱いにくいため）。

使い方:

    python -m retroux.tools.battle_cases survey
    python -m retroux.tools.battle_cases export
    python -m retroux.tools.battle_cases export --action-type heal --actor samaltria
    python -m retroux.tools.battle_cases export --category emergency_heal
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sqlite3
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "work" / "retroux.sqlite3"
#: ★観測ケースの置き場（⚠ Git 管理外。いつでも作り直せます）
DEFAULT_OUT = (PROJECT_ROOT / "work" / "battle-cases"
               / "observed.jsonl")

#: ★1行の行動として意味があるもの（⚠ 観測イベントとは別）
ACTION_KIND = "action"

#: ★通常攻撃の名前（`bridge.lua` の `_flush_physical` が書くもの）
PHYSICAL_NAME = "たたかう"

CONFIG_PATH = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
MEMORY_MAP_PATH = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml"


def _out(text: str = "") -> None:
    print(text)


def _load_names() -> dict:
    """行動の名前 -> 種類 の対応を**設定から**作る。

    ⚠⚠ **手で並べません**（★推測で分類しない / 指示書 §6 の注意）。

      道具   … `config.yaml` の `auto_input.battle_items.items`
      呪文   … `memory_map.yaml` の `spells`
               ★`heal: true` なら回復、★威力があれば攻撃呪文

    ⚠ 読めなければ空を返します（★分類が `unknown` になるだけ）。
    """
    names: dict = {}
    try:
        import yaml

        config = yaml.safe_load(CONFIG_PATH.read_bytes().decode("utf-8"))
        items = ((config.get("auto_input") or {}).get("battle_items") or {}
                 ).get("items") or []
        for item in items:
            if item.get("name"):
                names[str(item["name"])] = "item"
    except Exception:                                  # noqa: BLE001
        pass

    try:
        import yaml

        mm = yaml.safe_load(MEMORY_MAP_PATH.read_bytes().decode("utf-8"))
        for spell in (mm.get("spells") or {}).values():
            name = spell.get("name")
            if not name:
                continue
            if spell.get("heal"):
                names[str(name)] = "heal"
            elif spell.get("damage_avg") is not None:
                names[str(name)] = "attack_spell"
    except Exception:                                  # noqa: BLE001
        pass

    # ⚠ `memory_map` の呪文名は英語（`Healmore`）。★実機ログの日本語も拾う
    #   （`memory_map` に日本語で書いてあるものはそのまま入っています）。
    names[PHYSICAL_NAME] = "physical"
    return names


#: ★1回だけ作る（⚠ 1件ごとに YAML を読むと遅い）
_NAMES: dict | None = None


def _classify(action_name: str | None) -> str:
    """行動の種類。⚠ 分からないものは `unknown`（★0 と不明を混ぜない）。"""
    global _NAMES
    if not action_name:
        return "unknown"
    if _NAMES is None:
        _NAMES = _load_names()
    return _NAMES.get(str(action_name), "unknown")


def survey(db_path: pathlib.Path) -> int:
    """いまのログから**何件のケースが作れるか**を数える（指示書 §5.1）。

    ⚠⚠ **足りないものも必ず出します。** ★「1,204件作れます」だけ言うと、
      何が取れていないのかが分かりません（指示書 §18 Phase 1
      「何件あるか / 何が取れるか / **何が不足か**」）。
    """
    if not db_path.exists():
        _out(f"✗ DB がありません: {db_path}")
        return 1

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    battles = con.execute("select count(*) from BattleLog").fetchone()[0]
    events = con.execute("select count(*) from BattleEvent").fetchone()[0]

    _out("== ★ いまあるもの ==")
    _out(f"  BattleLog    {battles:>7,} battles")
    _out(f"  BattleEvent  {events:>7,} events")
    _out()

    kinds = collections.OrderedDict(
        (r["kind"], r["n"]) for r in con.execute(
            "select kind, count(*) as n from BattleEvent"
            " group by kind order by n desc"))
    _out("== ★ イベントの種類 ==")
    for kind, n in kinds.items():
        _out(f"  {kind:<20} {n:>7,}")
    _out()

    # --- ★★ 行動ケース（★これが Observed Case のもと）------------------
    actions = con.execute(
        "select action_name, count(*) as n from BattleEvent"
        " where kind = ? group by action_name order by n desc",
        (ACTION_KIND,)).fetchall()
    total_actions = sum(r["n"] for r in actions)
    by_type: collections.Counter[str] = collections.Counter()
    for r in actions:
        by_type[_classify(r["action_name"])] += r["n"]

    _out("== ★★★ 行動ケース（Observed Case のもと）==")
    _out(f"  action events        {total_actions:>7,}")
    for name, label in (("heal", "回復"), ("attack_spell", "攻撃呪文"),
                        ("item", "道具"), ("physical", "物理攻撃"),
                        ("unknown", "⚠ 種類不明")):
        _out(f"    {label:<12} {by_type.get(name, 0):>7,}")
    _out()

    # --- ⚠⚠ 何が**取れていない**か -------------------------------------
    missing: list[str] = []
    if by_type.get("physical", 0) == 0:
        missing.append(
            "物理攻撃（たたかう）が **1件も記録されていません**")
    if by_type.get("attack_spell", 0) == 0:
        missing.append("攻撃呪文が **1件も記録されていません**")
    if by_type.get("item", 0) == 0:
        missing.append("道具の使用が **1件も記録されていません**")

    selected = collections.OrderedDict(
        (str(r["selected_by"]), r["n"]) for r in con.execute(
            "select selected_by, count(*) as n from BattleEvent"
            " where kind = ? group by selected_by order by n desc",
            (ACTION_KIND,)))
    if set(selected) <= {"ai", "None"}:
        missing.append(
            "手動入力が記録されていません（★`selected_by` が `ai` だけ）")

    # ★戦術・大目的はイベントに載っているか
    has_strategy = con.execute(
        "select count(*) from BattleEvent where kind = ? and reason like '%戦術%'",
        (ACTION_KIND,)).fetchone()[0]
    if has_strategy == 0:
        missing.append("戦術（作戦プロフィール）がログに残っていません")
    missing.append("大目的（mission）がログに残っていません")

    # --- ★ 状態をどこまで戻せるか ---------------------------------------
    #
    # ⚠ 「復元できる」とは、**その行動の直前の HP/MP/敵HP** を言い当てられる
    #   こと。★観測（`party_hp` など）の `before` を積み直せば作れます。
    reconstruct = _reconstructability(con)

    _out("== ★ その行動の直前の状態を戻せるか ==")
    _out(f"  完全に戻せる          {reconstruct['full']:>7,}")
    _out(f"  一部だけ戻せる        {reconstruct['partial']:>7,}")
    _out(f"  ⚠ 観測のみ（戻せない） {reconstruct['none']:>7,}")
    _out()
    _out("  ★内訳（★行動の直前に読めた項目）")
    for label, n in reconstruct["detail"].items():
        _out(f"    {label:<20} {n:>7,}")
    _out()

    _out("== ⚠⚠ 足りないもの（★ここが次の仕事）==")
    for i, text in enumerate(missing, 1):
        _out(f"  {i}. ⚠ {text}")
    _out()
    _out("★指示書 §18 Phase 4「Decision Snapshot」で埋める内容です。")
    _out("⚠ いまのログだけでは、回復以外のケースは作れません。")

    con.close()
    return 0


def _reconstructability(con: sqlite3.Connection) -> dict:
    """行動ごとに「直前の状態をどこまで戻せるか」を数える。

    ★同じ戦闘・同じターンの中で、その行動より**前**に観測があれば、
      その値は戻せます（`value_before` があるため）。

    ⚠⚠ **「戻せる」を甘く数えないこと。** ★味方HPだけ戻せても、
      敵のHPが分からなければ AI は同じ判断をしません。
    """
    rows = con.execute(
        "select battle_id, turn_no, sequence_no, kind from BattleEvent"
        " where battle_id is not null"
        " order by battle_id, turn_no, sequence_no, id").fetchall()

    #: 戦闘ごとに「そのターンまでに何を観測したか」を積む
    seen: dict[tuple, set] = collections.defaultdict(set)
    full = partial = none = 0
    detail: collections.Counter[str] = collections.Counter()

    WANT = ("party_hp", "party_mp", "enemy_hp")
    for r in rows:
        key = (r["battle_id"],)
        kind = r["kind"]
        if kind == ACTION_KIND:
            got = {k for k in WANT if k in seen[key]}
            for k in got:
                detail[k] += 1
            if len(got) == len(WANT):
                full += 1
            elif got:
                partial += 1
            else:
                none += 1
        elif kind in WANT:
            seen[key].add(kind)

    return {"full": full, "partial": partial, "none": none,
            "detail": collections.OrderedDict(
                (k, detail.get(k, 0)) for k in WANT)}



#: ★HP/MP の帯（指示書 §7）。⚠ 代表ケースを選ぶときの特徴量にも使います。
BUCKETS = ((0.25, "0-25%"), (0.50, "25-50%"), (0.75, "50-75%"),
           (1.01, "75-100%"))


def bucket(value, total) -> str:
    """割合を帯にする。⚠ 分からなければ `unknown`（★0% にしない）。"""
    try:
        v, t = float(value), float(total)
    except (TypeError, ValueError):
        return "unknown"
    if t <= 0:
        return "unknown"
    ratio = v / t
    for edge, label in BUCKETS:
        if ratio < edge:
            return label
    return "75-100%"


def categories(event: dict) -> list[str]:
    """そのケースの分類（指示書 §6）。

    ⚠⚠ **`reason` の文字列に寄りかかりすぎないこと**（指示書の注意）。
      ★いまは「どの行動か」と「誰を狙ったか」から機械的に決められるものだけ
        を付けます。⚠ 戦況からの分類（`life_first` など）は、
        ログに戦術が残るようになってから（★Phase 4 の宿題）。
    """
    got = [_classify(event.get("action_name"))]
    if got[0] == "heal":
        # ★自分を回復したか、仲間を回復したか（⚠ 判断が違います）
        if event.get("actor") and event.get("actor") == event.get("target"):
            got.append("self_heal")
        else:
            got.append("ally_heal")
    return got


def reconstruct(rows: list, upto: int) -> dict:
    """その行動の**直前**の状態を、観測を積み直して復元する（Phase 3）。

    ★`BattleEvent` の観測は `value_before` / `value_after` を持つので、
      行動より前の観測を順に見れば「直前の値」が分かります。

    ⚠⚠ **推定値と確定値を混ぜません**（指示書 §2.2・原則4）。
      項目ごとに `confidence` を付けます:

        exact               … ★その行動の直前に観測した値
        event_reconstructed … ★少し前の観測から引き継いだ値
        unknown             … ⚠ 一度も観測していない

    ⚠ `upto` はその行動の `id`。★これより**前**だけを見ます。
    """
    party: dict = {}
    enemies: dict = {}
    confidence: dict = {}

    for r in rows:
        if r["id"] >= upto:
            break
        kind, name = r["kind"], r["actor"]
        value = r["value_after"]
        if value is None:
            value = r["value_before"]
        if value is None:
            continue
        if kind == "party_hp" and name:
            party.setdefault(name, {})["hp"] = value
        elif kind == "party_mp" and name:
            party.setdefault(name, {})["mp"] = value
        elif kind == "enemy_hp":
            enemies[str(name or r["target"] or "?")] = value

    if party:
        confidence["party_hp"] = "event_reconstructed"
    else:
        confidence["party_hp"] = "unknown"
    if any("mp" in v for v in party.values()):
        confidence["party_mp"] = "event_reconstructed"
    else:
        confidence["party_mp"] = "unknown"
    confidence["enemy_hp"] = "event_reconstructed" if enemies else "unknown"
    # ⚠ 最大HP・敵の能力は ROM から引けますが、★ここでは埋めません
    #   （`monster_id` を持たせて、使うときに引く / 指示書 §11.4）。
    confidence["max_hp"] = "unknown"
    confidence["status"] = "unknown"

    return {"party": party, "enemies": enemies, "confidence": confidence}


def _case(event, battle, state) -> dict:
    """1件のケース（指示書 §2.1・§2.2・§12）。

    ★★★ **`expected` は必ず null です**（指示書 §1・原則1）。
      ⚠⚠ 実戦の行動を自動で「正解」にすると、旧AIの不適切行動やバグまで
        固定してしまいます。★人が見て決めたものだけが golden になります。
    """
    import json as _json

    monsters = []
    raw = battle["monster_ids"]
    if raw:
        try:
            monsters = _json.loads(raw)
        except Exception:                              # noqa: BLE001
            monsters = []

    case_id = "b{}_t{}_s{}_{}".format(
        event["battle_id"], event["turn_no"], event["sequence_no"],
        event["actor"] or "?")
    return {
        "schema_version": 1,
        "case_type": "reconstructed" if state["party"] else "observed",
        "case_id": case_id,
        "categories": categories(dict(event)),
        "source": {
            "battle_id": event["battle_id"],
            "turn": event["turn_no"],
            "sequence": event["sequence_no"],
        },
        "state": {
            "turn": event["turn_no"],
            "party": state["party"],
            "enemies": state["enemies"],
            "monster_ids": monsters,
        },
        "confidence": state["confidence"],
        "observed": {
            "actor": event["actor"],
            "action_type": _classify(event["action_name"]),
            "action_name": event["action_name"],
            "target": event["target"],
            "reason": event["reason"],
            "selected_by": event["selected_by"],
        },
        "result": {
            "victory": battle["result"] == "win",
            "outcome": battle["result"],
        },
        # ★★★ 実戦の行動を「正解」にしない（指示書 §1）
        "expected": None,
        "provenance": {
            "source": "real_emulator",
            "rom_hash": battle["rom_hash"],
            "battle_id": event["battle_id"],
            "turn": event["turn_no"],
            "actor": event["actor"],
            "is_boss": bool(battle["is_boss"]),
            "is_first_encounter": bool(battle["is_first_encounter"]),
        },
    }


def export(db_path: pathlib.Path, out_path: pathlib.Path,
           action_type=None, actor=None, category=None) -> int:
    """ケースを JSONL で書き出す（指示書 §5.2・§5.3）。"""
    import json as _json

    if not db_path.exists():
        _out(f"✗ DB がありません: {db_path}")
        return 1

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    actions = con.execute(
        "select e.*, b.result, b.monster_ids, b.is_boss, b.rom_hash,"
        " b.is_first_encounter"
        " from BattleEvent e join BattleLog b on b.id = e.battle_id"
        " where e.kind = ? order by e.id", (ACTION_KIND,)).fetchall()

    #: ★戦闘ごとに観測をまとめて持つ（⚠ 1件ずつ問い合わせると遅い）
    by_battle: dict = collections.defaultdict(list)
    for r in con.execute(
            "select id, battle_id, kind, actor, target, value_before,"
            " value_after from BattleEvent where battle_id is not null"
            " order by battle_id, id"):
        by_battle[r["battle_id"]].append(r)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for event in actions:
            if action_type and _classify(event["action_name"]) != action_type:
                skipped += 1
                continue
            if actor and event["actor"] != actor:
                skipped += 1
                continue
            state = reconstruct(by_battle[event["battle_id"]], event["id"])
            case = _case(event, event, state)
            if category and category not in case["categories"]:
                skipped += 1
                continue
            fh.write(_json.dumps(case, ensure_ascii=False) + "\n")
            written += 1

    con.close()
    _out(f"★ {written:,} 件を書きました: {out_path}")
    if skipped:
        # ⚠ 黙って減らさない（★絞り込みで何件外したかを出す）
        _out(f"⚠ 絞り込みで {skipped:,} 件を外しました")
    if written == 0:
        _out("⚠⚠ 0件です。★絞り込みの条件を確かめてください")
    return 0



#: ★判断の直前の状態（Lua が出す / 指示書 §8）
SNAPSHOT_TYPE = "battle_decision_snapshot"
DEFAULT_EVENTS = PROJECT_ROOT / "work" / "events.jsonl"
DEFAULT_REPLAY_OUT = (PROJECT_ROOT / "work" / "battle-cases"
                      / "replayable.jsonl")


def replayable(events_path: pathlib.Path, out_path: pathlib.Path,
               actor=None, action_type=None) -> int:
    """判断の記録から**再生できるケース**を作る（指示書 §2.3）。

    ## ★★ なぜ DB ではなく `events.jsonl` を読むのか

      ⚠ `Recorder` は知らない種類のイベントを**捨てます**。
      ★判断の記録は DB に入りません（⚠ 表を足すと既存の解析を壊します /
        指示書 §19「現行 battle log / DB / analysis を壊さない」）。
      → ★生のログをそのまま読みます。

    ## ⚠⚠ `expected` は必ず null（★原則1）

      実戦の行動を自動で「正解」にしません。
    """
    import json as _json

    if not events_path.exists():
        _out(f"✗ ログがありません: {events_path}")
        return 1

    snapshots: dict = {}
    actions: dict = {}
    battle = {"seq": None, "ids": []}

    for line in events_path.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = _json.loads(line)
        except Exception:                              # noqa: BLE001
            continue                                   # ⚠ 壊れた行は飛ばす
        kind = d.get("type")
        if kind == "battle_start":
            battle = {"seq": battle["seq"], "ids": d.get("enemy_ids") or []}
        elif kind == SNAPSHOT_TYPE:
            key = d.get("decision_id")
            if key:
                d["_monster_ids"] = list(battle["ids"])
                snapshots[key] = d
        elif kind == "battle_action":
            key = d.get("decision_id")
            if key:
                actions[key] = d

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = orphan = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for key, snap in snapshots.items():
            act = actions.get(key)
            if act is None:
                # ⚠ 行動と対にならなかった判断。
                #   ★古いログ（2026-08-08 に行動の記録を広げる前）は
                #     判断だけが残っているので、ここに落ちます。
                orphan += 1
                continue
            if actor and snap.get("actor") != actor:
                continue
            kind = _classify(act.get("action"))
            if action_type and kind != action_type:
                continue
            fh.write(_json.dumps({
                "schema_version": 1,
                "case_type": "replayable",
                "case_id": key,
                "categories": categories({
                    "action_name": act.get("action"),
                    "actor": snap.get("actor"), "target": act.get("target")}),
                "state": {
                    "turn": snap.get("turn"),
                    "actor": snap.get("actor"),
                    "party": snap.get("party") or [],
                    "enemies": snap.get("enemies") or [],
                    "monster_ids": snap.get("_monster_ids") or [],
                },
                "strategy": snap.get("strategy") or {},
                "observed": {
                    "actor": snap.get("actor"),
                    "action_type": kind,
                    "action_name": act.get("action"),
                    "target": act.get("target"),
                    "reason": act.get("reason"),
                    "selected_by": act.get("selected_by"),
                },
                # ★★★ 実戦の行動を「正解」にしない（指示書 §1・原則1）
                "expected": None,
                "confidence": {
                    # ★判断の直前に読んだ値なので **exact**
                    "party_hp": "exact", "party_mp": "exact",
                    "enemy_hp": "exact",
                    # ⚠ 図鑑から引くもの（★ログには入れていない / §11.4）
                    "enemy_stats": "rom",
                    "status": "unknown",
                },
                "provenance": {
                    "source": "real_emulator",
                    "rom_hash": snap.get("rom_hash"),
                    "decision_id": key,
                    "turn": snap.get("turn"),
                    "actor": snap.get("actor"),
                },
            }, ensure_ascii=False) + "\n")
            written += 1

    _out(f"★ {written:,} 件を書きました: {out_path}")
    _out(f"  判断の記録 {len(snapshots):,} 件 / 行動 {len(actions):,} 件")
    if orphan:
        # ⚠⚠ **黙って捨てない。** ★行動を記録していない種類がまだあります。
        _out(f"⚠ 行動と対にならなかった判断が {orphan:,} 件ありました"
             "（★古いログには行動が残っていません）")
    if written == 0 and snapshots:
        _out("⚠⚠ 0件です。★`decision_id` が行動側に付いているか確かめてください")
    if not snapshots:
        _out("⚠ 判断の記録がまだありません（★実機を1回動かすと貯まります）")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                   # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(
        description="戦闘ログから AI テストのケースを作る（★まずは survey）")
    parser.add_argument("command",
                        choices=("survey", "export", "replayable"))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS),
                        help="判断の記録を読むログ（既定 work/events.jsonl）")
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help="見に行く DB（既定 work/retroux.sqlite3）")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="書き出し先（★JSONL / 既定 work/battle-cases/）")
    parser.add_argument("--action-type", default=None,
                        help="行動の種類で絞る（例 heal）")
    parser.add_argument("--actor", default=None, help="人で絞る")
    parser.add_argument("--category", default=None,
                        help="分類で絞る（例 self_heal / ally_heal）")
    args = parser.parse_args(argv)

    if args.command == "survey":
        return survey(pathlib.Path(args.db))
    if args.command == "export":
        return export(pathlib.Path(args.db), pathlib.Path(args.out),
                      action_type=args.action_type, actor=args.actor,
                      category=args.category)
    if args.command == "replayable":
        out = args.out
        if out == str(DEFAULT_OUT):
            out = str(DEFAULT_REPLAY_OUT)   # ★別のファイルへ（⚠ 上書きしない）
        return replayable(pathlib.Path(args.events), pathlib.Path(out),
                          actor=args.actor, action_type=args.action_type)
    return 1


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
