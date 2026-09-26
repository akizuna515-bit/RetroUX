"""点滅しているカーソルの見分け（RX3-0015 / 2026-08-27）。

★★ なぜこの検査が要るか ★★

画面に ▶（タイル `0x72`）は**複数出る**。⚠ 静止画 1 枚では、
どれが本物のカーソルか分からない。

    ★点滅している ▶ … 本物
    ⚠ 静止した ▶  … 飾り

⚠⚠ ここを 1 枚から決めて **2 回とも外した**（「一覧に出る」「出ない」の両方）。
★これが呪文の段で止まった失敗の**根っこ**だった。

依頼者の指摘（2026-08-27）:

    「窓が開いている場合、カーソルが点滅しているのだけど、
     そのカーソルが点滅している、というのを捕まえられない？
     その点滅の右がコマンドの内容なんだけど」

    「点滅については CPU が PPU に指令を送っているはずだから、
     動きで捉えられると思うんだよな」

★後者のとおり、`$2006` / `$2007` への書き込みを見張ると**その場で決まる**。
⚠ 画面を眺める方法は点滅の周期が 8 フレームなので十数フレームかかる。

★裏取りは実測（`work/dq3-probe/ppu_trace.txt`）:

    $2289 = 画面(9,20)   72 を 24 回 / 00 を 19 回   → ★点滅
    $22C5 = 画面(5,22)   72 を  1 回 / 00 を  0 回   → ⚠ 点いたまま
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_cursor_test.lua"
MODULE = ROOT / "dq3" / "phase0" / "cursor.lua"
MANTAN = ROOT / "dq3" / "phase0" / "mantan_v0.lua"
AUTO = ROOT / "dq3" / "phase0" / "auto_v0.lua"
DEV = ROOT / "dq3" / "phase0" / "dev.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and MODULE.exists()),
    reason="Lua を動かす材料が無い")


@pytest.fixture(scope="module")
def run() -> str:
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both


# --- ★ハーネスが最後まで走ること -------------------------------------

def test_最後まで走って合格する(run):
    assert "すべて合格" in run, f"⚠ 失敗があります\n{run}"


def test_OKが減っていない(run):
    """⚠ 途中で静かに減っていないか（★字面だけの合格を防ぐ）。"""
    count = sum(1 for line in run.splitlines() if re.match(r"^OK\b", line))
    assert count >= 19, f"⚠ OK が {count} 件しかありません\n{run}"


def test_書き込みからの経路も見ている(run):
    """★★ 依頼者の指摘した本命の経路が、実際に走っていること。

    ⚠ 画面を眺める経路だけ緑でも、実機で使うのは書き込みのほう。
    """
    assert "書き込みだけで点滅を見分けられる" in run, run
    assert "1 回きりの書き込みは点滅としない" in run, run
    assert "実測の番地が実測の升に直る" in run, run


# --- ⚠ 中身の方針が崩れていないこと ----------------------------------

def test_静止した印を本物としない():
    """⚠⚠ 「▶ があれば本物」に戻したら赤くする。"""
    src = MODULE.read_text(encoding="utf-8")
    assert "BLINKS_NEEDED" in src, "⚠ 点滅の回数を見ていない"
    assert "vram_blinks" in src, "⚠ 書き込みからの経路が消えている"


def test_属性の番地を文字として拾わない():
    """⚠ `+0x3C0` 以降はパレットの組。★文字ではない。"""
    src = MODULE.read_text(encoding="utf-8")
    assert "0x3C0" in src, "⚠⚠ 属性を弾いていない"


def test_まんたんが点滅で判断している():
    """★製品側に繋がっていること（⚠ 道具だけ作って繋ぎ忘れる）。"""
    src = MANTAN.read_text(encoding="utf-8")
    assert "install_writes" in src, "⚠⚠ 書き込みの見張りを繋いでいない"
    assert "set_scroll" in src, "⚠ スクロールを渡していない（★升がずれる）"
    assert "track.active()" in src, "⚠ 点滅しているカーソルを使っていない"


def test_戦闘側も点滅で判断している():
    """★★ RX3-0020（2026-08-30）: ⚠ ここが**まんたん側だけ**だった。

    ★戦闘側は「上から最初の ▶」を採る古いままで、⚠ 静止した ▶
    （つよさ の窓など）に釣られる形が残っていた。
    """
    src = AUTO.read_text(encoding="utf-8")
    assert "track.active()" in src, (
        "⚠⚠ 点滅しているカーソルを使っていない（★座標に戻っています）")
    assert "set_scroll" in src, "⚠ スクロールを渡していない（★升がずれる）"
    # ★註釈には「なぜ捨てたか」と一緒に昔の名前が引用してある。
    #   ⚠ 素で探すとそこに当たる（★検出器の誤検知）。本文だけを見る。
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("--"))
    for gone in ("cursor_row", "add_cursors", "new_cursor",
                 "has_entry_above"):
        assert gone not in body, (
            "⚠⚠ 座標で探す道具（%s）が戻っています" % gone)


def test_見張りは1つだけ():
    """⚠⚠ `memory.registerwrite` は**番地ごとに 1 つ**しか覚えない。

    ★2 つ作って両方が `install_writes()` すると、あとに読まれたほうが
    前を**黙って潰す**。潰されたほうは書き込みを 1 つも受け取れない。
    ⚠ `HOST.screen` で同じことを 2026-08-29 に実機で踏んでいる。
    """
    dev = DEV.read_text(encoding="utf-8")
    assert "cursor = cursor_track" in dev, (
        "⚠⚠ `dev.lua` が見張りを配っていない（★機能ごとに作られます）")
    for name, src in (("auto_v0", AUTO.read_text(encoding="utf-8")),
                      ("mantan_v0", MANTAN.read_text(encoding="utf-8"))):
        assert "HOST.cursor" in src, (
            "⚠⚠ %s が自前の見張りを作っています（★片方が黙ります）" % name)


def test_点滅が無いときの歯止めがある():
    """⚠⚠ 「押さない」だけでは足りない。★待ち続けるほうも止める。

    ⚠ 待ち時間の勘定を `waited` と共用したら、`need_window` が毎フレーム
    0 に戻して**永遠に待ち続けた**（2026-08-27 に実際に踏んだ）。
    """
    src = MANTAN.read_text(encoding="utf-8")
    assert "cursor_not_blinking" in src, "⚠ 点滅が無いまま待ち続ける道が残っている"
    assert "no_blink" in src, "⚠⚠ 勘定を共用している（★0 に戻され続けます）"
