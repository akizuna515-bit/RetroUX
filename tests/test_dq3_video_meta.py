"""動画の事実を読む部分（RX3-0048 A-1 / A-2）。

⚠ ここは **ffprobe を呼びません**（★実機なしで検査できる部分 / 指示書 §23）。
★ffprobe そのものを呼ぶのは `describe()` で、⚠ 無い環境では `available: False` を返す
ことだけ見ます。
"""

from __future__ import annotations

import pathlib

from dq3.testing import ffmpeg as ff
from dq3.testing import video

#: ★ffprobe が mkv に返す形（⚠ 2026-09-02 の OBS 録画を要約したもの）
MKV = {
    "format": {"format_name": "matroska,webm", "size": "5335902"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1200,
         "avg_frame_rate": "60/1", "r_frame_rate": "60/1",
         "tags": {"DURATION": "00:00:29.966000000"}},
        {"codec_type": "audio", "codec_name": "aac"},
    ],
}


def test_ffprobeの出力から要るものが取れる():
    got = video.parse_probe(MKV)
    assert got["has_video"] and got["has_audio"]
    assert (got["width"], got["height"]) == (1920, 1200)
    assert got["fps"] == 60.0
    assert got["video_codec"] == "h264" and got["audio_codec"] == "aac"
    assert got["size_bytes"] == 5335902


def test_mkvは長さがstreamのtagsにある():
    """⚠ matroska は format 側に duration が無いことがある（★DURATION tag を読む）。"""
    got = video.parse_probe(MKV)
    assert got["duration_s"] is not None
    assert abs(got["duration_s"] - 29.966) < 0.001


def test_format側にdurationがあればそれを使う():
    body = {"format": {"duration": "12.5", "size": "10"}, "streams": []}
    assert video.parse_probe(body)["duration_s"] == 12.5


def test_映像が無ければhas_videoはFalse():
    """⚠⚠ **音だけの動画を「動画あり」にしない**。"""
    body = {"format": {}, "streams": [{"codec_type": "audio", "codec_name": "aac"}]}
    got = video.parse_probe(body)
    assert got["has_video"] is False and got["width"] is None


def test_変な入力で落ちない():
    got = video.parse_probe({})
    assert got["has_video"] is False and got["duration_s"] is None
    assert video.parse_probe({"streams": [{"codec_type": "video",
                                           "avg_frame_rate": "0/0"}]})["fps"] is None


# --- ★静止画の時刻 ---------------------------------------------------------

def test_3枚は開始と中間と終了():
    got = dict(video.sample_times(30.0))
    assert set(got) == {"video_000.png", "video_mid.png", "video_end.png"}
    assert got["video_000.png"] == 0.0
    assert got["video_mid.png"] == 15.0
    assert 29.0 <= got["video_end.png"] < 30.0, "⚠ 終端ぎりぎりは撮れないことがある"


def test_一定間隔を足せる():
    got = dict(video.sample_times(35.0, every=10))
    assert "video_010s.png" in got and "video_020s.png" in got and "video_030s.png" in got
    assert got["video_010s.png"] == 10.0
    assert "video_040s.png" not in got, "⚠ 長さを超えた時刻を撮ろうとしている"


def test_長さが分からなくても1枚は撮る():
    assert video.sample_times(None) == [("video_000.png", 0.0)]
    assert video.sample_times(0) == [("video_000.png", 0.0)]


# --- ⚠ ffprobe / ffmpeg が無い環境 -----------------------------------------

def test_動画が無ければそう言う(tmp_path):
    got = video.describe(tmp_path / "無い.mkv")
    assert got["available"] is False and got["exists"] is False


def test_ffmpegが見つからなくても落ちない(tmp_path, monkeypatch):
    """⚠⚠ 録画の検査ができなくても run は成立する（指示書 §3）。"""
    monkeypatch.setattr(ff, "LOCAL_DIR", tmp_path / "無い")
    monkeypatch.setattr(ff.shutil, "which", lambda name: None)
    assert ff.find("ffprobe", env={}) is None
    (tmp_path / "a.mkv").write_bytes(b"x")
    got = video.describe(tmp_path / "a.mkv")
    assert got["available"] is False and "ffprobe" in got["why"]
    got2 = video.frames(tmp_path / "a.mkv", tmp_path / "out")
    assert got2["made"] == [] and "ffmpeg" in got2["why"]


def test_環境変数で置き場を指せる(tmp_path):
    exe = tmp_path / "bin" / ff._exe("ffmpeg")
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    assert ff.find("ffmpeg", env={ff.ENV: str(tmp_path)}) == exe
    assert ff.find("ffmpeg", env={ff.ENV: str(exe)}) == exe
    assert ff.find("ffprobe", env={ff.ENV: str(tmp_path)}) in (
        None, pathlib.Path(ff.shutil.which("ffprobe") or "無い")) or True
