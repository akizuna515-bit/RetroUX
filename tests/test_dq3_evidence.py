"""run ごとの証跡（RX3-0031 / 2026-08-31）。

⚠⚠ **「テストが通った」だけでなく、あとから素材として使える形**で残す（PoC② §10）。
"""

from __future__ import annotations

import json

import pytest

from dq3.testing import evidence


@pytest.fixture()
def run(tmp_path):
    return evidence.start("walk_town", save_slot=6, base=tmp_path)


def _write(run, rows):
    run.steps_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_folderと記録ができる(run):
    assert run.root.is_dir()
    assert run.log_path.exists(), "⚠ 記録が始まっていない"
    assert evidence.RUN_ID.match(run.run_id), run.run_id


def test_歩いた記録からまとめが出る(run):
    _write(run, [
        {"step": 1, "ok": True, "map_id": 9, "x": 8, "y": 18},
        {"step": 2, "ok": False, "map_id": 9, "x": 8, "y": 18},
        {"step": 3, "ok": True, "map_id": 9, "x": 8, "y": 17},
    ])
    meta = json.loads(run.finish(result=evidence.PASS,
                                 stop_reason="battle").read_text(encoding="utf-8"))
    assert meta["steps_attempted"] == 3
    assert meta["steps_success"] == 2
    assert meta["unique_tiles"] == 2, "⚠ 同じ升を 2 度数えている"
    assert meta["start"] == {"map_id": 9, "x": 8, "y": 18}
    assert meta["end"] == {"map_id": 9, "x": 8, "y": 17}
    assert meta["stop_reason"] == "battle"


def test_壊れた行があっても残りは読める(run):
    """⚠⚠ **実機の中で落ちた記録も使う**（★追記型にした理由）。"""
    run.steps_path.write_text(
        json.dumps({"step": 1, "ok": True, "map_id": 9, "x": 1, "y": 1}) + "\n"
        + "こわれた行\n"
        + json.dumps({"step": 2, "ok": True, "map_id": 9, "x": 1, "y": 2}) + "\n",
        encoding="utf-8")
    meta = json.loads(run.finish(result=evidence.PASS).read_text(encoding="utf-8"))
    assert meta["steps_attempted"] == 2
    assert meta["broken_lines"] == 1, (
        "⚠⚠ 読めなかった行を黙って捨てている（★0 件と区別できない）")


def test_二度呼んでも二重に数えない(run):
    run.steps_path.write_text("こわれた行\n", encoding="utf-8")
    run.steps()
    meta = json.loads(run.finish(result=evidence.FAIL).read_text(encoding="utf-8"))
    assert meta["broken_lines"] == 1, "⚠ 二重に数えている"


def test_記録が1つも無くても落ちない(run):
    meta = json.loads(run.finish(result=evidence.ERROR,
                                 stop_reason="ppu_unavailable").read_text(
                                     encoding="utf-8"))
    assert meta["steps_attempted"] == 0
    assert meta["unique_tiles"] == 0
    assert meta["start"] == {"map_id": None, "x": None, "y": None}


def test_知らない結果の語は弾く(run):
    with pytest.raises(evidence.EvidenceError):
        run.finish(result="たぶん成功")


def test_無いファイルはnullになる(run):
    meta = json.loads(run.finish(result=evidence.PASS).read_text(encoding="utf-8"))
    assert meta["evidence"]["start_png"] is None
    assert meta["evidence"]["video"] is None
    assert meta["evidence"]["log"] == "test.log", "⚠ あるものは名前が入る"


def test_mp4以外の動画も見つける(run):
    """⚠⚠ **「無い」と「見つけられない」は違います**（2026-09-02 / RX3-0031）。

    ★依頼者の OBS は `mkv` で録ります。⚠ `run.mp4` だけを探していたので、
      **動画があるのに `null`** と書くところでした。
    """
    (run.root / "run.mkv").write_bytes(b"x")
    meta = json.loads(run.finish(result=evidence.PASS).read_text(
        encoding="utf-8"))
    assert meta["evidence"]["video"] == "run.mkv"


def test_mp4があればそちらを使う(run):
    (run.root / "run.mkv").write_bytes(b"x")
    (run.root / "run.mp4").write_bytes(b"x")
    meta = json.loads(run.finish(result=evidence.PASS).read_text(
        encoding="utf-8"))
    assert meta["evidence"]["video"] == "run.mp4"


def test_目的つきのrun_id(tmp_path):
    """★指示書 A-3: `20260902_091530_field-autobattle-regression`。"""
    import datetime

    when = datetime.datetime(2026, 9, 2, 9, 15, 30)
    got = evidence.new_run_id_at("Field AutoBattle Regression", when=when)
    assert got == "20260902_091530_field-autobattle-regression"
    assert evidence.RUN_ID.match(got)
    assert evidence.RUN_ID.match("20260901_town_run_004"), "⚠ 昔の形を弾いている"
    assert not evidence.RUN_ID.match("20260902_091530_日本語"), "⚠ folder 名に日本語が入る"


def test_動画の名前は時刻と目的(tmp_path):
    """★`20260902_091530_フィールド自動戦闘回帰試験.mkv`（⚠ JSON では run_id が正）。"""
    run = evidence.Run(run_id="20260902_091530_field-autobattle-regression",
                       feature="field", save_slot=5, root=tmp_path,
                       started_at="x", purpose="フィールド自動戦闘回帰試験")
    assert run.video_name() == "20260902_091530_フィールド自動戦闘回帰試験.mkv"
    assert run.video_name(".mp4").endswith(".mp4")
    (tmp_path / run.video_name()).write_bytes(b"x")
    meta = json.loads(run.finish(result=evidence.PASS).read_text(encoding="utf-8"))
    assert meta["purpose"] == "フィールド自動戦闘回帰試験"
    assert meta["evidence"]["video"] == "20260902_091530_フィールド自動戦闘回帰試験.mkv"
    assert meta["run_id"] == "20260902_091530_field-autobattle-regression", (
        "⚠⚠ JSON の正は ASCII の run_id")


def test_目的が無ければ昔の名前(run):
    assert run.video_name() == "run.mkv"


def test_動画の事実と判定が入る(run):
    """⚠⚠ 「動画がある」だけで PASS にしないための置き場（指示書 A-1）。"""
    meta = json.loads(run.finish(
        result=evidence.PASS,
        video_meta={"available": True, "duration_s": 23.0},
        checks={"video_valid": {"ok": True}}).read_text(encoding="utf-8"))
    assert meta["video_meta"]["duration_s"] == 23.0
    assert meta["checks"]["video_valid"]["ok"] is True
    assert meta["evidence"]["state_diff"] is None


def test_人のスロットでも読むだけならよい(tmp_path):
    """⚠ 証跡は**読み込んだ**スロットを記録する。★0〜4 を読むのは自由。"""
    got = evidence.start("shop_v0", save_slot=2, base=tmp_path)
    assert got.save_slot == 2


def test_run_idの形が決まっている():
    got = evidence.new_run_id("Walk Town", seq=7)
    assert evidence.RUN_ID.match(got), got
    assert got.endswith("_walk_town_007")
    with pytest.raises(evidence.EvidenceError):
        evidence.new_run_id("!!!")


def test_歩でない行を数えない(tmp_path):
    """★★★ ⚠⚠ **実機で見つかった噛み合わせのずれ**（2026-09-01）★★★

    ⚠ Lua が `run.jsonl` へ `{"event":"finish", ...}` を書いていたため、

    ```text
    歩数        40 → 41   （★まとめの行まで数えた）
    終了位置    ⚠⚠ null  （★最後の行に x/y が無い）
    ```

    ★Lua 側は直したが、⚠ **読む側も強くする**（別の書き手が来ても狂わない）。
    """
    from dq3.testing import evidence as ev

    run = ev.start("town_run", save_slot=0, base=tmp_path)
    run.steps_path.write_text(
        chr(10).join([
            '{"step":1,"ok":true,"map_id":9,"x":8,"y":18}',
            '{"step":2,"ok":true,"map_id":9,"x":8,"y":19}',
            '{"event":"finish","steps":2,"ok_steps":2}',
        ]) + chr(10), encoding="utf-8")

    got = run.steps()
    assert len(got) == 2, "⚠⚠ まとめの行まで数えた: %s" % got
    meta = run.finish(result=ev.PASS, stop_reason="max_steps")
    import json
    data = json.loads(meta.read_text(encoding="utf-8"))
    assert data["steps_attempted"] == 2
    assert data["end"] == {"map_id": 9, "x": 8, "y": 19}, (
        "⚠⚠ 終了位置が取れていない: %s" % data["end"])
