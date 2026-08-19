"""画面の軽量化・差分更新（2026-08-07 / 軽量化指示書）。

指示書: `input/RetroUX_UI監視処理_軽量化差分更新_実装指示_20260807.md`

## ⚠⚠ この検査が守っているのは「速さ」ではなく **「嘘をつかないこと」**

  ★差分更新は、間違えると**変わったのに描き直さない**という形で壊れます。
  ⚠ 速くなったかより、**取りこぼしが無いか**を先に見ます
    （`docs/design/handoff-20260807.md` §5 の12件は全部この形でした）。

## ★★★ 依頼者の報告「高速化ONOFFボタンを押しても利かない時がある」

  ⚠ 実測して分かった正体は **表示の往復**でした（§7.3 の検査を参照）。
"""

from __future__ import annotations

import os
import pathlib
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.bridge.state_reader import (  # noqa: E402
    Enemy,
    GameState,
    Member,
)
from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.panels import (  # noqa: E402
    AiPanel,
    PartyPanel,
    snapshot,
)
from retroux.ui.view_model import ViewModel  # noqa: E402

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        created = QApplication([])
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")
    yield created


@pytest.fixture
def window(app, tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    vm = ViewModel(recorder, db, "HASH", {1: "スライム"})
    vm._mission_path = tmp_path / "mission.yaml"
    win = MainWindow(vm, interval_ms=10 ** 6, log_path=tmp_path / "r.log")
    yield win
    win.close()


# --- ★ 写し取り（§5.2）--------------------------------------------------


def test_写し取りは中身が同じなら等しい():
    assert snapshot({"a": [1, 2], "b": None}) == snapshot({"b": None,
                                                           "a": [1, 2]})


def test_写し取りは中身が違えば違う():
    assert snapshot({"a": [1, 2]}) != snapshot({"a": [1, 3]})


def test_知らない型は毎回違う扱いにしない():
    """⚠ 同じものは同じと言えること（★でなければ差分が一度も効きません）。"""
    class Thing:
        pass

    t = Thing()
    assert snapshot(t) == snapshot(t)


def test_写し取りが入れ子まで届く():
    """⚠⚠ **浅いと、中の HP が変わっても気づけません。**"""
    a = {"party": [{"hp": 10}]}
    b = {"party": [{"hp": 9}]}
    assert snapshot(a) != snapshot(b)


# --- ★★★ 取りこぼさないこと（⚠ これが本題）-----------------------------


def _member(hp=10):
    """⚠ 本物の `Member` を使う（★偽物だと項目の抜けに気づけません）。"""
    return Member(name="lorasia", index=0, hp=hp, max_hp=20, mp=3, max_mp=8,
                  level=5, exp=100, next_level=6, exp_to_next=50,
                  attack=12, defense=11, strength=10, agility=9)


def test_パーティは変わらなければ描き直さない(app):
    panel = PartyPanel()
    members = [_member()]
    panel.update_party(members)
    panel._table.setRowCount(99)              # ★描き直したら 1 に戻るはず
    panel.update_party(members)
    assert panel._table.rowCount() == 99, "⚠ 変わっていないのに描き直しています"


def test_パーティはHPが変われば描き直す(app):
    """★★★ **ここを落とすと画面が嘘をつきます**（⚠ 速くなっても意味が無い）。"""
    panel = PartyPanel()
    panel.update_party([_member(hp=10)])
    panel._table.setRowCount(99)
    panel.update_party([_member(hp=9)])
    assert panel._table.rowCount() == 1, "⚠⚠ HP が変わったのに描き直していません"


def test_パーティは誰の番かが変われば描き直す(app):
    """⚠ `actor` は表の中の ◀ 印になります。★鍵に入れ忘れやすい。"""
    panel = PartyPanel()
    members = [_member()]
    panel.update_party(members, actor=None)
    panel._table.setRowCount(99)
    panel.update_party(members, actor="lorasia")
    assert panel._table.rowCount() == 1


# --- ⚠ 敵の描き直しの検査は削除しました（2026-08-11 / 依頼者）------------
#
#   > 敵情報は、もはや用済みの資料だから不要だね。このロジック自体いらない
#
#   ★`EnemyPanel` ごと消えたので、その「変わらなければ触らない」の検査も
#     一緒に消しました。⚠ 同じ約束はパーティ状態のほうで見ています。

def _ai_state(action="たたかう", actor=None):
    return GameState(
        ai_decisions=[{"index": 0, "name": "lorasia",
                       "action": action, "reason": "理由"}],
        actor=actor, force_auto=False, manual_latched=False,
        auto_input=True, danger_reason=None)


def test_AI判断は変わらなければ書き直さない(app):
    panel = AiPanel()
    state = _ai_state()
    panel.update_state(state)
    panel._member_rows[0]["action"].setText("印")
    panel.update_state(_ai_state())
    assert panel._member_rows[0]["action"].text() == "印"


def test_AI判断は中身が変われば書き直す(app):
    panel = AiPanel()
    panel.update_state(_ai_state("たたかう"))
    panel._member_rows[0]["action"].setText("印")
    panel.update_state(_ai_state("ホイミ"))
    assert panel._member_rows[0]["action"].text() == "ホイミ"


def test_AI判断の鍵に毎回変わる値を入れていない(app):
    """⚠⚠⚠ **`frame` や `time` を鍵に入れると一度も止まりません。**

    ★「差分にしたつもり」で何も変わっていない、という壊れ方です。
    ⚠ 実際に `state` 全体を写し取りかけました。
    """
    panel = AiPanel()
    a = _ai_state()
    a.frame, a.time = 1, 100
    panel.update_state(a)
    panel._member_rows[0]["action"].setText("印")
    b = _ai_state()
    b.frame, b.time = 2, 200                  # ★毎ポーリング変わる値だけ違う
    panel.update_state(b)
    assert panel._member_rows[0]["action"].text() == "印", (
        "⚠⚠ 毎回変わる値が鍵に入っています（★差分が効きません）")


def test_AI判断は誰の番かが変われば書き直す(app):
    panel = AiPanel()
    panel.update_state(_ai_state(actor=None))
    panel._member_rows[0]["who"].setText("印")
    panel.update_state(_ai_state(actor="lorasia"))
    assert "印" not in panel._member_rows[0]["who"].text()


# --- ★ 地図（§5.7）------------------------------------------------------


def test_地図は動かなければ描き直さない(window):
    w = window._ensure_map_window()
    calls = []
    w._draw = lambda here=None: calls.append(here)
    w.follow(1, 0x8000, 10, 20)
    w.follow(1, 0x8000, 10, 20)
    w.follow(1, 0x8000, 10, 20)
    assert len(calls) == 1, f"⚠ 立ち止まっているのに {len(calls)} 回描いています"


def test_地図は動けば描き直す(window):
    w = window._ensure_map_window()
    calls = []
    w._draw = lambda here=None: calls.append(here)
    w.follow(1, 0x8000, 10, 20)
    w.follow(1, 0x8000, 11, 20)
    assert len(calls) == 2


def test_追うのを切ったらすぐ印が消える(window):
    """⚠⚠⚠ **ここを踏むところでした。**

    `いまの場所を追う` の枠には `stateChanged` がつながっておらず、
    ★次に `follow()` が呼ばれたときに反応する作りです。
    ⚠ 座標だけを鍵にすると、**枠を切っても動くまで印が消えません**。
    """
    w = window._ensure_map_window()
    w.follow(1, 0x8000, 10, 20)
    calls = []
    w._draw = lambda here=None: calls.append(here)
    w._follow.setChecked(False)
    w.follow(1, 0x8000, 10, 20)               # ★座標は同じ
    assert calls == [None], "⚠⚠ 追うのを切ったのに印が残ります"


def test_一覧で選び直したら次の追従で戻る(window):
    """⚠ 人が別のマップを選んだら、鍵を落として**元どおり追い直す**。

    ★これが無いと、選んだあと動くまで現在地へ戻りません（従来は 0.2 秒）。
    """
    w = window._ensure_map_window()
    w.follow(1, 0x8000, 10, 20)
    calls = []
    w._draw = lambda here=None: calls.append(here)
    w._redraw()                               # ★人が一覧を触った相当
    w.follow(1, 0x8000, 10, 20)
    assert len(calls) == 2, "⚠ 選び直したあと現在地へ戻りません"


# --- ★ 低頻度の仕事（§6）-----------------------------------------------


def test_低頻度の仕事は初回に必ず走る(window):
    # ⚠ 窓を組む時点で一度 refresh() が走っています（★印を落としてから）
    window._slow_job_at.clear()
    for name in window.SLOW_JOBS:
        assert window._due(name) is True, f"⚠ {name} が初回に走りません"


def test_低頻度の仕事はすぐには繰り返さない(window):
    window._slow_job_at.clear()
    for name in window.SLOW_JOBS:
        window._due(name)
        assert window._due(name) is False, f"⚠ {name} が毎回走っています"


def test_低頻度の仕事は時間が経てば走る(window):
    name = "SystemLog更新"
    window._due(name)
    window._slow_job_at[name] -= window.SLOW_JOBS[name] + 0.01
    assert window._due(name) is True


def test_間隔が期限より十分短い():
    """⚠⚠ **間隔を期限に近づけない**。★1回取りこぼすと「止まった」と出ます。"""
    from retroux.core import backup_status, single_instance

    assert (MainWindow.SLOW_JOBS["心拍"]
            <= single_instance.HEARTBEAT_STALE_SECONDS / 6)
    assert (MainWindow.SLOW_JOBS["保護の状態"]
            <= backup_status.STALE_SECONDS / 6)


# --- ★★★ §7.3 頼んだ値と実機の値を分ける -------------------------------


def test_押した直後に実機の古い値で押し戻さない(window):
    """★★★ **依頼者の報告「高速化ONOFFボタンを押しても利かない時がある」**。

    ⚠⚠ 押した 0.2 秒後、Lua はまだ古い値を書いています。
      ★そこで押し戻すと、利用者には「押しても効かない」と見えます。
    """
    window._on_turbo_toggled(True)
    window._turbo_button.setChecked(True)
    window._sync_turbo_button(False)          # ★Lua はまだ OFF のまま
    assert window._turbo_button.isChecked() is True, (
        "⚠⚠⚠ 押した直後に実機の古い値で戻しています（★これが「効かない」の正体）")


def test_実機が追いついたら実機が正になる(window):
    window._on_auto_toggled(True)
    window._auto_button.setChecked(True)
    window._sync_auto_button(True)            # ★届いた
    assert "AUTO" not in window._pending_toggle
    window._sync_auto_button(False)           # ★このあとキー操作で切られた
    assert window._auto_button.isChecked() is False, (
        "⚠ 届いたあとも希望を握り続けています（★キー操作が効かなくなります）")


def test_届かないまま居座らない(window):
    """⚠⚠ **返事が来ないのに希望を出し続けるのは、逆向きの嘘です。**"""
    window._on_turbo_toggled(True)
    window._turbo_button.setChecked(True)
    window._pending_toggle["高速化"] = (
        True, time.monotonic() - MainWindow.TOGGLE_CONFIRM_SECONDS - 1)
    window._sync_turbo_button(False)
    assert window._turbo_button.isChecked() is False


def test_戻したことを黙っていない(window):
    """★「黙って捨てない」（⚠ 戻った理由が分からないのが一番困る）。"""
    window._on_turbo_toggled(True)
    window._turbo_button.setChecked(True)
    window._pending_toggle["高速化"] = (
        True, time.monotonic() - MainWindow.TOGGLE_CONFIRM_SECONDS - 1)
    window._sync_turbo_button(False)
    assert "届きません" in window._align_status.text()


def test_希望を覚えるのは人が押したときだけ(window):
    """⚠ `_sync_toggle` の書き戻しで覚えると、実機の値を希望と取り違えます。"""
    window._pending_toggle.clear()
    window._sync_turbo_button(True)
    assert window._pending_toggle == {}, (
        "⚠⚠ 実機に合わせただけで「人が頼んだ」ことにしています")


# --- ★ 戦術の表示（§7.2）-----------------------------------------------


def test_作戦を選び直したら戦術の行がその場で変わる(window):
    """⚠ 定期更新は 1 秒に1回になりました。★人が触った所は待たせません。"""
    window._tactics_label.setText("印")
    window.reload_tactics_picker()
    assert window._tactics_label.text() != "印"


# --- ★ Lua 側（§4）-----------------------------------------------------


def test_マップ採取が動いたときだけになっている():
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "function Bridge:_map_sample" in source
    # ⚠ `_write_state` が**使っている**こと（★作っただけでは意味がない）
    at = source.index("function Bridge:_write_state")
    body = source[at:at + 12000]
    assert "self:_map_sample(" in body, "⚠⚠ 作っただけで呼んでいません"
    assert "self:map_seen_colors(radius)" not in body, (
        "⚠ 書き出しから直に採っています（★門を素通りします）")


def test_採取の設定が原本にある():
    """⚠ 検査に**生成物**を使わない（★引き継ぎ §5 の作法10）。"""
    body = CONFIG.read_bytes().decode("utf-8")
    assert "on_move_only: true" in body
    assert "retry_limit:" in body


def test_色を採るのをやめていない():
    """⚠⚠ **指示書 §4.3 は既定 OFF を求めていますが、ON のままです。**

    ★実測（`work/retroux.sqlite3` 55,334 マス）で 16×16 の絵は 24%
      （世界地図は 14%）しか引けていません。絵が無いマスは**色で塗って**
      いるので、色を採らないと⚠ **世界地図で陸と海が区別できなくなります**
      （★指示書 §4.5「通常プレイでマップ記録が欠落しない」に反する）。

    ⚠ 重さのほうは `on_move_only` で解いてあります。
    ★絵の網羅率が上がったら false にしてください（そのとき**この検査も直す**）。
    """
    body = CONFIG.read_bytes().decode("utf-8")
    assert "legacy_colors: true" in body, (
        "⚠ 色を採らなくしました。★世界地図の見え方を実機で確かめてください")


# --- ★ 押した直後に見出しの色も変わる（2026-08-08 / 依頼者の指摘）--------
#
#     > AUTOと高速化ボタンが、エミュで動作したら始めて色が変わる。
#     > 知らない人は反応してないのかな？と思う


def test_押した直後に見出しが反映待ちになる(window):
    """★★ ボタンの文字は即変わるが、⚠ 見出しの色は state.json 由来だった。"""
    window._pending_toggle.clear()
    window._remember_request("AUTO", False)
    from retroux.ui import view_model as vm

    badge = window._badge_with_request(vm.Badge("ON", vm.TONE_OK), "AUTO")
    assert "反映待ち" in badge.text
    assert badge.text.startswith("OFF")
    assert badge.tone == vm.TONE_CAUTION


def test_速度の欄には速度の言葉で出す(window):
    """⚠ 「速度」の欄に「ON」と出しても読めない。"""
    window._pending_toggle.clear()
    window._remember_request("高速化", True)
    from retroux.ui import view_model as vm

    badge = window._badge_with_request(vm.Badge("等速", vm.TONE_MUTED), "高速化")
    assert badge.text == "Turbo へ（反映待ち）"


def test_届いていれば普段どおりの表示に戻る(window):
    """⚠⚠ **確かめていないことを確かめたように書かない**の裏返し。

    ★届いたら「反映待ち」を消さないと、今度は**逆の嘘**になります。
    """
    window._pending_toggle.clear()
    from retroux.ui import view_model as vm

    original = vm.Badge("ON", vm.TONE_OK)
    assert window._badge_with_request(original, "AUTO") is original
