"""RetroUX DQ2 / DQ3 の製品間排他（RX-0152 / RX3-0505 / 依頼者 2026-10-03）。

★仕様（依頼者）:
  DQ2 起動中に DQ3 を起動 → 起動しない・理由を表示して終了（逆も同じ）
  ⚠ FCEUX の有無では判定しない / ⚠ 異常終了の古いロックで永久に起動不能にならない /
  ⚠ ほぼ同時に起動しても両方は起動しない（★確認 → 取得の 2 段にしない）

★ここで見るもの:
  1. 取り方の判断（偽の OS で / 速い）
  2. ★本物の OS の Mutex と**別プロセス**で: 相手が居れば拒否・殺されたら起動できる・同時でも 1 つだけ
  3. DQ2 / DQ3 の写しと起動スクリプトが**同じ名前**を使う（⚠ 違えば排他にならない）
  4. GUI の入口が、拒否のとき何も始めずに終わる
  5. 起動スクリプトが、控え・GUI・FCEUX より先に判定し、GUI の名札が出るまで順番待ちを持つ

⚠ 本物の名前（`Local\\RetroUX_Product…`）は使わない（★遊んでいる製品と取り合わない / 検査ごとに別の接頭辞）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from dq3 import product_lock as dq3_lock
from retroux.core import product_lock as dq2_lock

ROOT = Path(__file__).resolve().parents[1]
WIN = sys.platform == "win32"


# --- 1. 取り方の判断（偽の OS）--------------------------------------------------

class FakeOS:
    """★名前つき Mutex の偽物（所有者 1 つ / handle が 1 つでもあれば存在する）。"""

    def __init__(self) -> None:
        self.refs: dict[str, int] = {}
        self.owner: dict[str, object] = {}
        self.handles: dict[int, tuple[str, object]] = {}
        self._next = 1

    def available(self) -> bool:
        return True

    def handle_for(self, who):
        def create(name):
            h = self._next
            self._next += 1
            self.handles[h] = (name, who)
            self.refs[name] = self.refs.get(name, 0) + 1
            return h
        return create

    def try_own(self, h) -> bool:
        name, who = self.handles[h]
        if self.owner.get(name) in (None, who):
            self.owner[name] = who
            return True
        return False

    def exists(self, name) -> bool:
        return self.refs.get(name, 0) > 0

    def release(self, h) -> None:
        name, who = self.handles[h]
        if self.owner.get(name) == who:
            self.owner.pop(name)

    def close(self, h) -> None:
        name, who = self.handles.pop(h)
        self.refs[name] -= 1

    def die(self, who) -> None:
        """★プロセスの終わり（★OS が handle を閉じ、所有を手放す）。"""
        for h, (name, w) in list(self.handles.items()):
            if w == who:
                self.close(h)
        for name, w in list(self.owner.items()):
            if w == who:
                self.owner.pop(name)


class Proc:
    """★1 プロセスぶんの API（★作った handle の持ち主を覚える）。"""

    def __init__(self, os_: FakeOS, who: str) -> None:
        self.os, self.who = os_, who
        self.create = os_.handle_for(who)

    def available(self):
        return True

    def try_own(self, h):
        return self.os.try_own(h)

    def exists(self, name):
        return self.os.exists(name)

    def release(self, h):
        self.os.release(h)

    def close(self, h):
        self.os.close(h)


@pytest.mark.parametrize("mod", [dq2_lock, dq3_lock], ids=["dq2", "dq3"])
def test_最初の製品は取れて相手は拒否される(mod) -> None:
    os_ = FakeOS()
    first = mod.ProductLock("DQ2", prefix="T", api=Proc(os_, "a"))
    assert first.acquire() == mod.Result(ok=True, primary=True)
    second = mod.ProductLock("DQ3", prefix="T", api=Proc(os_, "b"))
    assert second.acquire() == mod.Result(ok=False, other="DQ2")
    # ★拒否された側は名札を残さない（⚠ 残すと、次に起動する DQ2 が「DQ3 が起動中」と誤る）
    assert not os_.exists("T_DQ3")


@pytest.mark.parametrize("mod", [dq2_lock, dq3_lock], ids=["dq2", "dq3"])
def test_同じ製品の2つ目は拒否しない(mod) -> None:
    """★同じ製品の二重起動は、既存の仕組み（DQ2 の記録役ロックなど）に任せる。"""
    os_ = FakeOS()
    assert mod.ProductLock("DQ2", prefix="T", api=Proc(os_, "a")).acquire().primary
    second = mod.ProductLock("DQ2", prefix="T", api=Proc(os_, "b")).acquire()
    assert second == mod.Result(ok=True, primary=False)


def test_相手が終わったら起動できる() -> None:
    os_ = FakeOS()
    dq2_lock.ProductLock("DQ2", prefix="T", api=Proc(os_, "a")).acquire()
    os_.die("a")                                   # ★正常終了でも異常終了でも OS が手放す
    got = dq3_lock.ProductLock("DQ3", prefix="T", api=Proc(os_, "b")).acquire()
    assert got.ok and got.primary


def test_同時に名札を出しても勝つのは1つ() -> None:
    """★名札 → 所有の順なので、負けた側は必ず勝った側の名札を見る（⚠ 確認 → 取得の隙間が無い）。"""
    os_ = FakeOS()
    a = dq2_lock.ProductLock("DQ2", prefix="T", api=Proc(os_, "a"))
    b = dq3_lock.ProductLock("DQ3", prefix="T", api=Proc(os_, "b"))
    # ★両方が名札を出し終えたところで、所有を取り合う
    a._handles.append(a.api.create("T_DQ2"))
    b._handles.append(b.api.create("T_DQ3"))
    ea, eb = a.api.create("T"), b.api.create("T")
    assert a.api.try_own(ea) is True
    assert b.api.try_own(eb) is False
    assert b.api.exists("T_DQ2")                     # ★負けた側は相手の名札を見られる


@pytest.mark.parametrize("mod", [dq2_lock, dq3_lock], ids=["dq2", "dq3"])
def test_名札は所有を試すより先に出す(mod) -> None:
    """★順番が逆だと、所有に負けた側が「相手の名札がまだ無い」を見て、同じ製品と誤って起動する。"""
    order = []
    api = Proc(FakeOS(), "a")
    create, try_own = api.create, api.try_own
    api.create = lambda name: (order.append(("create", name)), create(name))[1]
    api.try_own = lambda h: (order.append(("own",)), try_own(h))[1]
    mod.ProductLock("DQ2", prefix="T", api=api).acquire()
    assert order.index(("create", "T_DQ2")) < order.index(("own",))


def test_Windows以外では止めない() -> None:
    class NoOS:
        def available(self):
            return False

    assert dq2_lock.ProductLock("DQ2", api=NoOS()).acquire().ok


def test_知らない製品は受け付けない() -> None:
    with pytest.raises(ValueError):
        dq2_lock.ProductLock("DQ4")


def test_拒否の文面は依頼者のとおり() -> None:
    assert dq2_lock.busy_message("DQ2", "DQ3") == (
        "RetroUX DQ3 が起動中です。\nDQ3を終了してからRetroUX DQ2を起動してください。")
    assert dq3_lock.busy_message("DQ3", "DQ2") == (
        "RetroUX DQ2 が起動中です。\nDQ2を終了してからRetroUX DQ3を起動してください。")


# --- 3. 写しと起動スクリプトが同じ名前を使う -------------------------------------

def test_DQ2とDQ3の写しが同じ名前を使う() -> None:
    for name in ("PRODUCTS", "LABELS", "DEFAULT_PREFIX", "EXCLUSIVE_SUFFIX", "LAUNCH_SUFFIX", "PREFIX_ENV"):
        assert getattr(dq2_lock, name) == getattr(dq3_lock, name), name
    for product in ("DQ2", "DQ3"):
        assert dq2_lock.identity_name(product) == dq3_lock.identity_name(product)
    assert dq2_lock.exclusive_name() == dq3_lock.exclusive_name()


def test_起動スクリプトも同じ名前を使う() -> None:
    text = (ROOT / "scripts" / "launcher-common.ps1").read_text(encoding="utf-8-sig")
    assert f'$script:RetroUXProductPrefix = "{dq2_lock.DEFAULT_PREFIX}"' in text
    assert '($Prefix + "Launch")' in text and dq2_lock.LAUNCH_SUFFIX == "Launch"
    assert '($Prefix + "_" + $p)' in text and dq2_lock.identity_name("DQ2", "P") == "P_DQ2"
    for product, label in dq2_lock.LABELS.items():
        assert f'{product} = "{label}"' in text


def test_検査は本物の名前で取らない() -> None:
    """⚠ 遊んでいる DQ2 / DQ3 と取り合わない（conftest が接頭辞を差し替える）。"""
    got = os.environ.get(dq2_lock.PREFIX_ENV, "")
    assert got and got != dq2_lock.DEFAULT_PREFIX
    assert dq2_lock.current_prefix() == got


# --- 2. 本物の OS の Mutex と別プロセス -------------------------------------------

def _prefix() -> str:
    return "Local\\RetroUX_ProductTest_" + uuid.uuid4().hex[:12]


def _hold(product: str, prefix: str, seconds: float) -> subprocess.Popen:
    module = "retroux.core.product_lock" if product == "DQ2" else "dq3.product_lock"
    return subprocess.Popen(
        [sys.executable, "-m", module, "--hold", product, "--prefix", prefix, "--seconds", str(seconds)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _first_line(proc: subprocess.Popen) -> str:
    """★最初の 1 語（ACQUIRED / SAME / REFUSED=…）。★本当のプロセス番号は `proc.real_pid` に覚える。"""
    words = (proc.stdout.readline() or "").split()
    proc.real_pid = next((int(w[4:]) for w in words if w.startswith("pid=")), None)
    return words[0] if words else ""


def _stop(proc: subprocess.Popen) -> None:
    """★握っている本体を止める（⚠ venv の python.exe は子に本体を起こすので、親だけ止めても握ったまま）。"""
    import signal

    pid = getattr(proc, "real_pid", None)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)           # ★Windows では TerminateProcess（= 異常終了と同じ）
        except OSError:
            pass
    proc.wait(timeout=10)


@pytest.mark.skipif(not WIN, reason="Windows の Mutex の話")
def test_本物_相手が動いていれば拒否し終われば起動できる() -> None:
    prefix = _prefix()
    holder = _hold("DQ3", prefix, 30)
    try:
        assert _first_line(holder) == "ACQUIRED"
        got = dq2_lock.ProductLock("DQ2", prefix=prefix).acquire()
        assert got == dq2_lock.Result(ok=False, other="DQ3")
        assert dq2_lock.other_running("DQ2", prefix=prefix) == "DQ3"
    finally:
        _stop(holder)
    lock = dq2_lock.ProductLock("DQ2", prefix=prefix)
    try:
        assert lock.acquire().primary
    finally:
        lock.close()


@pytest.mark.skipif(not WIN, reason="Windows の Mutex の話")
def test_本物_殺されたプロセスの古いロックは残らない() -> None:
    """★異常終了（kill）でも OS が手放す（⚠ 永久に起動不能にならない）。"""
    prefix = _prefix()
    holder = _hold("DQ2", prefix, 60)
    assert _first_line(holder) == "ACQUIRED"
    _stop(holder)                                  # ★kill（解放せずに死ぬ）
    lock = dq3_lock.ProductLock("DQ3", prefix=prefix)
    try:
        got = lock.acquire()
        assert got.ok and got.primary
    finally:
        lock.close()


@pytest.mark.skipif(not WIN, reason="Windows の Mutex の話")
@pytest.mark.parametrize("round_", range(5))
def test_本物_ほぼ同時に起動しても1つだけ(round_: int) -> None:
    prefix = _prefix()
    a = _hold("DQ2", prefix, 3)
    b = _hold("DQ3", prefix, 3)
    try:
        got = sorted([_first_line(a), _first_line(b)])
    finally:
        for p in (a, b):
            _stop(p)
    assert got in (["ACQUIRED", "REFUSED=DQ2"], ["ACQUIRED", "REFUSED=DQ3"]), got


# --- 4. GUI の入口 --------------------------------------------------------------

def test_DQ2のGUIは拒否されたら何も始めない(monkeypatch: pytest.MonkeyPatch) -> None:
    from retroux import gui
    from retroux.core import product_lock

    calls = []
    monkeypatch.setattr(gui, "setup_logging",
                        lambda *a, **k: type("H", (), {"buffer": None, "shutdown": lambda self: None})())
    monkeypatch.setattr(gui.user_config_mod, "load", lambda *a, **k: (gui.user_config_mod.UserConfig(), []))
    monkeypatch.setattr(product_lock, "guard", lambda me, **k: calls.append(me))

    def boom(*a, **k):
        raise AssertionError("⚠ 拒否されたのに記録役のロックを取りにいった")

    monkeypatch.setattr(gui, "RecorderLock", boom)
    assert gui.main([]) == 1
    assert calls == ["DQ2"]


def test_DQ3の画面は拒否されたら何も始めない(monkeypatch: pytest.MonkeyPatch) -> None:
    from dq3 import product_lock
    from dq3.ui import app

    calls = []
    monkeypatch.setattr(product_lock, "guard", lambda me, **k: calls.append(me))

    def boom(*a, **k):
        raise AssertionError("⚠ 拒否されたのに画面の材料を作った")

    monkeypatch.setattr(app, "Dq3ViewModel", boom)
    assert app.main(["--no-migrate-offer"]) == 1
    assert calls == ["DQ3"]


def test_拒否の理由は箱でもログでも出る() -> None:
    shown, logged = [], []

    class Log:
        def warning(self, fmt, text):
            logged.append(text)

    other = dq2_lock.ProductLock("DQ3", prefix="T", api=Proc(FakeOS(), "x"))
    assert other is not None
    os_ = FakeOS()
    dq3_lock.ProductLock("DQ3", prefix="T", api=Proc(os_, "a")).acquire()
    got = dq2_lock.guard("DQ2", log=Log(), box=shown.append, prefix="T", api=Proc(os_, "b"))
    assert got is None
    assert shown == [dq2_lock.busy_message("DQ2", "DQ3")]
    assert logged and "RetroUX DQ3 が起動中です" in logged[0]


# --- 5. 起動スクリプト -----------------------------------------------------------

def _code(rel: str) -> list[str]:
    text = (ROOT / rel).read_text(encoding="utf-8-sig")
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def _index(lines: list[str], needle: str) -> int:
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"見つからない: {needle}")


def test_DQ2の起動スクリプトは何より先に判定し名札が出るまで待つ() -> None:
    code = _code("scripts/start-dq2.ps1")
    enter = _index(code, "$productLaunch = Enter-RetroUXProductLaunch")
    check = _index(code, 'Get-RetroUXOtherProduct -Me "DQ2"')
    backup = _index(code, '"retroux.tools.dq2_savestate_backup",')
    gui = _index(code, "$gui = Start-NoConsole")
    wait = _index(code, 'Wait-RetroUXProduct -Me "DQ2"')
    fceux = _index(code, "Start-Dq2Emulator @startArgs")
    assert enter < check < backup < gui < wait < fceux
    assert any("Exit-RetroUXProductLaunch $productLaunch" in ln for ln in code[_index(code, "finally {"):])


def test_DQ3の起動スクリプトは控えより先に判定し名札が出るまで待つ() -> None:
    code = _code("scripts/start-dq3.ps1")
    early = _index(code, 'Get-RetroUXOtherProduct -Me "DQ3"')
    migrate = _index(code, "--migrate-offer-only")
    enter = _index(code, "$productLaunch = Enter-RetroUXProductLaunch")
    backup = _index(code, '"dq3.savestate_backup"')
    fceux = _index(code, "Start-Process -FilePath $fceux")
    ui = _index(code, "Start-Process -FilePath $pythonw")
    wait = _index(code, 'Wait-RetroUXProduct -Me "DQ3"')
    assert early < migrate < enter < backup < fceux < ui < wait
    recheck = [i for i, ln in enumerate(code) if 'Get-RetroUXOtherProduct -Me "DQ3"' in ln]
    assert len(recheck) == 2 and enter < recheck[1] < backup, "★順番待ちを取ってからもう一度見る"


@pytest.mark.skipif(not WIN, reason="PowerShell と Windows の Mutex")
def test_本物_起動スクリプトの関数が相手を見つける(tmp_path: Path) -> None:
    """★PowerShell の関数を実際に動かす（⚠ 字面だけでは .NET の呼び方の誤りを見落とす）。"""
    prefix = _prefix()
    holder = _hold("DQ3", prefix, 30)
    try:
        assert _first_line(holder) == "ACQUIRED"
        script = tmp_path / "probe.ps1"
        common = ROOT / "scripts" / "launcher-common.ps1"
        script.write_text(
            "﻿"
            f". '{common}'\n"
            f"$p = '{prefix}'\n"
            "$m = Enter-RetroUXProductLaunch -TimeoutMs 5000 -Prefix $p\n"
            "Write-Output ('LAUNCH=' + ($null -ne $m))\n"
            "Write-Output ('OTHER=' + (Get-RetroUXOtherProduct -Me 'DQ2' -Prefix $p))\n"
            "Write-Output ('SELF=' + (Get-RetroUXOtherProduct -Me 'DQ3' -Prefix $p))\n"
            "Write-Output ('WAIT=' + (Wait-RetroUXProduct -Me 'DQ3' -TimeoutMs 2000 -Prefix $p))\n"
            "Exit-RetroUXProductLaunch $m\n"
            "Write-Output ('MSG=' + (Get-RetroUXBusyMessage -Me 'DQ2' -Other 'DQ3').Replace(\"`n\", '|'))\n",
            encoding="utf-8")
        done = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             "[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '" + str(script) + "'"],
            capture_output=True, timeout=60)
    finally:
        _stop(holder)
    out = done.stdout.decode("utf-8", "replace")
    assert "LAUNCH=True" in out, out + done.stderr.decode("utf-8", "replace")
    assert "OTHER=DQ3" in out
    assert "SELF=" in out and "SELF=DQ" not in out    # ★自分の製品は「相手」に数えない
    assert "WAIT=True" in out
    assert "MSG=" + dq2_lock.busy_message("DQ2", "DQ3").replace("\n", "|") in out
