"""⚠⚠ **書いたのに一度も走らせていない Lua の検査**を無くす（2026-08-12 / F-089）。

## ★なぜこのファイルが要るか

監査で、`research/probes/**/*_test.lua` のうち **29本が `pytest` から
一度も呼ばれていない**ことが分かりました。名前が `.py` の docstring に
出てくるだけ、というものまでありました。

⚠⚠ 実害が出ていました。`manual_input_test.lua`（★人の入力が消える不具合の
見張り）は、`bridge.lua` に `_track_turn_actor` が増えた **2026-08-08 から
9日間、最初の関数で落ちたまま**でした。⚠ 走らせていないので誰も気づきません。
そのあいだ、対応する `.py` の**文字列検査は全部緑**でした。

## ★ここで守ること

| | |
| --- | --- |
| **走る** | 下の `RUNNABLE` は実際に起動し、成功の目印と件数まで見ます |
| **数える** | ⚠ 途中で落ちて「0件なので合格」にならないよう、**最低件数**を置きます |
| **見張る** | ⚠⚠ `*_test.lua` を新しく足したのに**どちらの表にも入れなかったら赤**にします |

★`NEEDS_FCEUX` は「実機の中でしか動かない」と**明記して**外すための表です。
⚠ 黙って除外しません（除外は理由つきで残す / playbook）。
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
PROBES = PROJECT_ROOT / "research" / "probes"

#: 実機なしで走るもの。`(ファイル名, 成功の目印, OK行の最低数)`
#:   ★目印は**その検査が最後まで行った印**を選ぶ（途中で落ちたら出ない）。
RUNNABLE: list[tuple[str, str, int]] = [
    # ⚠⚠ この3本は「別の .py の docstring が名前を出しているだけ」でした。
    #   ★読んだ人は「確認してある」と思いますが、**走っていません**でした。
    ("manual_input_test.lua", "すべて合格", 11),
    # ★F-089 の置き換え第2弾（2026-08-12）。亀の子の入口を実 Lua で見る。
    ("fixed_action_test.lua", "すべて合格", 11),
    # ★F-089 第3弾。攻撃呪文の門（2026-08-03 に実際に事故ったところ）。
    ("attack_spell_gate_test.lua", "すべて合格", 20),
    # ★F-089 第4弾。行動の記録（実機で25件・35件の欠けが出たところ）。
    ("record_action_test.lua", "すべて合格", 24),
    # ★F-089 第5弾。自己回復の道具選び（2026-08-04 の実機ログの穴）。
    ("self_heal_item_test.lua", "すべて合格", 17),
    # ★F-089 第6弾。判断の記録（2026-07-31「切り替わる」の不具合）。
    ("ai_decisions_test.lua", "すべて合格", 20),
    # ★F-089 第7弾。暗転中に地図を採らない（2026-08-11「なぜ黒塗りに」）。
    ("map_blackout_test.lua", "すべて合格", 17),
    # ★F-089 第8弾。既定 legacy（★4ファイルが同じ字面を見ていた束）。
    ("engine_default_test.lua", "すべて合格", 17),
    # ★F-089 第9弾。属性（パレット組）の式。⚠ 期待値は Python が作るので、
    #   ここ単独で走らせると照合の部分だけ SKIP になります
    #   （★通しは tests/test_live_map_wiring.py から）。
    ("attribute_formula_test.lua", "すべて合格", 8),
    # ★F-089 第10弾。見立てへ渡す敵（★2026-08-06 と 08-11 に2回こけた）。
    ("assess_enemy_view_test.lua", "すべて合格", 18),
    ("framecount_rewind_test.lua", "すべて通りました", 9),
    ("overkill_test.lua", "すべて通りました", 16),
    ("mantan_ranking_test.lua", "すべて通りました", 40),
    ("mantan_settings_test.lua", "すべて通りました", 20),
    ("map_observe_gate_test.lua", "NG 0 件", 20),
    ("spellrow_test.lua", "不一致・食い違い: 0", 0),
    ("tile_scroll_test.lua", "すべて通りました", 0),
]

#: ⚠ FCEUX の中でしか動かないもの（`emu` / `savestate` の本物が要る）。
#:   ★理由を書いて**明示的に**外します。黙って落とさないため。
NEEDS_FCEUX: dict[str, str] = {
    "carrier_balance_test.lua": "emu.framecount と実機の持ち物が要る",
    "caution_test.lua": "emu が要る",
    "encountered_merge_test.lua": "emu が要る",
    "force_auto_test.lua": "emu が要る",
    "force_auto_toggle_test.lua": "emu が要る",
    "hoimi_test.lua": "emu が要る",
    "latch_test.lua": "emu が要る",
    "levelup_b11_test.lua": "emu が要る",
    "mantan_command_test.lua": "emu が要る",
    "mantan_integration_test.lua": "★自分で「FCEUX の中で動かしてください」と言う",
    "mantan_rows_test.lua": "emu が要る",
    "msg_test.lua": "実機の RAM とメッセージ表示が要る",
    "o2_api_test.lua": "emu が要る",
    "p3_plan_test.lua": "実機の戦闘状態が要る",
    "ratio_test.lua": "emu が要る",
    "restock_test.lua": "emu が要る",
    "savestate_command_test.lua": "savestate の本物が要る",
    "speed_events_test.lua": "emu が要る",
    "staff_use_test.lua": "emu が要る",
    "stale_config_test.lua": "emu が要る",
    "talk_dispatch_test.lua": "emu が要る",
    "target_priority_test.lua": "emu と実際の入力レジスタが要る",
    "throttle_actual_test.lua": "emu の速度制御が要る",
    "thunder_test.lua": "emu が要る",
}


def _find(name: str) -> pathlib.Path | None:
    hits = sorted(PROBES.glob(f"**/{name}"))
    return hits[0] if hits else None


def _run(path: pathlib.Path) -> str:
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(path)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=180,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    both = out + err
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, (
        f"⚠⚠ {path.name} が落ちました。★文字列検査だけでは分かりません\n{both}")
    return both


@pytest.mark.parametrize(("name", "marker", "least"), RUNNABLE,
                         ids=[r[0] for r in RUNNABLE])
def test_ハーネスが本当に走って合格する(name, marker, least):
    """★起動して、成功の目印が出るまで見ます。"""
    path = _find(name)
    if path is None:
        pytest.skip(f"{name} が無い")
    result = _run(path)
    assert marker in result, f"⚠ 成功の目印『{marker}』が出ていません\n{result}"
    if least:
        count = sum(1 for line in result.splitlines()
                    if re.match(r"^OK\b", line))
        assert count >= least, (
            f"⚠⚠ OK が {count} 件しかありません（{least} 件以上のはず）。"
            f"★途中で落ちていないか見てください\n{result}")


def _named_in_code() -> set[str]:
    """★他の `.py` が**コードとして**名前を持っているものを集める。

    ⚠⚠ **docstring の中の名前は数えません。**
      ★`manual_input_test.lua` は「この検査が動きを見ている」と
        docstring に書いてあるだけで、**一度も走っていませんでした**。
        文字列を素朴に探すと、これを「走らせている」と誤って数えます。
    """
    found: set[str] = set()
    for path in sorted((PROJECT_ROOT / "tests").glob("*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        docstrings = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.endswith(".lua")
                    and id(node) not in docstrings):
                found.add(node.value.rsplit("/", 1)[-1])
    return found


def test_走らせていないハーネスを増やさない():
    """⚠⚠ **これがこのファイルの本体です。**

    `*_test.lua` を新しく置いたのに、どこからも走らせず、
    `RUNNABLE` にも `NEEDS_FCEUX` にも入れなかったら赤くします。

    ★「書いたけれど走らせていない」を**増やさない**ための門です。
      ⚠ 29本まで溜まってから気づいた、というのが 2026-08-12 の反省です。
    """
    known = {n for n, _m, _l in RUNNABLE} | set(NEEDS_FCEUX) | _named_in_code()
    found = {p.name for p in PROBES.glob("**/*_test.lua")}
    unlisted = sorted(found - known)
    assert not unlisted, (
        "⚠⚠ 走らせるかどうかを決めていない Lua の検査があります:\n  "
        + "\n  ".join(unlisted)
        + "\n★実機なしで走るなら RUNNABLE へ、"
          "FCEUX が要るなら理由つきで NEEDS_FCEUX へ入れてください")


def test_外した理由を必ず書いてある():
    """⚠ `NEEDS_FCEUX` に空の理由を置かせない（★黙って外さない）。"""
    empty = [n for n, why in NEEDS_FCEUX.items() if not (why or "").strip()]
    assert not empty, f"★外す理由が空です: {empty}"
