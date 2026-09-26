"""開発用の 1 本と、その共有部分（RX3-0018 / 2026-08-29）。

★★ なぜこれが要るか ★★

依頼者「別々に確認すると手間なので、開発中の機能として、
        両方含めた lua で進めたい」（2026-08-29）

⚠⚠ 手間の話だけではありません。**`joypad.set` は後勝ち**で、
同じフレームに 2 つが書くと片方が**無かったことになります**。

★実機では「12,000 フレームで HP 変化 0 回」という形でしか出ませんでした。
⚠ エラーは 1 つも出ません。だから足場で捕まえます。

## ⚠ 足場が実際に捕まえたもの（2026-08-29）

    ターボの `T` を 2 つの機能が別々に見ていて、
    ★1 回押すと 2 回反転して**元に戻っていた**。

→ ★共有するスイッチは、**見る場所も 1 つ**にしました。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
ACTIVE = ROOT / "research" / "probes" / "active"
PHASE0 = ROOT / "dq3" / "phase0"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

CORE = PHASE0 / "core.lua"
DEV = PHASE0 / "dev.lua"
AUTO = PHASE0 / "auto_v0.lua"
MANTAN = PHASE0 / "mantan_v0.lua"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and CORE.exists() and DEV.exists()),
    reason="Lua を動かす材料が無い")


def _run(harness: pathlib.Path) -> str:
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(harness)],
        cwd=str(ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both


@pytest.fixture(scope="module", autouse=True)
def _材料を自分で用意する():
    """⚠⚠ **他の検査が先に走っていることに頼っていました。**

    ★詳しくは `conftest.prepare_dq3_probe`。
    """
    from conftest import prepare_dq3_probe

    prepare_dq3_probe()


@pytest.fixture(scope="module")
def core_run() -> str:
    return _run(ACTIVE / "dq3_core_test.lua")


@pytest.fixture(scope="module")
def dev_run() -> str:
    return _run(ACTIVE / "dq3_dev_test.lua")


# --- ★足場が最後まで走ること -------------------------------------------

def test_共有部分の足場が合格する(core_run):
    assert "すべて合格" in core_run, core_run


def test_共有部分のOKが減っていない(core_run):
    n = sum(1 for ln in core_run.splitlines() if re.match(r"^OK\b", ln))
    assert n >= 34, f"⚠ OK が {n} 件しかありません\n{core_run}"


def test_1本の足場が合格する(dev_run):
    assert "すべて合格" in dev_run, dev_run


def test_1本のOKが減っていない(dev_run):
    n = sum(1 for ln in dev_run.splitlines() if re.match(r"^OK\b", ln))
    assert n >= 48, f"⚠ OK が {n} 件しかありません\n{dev_run}"


# --- ⚠⚠ ここが本丸: 同じフレームに 2 つが押さない ---------------------

def test_同じフレームに2つが押さないことを動かして確かめている(dev_run):
    """⚠⚠ **これが RX3-0018 の存在理由**。

    ★字面ではなく、120 フレーム通しで動かして確かめていること。
    """
    assert "1 フレームに押すのは 1 回まで" in dev_run, dev_run
    assert "握っているのは、いつでも 1 つだけ" in dev_run, dev_run


def test_毎フレームの登録が1つだけであることを確かめている(dev_run):
    """⚠⚠ `registerafter` を 2 つ呼ぶと、FCEUX は**後のものしか覚えない**。

    ★片方が黙って動かなくなる（エラーは出ない）。
    """
    assert "毎フレームの登録は 1 つだけ" in dev_run, dev_run


def test_持ち主でなければ押せないことを確かめている(core_run):
    assert "持ち主でなければ押せない" in core_run, core_run
    assert "拒んだことが記録に残る" in core_run, core_run


def test_1本から6つの機能が乗る(dev_run):
    """★auto / mantan / walk_v0 / nav_v0 / restock_v0 / item_use_v0。

    ⚠ 2026-08-31 に歩き、2026-09-02 に街ナビ、2026-09-08 に補充、
      ★2026-09-11 に道具を使う（RX3-0159）を足した。
    """
    assert "1 本から 6 つの機能が乗る" in dev_run, dev_run


def test_歩きは居場所を自分で読まない(dev_run):
    """⚠⚠ 同じ判定を 2 か所に書くと、★片方だけ直る（この計画で踏んだ形）。"""
    assert "歩きは居場所を自分で読まない" in dev_run, dev_run


def test_Wで歩きが始まり止まる(dev_run):
    """⚠⚠ 最初はここが空いていて、★`W` を見る行を消しても全部緑でした。"""
    assert "W で歩きが始まり、出発の場所が残る" in dev_run, dev_run
    assert "もう一度 W で止まる" in dev_run, dev_run


def test_歩きは本当に方向キーを押す(dev_run):
    """★★ ⚠⚠ 2026-08-31 実機: **1 歩も動きませんでした**。 ★★

    ★歩きが `BUTTONS.claim` を呼んでおらず、`press` が毎回断られていました。
    ⚠ 記録には「歩いた」と出るのに、`dev.log` には
      「持ち主は nil」が 16 回。★動いて見えた 2 歩は依頼者の入力でした。

    ⚠⚠ ここは「記録が伸びたか」しか見ておらず、**素通りしていました**。
    """
    assert "歩きは本当に方向キーを押す" in dev_run, dev_run
    assert "歩きは $16 を見て、1 歩ぶん長く押す" in dev_run, dev_run
    assert "止めたらボタンを離す" in dev_run, dev_run
    assert "ほかの機能が握っていたら歩かない" in dev_run, dev_run


def test_いまの場所が画面と記録に出る(dev_run):
    """★`RX3-0013` の実機確認に要る（⚠ 依頼者「座標はどこにも出ない」）。"""
    assert "いまの地図と升が画面に出る" in dev_run, dev_run
    assert "地図が変わったときだけ記録に残る" in dev_run, dev_run


# --- ⚠ ターボのスイッチが 1 つであること -------------------------------

def test_ターボが1回のタップで1回だけ反転する(dev_run):
    """⚠⚠ ここは**足場が実際に捕まえた不具合**です（2026-08-29）。

    ★`T` を 2 つの機能が別々に見ていて、1 回押すと 2 回反転して元に戻った。
    """
    # ★RX3-0169: T は「Auto 中の Turbo の頼み」になった。★1 回のタップで頼みは 1 回だけ
    assert "1 回のタップで Turbo の頼みは 1 回だけ" in dev_run, dev_run


def test_ターボを見る場所が1つだけ():
    """⚠ 機能側が `T` を見直したら赤くする（★2 回反転が戻る）。"""
    for path in (AUTO, MANTAN):
        src = path.read_text(encoding="utf-8")
        assert "HOST == nil and edge(KEY_TURBO)" in src, (
            f"⚠⚠ {path.name} が単独でないときも T を見ている")


# --- ⚠ 作りが崩れていないこと ------------------------------------------

def test_joypadを押すのは共有部分だけ():
    """⚠⚠ 各機能が直接 `joypad.set` を呼び戻したら赤くする。

    ★後勝ちで片方が消える事故は、ここでしか防げない。
    """
    for path in (AUTO, MANTAN, DEV):
        src = path.read_text(encoding="utf-8")
        body = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("--"))
        assert "joypad.set" not in body, (
            f"⚠⚠ {path.name} が直接 joypad.set を呼んでいる")
    assert "joypad.set" in CORE.read_text(encoding="utf-8"), (
        "⚠ 共有部分が押していない")


def test_機能は1本から動かすときに自分で登録しない():
    """⚠⚠ 両方が `registerafter` すると、片方が黙って動かなくなる。"""
    for path in (AUTO, MANTAN):
        src = path.read_text(encoding="utf-8")
        assert "if HOST ~= nil then" in src, f"⚠ {path.name} が host を見ていない"
        assert "emu.registerafter(frame)" in src, (
            f"⚠ {path.name} が単独で動かなくなっている")


def test_画面の見張りは1つだけ(dev_run):
    """⚠⚠ `memory.registerwrite` は**番地ごとに 1 つ**しか覚えない。

    ★`Screen` を 2 つ作ると、あとの `install()` が前のを**黙って潰す**。
    ⚠ 潰されたほうは `scroll_x = 0` のままで、**生のネームテーブルの座標**を返す。

    実機で踏んだ（2026-08-29）:

        まんたん  窓は (8,20)   ← ⚠ 生の座標
        Python    窓は (6,20)   ← ★スクロール 16px = 2 マスを反映

    ⚠ そのため「閉じる」を 10 回押しても、狙いが違って閉じなかった。
    """
    assert "画面の見張りは番地ごとに 1 回だけ" in dev_run, dev_run
    assert "画面の読み手を共有している" in dev_run, dev_run


def test_機能は画面の読み手を共有する():
    """★`registerafter` と同じ。⚠ **持ち主は 1 つ**。"""
    src = MANTAN.read_text(encoding="utf-8")
    assert "(HOST and HOST.screen) or Screen.new()" in src, (
        "⚠⚠ まんたんが自分で画面の読み手を作っている（★見張りを潰し合います）")
    dev = DEV.read_text(encoding="utf-8")
    assert "screen = screen_reader" in dev, "⚠ 共有していない"


def test_単独でも動く足場が残っている():
    """★実機で通った版を消さない（`RX3-0018` の Non-Goals）。"""
    for name in ("dq3_auto_v0_test.lua", "dq3_mantan_v0_test.lua"):
        assert (ACTIVE / name).exists(), f"⚠ {name} が消えている"


def test_表示の差し込み口がある(dev_run):
    """★勇者のメモ / マップ / 仮 UI を足す場所（⚠ 中身は別 WI）。"""
    assert "表示を足すと、毎フレーム呼ばれる" in dev_run, dev_run
    assert "表示が落ちても本体は止まらない" in dev_run, dev_run


def test_dq3のluaが構文検査の対象に入っている():
    """⚠⚠ **入っていなかった**（2026-08-29 に発見）。

    ★実機で人が使う Lua そのものなのに、一度も構文を見ていなかった。
    ⚠ `goto` を 1 つ書けば FCEUX がダイアログを出したまま止まる。
    """
    src = (ROOT / "research" / "probes" / "reusable"
           / "luacheck.py").read_text(encoding="utf-8")
    assert '"dq3" / "phase0"' in src, "⚠⚠ dq3/phase0 が構文検査から外れている"


def test_1本が起動の一覧に載っている():
    src = (ROOT / "scripts" / "run_probe.py").read_text(encoding="utf-8")
    assert '"dev": ROOT / "dq3" / "phase0" / "dev.lua"' in src, (
        "⚠ `run_probe.py dev` で起動できない")


# --- ⚠⚠ 記録の不調で本体を止めない（RX3-0016 の前段 / 2026-08-30）---------

def test_記録用folderが無くても両方の機能が乗る(tmp_path):
    """★★ ⚠⚠ **記録は本体の付属品**。付属品が無いから本体を止めない ★★

    ## ⚠⚠ 実際に止まっていました

      `mantan_v0.lua` は `assert(io.open(...))` でした。
      ★`work/dq3-probe/` が無いと **まんたんが読み込みに失敗**し、
      ⚠ `dev.lua` の `pcall` に飲まれて「機能が 1 件（2 のはず）」に
      なっていました。⚠⚠ **理由はどこにも出ませんでした**
      （★理由を書く先が、その開けなかった記録だったため）。

    ## ★依頼者の決めごと（2026-08-30）

      ```text
      1  必要な folder は作る
      2  記録が出せないときは console に伝える
      3  ⚠⚠ 記録の不調だけを理由に、本体機能を止めない
      ```

    ⚠ この検査は **folder を作らずに**走らせます。
    """
    import os
    import shutil

    sandbox = pathlib.Path(tempfile.mkdtemp(prefix="retroux-nolog-"))
    try:
        (sandbox / "work").mkdir(parents=True)
        assert not (sandbox / "work" / "dq3-probe").exists()
        env = dict(os.environ)
        env["RETROUX_TEST_SANDBOX"] = str(sandbox)
        env["RETROUX_ROOT"] = str(ROOT)
        env["PYTHONUTF8"] = "1"
        done = subprocess.run(
            [sys.executable, str(RUNNER), str(ACTIVE / "dq3_dev_test.lua")],
            cwd=str(ROOT), capture_output=True, timeout=180,
            text=True, encoding="utf-8", errors="replace", env=env)
        both = (done.stdout or "") + (done.stderr or "")
        if "lua5.1" in (done.stderr or "") and done.returncode != 0:
            pytest.skip("Lua を動かせない環境")
        assert done.returncode == 0, "⚠⚠ 記録が無いだけで落ちました\n" + both
        assert "すべて合格" in both, both
        # ★folder は作られる（⚠ 依頼者の決めごと 1）
        assert (sandbox / "work" / "dq3-probe").is_dir(), (
            "⚠ 記録用 folder が作られていない")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_記録の入口が1つにまとまっている():
    """⚠ 各ファイルが素の `io.open` に戻っていないこと。

    ★`Core.open_log` を通せば、⚠ folder 作成と console への通知が
      **必ず**付いてきます。⚠⚠ 素で開くと、また黙って止まります。
    """
    guilty = []
    for name in ("dev.lua", "auto_v0.lua", "mantan_v0.lua"):
        text = (PHASE0 / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "io.open(" in line and "dq3-probe" in line:
                guilty.append("%s: %s" % (name, line.strip()))
    assert not guilty, (
        "⚠⚠ 記録を素で開いています（★Core.open_log を使う）:\n"
        + "\n".join(guilty))


def test_openlogは開けなくてもnilを返す():
    """⚠⚠ **落ちないこと**が肝。★戻り値が nil なら `say` が黙るだけ。"""
    core = (PHASE0 / "core.lua").read_text(encoding="utf-8")
    assert "function M.open_log" in core
    # ⚠ 註釈に昔の書き方を引用してある。★コードの行だけ見る
    #   （「文中に書いただけで落ちる」のは検査の誤り）
    code = "\n".join(one for one in core.splitlines()
                     if not one.lstrip().startswith("--"))
    assert "assert(io.open" not in code, "⚠⚠ ここで落とすと元に戻る"
    assert "本体機能を止めない" in core, "★理由が書かれていない"
