"""保存したケースを AI へ投入する（2026-08-08 / 資産化 §18 Phase 5）。

    > Replayable / Golden Case を AI エンジンへ投入し、
    > **ゲームを起動せずに**判定する。（指示書 §14）

## ★★★ 何ができるか

    replay        … ★1件のケースを AI へ入れて、判断を見る
    compare       … ★同じ場面を**戦術だけ変えて**比べる（§15 反実仮想）
    check         … ★golden ケース（`expected` 入り）を判定する

## ⚠⚠ 再生できないもの（★正直に書きます）

  「たたかう / 呪文 / 道具」の**最終的な選択**は再生できません。
  ★あれは `bridge.lua` の claim が RAM とメニューを見て決めます。
  ⚠ ここで「できる」ことにすると、**通っていない道を通ったことに**なります。

  ★再生できるのは、その手前の層です:
    BattleAssessment / BattleDirective / ActorRole /
    allowed・prohibited action types / 回復の狙い先 / 補助行動の候補

## ★ 使い方

    python -m retroux.tools.battle_replay replay --case b10_t0_lorasia
    python -m retroux.tools.battle_replay compare --case b10_t0_lorasia
    python -m retroux.tools.battle_replay check --golden tests/data/battle_cases

⚠ `Bridge.new` を通さないので、★人が遊んでいる最中でも安全です。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
REPLAY = PROJECT_ROOT / "research" / "probes" / "reusable" / "replay_case.lua"
DEFAULT_CASES = (PROJECT_ROOT / "work" / "battle-cases" / "replayable.jsonl")
GOLDEN_DIR = PROJECT_ROOT / "tests" / "data" / "battle_cases"

#: ★戦術を差し替えて比べる（指示書 §15）
PLANS = ("quick", "protect", "conserve", "threat", "turtle", "spellfire")


def _out(text: str = "") -> None:
    print(text)


def _lua_literal(value) -> str:
    """Python の値を Lua のリテラルにする。

    ⚠⚠ **Lua に JSON パーサはありません**（★同梱されていない）。
      → ケースを Lua のテーブルとして書き出して読ませます。
    """
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # ⚠ `%q` 相当。★改行と引用符を落とさない
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(_lua_literal(v) for v in value) + "}"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if isinstance(k, int):
                parts.append(f"[{k}]={_lua_literal(v)}")
            else:
                parts.append(f"[{_lua_literal(str(k))}]={_lua_literal(v)}")
        return "{" + ",".join(parts) + "}"
    return _lua_literal(str(value))


def run_case(case: dict, override: dict | None = None) -> dict:
    """1件のケースを AI へ入れて、返ってきた値を辞書にする。

    ⚠ 落ちたら `{"error": ...}` を返します（★呼ぶ側が判定できるように）。
    """
    script = (
        f"CASE = {_lua_literal(case)}\n"
        f"OVERRIDE = {_lua_literal(override or {})}\n"
        f'dofile("{REPLAY.as_posix()}")\n'
    )
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    try:
        done = subprocess.run(
            [sys.executable, str(RUNNER), path],
            cwd=str(PROJECT_ROOT), capture_output=True, timeout=60)
        text = ((done.stdout or b"") + (done.stderr or b"")).decode(
            "utf-8", "replace")
    finally:
        try:
            pathlib.Path(path).unlink()
        except OSError:
            pass

    got: dict = {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        key, _, value = line.partition("\t")
        got[key.strip()] = value.strip()
    if not got:
        return {"error": text.strip()[:400]}
    return got


def load_cases(path: pathlib.Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:                              # noqa: BLE001
            continue                                   # ⚠ 壊れた行は飛ばす
    return out


def cmd_replay(cases_path: pathlib.Path, case_id: str | None,
               limit: int) -> int:
    cases = load_cases(cases_path)
    if not cases:
        _out(f"✗ ケースがありません: {cases_path}")
        _out("★`battle_cases replayable` で作ってください")
        return 1
    if case_id:
        cases = [c for c in cases if c.get("case_id") == case_id]
        if not cases:
            _out(f"✗ そのケースがありません: {case_id}")
            return 1
    shown = 0
    for case in cases[:limit]:
        got = run_case(case)
        if "error" in got:
            _out(f"⚠ {case.get('case_id')}: {got['error']}")
            continue
        _out(f"== ★ {got.get('case_id')} / {got.get('actor')} ==")
        _out(f"  戦況     {got.get('balance')} / {got.get('length')}"
             f"（撃破 {got.get('win_turns')} / 崩壊 {got.get('lose_turns')}）")
        _out(f"  戦術     {got.get('plan')}"
             f"（資源 {got.get('resource_policy')}）")
        _out(f"  回復先   {got.get('heal_target')}"
             f"（{got.get('heal_reason')}）")
        _out(f"  補助     {got.get('support')}")
        # ⚠ 観測は「実際にこう動いた」だけ。★正解ではありません（原則1）
        _out(f"  ⚠ 実際  {got.get('observed.action')}"
             f" -> {got.get('observed.target')}（★正解ではありません）")
        shown += 1
    _out()
    _out(f"★ {shown} 件を再生しました（全 {len(cases)} 件）")
    return 0


def cmd_compare(cases_path: pathlib.Path, case_id: str | None) -> int:
    """同じ場面を**戦術だけ変えて**比べる（指示書 §15 反実仮想）。

    ★これが「戦術差の確認に非常に有効」と書かれているものです。
    """
    cases = load_cases(cases_path)
    if case_id:
        cases = [c for c in cases if c.get("case_id") == case_id]
    if not cases:
        _out("✗ ケースがありません")
        return 1
    case = cases[0]
    _out(f"== ★ {case.get('case_id')} を戦術ごとに比べる ==")
    base = run_case(case)
    _out(f"  戦況 {base.get('balance')}（撃破 {base.get('win_turns')}"
         f" / 崩壊 {base.get('lose_turns')}）")
    _out()
    _out(f"  {'戦術':<10} {'資源':<12} {'回復先':<12} {'補助'}")
    for plan in PLANS:
        got = run_case(case, {"plan": plan})
        if "error" in got:
            _out(f"  ⚠ {plan}: {got['error'][:80]}")
            continue
        _out(f"  {plan:<10} {str(got.get('resource_policy')):<12}"
             f" {str(got.get('heal_target')):<12} {got.get('support')}")
    _out()
    _out("⚠ 「たたかう/呪文/道具」の最終選択は再生できません"
         "（★RAM とメニューを見る claim の担当）")
    return 0


def check_case(case: dict) -> tuple:
    """golden ケースを判定する（指示書 §14.1・§14.2）。

    戻り値: `(合否, 理由の並び)`
    ⚠ `expected` が無いケースは**判定しません**（★観測は正解ではない）。
    """
    expected = case.get("expected")
    if not expected:
        return None, ["⚠ `expected` がありません（★観測は正解ではありません）"]

    got = run_case(case, expected.get("override"))
    if "error" in got:
        return False, [f"⚠ 動かせません: {got['error'][:200]}"]

    problems = []
    for key in ("plan", "balance", "resource_policy", "heal_target",
                "support"):
        want = expected.get(key)
        if want is None:
            continue
        if str(got.get(key)) != str(want):
            problems.append(f"⚠ {key}: {got.get(key)}（期待 {want}）")

    # ★§14.1 許容結果
    for kind in expected.get("allowed_action_types") or []:
        if got.get(f"may_act.{kind}") != "true":
            problems.append(f"⚠ {kind} を許していません")
    # ★§14.2 禁止結果
    for kind in expected.get("forbidden_action_types") or []:
        if got.get(f"may_act.{kind}") != "false":
            problems.append(f"⚠⚠ {kind} を禁じていません")

    return (not problems), problems


def cmd_check(golden_dir: pathlib.Path) -> int:
    if not golden_dir.exists():
        _out(f"⚠ golden がありません: {golden_dir}")
        _out("★人が見て「これは正解」と決めたケースを置く場所です")
        return 0                      # ⚠ 無いこと自体は失敗ではない
    files = sorted(golden_dir.glob("*.json"))
    if not files:
        _out(f"⚠ golden が0件です: {golden_dir}")
        return 0
    ok = ng = skip = 0
    for path in files:
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:                       # noqa: BLE001
            _out(f"  ★NG {path.name}: 読めません（{exc}）")
            ng += 1
            continue
        passed, problems = check_case(case)
        if passed is None:
            _out(f"  ⚠ SKIP {path.name}: {problems[0]}")
            skip += 1
        elif passed:
            _out(f"  OK   {path.name}")
            ok += 1
        else:
            _out(f"  ★NG {path.name}")
            for text in problems:
                _out(f"         {text}")
            ng += 1
    _out()
    _out(f"結果: OK {ok} 件 / NG {ng} 件 / ⚠ 判定なし {skip} 件")
    return 1 if ng else 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(
        description="保存したケースを AI へ投入する（★ゲームを起動しない）")
    parser.add_argument("command", choices=("replay", "compare", "check"))
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--case", default=None, help="case_id で1件だけ")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--golden", default=str(GOLDEN_DIR))
    args = parser.parse_args(argv)

    if args.command == "replay":
        return cmd_replay(pathlib.Path(args.cases), args.case, args.limit)
    if args.command == "compare":
        return cmd_compare(pathlib.Path(args.cases), args.case)
    if args.command == "check":
        return cmd_check(pathlib.Path(args.golden))
    return 1


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
