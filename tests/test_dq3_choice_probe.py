"""窓が開いた瞬間を捕まえる probe（RX3-0124 ① / 2026-09-19）。

## ⚠⚠ なぜ実機の前にここで確かめるか

★前の probe は**実機で走らせて初めて**「撮れていない」と分かりました。

```text
⚠ `$0077` は作業用の番地で、実測 60 秒に 6,936 回変わる
→ 「変わってから 20 フレーム後に撮る」形では、★次の変化が予約を上書きする
→ ⚠ 60 秒で 26 枚しか撮れず、意味があったのは起動メニュー 1 枚だけ
```

★いまは**窓を開く処理の実行**（bank14 `$87F5`）を捕まえます。
⚠ `memory.registerexec` は**番地**でしか鳴らないので、★毎回 bank を確かめます。

⚠ 実機の走行は高いので、★鳴り方は**偽の FCEUX API**でここに固定します。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_choice_probe_test.lua"
PROBE = ROOT / "research" / "probes" / "active" / "dq3_choice_probe.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and PROBE.exists()),
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
    assert done.returncode == 0, "⚠⚠ 落ちました" + chr(10) + both
    return both


def test_最後まで走って合格する(run):
    assert "すべて合格" in run, "⚠ 失敗があります" + chr(10) + run


def test_OKが全部出ている(run):
    got = [ln for ln in run.splitlines() if ln.startswith("OK ")]
    assert len(got) >= 7, "⚠ OK が %d 件しかありません%s%s" % (len(got), chr(10), run)


def test_その場では撮らないことを動かして確かめている(run):
    assert "その場では撮らず" in run, run


def test_別のbankでは撮らないことを動かして確かめている(run):
    """⚠⚠ `memory.registerexec` は**番地**でしか鳴らない（★同じ番地が別の bank にもある）。"""
    assert "別の bank の同じ番地では撮らない" in run, run


# --- ★作りの見張り（⚠ 作っただけで使っていない、を防ぐ）------------------

def _body() -> str:
    return chr(10).join(ln for ln in PROBE.read_text(encoding="utf-8").splitlines()
                        if not ln.lstrip().startswith("--"))


def test_実行を捕まえている():
    """⚠ `$0077` の見張りに戻すと、★また撮れなくなる。"""
    body = _body()
    assert "memory.registerexec" in body, "⚠⚠ 実行を捕まえていない"
    assert "0x87F5" in body, "⚠ STA $77 の**次**を引っ掛けていない"


def test_bankを毎回確かめている():
    body = _body()
    assert "bank_ok" in body and "SIGN" in body
    assert "if not bank_ok() then" in body, "⚠⚠ 作っただけで使っていない"


def test_前の関数を呼んでいる():
    """⚠⚠ `emu.registerafter` は**前の関数を返す**（★製品を止めない / RX3-0107）。"""
    body = _body()
    assert "prev = emu.registerafter(tick)" in body
    assert "if prev then prev() end" in body, "⚠⚠ 製品の毎フレームを止めている"


def test_枚数を終わりに残している():
    """⚠ 「0 枚」を黙って見逃さない。"""
    body = _body()
    assert "choice probe end" in body and "taken" in body
