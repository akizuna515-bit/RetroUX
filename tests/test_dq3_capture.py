"""画面を撮る（RX3-0031 / 2026-08-31）。

## ⚠⚠ まだ実機で 1 度も呼んでいない

  `gui.savescreenshotas` は同梱の `fceux64.exe` に**ある**ことを
  ★実行ファイルのバイト列で確認しただけです（`docs/research/260831_dq3-poc1.md` F 章）。

  ⚠ だから「呼べなかったときに**黙らない**か」を、ここで見ます。
  ★黙って何も残らないのが、いちばん困る壊れ方です。
"""

from __future__ import annotations

import io
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_capture_test.lua"
TARGET = ROOT / "dq3" / "phase0" / "capture.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"
FCEUX = ROOT / "tools" / "fceux" / "fceux64.exe"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and TARGET.exists()),
    reason="Lua を動かせない環境")


@pytest.fixture(scope="module")
def result() -> str:
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, result


def test_OKが減っていない(result):
    n = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert n >= 8, f"⚠ OK が {n} 件しかありません\n{result}"


def test_撮れないときに黙らないことを動かして確かめている(result):
    for line in ("OK API が無ければ、記録に残して失敗を返す",
                 "OK 同じ理由では 1 度しか鳴かない（★記録を埋めない）",
                 "OK 撮れなかった枚は持たない（★後で「無いファイル」を指さない）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_リングバッファが効いていることを動かして確かめている(result):
    for line in ("OK 決めた間隔でだけ撮る（★60 フレームで 10 枚）",
                 "OK 直近の枚数だけを持つ（★異常時にそのぶんを残す）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


@pytest.mark.skipif(not FCEUX.exists(), reason="⚠ 同梱の FCEUX が無い")
def test_同梱のFCEUXにその関数がある():
    """★呼ぶ前に、**実行ファイルに名前があるか**だけは確かめられる。

    ⚠⚠ これは「呼べる」証明ではありません（★実機で 1 度も呼んでいない）。
    ★無いことだけは、ここで先に分かります。
    """
    blob = FCEUX.read_bytes()
    assert b"savescreenshotas" in blob, (
        "⚠⚠ 同梱の FCEUX に `savescreenshotas` がありません（★方式を変える）")


def test_動画をここで作っていない():
    """⚠⚠ この環境には **ffmpeg も Pillow もありません**（★2026-08-31 実測）。

    ★PNG を並べても動画にできないので、⚠ ここは静止画だけにします。
    """
    src = io.open(TARGET, encoding="utf-8", newline="").read()
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("--"))
    for gone in ("ffmpeg", "PIL", "mp4", "gif"):
        assert gone not in body, "⚠ 動画を作ろうとしています（%s）" % gone
