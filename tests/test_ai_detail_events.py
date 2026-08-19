"""AI 判断の詳細を events へ移したこと（§6・§9 / 完了条件 #6）。

## ⚠⚠ 何が足りていなかったか

Phase 3 で human log からは DEBUG へ落としたが、
★**events 側へ入れる**ほうをやっていなかった。

指示書 §6:

> AI判断改善に必要な、戦況／戦術／役割／候補／score／margin／veto／
> decision snapshot／actual action 等は、原則として構造化イベントへ残す。

そのため §9 の分析のうち、次は**出せなかった**:

| 出したいもの | 足りなかった項目 |
| --- | --- |
| 役割分布 | `role` |
| 戦術 score と実戦結果 | score / margin |
| 同一条件で判断が揺れたケース | margin |
| veto 発生ケース | `battle_veto` |

## ⚠ events を膨らませない

★候補の**全件**は入れない（1戦闘で数十件になる）。
1人につき「一番の役割・点数・2番手との差・候補数」だけ。
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


@pytest.fixture(scope="module")
def src():
    return BRIDGE.read_text(encoding="utf-8")


# --- role -----------------------------------------------------------------

def test_snapshotにroleが入る(src):
    block = src.split('self:emit("battle_decision_snapshot"')[1][:600]
    assert "role = role" in block, block


def test_roleは1人1件で候補全件を持たない(src):
    """⚠ 全件入れると events が膨らむ（1戦闘で数十件）。"""
    block = src.split("self.role_view = self.role_view or {}")[1][:700]
    for key in ("action", "score", "margin", "candidates"):
        assert f"{key} =" in block, f"{key} が無い: {block[:400]}"
    # ★候補そのものの配列を入れていないこと。
    #   ⚠ `candidates = #list`（★件数だけ）は良い。`candidates = list` は駄目。
    assert "candidates = #list" in block, block[:400]
    assert "candidates = list" not in block, block[:400]


def test_marginは2番手との差(src):
    """★僅差だったかが分かること（§9「判断が揺れたケース」）。"""
    block = src.split("self.role_view = self.role_view or {}")[1][:700]
    assert "second" in block
    assert "contribution_score - second.contribution_score" in block, block[:500]


def test_見立てが無ければroleはnil(src):
    """⚠ 空の表を作らない（★「調べていない」と「役割なし」は別）。"""
    block = src.split("local role = ")[1][:200]
    assert "(self.role_view or {})[member.name]" in block, block


# --- veto -----------------------------------------------------------------

def test_vetoがイベントになっている(src):
    assert 'self:emit("battle_veto"' in src


def test_vetoイベントに必要な項目がある(src):
    block = src.split('self:emit("battle_veto"')[1][:500]
    for key in ("turn", "actor", "kind", "reason", "decision_id"):
        assert f"{key} =" in block, f"{key} が無い: {block[:300]}"


def test_vetoも1人1ターン1回の門の内側(src):
    """⚠ 実機で 37 件出て他の記録が読めなくなった経緯がある。

    ★human log と**同じ門**の内側に置くこと（別に出すと増える）。
    """
    # `veto_logged[mark] == nil` の分岐の中に emit があること
    guard = src.split("if self.veto_logged[mark] == nil then")[1]
    closing = guard.index("\n    end")
    inside = guard[:closing]
    assert 'self:emit("battle_veto"' in inside, (
        "veto のイベントが「1人1ターン1回」の門の外にある")


def test_decision_idが無い場合を隠さない(src):
    """⚠ 却下は**候補を作る前**に起きるので、まだ ID が無いことがある。

    ★そのときは nil のまま出す（★対にできないことを隠さない）。
    """
    block = src.split('self:emit("battle_veto"')[1][:500]
    assert "(self.snapshot_done or {})[mark_id]" in block, block[:300]


# --- ★ 実データで数えられるか ---------------------------------------------

def test_溜まったeventsから役割分布を数えられる():
    """★§9 の「役割分布」が**機械処理で**出せること。

    ⚠ 古いデータには `role` が無い（2026-08-13 より前）。
      ★無ければ skip する（**直したのに永久に赤い**検査にしない）。
    """
    import collections
    import json

    events = PROJECT_ROOT / "work" / "events.jsonl"
    if not events.exists():
        pytest.skip("実測データが無い")
    roles = collections.Counter()
    for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
        if "battle_decision_snapshot" not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        role = e.get("role")
        if isinstance(role, dict) and role.get("action"):
            roles[role["action"]] += 1
    if not roles:
        pytest.skip("role を持つ snapshot がまだ無い（★実機で貯め直すと入る）")
    assert sum(roles.values()) > 0


def test_human_logのveto行はDEBUGへ落ちている(src):
    """★数えるのはイベント側。human log は調査用に残すだけ。

    ⚠ 正規表現で組み立てを当てにいくと、書き方を少し変えただけで
      **見つからない**になる（★実際にここで1度踏んだ）。
      → 棚卸しの判定表（＝1か所の根拠）から読む。
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_log_inventory import build

    judged, _ = build()
    got = [r for r in judged
           if r["file"].endswith("bridge.lua") and "[veto]" in r["snippet"]
           and r["kind"] == "lua-log"]
    assert got, "veto の human log が棚卸しに出てこない"
    assert got[0]["level"] == "DEBUG", (
        f"veto の human log が {got[0]['level']}: {got[0]['text'][:60]}")
