"""動画を**あとから検査できる材料**にする（RX3-0048 / OBSERVER）。

## ⚠⚠ 「動画ファイルがある」は PASS ではない（指示書 A-1）

★2026-09-02 に、OBS が書き終える前に move して**途中まで写した壊れた動画**が
「成功」として残りました（491,520 バイト / 本物は 984,452）。
⚠ ファイルの有無では、この壊れ方に気づけません。

→ ★`ffprobe` で **長さ・大きさ・映像ストリームの有無**まで見て、それを
`metadata.json` に入れます（`describe()`）。

## ★静止画（指示書 A-2）

```text
video_000.png   ★開始付近
video_mid.png   ★中間
video_end.png   ★終了付近
video_010s.png  ⚠ 一定間隔（★長い run 用 / `every=` を渡す）
```

⚠ 画像の中身は判定しません（★「後から AI が見られる」まで / 指示書 A-2）。

## ⚠ ffprobe が無いとき

★`describe()` は `{"available": False, "why": ...}` を返します。
⚠⚠ **例外を投げません。** 録画の検査ができなくても run は成立します。

## ★責務

```text
ここ（OBSERVER）  ffprobe / ffmpeg を呼んで**事実**を集める
verdict.py（ASSERT） その事実から「動画として成立しているか」を決める
```
"""

from __future__ import annotations

import json
import pathlib
import subprocess

from . import ffmpeg as ff

#: ⚠ ffprobe / ffmpeg の待ち時間
PROBE_TIMEOUT = 30.0
FRAME_TIMEOUT = 60.0

#: ★静止画の名前（⚠ 指示書 A-2 の例のまま）
FRAME_NAMES = ("video_000.png", "video_mid.png", "video_end.png")

#: ⚠ 終端ぎりぎりは 1 枚も取れないことがある（★少し手前を取る）
END_MARGIN = 0.5


# --- ★ffprobe の JSON → 平らな辞書 ---------------------------------------

def _fraction(text) -> float | None:
    """★`"60/1"` → 60.0。⚠ 変なものは `None`。"""
    if text is None:
        return None
    try:
        if "/" in str(text):
            a, b = str(text).split("/", 1)
            return float(a) / float(b) if float(b) != 0 else None
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def parse_probe(body: dict) -> dict:
    """★★ ffprobe の出力（`-print_format json`）から要るものだけを抜く。

    ⚠ ここは**ffprobe を呼びません**（★実機なしで検査できる部分 / 指示書 §23）。

    ```text
    duration_s / width / height / fps / video_codec / audio_codec
    has_video / has_audio / size_bytes / format
    ```
    """
    fmt = body.get("format") or {}
    streams = body.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    out = {
        "has_video": video is not None,
        "has_audio": audio is not None,
        "format": fmt.get("format_name"),
        "duration_s": _fraction(fmt.get("duration")),
        "size_bytes": int(fmt["size"]) if str(fmt.get("size", "")).isdigit() else None,
        "width": None, "height": None, "fps": None,
        "video_codec": None, "audio_codec": None,
    }
    if video is not None:
        out["width"] = video.get("width")
        out["height"] = video.get("height")
        out["fps"] = _fraction(video.get("avg_frame_rate")) or _fraction(
            video.get("r_frame_rate"))
        out["video_codec"] = video.get("codec_name")
        # ⚠ mkv は format 側に duration が無いことがある（★stream 側を見る）
        if out["duration_s"] is None:
            out["duration_s"] = _fraction(video.get("duration"))
            tags = video.get("tags") or {}
            if out["duration_s"] is None and tags.get("DURATION"):
                out["duration_s"] = _hms(tags["DURATION"])
    if audio is not None:
        out["audio_codec"] = audio.get("codec_name")
    return out


def _hms(text: str) -> float | None:
    """★`"00:00:29.966000000"` → 29.966。"""
    try:
        h, m, s = str(text).split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (TypeError, ValueError):
        return None


# --- ★ffprobe を呼ぶ -----------------------------------------------------

def describe(path) -> dict:
    """★★ 動画の事実を集める。⚠ **例外を投げません**。

    ```text
    {"available": True,  "path": ..., ...parse_probe の中身...}
    {"available": False, "why": "⚠ ffprobe が見つかりません" ...}
    ```
    """
    path = pathlib.Path(path)
    out = {"available": False, "file": path.name,
           "exists": path.exists(),
           "size_bytes": path.stat().st_size if path.exists() else None}
    if not path.exists():
        out["why"] = "⚠ 動画がありません"
        return out
    exe = ff.find("ffprobe")
    if exe is None:
        out["why"] = "⚠ ffprobe が見つかりません（★work/tools/ffmpeg か RETROUX_FFMPEG）"
        return out
    cmd = [str(exe), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as err:
        out["why"] = "⚠ ffprobe を起動できません: %s" % err
        return out
    if done.returncode != 0:
        out["why"] = "⚠ ffprobe が %d で終わりました: %s" % (
            done.returncode, (done.stderr or b"").decode("utf-8", "replace")[:200])
        return out
    try:
        body = json.loads((done.stdout or b"{}").decode("utf-8", "replace"))
    except ValueError as err:
        out["why"] = "⚠ ffprobe の出力を読めません: %s" % err
        return out
    got = parse_probe(body)
    got["size_bytes"] = got["size_bytes"] or out["size_bytes"]
    out.update(got)
    out["available"] = True
    out["ffprobe"] = str(exe)
    return out


# --- ★静止画 -------------------------------------------------------------

def sample_times(duration_s, *, every: float | None = None) -> list[tuple[str, float]]:
    """★どの時刻を撮るか（⚠ ffmpeg を呼ばない / 検査できる）。

    ```text
    every=None   開始 / 中間 / 終了 の 3 枚
    every=10     上の 3 枚 + 10s, 20s, 30s …（★長い run 用）
    ```
    """
    if duration_s is None or duration_s <= 0:
        return [("video_000.png", 0.0)]
    end = max(0.0, duration_s - END_MARGIN)
    out = [("video_000.png", 0.0), ("video_mid.png", duration_s / 2.0),
           ("video_end.png", end)]
    if every and every > 0:
        t = every
        while t < end:
            out.append(("video_%03ds.png" % int(t), float(t)))
            t += every
    return out


def frames(path, out_dir, *, duration_s=None, every: float | None = None) -> dict:
    """★★ 動画から静止画を抜く。⚠ `{"made": [...], "failed": [...], "why": ...}`。

    ⚠ 1 枚ごとに ffmpeg を呼びます（★数枚なら十分速い / -ss を入力の前に置く）。
    """
    path, out_dir = pathlib.Path(path), pathlib.Path(out_dir)
    out = {"made": [], "failed": []}
    exe = ff.find("ffmpeg")
    if exe is None:
        out["why"] = "⚠ ffmpeg が見つかりません"
        return out
    if not path.exists():
        out["why"] = "⚠ 動画がありません"
        return out
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, at in sample_times(duration_s, every=every):
        dest = out_dir / name
        cmd = [str(exe), "-v", "error", "-y", "-ss", "%.3f" % at,
               "-i", str(path), "-frames:v", "1", str(dest)]
        try:
            done = subprocess.run(cmd, capture_output=True, timeout=FRAME_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as err:
            out["failed"].append({"name": name, "at": at, "why": str(err)})
            continue
        if done.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            out["made"].append({"name": name, "at": at,
                                "size_bytes": dest.stat().st_size})
        else:
            out["failed"].append({
                "name": name, "at": at,
                "why": (done.stderr or b"").decode("utf-8", "replace")[:200]})
    return out
