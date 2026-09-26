"""run をどう評価するか（RX3-0048 A-6 / ASSERT）。

## ★責務（指示書 §2）

```text
RUNNER    scripts/run_town_run.py     ★起動して、待って、後始末する
OBSERVER  video.py / state_diff.py    ★事実を集める（⚠ 判断しない）
ASSERT    ここ                          ★事実から「よかったか」を決める（⚠ 集めない）
```

⚠ 判断をここに寄せるのは、★「動画があるから PASS」のような**近道を 1 か所で止める**ためです。

## ⚠⚠ 2026-09-02 に踏んだ 2 つ

```text
left_local_map を FAIL と書いた      → ★止まる形は仕様（PoC② §6）
途中まで写した動画を「成功」にした   → ★中身を見ずにファイルの有無で決めていた
```
"""

from __future__ import annotations

#: ★結果の語（⚠ evidence.py と同じ / 増やさない）
PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"

#: ★★ 「ここで止まったら walker は正しく働いた」と言える理由（PoC② §6）
GOOD_STOPS = ("max_steps", "battle", "left_local_map", "boundary_reached",
              # ★field（PoC-C）: 決めた戦闘数 / 町に入った（★安全停止） / 全滅（⚠ 観測できたので run は成立）
              "max_battles", "entered_local", "player_death",
              # ★path（RX3-0051 / 0052）: 目的の升に着いた / 話した / 控えた
              "path_done", "talk_done", "saved")

#: ⚠ 止まったが、道具か環境の側に問題がある理由
BAD_STOPS = ("save_not_loaded", "state_unavailable", "battle_too_long", "unexpected_map",
             "boxed_in", "boundary_lost", "auto_stopped",
             "path_deviation", "path_map_changed", "no_path", "path_blocked", "face_moved",
             "save_failed", "lua_error")

#: ⚠⚠ 終わらなかった理由（★ASSERT: no_hang / ui_alive）
DEAD_STOPS = ("hang_suspected", "fceux_exited", "timeout", "navigation_hang")

#: ⚠ これより短い動画は「録れていない」と見る（★LEAD + TAIL = 4 秒より短いのは変）
MIN_VIDEO_S = 3.0


def video_valid(meta: dict | None) -> dict:
    """★★ 動画として成立しているか（指示書 A-1「存在するだけで PASS にしない」）。

    ```text
    ok=True    映像ストリームがあり、長さが MIN_VIDEO_S 以上、幅と高さがある
    ok=False   ⚠ どれか欠けている（★理由を `why` に）
    ok=None    ⚠ 検査できなかった（★ffprobe が無い / 動画が無い）
    ```
    """
    if not meta:
        return {"ok": None, "why": "⚠ 動画の情報がありません"}
    if not meta.get("available"):
        return {"ok": None, "why": meta.get("why") or "⚠ ffprobe で見られませんでした"}
    why = []
    if not meta.get("has_video"):
        why.append("映像ストリームが無い")
    d = meta.get("duration_s")
    if d is None:
        why.append("長さが分からない")
    elif d < MIN_VIDEO_S:
        why.append("短すぎる（%.1f 秒）" % d)
    if not meta.get("width") or not meta.get("height"):
        why.append("幅か高さが無い")
    return {"ok": not why, "why": " / ".join(why) if why else None,
            "duration_s": d, "size_bytes": meta.get("size_bytes")}


def classify(*, done: bool, reason, moved: int) -> str:
    """★run の結果。

    ```text
    PASS   ★決めた止まり方をして、⚠ 1 歩でも進んだ
    FAIL   ⚠ セーブが入らない / 状態が取れない / 1 歩も進まない
    ERROR  ⚠⚠ 終わらなかった（★hang / FCEUX が消えた / 時間切れ）
    ```
    """
    if not done or reason in DEAD_STOPS:
        return ERROR
    if reason in GOOD_STOPS and moved > 0:
        return PASS
    return FAIL


def checks(*, done: bool, reason, moved: int, video_meta=None,
           watchdog=None, expected_video: bool = False) -> dict:
    """★ASSERT をまとめて 1 つの辞書に（⚠ `metadata.json` の `checks`）。"""
    out = {
        "result": classify(done=done, reason=reason, moved=moved),
        "no_hang": {"ok": reason not in DEAD_STOPS and done,
                    "reason": reason, "watchdog": watchdog},
        "video_valid": video_valid(video_meta),
    }
    if expected_video and out["video_valid"]["ok"] is False:
        # ⚠ 録画するつもりだったのに壊れている → ★run は成立でも記録に残す
        out["warnings"] = ["⚠ 動画が成立していません: %s" % out["video_valid"]["why"]]
    return out
