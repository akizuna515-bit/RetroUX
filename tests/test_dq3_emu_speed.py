"""FCEUX の速度制御（RX3-0059）。★送る命令の列を偽の送り口で見る。"""
from __future__ import annotations

from dq3.ui import emu_speed as ES


def _ctl(ok=True):
    sent = []

    def sender(cmd):
        sent.append(cmd)
        return ok

    c = ES.EmulatorSpeedController(sender=sender, finder=lambda: 1 if ok else 0)
    return c, sent


def test_2倍速はNormalの錨のあとSpeedUpを2回():
    c, sent = _ctl()
    assert c.set_speed(2.0) and c.current == 2.0
    assert sent == [ES.CMD_NORMAL, ES.CMD_UP, ES.CMD_UP]


def test_戻すとNormalだけ():
    c, sent = _ctl()
    c.set_speed(2.0)
    sent.clear()
    assert c.restore() and c.current == 1.0 and sent == [ES.CMD_NORMAL]


def test_FCEUXが居なければ落ちずにfalse():
    c, sent = _ctl(ok=False)
    assert c.set_speed(2.0) is False and c.current == 1.0
    assert c.restore() is False and c.current == 1.0           # ⚠ 例外にしない


def test_出せない倍率は断る():
    c, _ = _ctl()
    try:
        c.set_speed(2.5)
    except ValueError:
        return
    raise AssertionError("2.5 倍は出せない")


def test_送り直しはいまの倍率をもう一度():
    c, sent = _ctl()
    c.set_speed(2.0)
    sent.clear()
    assert c.reassert() and sent == [ES.CMD_NORMAL, ES.CMD_UP, ES.CMD_UP]
    c.restore()
    sent.clear()
    assert c.reassert() and sent == []          # ★等速なら送らない
