"""止まったことに気づく（RX3-0048 A-4）。

★時計は偽物（⚠ 実時間で待つ検査は遅くて不安定）。
"""

from __future__ import annotations

import pathlib

from dq3.testing.watchdog import Watchdog


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _dog(tmp_path, clock, **kw):
    log = pathlib.Path(tmp_path) / "run.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    return Watchdog([log], limit_s=30, clock=clock, **kw), log


def _touch(path, text):
    """★1 行足すだけ（⚠ **細工はしません**）。

    ## ⚠⚠ 2026-09-07（RX3-0075）: ここに `os.utime` の細工がありました

      ★`mtime + 1ms` を明示的に書き込んでいました。⚠ それでも **300 回中 92 回**
      赤くなりました（★実測）。理由は「書いたあとの `stat()` が**古い mtime を返す**」
      ためで、⚠ +1ms しても**前と同じ値**になる回があったからです。

      ```text
      ★もとの検査（mtime ＋ 細工）  ⚠ 赤  92 / 300
      ⚠ 細工なしで mtime だけ        ⚠ 赤 242 / 300
      ★size を見る                  ★赤   0 / 300
      ```

      → ⚠ 細工で隠すのではなく、★`Watchdog` が `st_size` も見るように直しました。
      ⚠ **細工を戻さないでください**（★戻すと「本物の追記」を試さなくなります）。
    """
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def test_何も変わらなければ止まったと見る(tmp_path):
    clock = _Clock()
    dog, _log = _dog(tmp_path, clock)
    dog.beat()
    clock.t += 31
    dog.beat()
    assert dog.stalled(), "⚠⚠ 31 秒なにも変わっていないのに生きていると言った"


def test_期限内なら止まっていない(tmp_path):
    clock = _Clock()
    dog, _log = _dog(tmp_path, clock)
    dog.beat()
    clock.t += 29
    dog.beat()
    assert not dog.stalled()


def test_ファイルが更新されれば生きている(tmp_path):
    clock = _Clock()
    dog, log = _dog(tmp_path, clock)
    dog.beat()
    clock.t += 25
    _touch(log, '{"step":1}')
    assert dog.beat() is True, "⚠ 更新に気づいていない"
    clock.t += 25
    dog.beat()
    assert not dog.stalled(), "⚠⚠ 更新があったのに止まったと言った"


def test_壁にぶつかっただけは止まっていない(tmp_path):
    """⚠⚠ **壁衝突を hang にしない**（指示書 A-4）。

    ★座標は変わらないが、`run.jsonl` に `ok:false` の行が足される。
    """
    clock = _Clock()
    pos = {"xy": (8, 18)}
    dog, log = _dog(tmp_path, clock, extra=[lambda: pos["xy"]])
    dog.beat()
    for _ in range(5):
        clock.t += 10                        # ★50 秒ぶん壁にぶつかり続ける
        _touch(log, '{"step":1,"ok":false,"x":8,"y":18}')
        dog.beat()
    assert not dog.stalled(), "⚠⚠ 壁にぶつかっているだけなのに hang と言った"


def test_座標だけが動いても生きている(tmp_path):
    clock = _Clock()
    pos = {"xy": (8, 18)}
    dog, _log = _dog(tmp_path, clock, extra=[lambda: pos["xy"]])
    dog.beat()
    clock.t += 25
    pos["xy"] = (8, 19)
    dog.beat()
    clock.t += 25
    dog.beat()
    assert not dog.stalled()


def test_脈が読めなくても落ちない(tmp_path):
    clock = _Clock()

    def broken():
        raise RuntimeError("読めない")
    dog, _log = _dog(tmp_path, clock, extra=[broken])
    assert dog.beat() is True
    got = dog.report()
    assert got["beats"] == 1 and "stalled" in got


def test_無いファイルは待つ(tmp_path):
    clock = _Clock()
    dog = Watchdog([tmp_path / "まだ無い.jsonl"], limit_s=30, clock=clock)
    dog.beat()
    clock.t += 10
    (tmp_path / "まだ無い.jsonl").write_text("x", encoding="utf-8")
    assert dog.beat() is True, "⚠ ファイルが出来たことに気づいていない"


# ----------------------------------------------------------------------
# ⚠⚠ 追記に気づく根拠（RX3-0075 / 2026-09-07）
# ----------------------------------------------------------------------
def test_更新時刻が動かなくても追記に気づく(tmp_path):
    """★これが `RX3-0075` の本体（⚠ 時間に依らない形で固定する）。

    ⚠ Windows は間を空けずに追記すると `mtime` を進めません（★実測 79.4%）。
    → ★`mtime` を**わざと戻して**、`st_size` だけで気づけることを見ます。
    """
    import os

    clock = _Clock()
    dog, log = _dog(tmp_path, clock)
    dog.beat()
    before = log.stat()
    _touch(log, '{"step":1}')
    # ⚠⚠ 更新時刻を**書く前の値へ戻す**（★mtime だけを見ていたら気づけない）
    os.utime(log, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert log.stat().st_mtime_ns == before.st_mtime_ns, "⚠ 前提が崩れた"
    assert log.stat().st_size > before.st_size
    assert dog.beat() is True, "⚠⚠ 行が足されたのに気づいていない"


def test_大きさが同じでも書き直しに気づく(tmp_path):
    """⚠ `size` だけにしない理由（★同じ長さで書き直された場合）。"""
    import os

    clock = _Clock()
    dog, log = _dog(tmp_path, clock)
    log.write_text("aaaa", encoding="utf-8")
    dog.beat()
    st = log.stat()
    log.write_text("bbbb", encoding="utf-8")          # ★同じ大きさ
    os.utime(log, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    assert log.stat().st_size == st.st_size, "⚠ 前提が崩れた"
    assert dog.beat() is True, "⚠ 書き直しに気づいていない"


def test_壁にぶつかり続けても止まったと言わない_連続(tmp_path):
    """⚠⚠ **20 回連続で緑**（★`RX3-0075` の Acceptance）。

    ⚠ もとの形（`mtime` だけ）だと 300 回中 92 回赤くなりました。
    ★1 回だけ緑でも意味がないので、⚠ **同じ条件を 20 回**回します。
    """
    for i in range(20):
        clock = _Clock()
        pos = {"xy": (8, 18)}
        dog, log = _dog(tmp_path / ("r%02d" % i), clock, extra=[lambda: pos["xy"]])
        dog.beat()
        for _ in range(5):
            clock.t += 10
            _touch(log, '{"step":1,"ok":false,"x":8,"y":18}')
            dog.beat()
        assert not dog.stalled(), "⚠⚠ %d 回目で hang と言った（★quiet %.0f 秒）" % (
            i + 1, dog.quiet_for())
