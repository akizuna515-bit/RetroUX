"""DQ2 の Lua は根を自分の置き場から決める（RX-0160）。

⚠ 以前は `RETROUX_ROOT` が無いと開発機の絶対パス（F: の Projects）を見ていた（★配布物では存在しない場所）。
★`RETROUX_ROOT` が無ければ、`retroux/emulator/fceux/<この Lua>` の 3 つ上を根にする（`debug.getinfo` の source）。
★実 Lua（FCEUX 同梱の lua5.1.dll）で、**別の場所へ写した** bridge.lua が写した先の根を返すことを見る。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"
LUA = ROOT / "retroux" / "emulator" / "fceux"


@pytest.mark.parametrize("name", ["run.lua", "bridge.lua"])
def test_開発機の絶対パスを既定にしない(name) -> None:
    body = (LUA / name).read_bytes().decode("utf-8")
    assert "Projects/260721_RetroUX" not in body and "Projects\\260721_RetroUX" not in body
    assert "local function script_root()" in body and 'debug.getinfo(1, "S")' in body
    assert "root = script_root()" in body


@pytest.mark.skipif(not DLL.exists(), reason="Lua を動かせない環境（tools/fceux/lua5.1.dll が無い）")
def test_写した先のbridgeは写した先を根にする() -> None:
    import tempfile

    # ⚠ lua5.1 の loadfile は ANSI。pytest の tmp_path は検査名（日本語）を含むので使わない
    with tempfile.TemporaryDirectory(prefix="dq2-lua-root-") as tmp:
        _check_copied_bridge(Path(tmp))


def _check_copied_bridge(tmp_path: Path) -> None:
    home = tmp_path / "Portable DQ2"          # ★空白入り
    dst = home / "retroux" / "emulator" / "fceux"
    dst.mkdir(parents=True)
    shutil.copy2(LUA / "bridge.lua", dst / "bridge.lua")
    out = tmp_path / "got.txt"
    probe = tmp_path / "probe.lua"
    probe.write_text(
        'local Bridge = assert(loadfile([[%s]]))()\n'
        'local fh = assert(io.open([[%s]], "w"))\n'
        'fh:write(tostring(os.getenv("RETROUX_ROOT")) .. "|" .. Bridge.resolve_root())\n'
        'fh:close()\n' % (dst / "bridge.lua", out), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "RETROUX_ROOT"}
    done = subprocess.run([sys.executable, str(RUNNER), str(probe)], cwd=str(tmp_path), env=env,
                          capture_output=True, timeout=120)
    assert done.returncode == 0, (done.stdout + done.stderr).decode("utf-8", "replace")
    got = out.read_text(encoding="utf-8")
    assert got == "nil|" + home.as_posix(), got
