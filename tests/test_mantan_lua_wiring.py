"""まんたん設定が Lua まで届くか（2026-08-02 / 指示書 §13・§15.9）。

★★ **設定は「作った」だけでは届かない。** ★★

  ⚠ 過去に踏んだ形（リファクタ Phase 2 / playbook）:
    呼び出しだけ残して定義を入れ忘れ、構文チェックも pytest も緑のまま
    **実機で初めて効いていないと分かった**。

  ここでは「Python が書いた名前」と「Lua が読む名前」が
  **同じであること**を機械で見張る。⚠ 片方だけ直すと落ちる。

## 経路（指示書 §13）

    config/mantan.yaml
        ↓ Python で読込・検証・同梱設定とマージ
    work/generated/config.lua の `mantan`
        ↓
    retroux/plugins/dq2/mantan.lua
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

from retroux.core.config import generate_lua
from retroux.core.mantan import MantanSettings

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANTAN_LUA = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "mantan.lua"
PLUGIN_CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
SETTINGS_HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
                    / "mantan_settings_test.lua")
LOG_LINES_HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
                     / "mantan_log_lines_test.lua")


def _run_lua(harness: pathlib.Path) -> str:
    """★RX-0011: 本物の `mantan.lua` を実 Lua で動かした出力を返す。"""
    if not (RUNNER.exists() and harness.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(harness)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _section(result: str, header: str) -> str:
    """`== N. ... ==` の見出しから次の見出しまでを切り出す。

    ⚠ `mantan_settings_test.lua` は同じ名前（やくそう 等）を複数の節で
      出すので、節を切らないと**別の節の OK を拾って**しまう。
    """
    lines = result.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("== ")]
    for n, i in enumerate(starts):
        if header in lines[i]:
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            return "\n".join(lines[i:end])
    raise AssertionError(f"節が見つからない: {header}\n{result}")


@pytest.fixture(scope="module")
def settings_result() -> str:
    return _run_lua(SETTINGS_HARNESS)


@pytest.fixture(scope="module")
def log_lines_result() -> str:
    return _run_lua(LOG_LINES_HARNESS)


@pytest.fixture(scope="module")
def lua_source() -> str:
    return MANTAN_LUA.read_text(encoding="utf-8")


def test_設定の名前がLua側と一致する(lua_source):
    """★★ ここが今回の要。**名前は2か所で決めない。**

    `MantanSettings.to_lua_dict()` が出す名前を、`mantan.lua` が
    `mcfg.<名前>` で読んでいること。⚠ 片方を直し忘れたら赤くなる。
    """
    missing = []
    for name in MantanSettings().to_lua_dict():
        if f"mcfg.{name}" not in lua_source:
            missing.append(name)
    assert not missing, (
        f"Python が渡しているのに Lua が読んでいない: {missing}")


def test_生成されるconfigに新しい値が入る(tmp_path, monkeypatch):
    """★実際に `_merge_mantan` を通す（型を書き写すのではなく動かす）。"""
    user = tmp_path / "mantan.yaml"
    user.write_text(yaml.safe_dump({"target_hp_percent": 75,
                                    "mp_allocation": {"policy": "most_mp"}}),
                    encoding="utf-8")
    import retroux.core.mantan.repository as repo
    monkeypatch.setattr(repo, "USER_PATH", user)

    base = yaml.safe_load(PLUGIN_CONFIG.read_text(encoding="utf-8"))
    got = generate_lua._merge_mantan(base)

    assert got["mantan"]["target_hp_percent"] == 75
    assert got["mantan"]["mp_policy"] == "most_mp"
    assert got["mantan"]["settings_problems"] == []


def test_既存の設定名を壊していない(tmp_path, monkeypatch):
    """⚠ 指示書 §14: `methods` `cure_methods` `modes` などを消さない。"""
    import retroux.core.mantan.repository as repo
    monkeypatch.setattr(repo, "USER_PATH", tmp_path / "ない.yaml")

    base = yaml.safe_load(PLUGIN_CONFIG.read_text(encoding="utf-8"))
    before = set((base.get("mantan") or {}).keys())
    got = generate_lua._merge_mantan(base)
    after = set(got["mantan"].keys())
    assert before <= after, f"消えた項目: {before - after}"


def test_設定の不備はLuaまで運ばれる(tmp_path, monkeypatch):
    """★「黙って捨てない」。理由を Lua まで渡して画面に出せるようにする。"""
    user = tmp_path / "mantan.yaml"
    user.write_text(yaml.safe_dump({"target_hp_percent": 999}),
                    encoding="utf-8")
    import retroux.core.mantan.repository as repo
    monkeypatch.setattr(repo, "USER_PATH", user)

    base = yaml.safe_load(PLUGIN_CONFIG.read_text(encoding="utf-8"))
    got = generate_lua._merge_mantan(base)
    assert got["mantan"]["target_hp_percent"] == 90        # ★既定へ落ちる
    assert got["mantan"]["settings_problems"], "理由が運ばれていない"


def test_知らないpolicyはLua側でも安全側へ倒れる(lua_source):
    """⚠ 古い生成物が残っていることもある。Lua 側でも確かめている。"""
    assert "local function pick(" in lua_source
    assert '"after_spells"' in lua_source
    assert '"remaining_ratio_balance"' in lua_source


def test_知らないpolicyはLua側でも安全側へ倒れる_の挙動(settings_result):
    """★RX-0011: 字面の検査に挙動を併設。

    `mantan_settings_test.lua` §4 は本物の `Mantan.new` に
    でたらめな値（`herb_policy = "ぜんぶ使う"`, `mp_policy = 7`）を渡す。
    ★ここでは**その節の OK 行**を見る（⚠ 同じ名前が §1 にも出るので節で切る）。
    """
    sec = _section(settings_result, "== 4.")
    assert "OK   やくそう = after_spells" in sec, sec
    assert "OK   MP配分 = remaining_ratio_balance" in sec, sec
    assert "★NG" not in sec, sec


def test_既定がONの項目はnilでもONになる(lua_source):
    """⚠⚠ `mcfg.x or true` と書くと **false を true に戻してしまう**。

    ★`~= false` なら「設定が無い(nil)ときだけ ON」になる。
    """
    for name in ("healing_spells_enabled", "poison_cure_enabled",
                 "use_tactics_reserve"):
        assert re.search(rf"mcfg\.{name}\s*~=\s*false", lua_source), name
        assert f"mcfg.{name} or true" not in lua_source, name


def test_割合の指定はmodeより優先される(lua_source):
    """指示書 §6.2: `target_hp_percent` があれば最優先。"""
    assert "mcfg.target_hp_percent" in lua_source
    assert "percent / 100" in lua_source


def test_割合の指定はmodeより優先される_の挙動(settings_result):
    """★RX-0011: 字面の検査に挙動を併設。

    §6: `target_hp_percent = 60` だけ渡すと `target_ratio` が 0.6 になる
    （★設定ファイルの mode 既定 ratio90 より割合が勝つ）。
    """
    sec = _section(settings_result, "== 6.")
    assert "OK   mode 指定が無ければ割合 = 0.6" in sec, sec


def test_その場のmode指定は設定より優先される(lua_source):
    """⚠ `--mode full` と言われているのに 90% で上書きしたら指示を無視している。

    ★`opts.mode` が明示されたときは mode を勝たせる。
    """
    assert "opts.mode == nil" in lua_source


def test_その場のmode指定は設定より優先される_の挙動(settings_result):
    """★RX-0011: 字面の検査に挙動を併設。

    §6: `target_hp_percent = 90` を設定しつつ `opts.mode = "full"` を渡すと
    `target_ratio` が 1.0（★その場の指示が勝つ）。
    """
    sec = _section(settings_result, "== 6.")
    assert "OK   mode が勝つ = 1" in sec, sec


def test_既存のmodeは消していない(lua_source):
    """指示書 §14 の後方互換。"""
    for name in ("ratio90", "full", "mcfg.modes", "mcfg.mode"):
        assert name in lua_source, name


def test_進捗の通知は引数の数をそろえている(lua_source):
    """⚠⚠ 2026-08-02 に実際にやらかした。

    `on_progress(msg)` と1つで呼んだ箇所があり、受け側は `(phase, msg)` を
    期待していた。★引数の数が違っても Lua は落ちない。**静かにずれる**。
    """
    calls = re.findall(r"on_progress\(([^)]*)\)", lua_source)
    # ★代入（self.on_progress = ...）は拾わない
    calls = [c for c in calls if c.strip() and "opts." not in c]
    bad = [c for c in calls if c.count(",") != 1]
    assert not bad, f"引数が (phase, msg) になっていない: {bad}"


def test_実行開始時に方針の概要を出す(lua_source):
    """指示書 §11.1。★何が効いているかログだけで分かるように。"""
    assert "_settings_summary" in lua_source
    assert "まんたん開始: 目標" in lua_source
    assert "MP配分:" in lua_source
    # ⚠ 設定の不備も一緒に出す。黙って捨てない
    assert "settings_problems" in lua_source


def test_実行開始時に方針の概要を出す_の挙動(log_lines_result):
    """★RX-0011: 字面の検査に挙動を併設。

    `mantan_log_lines_test.lua` が本物の `Mantan.new` で作った入れ物から
    `_settings_summary()` を呼び、★設定した目標%・MP配分の説明・
    `settings_problems` の文言が**行として返る**ことを見る。
    """
    r = log_lines_result
    assert "すべて通りました" in r, r
    assert "OK   ★★ 1行目に設定した目標%が入る" in r, r
    assert "OK   ★★ MP配分の方針が日本語の説明で出る" in r, r
    assert "OK   ★★ settings_problems の文言が概要の行に入る" in r, r


def test_選んだ理由を出す(lua_source):
    """指示書 §11.2。"""
    assert "_healing_reason" in lua_source
    assert "推定総消費MP" in lua_source


def test_選んだ理由を出す_の挙動(log_lines_result):
    """★RX-0011: 字面の検査に挙動を併設。

    `_healing_reason(entry, missing)` を実際に呼び、★手段名・不足HP・
    推定回数・推定総消費MP が数字つきで1文に入ること、
    ⚠ 補正が効いたときだけ補正後の値が足されることを見る。
    """
    r = log_lines_result
    assert "すべて通りました" in r, r
    assert "OK   ★★ 推定総消費MPが数字つきで入る" in r, r
    assert "OK   ★★ 補正が効いたら補正後の値と唱える人を書く" in r, r
    assert "OK   ★期待回復量が未確認なら「比較の対象外」と言う" in r, r


def test_既定ONの判定はnilを偽にしない(lua_source):
    """⚠⚠ 2026-08-02 に実際にやらかした（既存テスト9件が赤くなった）。

    `if not self.poison_cure_enabled` と書いたところ、`Mantan.new` を
    通さずに作られた入れ物（検証ハーネス）では nil になり、
    **黙って解毒しなくなった**。

    ★`new()` と同じ規則にそろえる: **nil は「設定が無い」＝既定の ON**。
      判定は `== false` / `~= false` で書く。
    """
    for name in ("poison_cure_enabled", "healing_spells_enabled"):
        assert f"not self.{name}" not in lua_source, (
            f"self.{name} を `not` で見ている（nil が偽になる）")


def test_ログの文言は画面の選択肢をそのまま埋めない(lua_source):
    """⚠ 2026-08-02 に依頼者から「日本語的におかしい」とご指摘。

    「やくそうは**呪文を優先する**」は文として崩れる。
    ★選択肢は「やくそうの使用は？」への答え、ログは文の一部。用途が違う。
    """
    # ⚠ 注釈にはこの文字列が**例として**書いてある。コードだけを見る
    code = re.sub(r"--.*", "", lua_source)
    assert "呪文を優先する" not in code, "画面の選択肢をログに流用している"
    # ★ログ側は文に埋まる言い方
    assert "呪文の次に使う" in code
