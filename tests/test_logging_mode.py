"""NORMAL / DIAGNOSTIC の2モード（製品版ログ整理 Phase 2 / 指示書 §19〜§21）。

## ⚠⚠ ここで見ている一番大事なこと

  **Lua 側にも効くこと。**

  ⚠ 2026-08-13 の棚卸しで分かったのは、`work/retroux.log` の
    **63%（33,578 行）が Lua 側で、段階を1つも持っていなかった**こと。
    Python 側の `level` をいくら上げても、その6割は出続けていた。

  ★だから「Python の設定が効く」だけを見る検査では**足りない**。
    実 Lua を動かして、normal で DEBUG が**出ない**ことを見る。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
PROBE = PROJECT_ROOT / "research" / "probes" / "active" / "decision_snapshot_test.lua"
SANDBOX_LOG = PROJECT_ROOT / "work" / "_test_sandbox" / "work" / "retroux.log"
GENERATED = PROJECT_ROOT / "work" / "generated" / "config.lua"
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


# --- Python 側 -----------------------------------------------------------

def test_normalではDEBUGを書かない():
    from retroux.core.logging_setup import levels_for_mode
    import logging

    assert levels_for_mode("normal")["level"] == logging.INFO


def test_diagnosticではDEBUGから書く():
    from retroux.core.logging_setup import levels_for_mode
    import logging

    assert levels_for_mode("diagnostic")["level"] == logging.DEBUG


def test_知らない綴りは静かなほうへ倒す():
    """⚠ 打ち間違いで公開版が急に毎ポーリング出力になるのを防ぐ。"""
    from retroux.core.logging_setup import levels_for_mode
    import logging

    for bad in ("verbose", "DEBUGGING", "", None, "diagnostics"):
        assert levels_for_mode(bad)["level"] == logging.INFO, bad


def test_明示されたlevelはmodeより優先する():
    """⚠ 昔の `level: DEBUG` を持つ設定を黙って無視しない。"""
    from retroux.core.config.user_config import LoggingConfig
    import logging

    assert LoggingConfig(mode="normal").resolved()["level"] == logging.INFO
    assert (LoggingConfig(mode="normal", level="DEBUG").resolved()["level"]
            == logging.DEBUG)


def test_既定はnormal():
    from retroux.core.config.user_config import LoggingConfig

    assert LoggingConfig().mode == "normal"
    assert LoggingConfig().diagnostic is False


# --- Lua 側（★ここが要）--------------------------------------------------

def test_Luaのログ関数が段階を受け取る():
    src = BRIDGE.read_text(encoding="utf-8")
    assert "function Bridge:log(message, ascii_hint, level)" in src
    assert "Bridge.resolve_log_min" in src


def test_Luaに段階ごとの別入口を作らない():
    """★★ ⚠⚠ ここは**戻さないための歯止め** ★★

    一度 `self:debug(...)` という別入口を作り、実 Lua の検査 15 件が

        attempt to call method 'debug' (a nil value)

    で落ちた。⚠ `research/probes/` は **`log` だけを持つ擬似テーブル**を
    bridge の代わりに渡す（実測 24 本 / 31 箇所。★`debug` を持つものは 0）。

    ★入口が1つだから probe は差し替えられる。増やすと全部直して回ることになる。
    """
    for rel in ("retroux/emulator/fceux/bridge.lua",
                "retroux/emulator/fceux/battle_controller.lua",
                "retroux/emulator/fceux/speed_controller.lua",
                "retroux/emulator/fceux/command_reader.lua"):
        src = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for name in ("debug", "warn", "error"):
            assert f":{name}(message" not in src, (
                f"{rel} に `:{name}(` の別入口ができている。"
                "★段階は `self:log(msg, hint, \"LEVEL\")` の第3引数で渡すこと")


def test_状態を持たない補助をメソッドにしない():
    """⚠⚠ **同じ罠を2度踏んだので、探す範囲を広げる。**

    1度目: `self:debug(...)`     → `attempt to call method 'debug' (a nil value)`
    2度目: `self:short_path(...)` → 同じ形で `test_monster_art` 等が落ちた

    ★`research/probes/` は **必要な鍵だけを持つ擬似テーブル**を渡すので、
      `self:` で呼ぶものが増えるたびに、全部の probe を直して回ることになる。

    ⚠ ここでは「状態を持たない補助」を名指しで見張る。
      ★新しく足すときは**モジュール内の関数**にして、必要な値を引数で渡すこと。
    """
    src = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
           / "bridge.lua").read_text(encoding="utf-8")
    # ⚠ 説明文の中の引用を数えない（★誤検知も壊れ方。ここでも一度踏んだ）
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("--")]
    for name in ("short_path",):
        bad = [ln.strip() for ln in code if f"self:{name}(" in ln]
        assert bad == [], (
            f"`self:{name}(` はメソッド呼び出し。★擬似テーブルでは落ちる。"
            f"モジュール内の関数として `{name}(root, ...)` の形にすること: {bad}")


def test_擬似テーブルでも段階つきの呼び出しが通る():
    """⚠ 「定義が無い」だけでは足りない。★実際に呼べることを見る。"""
    import subprocess
    import tempfile

    script = """
local root = os.getenv("RETROUX_ROOT")
-- ★log だけを持つ擬似テーブル（probe と同じ形）
local said = {}
local shim = { log = function(_self, msg, _hint, level)
  said[#said + 1] = tostring(level) .. "|" .. tostring(msg)
end }
shim:log("ふつう", nil)
shim:log("しらべ", nil, "DEBUG")
for _, s in ipairs(said) do print(s) end
"""
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    done = subprocess.run([sys.executable, str(RUNNER), path],
                          cwd=str(PROJECT_ROOT), capture_output=True, timeout=60)
    out = (done.stdout or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in (done.stderr or b"").decode("utf-8", "replace"):
        pytest.skip("Lua を動かせない環境")
    assert "nil|ふつう" in out, out
    assert "DEBUG|しらべ" in out, out


def test_Luaは段階を省略するとINFO扱い():
    """★既存の 115 箇所を書き換えずに済ませるための約束。"""
    src = BRIDGE.read_text(encoding="utf-8")
    body = src.split("function Bridge:log(message, ascii_hint, level)")[1]
    assert 'level = level or "INFO"' in body[:400], body[:400]


def _run_probe(mode: str) -> list[str]:
    """generated config の mode を差し替えて実 Lua を動かす。

    ⚠ `user_config.yaml` は利用者のもの。★検査では**生成物だけ**を
      一時的に触り、必ず元へ戻す。
    """
    original = GENERATED.read_bytes()
    try:
        text = original.decode("utf-8")
        # ★`logging` ブロックの mode だけを狙う（⚠ speed.mode とは別物）。
        #   実際に一度 speed.mode を書き換えて測定を外している。
        head, sep, tail = text.partition("  logging = {")
        assert sep, "logging ブロックが無い"
        tail = re.sub(r'mode = "\w+"', f'mode = "{mode}"', tail, count=1)
        GENERATED.write_bytes((head + sep + tail).encode("utf-8"))

        done = subprocess.run(
            [sys.executable, str(RUNNER), str(PROBE)],
            cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out = (done.stdout or b"").decode("utf-8", "replace")
        err = (done.stderr or b"").decode("utf-8", "replace")
        if "SKIP:" in out or (done.returncode != 0 and "lua5.1" in err):
            pytest.skip("Lua を動かせない環境")
        assert "NG 0 件" in out, out[-1500:]
        return SANDBOX_LOG.read_text(encoding="utf-8").splitlines()
    finally:
        GENERATED.write_bytes(original)


@pytest.fixture(scope="module")
def logs():
    if not (RUNNER.exists() and PROBE.exists() and GENERATED.exists()):
        pytest.skip("Lua のハーネスか生成物が無い")
    return {"normal": _run_probe("normal"),
            "diagnostic": _run_probe("diagnostic")}


def test_実Luaでnormalの行にDEBUGが無い(logs):
    """★★ ここが Phase 2 の完了条件（指示書 §20）★★"""
    debug = [ln for ln in logs["normal"] if "[DEBUG]" in ln]
    assert debug == [], f"normal なのに DEBUG が {len(debug)} 行出ている: {debug[:3]}"


def test_実Luaでdiagnosticには出る(logs):
    """⚠ 「normal で出ない」だけでは、**そもそも書けていない**のと区別できない。"""
    debug = [ln for ln in logs["diagnostic"] if "[DEBUG]" in ln]
    assert debug, "diagnostic でも DEBUG が1行も無い（★書けていない疑い）"


def test_normalのほうが行数が少ない(logs):
    assert len(logs["normal"]) < len(logs["diagnostic"]), (
        f"normal {len(logs['normal'])} 行 / diagnostic {len(logs['diagnostic'])} 行")


def test_Luaの行がPythonと同じ並びになっている(logs):
    """★`[LEVEL] 名前 本文` に揃える（grep しやすさのため）。"""
    pat = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
                     r"\[(DEBUG|INFO|WARNING|ERROR)\] lua ")
    bad = [ln for ln in logs["diagnostic"] if ln and not pat.match(ln)]
    assert bad == [], f"並びが違う行: {bad[:3]}"
