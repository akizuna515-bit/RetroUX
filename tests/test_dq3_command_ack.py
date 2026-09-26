"""頼みが**どこまで**通ったかを判断できること（RX3-0130 / 2026-09-08）。

★指示書の Case A〜F をここで固定します。

```text
A  ai_reload → ACK → load_state         → 順番が守られる
B  state.json の書き出しが遅い           → ⚠ めくら撃ちの再送をしない
C  同じ seq を 2 回送る                  → ⚠ 二重実行しない（★Lua は seq <= 読んだ番号 を捨てる）
   ⚠⚠ 追い越された seq は `lost`         → ★新しい番号で出し直す（同じ番号では通らない）
D  Lua が受け取る前に timeout            → ★同じ seq で書き直す（安全な retry）
E  実行済みだが state 更新だけ遅い        → ⚠ 再実行しない
F  プロセスが終わった                    → ★待ち続けず、理由つきで失敗
```

⚠ 実機は要りません。★`state.json` を手で書いて、Lua の代わりをします。
"""
from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from dq3.ui import command_ack as CA
from dq3.ui.commands import CommandWriter

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Lua:
    """★Lua の代わり（⚠ `command_reader.lua` と同じ規則: `seq <= 読んだ番号` は捨てる）。"""

    def __init__(self, tmp: pathlib.Path, *, read_delay: float = 0.0,
                 state_delay: float = 0.0) -> None:
        self.cmd = tmp / "dq3-command.json"
        self.state = tmp / "state.json"
        self.read_delay = read_delay
        self.state_delay = state_delay
        self.received = 0
        self.applied = 0
        self.action = None
        self.executed: list[tuple[int, str]] = []      # ⚠ 二重実行はここに 2 回出る
        self.frame = 1000
        self.alive = True
        self._stop = False
        self._thread: threading.Thread | None = None
        self.write_state()

    # --- ★Lua がやること ---------------------------------------------
    def poll(self) -> None:
        """★`command_reader.tick()` 相当（⚠ 1 回ぶん）。"""
        try:
            got = json.loads(self.cmd.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        seq = int(got.get("seq") or 0)
        if seq <= self.received:
            return                                     # ⚠⚠ ここが二重実行を止める
        self.received = seq
        self.action = got.get("action")
        # ★取り出した瞬間を applied とする（`HOST.wants` 相当）
        self.applied = seq
        self.executed.append((seq, self.action))

    def write_state(self) -> None:
        self.frame += 1
        self.state.write_text(json.dumps({
            "frame": self.frame,
            "command_seq": self.received,
            "command": {"received": self.received, "applied": self.applied,
                        "action": self.action},
        }), encoding="utf-8")

    def run(self) -> None:
        """★裏で回す（⚠ 読む遅れと、state を書く遅れを別々に付けられる）。"""
        def loop():
            last_read = 0.0
            last_state = 0.0
            while not self._stop:
                now = time.time()
                if now - last_read >= self.read_delay:
                    last_read = now
                    self.poll()
                if now - last_state >= self.state_delay:
                    last_state = now
                    if self.alive:
                        self.write_state()
                time.sleep(0.02)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        if self._thread is not None:
            self._thread.join(timeout=2)


@pytest.fixture
def rig(tmp_path):
    lua = _Lua(tmp_path)
    writer = CommandWriter(tmp_path / "dq3-command.json")
    lines: list[str] = []
    waiter = CA.AckWaiter(tmp_path / "state.json", log=lines.append, sleep=0.02)
    return lua, writer, waiter, lines


# --- ★Case A ------------------------------------------------------------

def test_A_ai_reloadが通ってからload_stateを送る(rig):
    lua, writer, waiter, lines = rig
    lua.run()
    try:
        got = CA.send_and_wait(writer, waiter, "ai_reload", timeout=5)
        assert got.ok and got.stage == CA.APPLIED, got.line()
        assert lua.executed == [(1, "ai_reload")], "⚠ 順番が守れていない"
        got2 = CA.send_and_wait(writer, waiter, "load_state", slot="9", timeout=5)
        assert got2.ok, got2.line()
        assert [a for _s, a in lua.executed] == ["ai_reload", "load_state"], lua.executed
    finally:
        lua.stop()
    assert any("requested" in x for x in lines) and any("applied" in x for x in lines)


def test_A_旧式の即送りは前の頼みを消す(rig):
    """⚠⚠ **破壊試験**: 待たずに次を書くと、★前の頼みは実行されないまま消える。"""
    lua, writer, waiter, _lines = rig
    seq1 = writer.send("ai_reload")
    writer.send("load_state", slot="9")        # ⚠ 待たずに上書き（★元の race）
    lua.poll()
    lua.write_state()
    assert [a for _s, a in lua.executed] == ["load_state"], "⚠ race が再現していない"
    # ⚠⚠ 番号だけ見ると「通った」と読める（★applied=2 >= 1）。
    #   ★`lost`（追い越された）と言えることがこの WI の肝。
    assert waiter.stage_of(seq1, action="ai_reload") == CA.LOST, "⚠⚠ 取りこぼしを検出できていない"


# --- ★Case B ------------------------------------------------------------

def test_B_stateの書き出しが遅くてもめくら撃ちしない(rig):
    """★読むのは速いが、state.json が 1.2 秒に 1 回しか出ない場面。"""
    lua, writer, waiter, lines = rig
    lua.read_delay, lua.state_delay = 0.0, 1.2
    lua.run()
    try:
        got = CA.send_and_wait(writer, waiter, "ai_reload", timeout=6)
    finally:
        lua.stop()
    assert got.ok, got.line()
    assert got.resends == 0, "⚠⚠ 待てば分かるのに書き直している"
    assert lua.executed == [(1, "ai_reload")]


# --- ★Case C ------------------------------------------------------------

def test_C_同じseqを2回送っても二重実行しない(rig):
    lua, writer, waiter, _lines = rig
    writer.send("load_state", slot="9")
    lua.poll()
    writer.resend()
    lua.poll()
    lua.poll()
    assert lua.executed == [(1, "load_state")], "⚠⚠ 二重実行した: %r" % (lua.executed,)


def test_C_再送は同じ番号で書く(tmp_path):
    writer = CommandWriter(tmp_path / "c.json")
    seq = writer.send("ai_reload")
    assert writer.resend() == seq
    body = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert body["seq"] == seq and body["action"] == "ai_reload"


# --- ★Case D ------------------------------------------------------------

def test_D_受け取られていなければ同じseqで書き直す(rig):
    """★Lua が 1.5 秒読みに来ない場面（⚠ 新しい番号にはしない）。"""
    lua, writer, waiter, lines = rig
    lua.read_delay, lua.state_delay = 1.5, 0.0
    lua.run()
    try:
        got = CA.send_and_wait(writer, waiter, "ai_reload", timeout=0.5)
    finally:
        lua.stop()
    assert got.ok, got.line()
    assert got.resends >= 1, "⚠ 書き直していない"
    assert lua.executed == [(1, "ai_reload")], "⚠⚠ 書き直しで二重実行した"
    assert any("同じ番号で書き直す" in x for x in lines)


def test_D_届かないまま上限で諦める(rig):
    lua, writer, waiter, _lines = rig
    lua.read_delay, lua.state_delay = 99.0, 0.0     # ⚠ 読みに来ない
    lua.run()
    try:
        got = CA.send_and_wait(writer, waiter, "ai_reload", timeout=0.3)
    finally:
        lua.stop()
    assert not got.ok and got.stage == CA.UNSENT
    assert got.resends == CA.MAX_RESEND, "⚠ 上限まで書き直していない"
    assert "待ちました" in got.detail


# --- ★Case E ------------------------------------------------------------

def test_E_実行済みでstateが遅いだけなら再実行しない(rig):
    """⚠⚠ ここを間違えると、★load_state を 2 回読み込んで場面が飛ぶ。"""
    lua, writer, waiter, _lines = rig
    seq = writer.send("load_state", slot="9")
    lua.poll()                       # ★Lua は実行済み
    assert lua.executed == [(seq, "load_state")]
    # ⚠ state.json はまだ古い（★受け取ったことが見えない）
    assert waiter.stage_of(seq) == CA.UNSENT
    lua.write_state()                # ★遅れて反映
    assert waiter.stage_of(seq) == CA.APPLIED
    assert lua.executed == [(seq, "load_state")], "⚠⚠ 再実行した"


# --- ★Case F ------------------------------------------------------------

def test_F_プロセスが終わったら理由をつけて失敗する(rig):
    lua, writer, waiter, _lines = rig
    got = CA.send_and_wait(writer, waiter, "auto", timeout=5, alive=lambda: False)
    assert got.stage == CA.FROZEN and "FCEUX" in got.detail
    assert got.seconds < 3, "⚠ 死んでいるのに待っている"


def test_F_stateが進まなければ止まっていると言う(rig):
    lua, writer, waiter, _lines = rig
    waiter.sleep = 0.05
    old = CA.FROZEN_AFTER
    CA.FROZEN_AFTER = 0.3
    try:
        got = CA.send_and_wait(writer, waiter, "auto", timeout=5)
    finally:
        CA.FROZEN_AFTER = old
    assert got.stage == CA.FROZEN and "進んでいません" in got.detail


# --- ★Lua 側の写しが揃っていること --------------------------------------

def test_Luaもreceivedとappliedを分けている():
    """⚠⚠ 写しが 2 か所（★片方だけ直すと、待っても永久に来ない）。"""
    src = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "HOST.ack = {received = 0, applied = 0" in src
    assert "out.command = {received = HOST.ack.received, applied = HOST.ack.applied" in src
    assert "applied" in src and "CMD seq=" in src, "⚠ 記録に段階が出ない"
    reader = (ROOT / "dq3" / "phase0" / "command_reader.lua").read_text(encoding="utf-8")
    assert "seq <= R.seq" in reader, "⚠⚠ 同じ番号を捨てる規則が消えている（★二重実行する）"


def test_順番が大事な頼みを名指ししてある():
    assert "ai_reload" in CA.ORDERED and "load_state" in CA.ORDERED
