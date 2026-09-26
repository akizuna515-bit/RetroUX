"""「町の中」の判定は 1 つ（RX3-0311 / 2026-09-20）。

⚠⚠ 依頼者「ラダトームで聞き込みがきかない」「バラモスを倒したが、きかない」。

## ★何が起きていたか

```text
実機の state.json   loc_kind = 3 / map_id = 7（ラダトーム）
                    nav = {"reason": "not_local"}
                    town_speed.last_off = "HEARING_ERROR"
```

★`$2F`（kind）は **世界地図 0（上の世界）／ 2（アレフガルド）**、
⚠ **それ以外はすべて地図の中**です（町 1・アレフガルドの町 3・洞窟 5 …）。

⚠⚠ ところが `nav_v0.lua` だけが **`kind == 1` ちょうど**を見ていました。
★同じ判定は `map_art.lua`（RX3-0103）と `seen_map.py` で**既に直っていた**のに、
⚠ ここだけ取り残されていました（★2 か所に書いた判定の片方だけ直した型）。

→ ⚠ アレフガルドでは **街移動も聞き込みも自動移動も全部**断られていました。

## ★この検査が守ること

⚠ 「判定を書く場所」が増えても、★**世界地図の 2 つだけが例外**という形から外れないこと。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from dq3.knowledge import seen_map as SM

ROOT = pathlib.Path(__file__).resolve().parents[1]
LUA = ROOT / "dq3" / "phase0"

#: ★世界地図の kind（⚠ ここだけが「地図の中ではない」）
WORLD = (0, 2)
#: ★実際に出てくる地図の中の kind（★1 = 町 / 3 = アレフガルドの町 / 5 = 洞窟・塔）
LOCAL = (1, 3, 4, 5, 6, 7)


# --- ★Python 側 -----------------------------------------------------------

def test_世界地図の2つだけが地図の外():
    assert tuple(sorted(SM.WORLD_KINDS)) == WORLD, SM.WORLD_KINDS
    for kind in WORLD:
        assert SM.is_local(kind) is False, kind
    for kind in LOCAL:
        assert SM.is_local(kind) is True, kind


def test_アレフガルドの町は地図の中():
    """★★ これが直したかったこと（⚠ ラダトーム = kind 3）。"""
    assert SM.is_local(3) is True


def test_kindが無ければ地図の中とみなさない():
    assert SM.is_local(None) is False


# --- ★Lua 側（⚠ 実機で走るのはこちら）--------------------------------------

#: ★「町の中か」を判断する Lua（⚠ 増えたらここに足す）
DECIDERS = ("nav_v0.lua", "map_art.lua", "dev.lua")


def _source(name: str) -> str:
    path = LUA / name
    if not path.exists():
        pytest.skip("⚠ %s がありません" % name)
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", DECIDERS)
def test_Luaも世界地図の2つを例外にしている(name):
    """⚠⚠ `kind == 1` ちょうどで判断していないこと（★それが今回の不具合）。"""
    src = _source(name)
    body = [ln for ln in src.splitlines()
            if not ln.lstrip().startswith("--")]          # ⚠ 註は数えない
    text = chr(10).join(body)
    # ★「地図の中か」を決める関数が居ること
    assert re.search(r"function\s+is_local", text), (
        "⚠ %s に「地図の中か」を決める 1 か所がありません" % name)
    # ⚠⚠ `kind == 1` / `kind ~= 1` で町かどうかを決めていない
    bad = re.findall(r"kind\s*[=~]=\s*1\b", text)
    assert not bad, "⚠⚠ %s が kind == 1 ちょうどで町を決めている: %s" % (name, bad)


@pytest.mark.parametrize("name", DECIDERS)
def test_Luaが例外にしている番号はPythonと同じ(name):
    """★両端をつなぐ（⚠ 片方だけ直すと、また実機だけで壊れる）。"""
    src = _source(name)
    got = set()
    for line in src.splitlines():
        if line.lstrip().startswith("--"):
            continue
        m = re.match(r"\s*local\s+(KIND_WORLD|KIND_ALEFGARD)\s*=\s*(\d+)", line)
        if m:
            got.add(int(m.group(2)))
        # ★`dev.lua` のように literal で書いてある形も拾う
        m = re.search(r"kind\s*~=\s*(\d+)\s+and\s+kind\s*~=\s*(\d+)", line)
        if m:
            got.update({int(m.group(1)), int(m.group(2))})
    assert got == set(WORLD), (
        "⚠⚠ %s が例外にしている kind %s は Python の %s と違う" % (name, sorted(got), list(WORLD)))
