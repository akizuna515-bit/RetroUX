"""窓の見つけ方は Lua と Python で同じ答えになる（RX3-0019 / 2026-08-29）。

★★ なぜこの検査が要るか ★★

窓の見つけ方は **2 か所**にある。

    dq3/phase0/mantan_v0.lua  ← ★実機で走るのはこちら
    dq3rom/window.py          ← 解析で使うのはこちら

⚠⚠ **実際に食い違った**（2026-08-29）。

    Python: 「右上角を探す（⚠ 上辺に文字が入る窓もあるので、中身は問わない）」
    Lua   : 「角の右は必ず横線（⚠ 上辺に文字が入る窓でも、角の隣は横線）」

★実機のセーブ 0 を描いて数えたら、**Lua の前提が誤り**だった:

    y=20 x=6:  79 0B 10 32 00 78 ...  77 7C
                ↑角  ↑⚠ 横線ではなく**文字**（「あかり」）

⚠ そのため「窓は無い」と誤認し、★フィールドで A を叩いて暴れた
（依頼者 2026-08-29「満タンは暴れてしまうね」）。

★答えの元は**実機のセーブステート**。
⚠ 再実装どうしを比べても「同じ勘違いを 2 回書いた」かもしれない。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

from dq3rom import ppu, window

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_window_test.lua"
MANTAN = ROOT / "dq3" / "phase0" / "mantan_v0.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()


def _sandbox() -> pathlib.Path:
    """★走行ごとの隔離先（`conftest.py` が決める）。"""
    got = os.environ.get("RETROUX_TEST_SANDBOX")
    return pathlib.Path(got) if got else (
        ROOT / "work" / "tests" / "lua-sandbox")

# ⚠ 隔離先は**走行ごとに変わる**（RX-0114 / 2026-08-30）。
#   ★`conftest.py` が `RETROUX_TEST_SANDBOX` を立てる。
#   ⚠ 直書きすると、並列で走ったとき隣の走行の書いたものを読む。
SANDBOX = _sandbox() / "work"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists()
         and MANTAN.exists()),
    reason="Lua を動かす材料が無い")

#: ★材料に使うセーブステート。⚠ **場面の違うものを混ぜる**。
#:   `fc0` は依頼者が「まんたんが暴れた」ところで保存したもの（2026-08-29）。
CASES = ["DQ3_J.fc0", "DQ3_J.fc9", "DQ3_J.fc7", "DQ3_J.fc6"]


def _corners(screen) -> list[str]:
    """★Python 側の答え（⚠ `dq3rom/window.py` と同じ規則）。"""
    out = []
    for w in window.find_windows(screen):
        out.append("%d,%d" % (w.x, w.y))
    return sorted(out, key=lambda s: (int(s.split(",")[1]),
                                      int(s.split(",")[0])))


def _write_cases() -> list[str]:
    from retroux.core.bgmap import savestate as ss

    (SANDBOX / "runtime" / "dq3-probe").mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    blocks: list[str] = []
    for name in CASES:
        path = FCS / name
        if not path.exists():
            continue
        screen = ppu.screen_of(ss.load(path).chunks)
        blocks.append("%s\n%s\n%s\n" % (
            name, bytes(screen).hex(), " ".join(_corners(screen))))
        used.append(name)
    (SANDBOX / "runtime" / "dq3-probe" / "window_case.txt").write_text(
        "".join(blocks), encoding="utf-8")
    return used


@pytest.fixture(scope="module")
def run() -> str:
    used = _write_cases()
    if not used:
        pytest.skip("セーブステートが 1 つも無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both


def test_最後まで走って合格する(run):
    assert "すべて合格" in run, f"⚠ 失敗があります\n{run}"


def test_実機のセーブで突き合わせている(run):
    n = sum(1 for ln in run.splitlines() if re.match(r"^OK DQ3_J", ln))
    assert n >= 2, f"⚠ 突き合わせたセーブが {n} 件しかありません\n{run}"


def test_上辺に文字が入る窓を見落とさない(run):
    """⚠⚠ **これが実機で暴れた原因**（2026-08-29）。"""
    assert "上辺に文字が入っていても、窓として見つける" in run, run


def test_地形を窓と誤認しない(run):
    """⚠ `0x79` は地形にもある値（★1 マスでは弱い）。"""
    assert "右上の角が無ければ窓としない" in run, run


# --- ⚠ 2 か所の規則が揃っていること ------------------------------------

def test_LuaとPythonで同じ幅の下限を使う():
    """⚠⚠ 違えると、★片方だけが窓と認める食い違いが戻る。"""
    lua = MANTAN.read_text(encoding="utf-8")
    got = re.search(r"^local MIN_WIDTH = (\d+)", lua, re.M)
    assert got, "⚠ Lua 側に MIN_WIDTH が無い"
    assert int(got.group(1)) == window.MIN_WIDTH, (
        "⚠⚠ Lua=%s / Python=%s（★揃えること）"
        % (got.group(1), window.MIN_WIDTH))


def test_Luaが横線の決め打ちに戻っていない():
    """⚠⚠ 「角の右は必ず横線」に戻したら赤くする（★実測で崩れた前提）。"""
    lua = MANTAN.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in lua.splitlines()
                     if not ln.lstrip().startswith("--"))
    assert "== EDGE_TOP" not in body, (
        "⚠⚠ 角の右に横線を求めている（★上辺に文字が入る窓を見落とします）")
    assert "top_right_of" in body, "⚠ 右上の角を探していない"


def test_Luaが四隅をそろえて見ている():
    """⚠⚠ 上辺だけだと、★地形の 0x79 と遠くの 0x7C で**実在しない窓**を作る。

    ⚠ 2026-08-29 に実機で `(0,14)` を作り、閉じようとして 10 回 A を叩いた
    （依頼者「満タンは暴れてしまうね」の 2 度目）。
    ★`dq3rom/window.py` は下辺（左下・右下の角）まで見ている。
    """
    lua = MANTAN.read_text(encoding="utf-8")
    body = chr(10).join(ln for ln in lua.splitlines()
                        if not ln.lstrip().startswith("--"))
    assert "has_window" in body, "⚠ 四隅を見ていない"
    for name in ("BOTTOM_LEFT", "BOTTOM_RIGHT", "EDGE_LEFT", "MIN_HEIGHT"):
        assert name in body, (
            "⚠⚠ %s を見ていない（★下辺の確認が抜けています）" % name)


def _status_rule(path: pathlib.Path) -> str:
    """★`is_status_window` の**中身だけ**（⚠ 註釈と空白は落とす）。"""
    text = path.read_text(encoding="utf-8")
    start = text.index("local function is_status_window")
    end = text.index(chr(10) + "end", start) + len(chr(10) + "end")
    body = text[start:end].splitlines()
    return " ".join(ln.strip() for ln in body
                    if ln.strip() and not ln.strip().startswith("--"))


def test_製品と足場が同じ規則を持つ():
    """⚠⚠ **同じ規則が 2 か所にある**（★片方だけ直すと、足場は緑のまま実機が壊れる）。

    ★2026-09-18 に実際にそうなりかけた（依頼者「save6 一人だと、まんたんがつかえない」）。
    """
    harness = ROOT / "research" / "probes" / "active" / "dq3_window_test.lua"
    assert _status_rule(MANTAN) == _status_rule(harness), (
        "⚠⚠ まんたんと足場で見分けが違う" + chr(10)
        + "  まんたん: " + _status_rule(MANTAN) + chr(10)
        + "  足場    : " + _status_rule(harness))


def test_一人でもステータス表示を外す(run):
    """⚠⚠ 依頼者 2026-09-18「save6 一人だと、まんたんがつかえない。窓の認識が違うんだと思う」。

    ★実測（`work/runtime/dq3-probe/mantan_v0.log`）: 一人だと札が **1 つずつ**しか並ばず、
    ⚠ 旧い規則（1 行に 3 つ以上）では当たらない → ステータス表示を閉じようとして
    `window_will_not_close` で止まっていた。
    """
    assert "一人でもステータス表示を数から外している" in run, run
    assert "札が 1 種類だけなら、ふつうの窓として数える" in run, run


def test_ステータス表示は数に入れない(run):
    """依頼者 2026-08-29:

        パーティーのステータス表示は、何もしない時間があると勝手に表示されて
        A ボタンを押すと消える表示。無視して OK

    ⚠⚠ **B では消えない**（★実機で 10 回押しても窓が変わらなかった）。
    ★これを「閉じるべき窓」と数えたので、まんたんが先へ進めなかった。
    """
    # ⚠⚠ **セーブに頼らない**（2026-08-29 に踏んだ）。
    #   ★セーブは依頼者の進行で変わる。`fc0` を上書きされて「窓なし」になり、
    #   全体走行でだけ赤くなった（★単体では通っていた）。
    #   → 足場が**自分で作った画面**で確かめる。
    assert "ふつうの窓は数える" in run, run
    assert "ステータス表示を数から外している" in run, run


def test_見分けは中身で行う():
    """⚠ 位置で決め打ちしない（★戦闘中は (4,2)、フィールドは (6,20)）。"""
    lua = MANTAN.read_text(encoding="utf-8")
    body = chr(10).join(ln for ln in lua.splitlines()
                        if not ln.lstrip().startswith("--"))
    assert "is_status_window" in body, "⚠ 見分けが無い"
    assert "LEVEL_TILE" in body and "HP_TILE" in body, (
        "⚠⚠ 中身（札の並び）で見分けていない")
    # ⚠⚠ 2026-09-18: 「1 行に 3 つ以上」に戻すと**一人のとき**に当たらない
    #   （依頼者「save6 一人だと、まんたんがつかえない」）。★2 種類が同じ数だけ並ぶ、で見る。
    assert "hp == level" in body, (
        "⚠⚠ 人数に依らない見分け（★2 種類の札が同じ数）になっていない")
    assert "LEVEL_RUN" not in body, (
        "⚠⚠ 人数を前提にした古い規則（3 つ以上）が残っている")
    # ⚠⚠ **作っただけで呼び忘れる**を防ぐ（★この計画で何度も踏んだ形）。
    #   実際、外しても足場は緑のままだった（足場が自前の規則を持つため）。
    assert "not is_status_window(nt, x, y)" in body, (
        "⚠⚠ 見分けを作っただけで、窓を数えるところで**使っていない**")


def test_下辺がそろわなければ窓としない(run):
    """⚠⚠ これが 2 度目の暴れの直接の原因。"""
    assert "下辺がそろわなければ窓としない" in run, run
