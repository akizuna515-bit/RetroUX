"""エミュレータへの指示の組み立て（2026-08-01 のリファクタ指示書 §5.2）。

★★ **画面は JSON の形を知らない。** ★★
  画面は「AUTO を入れて」と言うだけ。`request_id` の採番も、
  キー名も、原子的な書き込みも、ここが引き受ける。

⚠ 検査するのは**書かれたファイルの中身**（実装の文字列ではない）。
  指示書 §10.3「入力 → 公開インターフェース → 出力・状態変化」。
"""

from __future__ import annotations

import json

import pytest

from retroux.application.command_service import (CommandService,
                                                 next_request_id)


@pytest.fixture
def service(tmp_path):
    return CommandService(command_path=tmp_path / "command.json")


def _read(service) -> dict:
    return json.loads(service.command_path.read_text(encoding="utf-8"))


# --- 状態の指示 -------------------------------------------------------

def test_setting_auto_writes_only_that_axis(service):
    """★★ AUTO と高速化は独立した2軸（2026-07-31 の指示書 §2.1）★★"""
    assert service.set_turbo(True) is None
    assert service.set_auto(False) is None

    body = _read(service)
    assert body["auto_enabled"] is False
    # ⚠ 高速化を**巻き添えで消さない**（書かなかった項目は残る）
    assert body["turbo_enabled"] is True


def test_a_state_change_needs_no_request_id(service):
    """★同じ値が続いても害がないので、通し番号は要らない。"""
    service.set_auto(True)
    assert "request_id" not in _read(service)


# --- 一度きりの指示 ---------------------------------------------------

def test_a_one_shot_request_gets_a_request_id(service):
    """⚠⚠ `command.json` は消えない。通し番号が無いと、Lua が巡回のたびに
    **同じ操作を何度も実行する**。
    """
    assert service.save_state(3) is None
    body = _read(service)
    assert body["action"] == "save_state"
    assert body["save_slot"] == 3
    assert isinstance(body["request_id"], int)


def test_two_requests_in_the_same_second_get_different_ids():
    """★★ ここが時刻だけでは足りない理由。 ★★

    ⚠ 秒で採ると、**同じ秒に2回**押したとき同じ値になり、
      2回目が「もう処理した」と無視される。
    """
    ids = {next_request_id() for _ in range(50)}
    assert len(ids) == 50, "同じ通し番号が出た"


def test_request_ids_increase(service):
    """★あとから押したほうが大きい（Lua が「新しい」と判断できる）。"""
    service.save_state(1)
    first = _read(service)["request_id"]
    service.save_state(1)
    second = _read(service)["request_id"]
    assert second > first


# --- 失敗の扱い（指示書 §15.2）----------------------------------------

def test_read_only_refuses_and_says_why(tmp_path):
    """⚠ 黙って無視しない。**理由を返す**（呼ぶ側が画面に出せる）。"""
    service = CommandService(command_path=tmp_path / "command.json",
                             read_only=True)
    problem = service.set_auto(True)
    assert problem is not None and "閲覧専用" in problem
    assert not service.command_path.exists(), "閲覧専用なのに書いた"


def test_a_write_failure_keeps_the_old_state(tmp_path):
    """★★ 書けなかったときは**元の状態のまま**（指示書 §15.2）★★"""
    service = CommandService(command_path=tmp_path / "command.json")
    service.set_auto(True)
    before = service.command_path.read_text(encoding="utf-8")

    # ⚠ 書けない場所を指すようにして、失敗させる。
    #   ★**フォルダ**を指す。無いフォルダは自動で作られるので失敗しない
    #     （実際にそれで「失敗するはず」が成功した）。
    folder = tmp_path / "as-a-folder"
    folder.mkdir()
    service.command_path = folder
    problem = service.set_turbo(False)
    assert problem is not None, "書けないのに成功と言っている"

    service.command_path = tmp_path / "command.json"
    assert service.command_path.read_text(encoding="utf-8") == before, \
        "失敗したのに元のファイルが変わった"


def test_the_encountered_list_is_read_at_write_time(tmp_path):
    """★遭遇中の敵は**書くたびに**取り直す（掴んだまま古くならない）。"""
    seen = [1]
    service = CommandService(command_path=tmp_path / "command.json",
                             encountered=lambda: seen)
    service.set_auto(True)
    assert _read(service)["encountered"] == [1]

    seen.clear()
    seen.extend([7, 8])
    service.set_auto(False)
    assert _read(service)["encountered"] == [7, 8]


def test_the_last_command_is_remembered_for_diagnosis(service):
    """★何を最後に頼んだかを残す（診断で「届いたか」を追える）。"""
    service.save_state(2)
    assert service.last is not None
    assert service.last.action == "save_state"
    assert service.last.payload["save_slot"] == 2
