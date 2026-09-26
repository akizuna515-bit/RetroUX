"""FCEUX の音を消す（RX3-0104 / 2026-09-07）。

⚠⚠ **本物の音は触りません。**★COM は環境に依存するので、`backend` を差し替えます。

## ★実機で 1 度だけ確かめたこと（2026-09-07）

⚠ 「例外が出なかった」は根拠になりません（★セッション 0 件でも例外は出ない）。
→ ★動いているプロセスを総当りして、**音のセッションを持つ 4 件**の
  消音状態を実際に読み出せることを確かめました（⚠ 書き換えはしていません）。

```text
RtkAudUService64.exe / steam.exe / obs64.exe / chrome.exe  → いずれも消音でない
```
"""
from __future__ import annotations

from dq3.ui import mute as MU


class _Backend:
    available = True

    def __init__(self, muted=False, ok=True):
        self.muted = muted
        self.ok = ok
        self.last_error = None
        self.seen: list[tuple[int, bool]] = []

    def get_mute(self, pid):
        return self.muted if self.ok else None

    def set_mute(self, pid, on):
        if not self.ok:
            self.last_error = "⚠ だめ"
            return False
        self.seen.append((pid, bool(on)))
        self.muted = bool(on)
        return True


def _ctl(**kw):
    b = _Backend(**kw)
    return MU.MuteController(backend=b, pid_finder=lambda: 99), b


def test_消して戻せる():
    c, b = _ctl()
    assert c.get() is False
    assert c.set(True) and b.muted is True and b.seen == [(99, True)]
    assert c.set(False) and b.muted is False


def test_FCEUXが居なければ触らない():
    c = MU.MuteController(backend=_Backend(), pid_finder=lambda: 0)
    assert c.get() is None and "FCEUX" in (c.last_error or "")
    assert c.set(True) is False


def test_分からないときはNoneでFalseと混ぜない():
    """⚠⚠ 「読めなかった」を「消音でない」にすると、★戻すときに間違えます。"""
    c, b = _ctl(ok=False)
    got = c.get()
    assert got is None and got is not False


def test_失敗しても例外にしない():
    c, b = _ctl(ok=False)
    assert c.set(True) is False
    assert c.last_error


def test_こちらが消したかを覚えている():
    """★`atexit` で戻すかの判断（⚠ 人が消していた音を戻さない）。"""
    c, b = _ctl()
    assert c.changed is False
    c.set(True)
    assert c.changed is True
    c.set(False)
    assert c.changed is False


def test_窓が無ければプロセス番号は0():
    assert MU.fceux_pid(finder=lambda: 0) == 0


def test_本物のbackendは組み立てられる():
    """⚠ import と GUID の変換までは、実機なしでも通ること。

    ★中身（COM の呼び出し）は環境に依存するので、ここでは呼びません。
    """
    b = MU.WindowsAudioBackend()
    got = b._guid(MU._IID_ISimpleAudioVolume)
    assert got.Data1 == 0x87CE5498
    # ⚠ vtable の番号を書き間違えると**別の関数**を呼ぶので、値そのものを守る
    assert (MU._VT_VOL_SET_MUTE, MU._VT_VOL_GET_MUTE) == (5, 6)
    assert MU._VT_CTL2_GET_PROCESS_ID == 14
