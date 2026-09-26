"""run の判定（RX3-0048 A-6 / ASSERT）。

⚠⚠ 2026-09-02 に踏んだ 2 つを、★ここで固定します。

```text
left_local_map を FAIL と書いた      → ★止まる形は仕様
途中まで写した動画を「成功」にした   → ★ファイルの有無で決めていた
```
"""

from __future__ import annotations

from dq3.testing import verdict


def test_町から出たのはPASS():
    """⚠⚠ **仕様どおりの停止を失敗と書かない**。"""
    assert verdict.classify(done=True, reason="left_local_map", moved=35) == "PASS"
    assert verdict.classify(done=True, reason="max_steps", moved=150) == "PASS"
    assert verdict.classify(done=True, reason="battle", moved=3) == "PASS"


def test_1歩も進まなければFAIL():
    assert verdict.classify(done=True, reason="max_steps", moved=0) == "FAIL"


def test_セーブが入らなければFAIL():
    assert verdict.classify(done=True, reason="save_not_loaded", moved=0) == "FAIL"


def test_終わらなければERROR():
    assert verdict.classify(done=False, reason="timeout", moved=10) == "ERROR"
    assert verdict.classify(done=False, reason="hang_suspected", moved=10) == "ERROR"
    assert verdict.classify(done=False, reason="fceux_exited", moved=10) == "ERROR"


# --- ⚠⚠ 動画は「ある」だけでは成立しない ------------------------------------

def test_中身のある動画は成立():
    got = verdict.video_valid({"available": True, "has_video": True, "duration_s": 23.0,
                               "width": 1920, "height": 1200, "size_bytes": 5335902})
    assert got["ok"] is True and got["why"] is None


def test_映像が無ければ成立しない():
    got = verdict.video_valid({"available": True, "has_video": False, "duration_s": 23.0,
                               "width": None, "height": None})
    assert got["ok"] is False and "映像" in got["why"]


def test_短すぎる動画は成立しない():
    """⚠⚠ 途中まで写した動画（491,520 バイト）はここで落ちる。"""
    got = verdict.video_valid({"available": True, "has_video": True, "duration_s": 0.4,
                               "width": 1920, "height": 1200})
    assert got["ok"] is False and "短すぎる" in got["why"]


def test_検査できなければ分からないと言う():
    """⚠ ffprobe が無いのを「壊れている」とは言わない（★None）。"""
    assert verdict.video_valid(None)["ok"] is None
    assert verdict.video_valid({"available": False, "why": "⚠ ffprobe が無い"})["ok"] is None


def test_まとめは結果と動画と止まり方を持つ():
    got = verdict.checks(done=True, reason="max_steps", moved=10,
                         video_meta={"available": True, "has_video": True,
                                     "duration_s": 0.4, "width": 1, "height": 1},
                         watchdog={"stalled": False}, expected_video=True)
    assert got["result"] == "PASS"
    assert got["no_hang"]["ok"] is True
    assert got["video_valid"]["ok"] is False
    assert got["warnings"], "⚠ 録るつもりだった動画が壊れているのに黙っている"
