"""遊んだ記録の消去（2026-08-08 / ★実際に2つ踏んだので検査にする）。

手順書: `docs/procedure-fresh-start.md`

## ⚠⚠ 2026-08-08 に踏んだ2つ

  1. `work/generated/` を消したら**起動できなくなった**
     ★`memory_map.lua` / `config.lua` は FCEUX 側の Lua が必ず読む。
     ⚠ 「作り直せる」と「作り直した」は別。

  2. `encountered.txt` / `caution.txt` が**消えていなかった**
     ★DB の `EncounteredMonster` は消していたので、⚠ **食い違って**いた。
     残ると初遭遇の安全機構が**一度も働かない**。

★どちらも文書に書くだけでは再発します。**ここで固定**します。
"""

from __future__ import annotations

import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROCEDURE = PROJECT_ROOT / "docs" / "procedure-fresh-start.md"
ARCHIVE = PROJECT_ROOT / "tests" / "data" / "battle_cases" / "archive"

from retroux.tools import playdata  # noqa: E402


# --- ⚠⚠ 1. 遭遇済みの控えを消し忘れない --------------------------------


def test_遭遇済みの控えを消す():
    """⚠⚠ **DB と食い違わせない。**

    ★DB の `EncounteredMonster` を空にするなら、
      ⚠ Lua 側の控え（`encountered.txt`）も消さないと、
      **まっさらから始めたのに全部「遭遇済み」**になります。
    """
    assert "encountered.txt" in playdata.PLAY_FILES, (
        "⚠⚠ 遭遇済みの控えが消す対象に入っていません"
        "（★初遭遇の安全機構が一度も働きません）")
    assert "caution.txt" in playdata.PLAY_FILES, (
        "⚠ 警戒リストが残ると、まだ会っていない敵に効きます")


def test_DBと控えの両方を消している():
    """★片方だけ消すと食い違います（⚠ それが 2026-08-08 に起きたこと）。"""
    assert "EncounteredMonster" in playdata.PLAY_TABLES
    assert "encountered.txt" in playdata.PLAY_FILES


# --- ⚠⚠ 2. 消したままにしない ------------------------------------------


def test_起動に要るものを作り直す():
    """⚠⚠ **`work/generated/` が無いと起動できません。**

    ★`clear` の最後で作り直すこと。
    ⚠ 「作り直せる」だけでは足りません（★作り直すまで動きません）。
    """
    source = (PROJECT_ROOT / "retroux" / "tools" / "playdata.py"
              ).read_bytes().decode("utf-8")
    assert "def _regenerate" in source, (
        "⚠⚠ 作り直す仕掛けがありません（★消したら起動できなくなります）")
    # ★`clear` から呼んでいること（⚠ 作っただけにしない）
    at = source.index("def cmd_clear")
    body = source[at:source.index("\ndef ", at + 10)]
    assert "_regenerate()" in body, (
        "⚠⚠ `clear` が作り直しを呼んでいません")


def test_作り直せなかったら黙らない():
    """⚠ 黙ると、★次の起動で理由の分からない失敗になります。"""
    source = (PROJECT_ROOT / "retroux" / "tools" / "playdata.py"
              ).read_bytes().decode("utf-8")
    at = source.index("def _regenerate")
    body = source[at:at + 2500]
    assert "作り直せませんでした" in body
    assert "generate_lua" in body, "★手で直す方法を書いてあること"


# --- ⚠ 触ってはいけないもの（★既存の守り）------------------------------


def test_ROMとセーブステートを消さない():
    """⚠⚠ **取り返しがつきません。**"""
    for name in ("rom", "savestate-backup", "savestate_backup"):
        assert name in playdata.NEVER_TOUCH, name
    # ★消す対象に紛れていないこと
    for name in playdata.NEVER_TOUCH:
        assert name not in playdata.PLAY_FILES
        assert name not in playdata.DERIVED_DIRS


def test_退避先を消さない():
    """⚠ 退避先を消したら、★戻す先が無くなります。"""
    assert "playdata-archive" in playdata.NEVER_TOUCH


# --- ★ 手順書 -----------------------------------------------------------


def test_手順書がある():
    assert PROCEDURE.exists(), (
        "⚠ 手順書がありません（★消す順番を間違えると取り返せません）")


def test_手順書に順番が書いてある():
    """★★ **書き出す -> Git へ移す -> 退避 -> 消す** の順。

    ⚠ 1つでも飛ばすと、二度と取れないものが消えます。
    """
    text = PROCEDURE.read_bytes().decode("utf-8")
    order = ["battle_cases export", "tests/data/battle_cases/archive",
             "playdata backup", "playdata clear"]
    at = -1
    for step in order:
        got = text.find(step)
        assert got > at, f"⚠ 手順の順番が違います: {step}"
        at = got


def test_手順書に踏んだ落とし穴を書いてある():
    """⚠ 同じ失敗を繰り返さないため。"""
    text = PROCEDURE.read_bytes().decode("utf-8")
    assert "generated" in text and "起動できません" in text
    assert "encountered.txt" in text


# --- ★★ 資産を Git へ移してある（★二度と取れないもの）------------------


def test_エンディングまでのケースを残してある():
    """★★★ **エンディングまでの 829 件は、もう二度と作れません。**

    ⚠ `work/` は Git 管理外なので、★ここへ移していないと失われます。
    """
    if not ARCHIVE.exists():
        pytest.skip("⚠ まだ書き出していません")
    files = sorted(ARCHIVE.glob("*.jsonl"))
    assert files, f"⚠ 保存したケースがありません: {ARCHIVE}"
    total = 0
    for path in files:
        n = sum(1 for line in path.open(encoding="utf-8") if line.strip())
        assert n > 0, f"⚠ 空です: {path.name}"
        total += n
    assert total >= 500, f"⚠ {total} 件しかありません"


def test_保存したケースが読める():
    """⚠ 壊れた JSONL を置いても気づけません。"""
    import json

    if not ARCHIVE.exists():
        pytest.skip("⚠ まだ書き出していません")
    for path in sorted(ARCHIVE.glob("*.jsonl")):
        for i, line in enumerate(path.open(encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except Exception as exc:                   # noqa: BLE001
                pytest.fail(f"⚠ {path.name}:{i} が読めません: {exc}")
            # ★★★ 原則1: 実戦の行動を正解にしていないこと
            assert case.get("expected") is None, (
                f"⚠⚠ {path.name}:{i} に期待値が入っています"
                "（★実戦の行動を正解にしてはいけません）")
