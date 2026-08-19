"""モンスターの絵の撮影を Lua で**実際に呼ぶ**（2026-07-27）。

依頼者の確認:

> グラフィックの撮影は、実機って本物のFCでやるわけじゃないよね？
> エミュ画面から、キャプチャを自動的に取れない？

★**取れる。** ROM の絵の形式は未解読（逆アセンブルも `unknown format`）だが、
  このROMは **UNROM = CHR-RAM** なので絵は実行時に PPU へ展開される。
  画面に出ているものを撮れば、形式を解読しなくてよい。
  ※このプロジェクトで言う「実機」は **FCEUX + 実際のセーブデータ**のこと
    （本物のファミコンではない / README の「現在の状態」参照）。

★守っている契約（中身は research/probes/active/art_capture_test.lua）:
  1. まだ絵が無い敵が居れば撮る
  2. **複数種でも撮る**。ファイル名に**画面の並び**を入れる（`12-06-06.png`）
     — `$0162` は画面の並び順どおりなので、切り出し側が対応づけられる
     ⚠ 以前は「1種だけ」に限っていたが、**10戦闘で0枚**だった（2026-07-27）
  3. ⚠ **すでに絵がある敵は撮らない**（見るのは切り出し後）
  4. 演出が終わるまで待つ（出現途中の絵にしない）
  5. **ファイルの有無で確かめる**（「撮った」と「撮れた」は別 / playbook #2）
  6. 書き出せなければ**理由を出して諦める**（上限つき / playbook #9）
  7. 戦闘から抜けたら諦める（フィールドの絵を撮らない）
  8. ⚠ 撮る直前に並びが変わっていたら**名前を付け直す**
     — ずれたまま保存すると切り出し側が取り違える
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
SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "art_capture_test.lua"
GENERATED = PROJECT_ROOT / "work" / "generated" / "config.lua"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and SCRIPT.exists() and GENERATED.exists()),
    reason="Lua を動かす材料が無い（tools/fceux/lua5.1.dll・work/generated）",
)


@pytest.fixture(scope="module")
def result() -> subprocess.CompletedProcess:
    # ★Lua はフォルダを作れない。撮影先（raw）はここで用意する
    (PROJECT_ROOT / "work" / "art_test" / "raw").mkdir(parents=True, exist_ok=True)
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
    assert result.returncode == 0, "art_capture_test.lua が NG を報告しました:\n" + out
    assert "NG 0 件" in out, out


def test_reports_enough_checks(result):
    """検査が1件も走らずに「成功」になっていないこと。"""
    out = _out(result)
    m = re.search(r"OK (\d+) 件", out)
    assert m is not None, "件数が報告されていない:\n" + out
    assert int(m.group(1)) >= 20, f"検査が {m.group(1)} 件しか走っていない:\n{out}"


def test_covers_the_dangerous_cases(result):
    """★危ない場合が検査に入っていること。

    特に「複数種では撮らない」と「フィールドの絵を撮らない」。
    どちらも**違う敵の絵を図鑑に載せる**ことにつながる。
    """
    out = _out(result)
    for phrase in ("複数種でも撮る", "戦闘から抜けたら諦める",
                   "すでに絵がある敵は撮らない",
                   "名前を付け直す",
                   "ファイルの有無で確かめる"):
        assert phrase in out, f"「{phrase}」が検査されていない:\n{out}"


def test_config_has_monster_art_section():
    """設定が入っていること（切れるようになっているか）。"""
    import yaml

    cfg = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml")
        .read_text(encoding="utf-8"))
    art = cfg.get("monster_art")
    assert art is not None, "monster_art の設定が無い"
    assert art.get("enabled") is True
    assert art.get("dir"), "保存先が無い"
    # ★演出を待つ設定があること（すぐ撮ると出現途中の絵になる）
    assert int(art.get("settle_frames", 0)) > 0
