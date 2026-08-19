"""MPの予約と行動の優先順を Lua で**実際に呼ぶ**（Phase 6 P5）。

★守っている契約（中身は research/probes/active/reserve_test.lua）:
  1. 予約は「その人が**覚えている**呪文」の mp_field の合計
     - ROM の SpellLevels: ルーラ(0x14) はサマルトリアだけ /
       リレミト(0x12) はサマルトリア LV12・ムーンブルク LV17 の両方
     - ローレシアは呪文を持たないので 0
  2. 予約を割り込んでは唱えない
  3. そのときの理由が「MP不足」ではなく**予約**だと分かる
     （混ぜると利用者は宿屋へ行き、戻ってきても同じことが起きる）
  4. 予約ぶんを満たせば唱える（予約が「常に唱えない」になっていない）
  5. 優先順の解決が、知らない名前・重複・書き漏れ・target の位置を直し、
     **直したことを必ずログに出す**

⚠ 材料（lua5.1.dll / work/ramdump / work/generated）が無い環境では skip する。
  ★Lua 側は材料が無いとき終了コード 2 を返し、ここで skip として扱う
  （playbook #43「採れなかったを合格に見せない」）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DLL = PROJECT_ROOT / "tools" / "fceux" / "lua5.1.dll"
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "reserve_test.lua"
GENERATED = PROJECT_ROOT / "work" / "generated" / "memory_map.lua"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and SCRIPT.exists() and GENERATED.exists()),
    reason=("Lua を動かす材料が無い（tools/fceux/lua5.1.dll・"
            "research/probes/active/reserve_test.lua・work/generated）"),
)


@pytest.fixture(scope="module")
def result() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER), str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
        env={**os.environ, "RETROUX_ROOT": str(PROJECT_ROOT)},
    )


def _out(result) -> str:
    return (result.stdout or "") + (result.stderr or "")


def test_lua_checks_pass(result):
    """★本題: NG が 0 件であること。"""
    out = _out(result)
    if result.returncode == 2:
        pytest.skip("RAM ダンプが無いため予約の検査を実施できていない:\n" + out)
    assert result.returncode == 0, "reserve_test.lua が NG を報告しました:\n" + out
    assert "NG 0 件" in out, out


def test_reports_enough_checks(result):
    """検査が1件も走らずに「成功」になっていないこと。"""
    out = _out(result)
    if result.returncode == 2:
        pytest.skip("材料不足")
    m = re.search(r"OK (\d+) 件", out)
    assert m is not None, "件数が報告されていない:\n" + out
    assert int(m.group(1)) >= 20, f"検査が {m.group(1)} 件しか走っていない:\n{out}"


def test_reserve_reason_is_distinguishable_from_low_mp(result):
    """★予約で唱えないことが、MP不足と**区別できる**文言で出ること。

    ここを混ぜると、利用者は「MPが無い」と思って宿屋へ行き、
    満タンで戻ってきても同じことが起きる（直しようがない報告になる）。
    """
    out = _out(result)
    if result.returncode == 2:
        pytest.skip("材料不足")
    assert "残すため" in out, out
    # ★「MPが足りない」だけの文言で落ちていないこと
    assert "唱えない: ホイミ は唱えられるが" in out or "残すため使わない" in out, out


def test_priority_changes_are_logged(result):
    """優先順を直したときに、**直したことを言っている**こと。

    ★黙って並べ替えると、設定を直したつもりの利用者に伝わらない
      （playbook #45「設定を変えたのに何も変わらない」の裏返し）。
    """
    out = _out(result)
    for phrase in ("戦闘の行動の優先順:", "知らない行動名", "末尾に足しました",
                   "末尾**に回しました"):
        assert phrase in out, f"「{phrase}」がログに出ていない:\n{out}"


def test_lorasia_has_no_reserve(result):
    """ローレシアに予約が付いていないこと（呪文を持たない）。"""
    out = _out(result)
    if result.returncode == 2:
        pytest.skip("材料不足")
    m = re.search(r"lorasia\s+予約\s+(\d+) MP", out)
    assert m is not None, "ローレシアの行が出ていない:\n" + out
    assert m.group(1) == "0", out
