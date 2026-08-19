"""検査が製品の記録を汚さないことを固定する（製品版ログ整理 Phase 2）。

## ⚠⚠ 何が起きていたか（2026-08-13 の実測）

    pytest tests/test_lua_harnesses_actually_run.py   # 19 件だけ
      work/events.jsonl  +1,251 バイト
      work/retroux.log   +5,883 バイト

`research/probes/` は実 Lua で `Bridge.new` を呼ぶ。`Bridge.new` は
`work/events.jsonl` と `work/retroux.log` を**追記で開く**ので、
検査を流すたびに本物の記録が伸びていた。

⚠ `events.jsonl` は `recorder` が SQLite へ取り込む。
  つまり**検査の記録が製品の DB に入っていた**（`session_start` 2,847 件の
  大半、同一秒に最大 13 件という不自然な並びで残っている）。

★直し方: `RETROUX_WRITE_ROOT` で**書く先だけ**を隔離先へ向ける。
  読み込み元（`RETROUX_ROOT`）は本物のまま（生成物がそこにしかない）。

## ★ ここで見ること

  1. 隔離先に**実際に書かれる**こと
     ⚠ 「本物が増えない」だけでは足りない。`io.open` が失敗して
       **黙って捨てている**場合も同じ見え方になる（`Bridge:log` は
       開けなければ何もしない）。
  2. 本物の `work/events.jsonl` / `work/retroux.log` が**増えない**こと
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
# ★Bridge.new を実際に呼ぶ probe（＝ログとイベントを開く）
PROBE = PROJECT_ROOT / "research" / "probes" / "active" / "decision_snapshot_test.lua"

SANDBOX = PROJECT_ROOT / "work" / "_test_sandbox" / "work"
REAL_EVENTS = PROJECT_ROOT / "work" / "events.jsonl"
REAL_LOG = PROJECT_ROOT / "work" / "retroux.log"


def _size(path: pathlib.Path) -> int:
    return path.stat().st_size if path.exists() else -1


@pytest.fixture(scope="module")
def run_probe():
    if not (RUNNER.exists() and PROBE.exists()):
        pytest.skip("Lua のハーネスが無い")
    before = (_size(REAL_EVENTS), _size(REAL_LOG))
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(PROBE)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out or (done.returncode != 0 and "lua5.1" in err):
        pytest.skip("Lua を動かせない環境")
    after = (_size(REAL_EVENTS), _size(REAL_LOG))
    return {"before": before, "after": after, "out": out + err}


def test_probeが実際に動いている(run_probe):
    """⚠ 動いていないのに「汚さない」が通るのを防ぐ。"""
    assert "NG 0 件" in run_probe["out"], run_probe["out"][-2000:]


def test_本物のeventsが増えない(run_probe):
    before, after = run_probe["before"][0], run_probe["after"][0]
    assert after == before, (
        f"work/events.jsonl が {after - before} バイト増えた。"
        "★検査の記録が製品 DB に入る")


def test_本物のログが増えない(run_probe):
    before, after = run_probe["before"][1], run_probe["after"][1]
    assert after == before, (
        f"work/retroux.log が {after - before} バイト増えた")


def test_隔離先に実際に書かれている(run_probe):
    """★★ ここが要（黙って捨てているだけ、を見抜く）★★

    ⚠ `Bridge:log` は `io.open` が失敗しても例外を出さない。
      隔離先の**中身**まで見ないと、「消えている」と「汚していない」を
      取り違える。

    ## ⚠ ログではなく events で見る理由（2026-08-13 に踏んだ）

      Phase 3 で人向けの行を DEBUG へ落とした結果、**normal では
      この probe がログを1行も書かなくなった**（★正しい挙動）。
      ⚠ ログの大きさで判定すると、正しくなった瞬間に赤くなる。

      ★`emit`（events.jsonl）は**段階を見ない**ので、
        「書き込みが届いているか」の判定材料として安定している。
      ★ログ側が届くことは `test_logging_mode` が diagnostic で見ている。
    """
    log = SANDBOX / "retroux.log"
    events = SANDBOX / "events.jsonl"
    assert log.exists() and events.exists(), f"隔離先が無い: {SANDBOX}"
    assert events.stat().st_size > 0, "隔離先の events が空（書き込みが消えている）"
    body = events.read_text(encoding="utf-8", errors="replace")
    assert "session_start" in body, body[:400]


def test_読み込み元は本物のまま():
    """⚠ `RETROUX_ROOT` まで隔離すると生成物を読めず、probe が全部落ちる。"""
    source = RUNNER.read_text(encoding="utf-8")
    assert "RETROUX_WRITE_ROOT" in source
    assert 'os.environ["RETROUX_ROOT"]' not in source, (
        "読み込み元まで差し替えている")
