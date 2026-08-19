"""推論の4段を画面に出す（2026-08-07 / 戦闘AI再設計 Phase 9）。

指示書 §18 Phase 9 の完了条件:

    通常ユーザーは目的とリスク設定だけで利用できる
    上級ユーザーは係数を直接編集できる
    ★AIが選んだ戦術と理由を確認できる

## ★★ 依頼者と決めた「画面で確認する観点」

    1. 目的 -> 戦況 -> 戦術 -> 役割 が1画面で追える
    2. ⚠⚠ 「分からない」と「0」を見分けられる
    3. ★★ 「まだ効かせていない」ことが分かる
    4. ⚠ 僅差かどうかが見える
    5. ★★★ 「全部同じ」になっていないか分かる
    6. ★ 選ばなかった理由が見える

⚠ このうち **3 と 5** が無いと、画面があっても**間違った安心**をする
だけになります。★そこを重点的に見張ります。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bridge.state_reader import GameState, _parse

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
MAIN_WINDOW = PROJECT_ROOT / "retroux" / "ui" / "main_window.py"


class _VM:
    """`ViewModel` の表示部分だけを借りる小さな入れ物。

    ⚠ 画面全体を組み立てると Qt が要ります。★見たいのは文字列だけ。
    """

    def __init__(self, game):
        from retroux.ui.view_model import ViewModel

        self._last_game = game
        self.assessment_label = ViewModel.assessment_label.__get__(self)
        self.roles_label = ViewModel.roles_label.__get__(self)
        self._BALANCE_LABELS = ViewModel._BALANCE_LABELS
        self._LENGTH_LABELS = ViewModel._LENGTH_LABELS


def _vm(**kw) -> _VM:
    return _VM(GameState(**kw))


# --- ★ 観点1: 4段が1画面で追える -------------------------------------

def test_戦況と戦術が同じ行に出る():
    got = _vm(battle_balance="advantage", battle_length="short",
              battle_turns_to_win=1.3, battle_turns_to_lose=4.9,
              battle_plan="省資源", battle_plan_score=5.5,
              battle_plan_margin=1.5).assessment_label()
    assert "優勢" in got and "短期戦" in got, got
    assert "敵撃破 1.3ターン" in got and "味方崩壊 4.9ターン" in got, got
    assert "省資源" in got and "5.5" in got, got


# --- ⚠⚠ 観点2: 「分からない」と「0」を見分けられる -------------------

def test_届いていないときは戦闘中に出ますと書く():
    """★空欄にしない。⚠ 何も出ないと「壊れている」のか分かりません。"""
    assert "—" in _vm().assessment_label()


def test_分からないを0で埋めない():
    """⚠⚠ **`unknown` は値が来ている**（材料が無いと分かった）。

    ★None（そもそも届いていない）とは別物です。
    """
    got = _vm(battle_balance="unknown").assessment_label()
    assert "分からない" in got, got
    # ⚠ 「優勢」などに化けていないこと
    assert "優勢" not in got and "均衡" not in got, got


def test_0ターンを届いていない扱いにしない():
    """★★ **0.0 は「測った結果ゼロ」**。⚠ `or None` で落とすと消えます。"""
    got = _vm(battle_balance="even", battle_turns_to_win=0.0,
              battle_turns_to_lose=3.0).assessment_label()
    assert "敵撃破 0.0ターン" in got, got


def test_片方しか出せなくても出せるほうは出す():
    got = _vm(battle_balance="even", battle_turns_to_win=2.0).assessment_label()
    assert "敵撃破 2.0ターン" in got, got
    assert "味方崩壊 —" in got, got


def test_json側でも0を落とさない():
    """⚠⚠ **`_parse` で `or None` を使うと 0.0 が消えます。**"""
    got = _parse({"battle_turns_to_win": 0, "battle_plan_score": 0,
                  "battle_plan_margin": 0})
    assert got.battle_turns_to_win == 0.0
    assert got.battle_plan_score == 0.0
    assert got.battle_plan_margin == 0.0


def test_json側で空文字はNoneにする():
    """★空欄を画面に出しても何も伝わりません。"""
    assert _parse({"battle_plan": ""}).battle_plan is None


# --- ★★★ 観点3: 「まだ効かせていない」ことが分かる -------------------

def test_判断がまだ従来どおりだと画面に出る():
    """★★★ **これが無いと必ず誤解されます。**

    ⚠ 「省資源と書いてあるのに MP を使っている」に見えるため。
      Phase 1〜9 は判断を変えていません。
    """
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    # ⚠ 2026-08-11: 初見の人向けに言い回しを平易化（依頼者）。意味は同じ:
    #   legacy=「戦況分析は試験中で判断にはまだ使っていない」/ layered=判断中。
    assert "判断にはまだ使っていません" in source, (
        "⚠⚠ legacy のとき『まだ効かせていない』が画面に出ません")
    assert "AIが戦況を見て判断しています" in source, (
        "⚠ layered に切り替えたとき、それが画面で分かりません")


def test_engineをLuaが画面へ渡している():
    """⚠ 画面側だけ作っても、値が来なければ何も出ません。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    assert 'add("battle_engine"' in source, (
        "⚠⚠ Lua が engine を state.json へ書いていません")


# --- ⚠ 観点4: 僅差かどうかが見える ------------------------------------

def test_僅差なら警告を出す():
    """⚠ 差が小さいなら**次のターンに変わりうる**ということ。"""
    got = _vm(battle_balance="advantage", battle_plan="通常速攻",
              battle_plan_score=2.0, battle_plan_margin=0.3).assessment_label()
    assert "⚠僅差" in got, got


def test_十分な差なら警告を出さない():
    """⚠ 鳴りすぎも壊れ方です（★毎回警告なら誰も読まなくなる）。"""
    got = _vm(battle_balance="advantage", battle_plan="省資源",
              battle_plan_score=5.5, battle_plan_margin=1.5).assessment_label()
    assert "僅差" not in got, got


# --- ★★★ 観点5: 「全部同じ」になっていないか ------------------------

def test_全員同じ点なら警告を出す():
    """★★★ **これがいちばん見落としやすい観点**（実際に見落としかけた）。

    ⚠⚠ `attack(1.0)` が3人並ぶと「動いている」ように見えます。
      ★実際は攻撃力が読めておらず、**役割を区別できていません**でした。
    """
    got = _vm(battle_roles="lorasia:attack(1.0) / samaltria:attack(1.0)"
                           " / moonbrooke:attack(1.0)").roles_label()
    assert "全員同じ点です" in got, got


def test_点が違えば警告を出さない():
    """⚠ 正常な状態で警告が出るなら、誰も読まなくなります。"""
    got = _vm(battle_roles="lorasia:attack(1.9) / samaltria:heal(1.6)"
                           " / moonbrooke:item(1.3)").roles_label()
    assert "全員同じ" not in got, got
    assert "lorasia:attack(1.9)" in got, got


def test_1人しか居なければ全員同じと言わない():
    """⚠ 1人なら「全部同じ」は意味を持ちません（★誤警報）。"""
    got = _vm(battle_roles="lorasia:attack(1.9)").roles_label()
    assert "全員同じ" not in got, got


def test_戦況は取れたが戦術が決まらないときそう書く():
    """★★ **空欄にしない。** ⚠ 材料不足だと分かるように。"""
    got = _vm(battle_balance="unknown").assessment_label()
    assert "決めていません" in got, got


# --- ★ 観点6: 選ばなかった理由が見える --------------------------------

def test_理由が画面に出る():
    got = _vm(battle_roles="lorasia:attack(1.9)",
              battle_plan_reasons="優勢・短期戦なので、確実に倒せる敵から"
                                  ).roles_label()
    assert "理由:" in got and "確実に倒せる敵から" in got, got


# --- ⚠⚠ Lua 側が本当に渡しているか ------------------------------------

@pytest.mark.parametrize("key", [
    "battle_balance", "battle_length", "battle_turns_to_win",
    "battle_turns_to_lose", "battle_tags", "battle_plan",
    "battle_plan_score", "battle_plan_margin", "battle_plan_reasons",
    "battle_roles",
])
def test_Luaが4段を画面へ渡している(key):
    """★★ **画面側だけ作っても値が来なければ何も出ません。**

    ⚠ Phase 6 で「部品は全部通るのに実機で0件」を踏んだばかりです。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    assert f'add("{key}"' in source or f'"{key}"' in source, (
        f"⚠ Lua が {key} を state.json へ書いていません")


def test_画面へ渡す値が本当に埋まる():
    """★★★ **項目名を推測で書かない**（2026-08-07 に踏んだ）。

    ⚠⚠ `a.turns_to_win` と書いていて、実機の `state.json` で
      **`null`** になりました。正しくは `enemy_defeat_turns` です。
      ★ログには「敵撃破 1.3ターン」と出ていたので、**画面だけが空欄**
        という気づきにくい形でした。

    ⚠⚠ **「`add(...)` が書いてあるか」だけの検査では捕まりません。**
      ★実物の見立てを渡して、**値が入ること**を見ます。
    """
    import os
    import subprocess
    import sys

    runner = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
    harness = (PROJECT_ROOT / "research" / "probes" / "active"
               / "contributions_wiring_test.lua")
    if not (runner.exists() and harness.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(runner), str(harness)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = ((done.stdout or b"").decode("utf-8", "replace")
           + (done.stderr or b"").decode("utf-8", "replace"))
    if "SKIP:" in out or ("lua5.1" in out and done.returncode != 0):
        pytest.skip("Lua を動かせない環境")

    def _passed(label: str) -> bool:
        return any(l.startswith("OK") and label in l
                   for l in out.splitlines())

    assert "NG 0 件" in out, out
    assert _passed("★★★ 敵撃破の推計が入る"), out
    assert _passed("★★★ 味方崩壊の推計が入る"), out
    assert _passed("⚠ 見立ての項目名は enemy_defeat_turns"), out


def test_戦闘が終わっても見立てを消さない():
    """★★ **依頼者の指示で、消さないほうに変えました**（2026-08-07）。

        > 戦況、役割は戦闘終了後クリアしなくて良い。

    ⚠ 最初は「`state.json` はいまの値だから消すべき」と考えて消して
      いました。★しかし戦闘は数秒で終わるので、**消すと読む間が
      ありません**。直前の戦闘で何が選ばれたかを見直せるほうが役立ちます。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    start = source.index("function Bridge:_on_battle_end")
    body = source[start:start + 2600]
    assert "self.last_assessment_view = nil" not in body, (
        "⚠ 戦闘終了で見立てを消しています（★依頼者は残す指示）")


# --- ★★★ つなぎ方の検査（⚠ 部品の検査では見つからない）---------------
#
# ⚠⚠ Phase 6 で「部品は OK 27件で全部通るのに、実機では 0件」を
#   踏んだばかりです。★画面を**実際に組んで**呼びます。

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402


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
    # ⚠ 人の設定ファイルを書かない（★テストの独立）
    vm._mission_path = tmp_path / "mission.yaml"
    win = MainWindow(vm, interval_ms=10 ** 6, log_path=tmp_path / "r.log")
    yield win
    win.close()


def test_画面が4段を実際に描く(window):
    """★★★ **これが無いと「実機で1行も出ない」を繰り返します。**"""
    game = GameState(
        battle_engine="legacy", battle_balance="advantage",
        battle_length="short", battle_turns_to_win=1.3,
        battle_turns_to_lose=4.9, battle_plan="省資源",
        battle_plan_score=5.5, battle_plan_margin=1.5,
        battle_roles="lorasia:attack(1.9) / samaltria:heal(1.6)")
    window.vm._last_game = game
    window._update_reasoning(game)

    # ★2026-08-11: 見出しは「戦況」。⚠「試験中」は見出しに、
    #   詳しい説明はツールチップに出す（依頼者の指定）。
    assert "戦況" in window._battle_engine_label.text()
    assert "試験中" in window._battle_engine_label.text()
    assert ("判断にはまだ使っていません"
            in window._battle_engine_label.toolTip())
    # ★★ 2026-08-12: 戦況欄は**4行**（依頼者の指示 §4）★★
    #   ⚠ 名前と行動は画面では短縮されます（内部値は変えていません）。
    rows = [label.full_text for label in window._assessment_rows]
    assert len(rows) == 4, "⚠ 4行構造が崩れています"
    assert "優勢" in rows[0] and "短期" in rows[0]
    assert "戦況" not in rows[0], "⚠ 本文に「戦況」が残っています（見出しと重複）"
    assert "撃破 1.3T" in rows[1] and "崩壊 4.9T" in rows[1]
    assert "省資源" in rows[2]
    assert "ロ:攻1.9" in rows[3] and "サ:回1.6" in rows[3]


def test_戦闘していないときも画面が壊れない(window):
    """⚠ 値が1つも来ていないときに落ちないこと。"""
    game = GameState()
    window.vm._last_game = game
    window._update_reasoning(game)
    assert "—" in window._assessment_rows[0].full_text
    # ★見出しは出す（★段の名前なので消さない）。⚠ 届いていないことは
    #   ツールチップで言う（★嘘を書かない）。
    assert window._battle_engine_label.text() == "戦況"
    assert "届いていません" in window._battle_engine_label.toolTip()


def test_新AIに切り替えたら画面で分かる(window):
    """★★ Phase 10 で切り替えたとき、⚠ 効いているかを確かめる手段。"""
    game = GameState(battle_engine="layered")
    window.vm._last_game = game
    window._update_reasoning(game)
    # ★2026-08-11: 見出しは「戦況」だけ。⚠ 試験中の印は付かない
    assert window._battle_engine_label.text() == "戦況"
    assert "試験中" not in window._battle_engine_label.text()
    assert ("AIが戦況を見て判断しています"
            in window._battle_engine_label.toolTip())


def test_毎回の描き直しで呼ばれている():
    """⚠ 作っただけで呼んでいなければ、画面は永遠に更新されません。"""
    source = MAIN_WINDOW.read_bytes().decode("utf-8")
    assert source.count("self._update_reasoning(") >= 1, (
        "⚠⚠ _update_reasoning を呼んでいる場所がありません")


def test_入りきらない行は末尾が点々になる(window):
    """⚠⚠ **黙って切らない**（2026-08-11 / 依頼者の画面）。

    依頼者のスクリーンショットで、戦況の行が窓の右で切れており、
    **続きがあること自体が見えません**でした（QLabel は省略記号を出しません）。

    ★行数は増やさず（4行固定は 2026-08-12 の依頼者の指示）、末尾を「…」に。
    ⚠ 全文は `full_text` とツールチップに残ること（★捨てない）。

    ⚠⚠ **2026-08-12 の注意。** ツールチップは「その行の全文」から
      **戦闘レビュー**へ変わりました（指示 §18: 欄ぜんぶに同じものを付ける）。
      ★そのぶん、レビューの**先頭に4行を入れて**「切れた行を読む」約束を
        守っています。ここではそれを確かめます。
    """
    game = GameState(
        battle_engine="layered", battle_balance="advantage",
        battle_length="short", battle_turns_to_win=0.8,
        battle_turns_to_lose=10.7,
        battle_roles=("lorasia:attack(1.9) / samaltria:heal(1.6)"
                      " / moonbrooke:attack_spell(1.4)"),
        battle_plan="battle_expected / single_strong_enemy / long_text")
    from PySide6.QtWidgets import QApplication

    # ★出していない窓には大きさの知らせが届かない（Qt）。
    #   ⚠ 実機は出ている窓なので、ここでも出して確かめる。
    window.show()
    window.vm._last_game = game
    row = window._assessment_rows[2]                   # ★戦術の行（長い）
    row.setFixedWidth(120)
    QApplication.processEvents()
    window._update_reasoning(game)

    full = row.full_text
    assert len(full) > 20, "★材料が短すぎて、切れる場面を作れていません"
    shown = row.text()
    assert shown.endswith("…"), (
        f"⚠ 切れているのに「…」が出ていません: {shown!r}")
    # ★全文は `full_text` に残る（★捨てない）
    assert row.full_text == full
    # ⚠⚠ 2026-08-19: 「いまの戦況」の4行はツールチップから**外した**
    #   （画面と被るので不要 / 依頼者）。★切れた行の全文は、戦闘中は
    #   レビューの各ターン（戦術/役割の行）で読める。ここでは
    #   「被る4行を出していない」ことと、help が出ていることを確かめる。
    assert "いまの戦況" not in row.toolTip()
    assert "【見かた】" in row.toolTip()

    # ★広げれば全部出る（⚠ いつも「…」ではない）
    row.setFixedWidth(4000)
    QApplication.processEvents()
    assert row.text() == full
