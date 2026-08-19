"""Lua の状態書き出しを**実際に呼んで**確かめる（MVP2 Phase 2）。

★なぜ要るか（2026-07-26 に実際に起きた）:

  `Bridge:_write_state` に `self.a.party` と書いた。`self.a` は
  **dq2.lua のフィールド**で Bridge には無い。構文は正しいので
  `research/probes/reusable/luacheck.py` は通り、**実機で初めてエラーダイアログが出た**。

  「呼ばないと分からない誤り」は、呼べば分かる。
  FCEUX 同梱の `lua5.1.dll` で Lua を動かし、FCEUX の API だけ差し替える。

★足りない材料があるときは skip する（失敗にしない）。
  ここで落とすと、materials の無い環境で**本題と関係ないテストが赤くなる**。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DLL = PROJECT_ROOT / "tools" / "fceux" / "lua5.1.dll"
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "state_write_test.lua"
LOG_SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "battlelog_test.lua"
SLOT_SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "enemyslot_test.lua"
WATCH_SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "ramwatch_test.lua"
RAMDUMP = PROJECT_ROOT / "work" / "ramdump" / "DQ2_J.fc0.bin"
GENERATED = PROJECT_ROOT / "work" / "generated" / "memory_map.lua"
OUTPUT = PROJECT_ROOT / "work" / "state_test.json"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and SCRIPT.exists()
         and RAMDUMP.exists() and GENERATED.exists()),
    reason=("Lua を動かす材料が無い（tools/fceux/lua5.1.dll・work/ramdump・"
            "work/generated）。python research/probes/active/check_spellrows.py --dump と "
            "python -m retroux.core.config.generate_lua で用意できる"),
)


@pytest.fixture(scope="module")
def written() -> dict:
    OUTPUT.unlink(missing_ok=True)
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
    )
    assert proc.returncode == 0, (
        "Lua の実行に失敗しました:\n" + (proc.stdout or "") + (proc.stderr or ""))
    assert OUTPUT.exists(), "state.json が書かれていない"
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_writes_valid_json(written):
    """★本題: 落ちずに、**JSON として読める**ものを書くこと。"""
    assert isinstance(written, dict)


def test_has_the_keys_the_gui_reads(written):
    """GUI が読むキーが揃っていること（片方だけ直すと黙って表示が消える）。"""
    for key in ("frame", "in_battle", "speed", "danger", "party",
                "enemy_groups", "actor", "ai_action", "ai_reason"):
        assert key in written, f"{key} が無い"


def test_map_fields_survive_the_move_gate(written):
    """★★★ マップの欄が**実際に書き出される**こと（2026-08-07）。

    ⚠⚠ 採取を「動いたときだけ」にしたので（軽量化指示書 §4.1）、
      ★門の作りを間違えると**欄がまるごと消えます**。

    ⚠ `test_live_map_wiring.py` は行の字面を見ていて、そこが動いた瞬間に
      落ちました。★そちらは字面をやめたので、**ここで実物を見ます**
      （`docs/design/handoff-20260807.md` §5 の作法8「渡す側と読む側の両方」）。

    ⚠ `map_tiles` / `map_cells` は `ppu` が要るのでこの走らせ方では出ません
      （★門とは無関係。以前からそうです）。ここでは `map_colors` を見ます。
    """
    for key in ("map_id", "map_x", "map_y", "map_view_radius", "map_colors"):
        assert key in written, f"⚠ {key} が消えました（★採取の門を疑う）"
    assert written["map_colors"], "⚠⚠ 色が空です（★門が閉じっぱなしです）"


def test_party_values_look_real(written):
    """実際のセーブステートの値が入っていること（0埋めになっていない）。"""
    party = written["party"]
    assert len(party) == 3
    for m in party:
        assert m["max_hp"] > 0
        assert 0 <= m["hp"] <= m["max_hp"]
        assert m["level"] > 0
    names = [m["name"] for m in party]
    assert names == ["lorasia", "samaltria", "moonbrooke"]


def test_reader_parses_what_lua_wrote(written):
    """★Lua が書いた形を、Python の読み手がそのまま解釈できること。

    書き手と読み手を別々にテストしていると、**形の食い違い**を見逃す。
    """
    from retroux.core.bridge.state_reader import StateReader

    state = StateReader(OUTPUT).read()

    assert state.fresh is True
    assert len(state.party) == 3
    assert state.speed == written["speed"]
    assert state.party[1].name == "samaltria"
    assert 0.0 < state.party[1].hp_ratio <= 1.0


def test_no_enemy_hp_field(written):
    """★**グループ**の記録にはHPを入れない。

    ⚠ 個体のHPは 2026-07-26 に確定していて、`enemies` のほうには出ます。
      ★ここで見ているのは**グループの記録に混ぜない**ことです
      （グループは「何が何体か」だけ。混ぜると分母が分からなくなる）。
    """
    for group in written["enemy_groups"]:
        assert "hp" not in group


def test_battle_log_tracking_runs(written):
    """★行動単位ログ（Phase 3）も**実際に呼んで**確かめる。

    HPを1点減らして、`party_hp` の観測が1件だけ出ることを見る。
    `self.a` の書き間違いのような「呼ばないと分からない誤り」を、
    実機まで持ち込まないため。
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(LOG_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "party_hp" in out
    assert "OK" in out


def test_enemy_slots_are_stable(written):
    """★回帰テスト: 先頭の敵が倒れても、残りの添字とHPが動かない。

    `enemy_ids()` は空きスロット(0xFF)で**打ち切る**ので、
    それで個体を追うと先頭が倒れた瞬間に後ろの敵まで見えなくなる。
    実際、行動単位ログに敵のHP変化が1件も残らなかった原因がこれだった。

    このテストは合わせて「ID 0 を敵として数えない」ことも見ている
    （まだ埋まっていない枠を『未知(0x00)』という敵にしていた）。
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(SLOT_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "OK: 先頭が倒れても" in out


def test_ram_watch(written):
    """★RAM Watch（Phase 5）も実際に呼んで確かめる。

    ・基準を取る回は 0 件
    ・増減の両方を数える／減少だけに絞れる
    ・上限で止まる（見張りがディスクを埋めない）
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(WATCH_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "OK" in out


# --- 移動方向の読み取り（2026-07-30 / 移動知識ログ）---------------------

INPUT_SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "input_direction_test.lua"


@pytest.mark.skipif(not INPUT_SCRIPT.exists(), reason="input_direction_test.lua が無い")
def test_input_direction_reads_the_bits():
    """★★ `$002F` から押されている方向を読む（実際の Lua で動かす）。

    FCEUX の Lua 5.1 には**ビット演算子が無い**ので
    `value % (mask * 2) >= mask` で見ている。Python で書き直して照合しても
    「Python の再実装は合っていた」にしかならない。
    **実機で走るのは Lua のほう。**

    ★確かめること: 4方向 / 他ボタンとの混在 / **同時押しは nil** / 何もなし
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(INPUT_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "NG" not in out, out
    assert "15 件すべて期待どおり" in out, out


# --- 遷移タイルの写真（2026-07-30 / マッパー仕様 フェーズ4）--------------

TILE_SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "tile_shot_test.lua"


@pytest.mark.skipif(not TILE_SCRIPT.exists(), reason="tile_shot_test.lua が無い")
def test_tile_shot_runs_and_refuses_when_it_should():
    """★★ 遷移タイルの写真も**実際の Lua で**動かす。

    ⚠ 座標は Lua が読む（Python の値は最大0.5秒古い）。
      写真と座標がずれた記録は、あとから直せない。

    ★確かめること:
      ファイル名に map_id と座標が入る / **戦闘中は撮らない** /
      位置が読めなければ撮らない / 書き出しは次フレーム /
      **書き出せなくても上限で諦めてログに出す**
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(TILE_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "NG" not in out, out
    assert "遷移タイルの写真は期待どおり" in out, out


# --- 戦術プロフィール（2026-07-30 / キャラクター別戦術AI）----------------

TACTICS_SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "tactics_test.lua"


@pytest.mark.skipif(not TACTICS_SCRIPT.exists(),
                    reason="tactics_test.lua が無い")
def test_tactics_lookup_falls_back_to_config():
    """★★ 戦術プロフィールの引き当てを**実際の Lua で**動かす。

    ⚠⚠ ここでいちばん静かに壊れるのは **%（0〜100）と割合（0.0〜1.0）の
      混同**。混ぜると 50 倍ずれるが、Lua は何も言わずに動く。

    ★確かめること:
      プロフィールが無ければ config の値（**これまでと同じ挙動**）／
      あればキャラクターごとの値／%→割合の変換／
      壊れた表・知らないキャラでも落ちない／
      **効かせるのは戦闘の始まり**（途中で戦術が入れ替わらない）
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(TACTICS_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "NG" not in out, out
    assert "戦術プロフィールの引き当ては期待どおり" in out, out
