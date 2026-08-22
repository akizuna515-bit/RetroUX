"""events から AI 判断の傾向を出す CLI（RX-0030 / 0031 / 0033）。

★検査由来の区間（同一秒に複数の session_start）を既定で除くこと、
  古い形の decision_id を一意と前提しないこと、出せないものは出せないと言うこと。
"""

from __future__ import annotations

import json
import pathlib

from retroux.tools import battle_analyze as ba


def _ev(type_, **kw):
    d = {"type": type_, "frame": 0, "time": kw.pop("time", 100)}
    d.update(kw)
    return d


def _session(t, sid, battles=1, profile="conserve", with_role=True, old_ids=False):
    out = [_ev("session_start", time=t, session_id=sid)]
    for b in range(battles):
        did = (f"b{b}_t0_lorasia" if old_ids else f"{sid}_b{b}_t0_lorasia")
        out += [
            _ev("battle_start", time=t, enemy_ids=[1]),
            _ev("battle_turn", time=t, turn=1),
            _ev("battle_decision_snapshot", time=t, actor="lorasia", decision_id=did,
                strategy={"profile": profile, "risk": "normal", "engine": "layered"},
                **({"role": {"action": "attack"}} if with_role else {})),
            _ev("battle_veto", time=t, actor="samaltria", kind="attack_spell", reason="省資源"),
            _ev("manual_latched", time=t, reason="危険状態"),
            _ev("battle_end", time=t, outcome="win"),
        ]
    return out


def _write(tmp_path, events) -> pathlib.Path:
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n{broken\n",
                 encoding="utf-8")
    return p


def test_同一秒に複数のsession_startは検査由来として除く(tmp_path):
    events = _session(100, "real1") + _session(200, "p1") + _session(200, "p2") + _session(200, "p3")
    sessions = ba.split_sessions(ba.read_events([_write(tmp_path, events)]))
    ba.mark_probes(sessions)
    assert [s["probe"] for s in sessions] == [False, True, True, True]
    kept = ba.select(sessions, include_probes=False)
    assert len(kept) == 1 and kept[0]["session_id"] == "real1"
    assert len(ba.select(sessions, include_probes=True)) == 4
    assert ba.sessions_summary(sessions) == {"sessions": 4, "probe_sessions": 3, "probe_battles": 3,
                                            "kept_sessions": 1, "kept_battles": 1}


def test_戦術と役割とvetoの分布(tmp_path):
    events = _session(100, "a", battles=2, profile="quick") + _session(300, "b", profile="conserve")
    sessions = ba.split_sessions(ba.read_events([_write(tmp_path, events)]))
    ba.mark_probes(sessions)
    st = ba.strategy_distribution(sessions)
    assert st["battles"] == 3
    assert st["rows"][0] == {"profile": "quick", "risk": "normal", "engine": "layered", "battles": 2}
    ro = ba.role_distribution(sessions)
    assert ro["rows"] == [{"actor": "lorasia", "action": "attack", "count": 3}]
    assert ba.veto(sessions)["rows"][0]["count"] == 3
    assert ba.outcomes(sessions)["rows"][0] == {"outcome": "win", "battles": 3, "avg_turns": 1.0}
    assert ba.manual_fallback(sessions)["rows"] == [{"reason": "危険状態", "count": 3}]


def test_古い形のdecision_idを一意と前提しない(tmp_path):
    """★古い形 `b{seq}_t{turn}_{name}` はセッションをまたぐと同じ値になる。
    セッション内で数えるので、別セッションの同じ id は重複に数えない。"""
    events = _session(100, "a", old_ids=True) + _session(300, "b", old_ids=True) + _session(500, "c")
    sessions = ba.split_sessions(ba.read_events([_write(tmp_path, events)]))
    got = ba.decision_ids(sessions)
    assert got == {"old_form": 2, "new_form": 1, "sessions_with_duplicates": 0}


def test_推定と実ターンの比較は材料が無いと言う(tmp_path):
    """⚠ 黙って 0 件にしない。"""
    sessions = ba.split_sessions(ba.read_events([_write(tmp_path, _session(100, "a"))]))
    got = ba.estimate_vs_actual(sessions)
    assert got["available"] is False and "events に入っていない" in got["note"]


def test_CLIが動いてJSONを返す(tmp_path, capsys):
    p = _write(tmp_path, _session(100, "a") + _session(200, "p1") + _session(200, "p2"))
    assert ba.main(["veto", "--events", str(p), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["probe_sessions"] == 2
    assert out["result"]["rows"][0]["count"] == 1          # ★検査由来の 2 本は除かれている
    assert ba.main(["veto", "--events", str(p), "--json", "--include-probes"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["rows"][0]["count"] == 3
