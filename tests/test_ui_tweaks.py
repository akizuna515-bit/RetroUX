"""実機で使ってみて気づいた点の直し（2026-07-31 / 依頼者の指摘 4件）。

| # | 指摘 | 直したこと |
| --- | --- | --- |
| 1 | 「FCEUX を左隣へ整列」は嘘（3つとも動く） | ラベルを「ウィンドウを整列」に |
| 2 | 「保存して終了」は嘘（保存しない道もある） | ラベルを「終了」に |
| 3 | 高速戦闘を切りたい（AI を目で追いたい） | トグルを追加 |
| 4 | 名前の列が広すぎる（和名は4文字） | 中身ぶんに詰めて左詰め |

★1・2 は**画面の文字が実際の動きと違う**という不具合。
  「押す前に何が起きるか分かる」ことは、取り消せない操作ほど大事。
"""

from __future__ import annotations

import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _source(*parts: str) -> str:
    return (PROJECT_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _bridge() -> str:
    return _source("retroux", "emulator", "fceux", "bridge.lua")


def _window() -> str:
    return _source("retroux", "ui", "main_window.py")


# --- 1. 整列ボタンのラベル ---------------------------------------------

def test_the_align_button_does_not_claim_to_move_only_fceux():
    """⚠ 実際は**3つとも**動かす（Lua は左 / FCEUX は中央 / この画面は右）。

    ★「FCEUX を左隣へ整列」は、動くものも向きも違っていた。
    """
    text = _window()
    assert '"FCEUX を左隣へ整列"' not in text, "古いラベルが残っている"
    # ★2026-08-01: 「整列」→「標準レイアウトに戻す」（指示書 §7.1）。
    #   ⚠ 覚えている配置を**捨てて**戻す操作なので、
    #     「整列」だけでは何が起きるか読み取れなかった。
    #
    # ★★ 2026-08-09: **「整列」へ戻しました**（依頼者の判断）★★
    #   ⚠ 4区画にすると、この画面の幅が 362px しかありません。
    #     「標準レイアウトに戻す」は 160px あり、ボタン列だけで
    #     幅が足りなくなりました（実測 412px / 目標 362px）。
    #   ★2026-08-01 の懸念（何が起きるか読み取れない）は**ツールチップで補う**、
    #     という形にしています。だから下の説明の検査は**残します**。
    #   ★★ 2026-08-09: さらにアイコン「⊞」へ（依頼者の指示）★★
    #     ⚠ 文字が消えたぶん、ツールチップの1行目に「整列する」と書きます。
    #   ★★ 2026-08-11: 一度 🪟 にしたが、実機で絵文字が崩れた（依頼者）ため
    #     確実に描ける ⊞ へ戻した。★真の絵アイコンは QIcon 資産で別途対応。
    #   ★★ 2026-08-18 / RX-0071: その「真の絵アイコン」に置き換えた（依頼者）。
    #     文字グリフ「⊞」をやめ `_button_icon("align", …)` を QIcon として持つ。
    #     ⚠ 名前（何が起きるか）は**ツールチップに残す**（下の検査で担保）。
    assert 'self._align_button.setIcon(_button_icon("align"' in text
    assert '"整列する\\n"' in text, "ツールチップに名前が無い"
    assert 'QPushButton("ウィンドウを整列")' not in text, "古いラベルが残っている"
    # ★何が動くのかは説明で補う（ラベルは短く、説明は具体的に）
    #   ⚠ 並びが4区画に変わったので、説明も4区画のものであること
    assert "左   : 見た地図" in text
    assert "中央 : FCEUX" in text
    assert "下   : ログ" in text
    assert "最小化: Lua Script" in text


# --- 2. 終了ボタンのラベル ---------------------------------------------

def test_the_exit_button_does_not_promise_to_save():
    """⚠ ダイアログで「保存せずに終了」も選べるので、
    ボタンに「保存して終了」と書くのは**嘘**だった。

    ★選択肢そのもの（ダイアログの中）は今までどおり。
    """
    text = _window()
    # ★2026-08-09: アイコン「✕」へ。⚠ 名前はツールチップの1行目に残す
    # ★2026-08-11: 一度 🚪 にしたが、実機で絵文字が崩れたため ✕ へ戻した。
    # ★★ 2026-08-18 / RX-0071: 文字グリフ「✕」をやめ `_button_icon("exit", …)`
    #     を QIcon として持つ（依頼者）。⚠ 名前はツールチップに残す（下で担保）。
    assert 'self._exit_button.setIcon(_button_icon("exit"' in text
    assert '"終了する\\n"' in text, "ツールチップに名前が無い"
    # ★ダイアログの選択肢としては残っていること（消してはいけない）
    assert 'box.addButton("保存して終了"' in text
    assert 'box.addButton("保存せずに終了"' in text


# --- 3. 高速戦闘の入切 -------------------------------------------------

def test_the_turbo_toggle_exists_and_defaults_to_on():
    """★既定は入＝**これまでどおり**（黙って挙動を変えない）。"""
    text = _window()
    assert "self._turbo_button" in text
    assert "setCheckable(True)" in text
    assert "self._turbo_button.setChecked(True)" in text, "既定が入になっていない"


def test_turbo_off_is_decided_in_one_place_and_only_for_battles():
    """★★ **倍速にする理由は複数あるので、一番手前で返す。** ★★

    ⚠ 後ろで弾く形にすると必ず漏れる。過去に同じ失敗をしている:
      「自動入力を止める条件を増やすたびに倍速側も直す、では必ず漏れる」
      （危険状態で自動は止まったのに倍速だけ残り、35倍速で操作を迫られた）

    ⚠ 効くのは**戦闘だけ**。まんたん等の自動操作の速さは変えない
      （そちらは待ち時間の短縮そのもので、この切り替えの目的ではない）。
    """
    # ★★ 2026-08-01 のリファクタで、判断は `speed_controller` へ移った。
    #   ⚠ 探す先を直さないと「直っているのに赤い」ままになる。
    src = _source("retroux", "emulator", "fceux", "speed_controller.lua")

    assert "if ctx.in_battle and self.turbo_enabled == false then" in src, \
        "戦闘だけを対象にしていない"
    assert '"高速戦闘オフ"' in src
    # ★既定は入（プロフィールが無い環境と同じで、黙って変わらない）
    assert "self.turbo_enabled = true" in src


def test_the_turbo_flag_travels_through_the_command_file():
    """★GUI -> command.json -> Lua の道が繋がっていること。"""
    writer = _source("retroux", "core", "bridge", "writer.py")
    assert "turbo_enabled" in writer
    # ⚠ 書かなかった項目を消さない仕組みの対象に入れること
    assert '"request_id", "turbo_enabled"' in writer

    # ★読むのは `command_reader`（リファクタ §4.2 で移した）
    reader = _source("retroux", "emulator", "fceux", "command_reader.lua")
    assert 'CommandReader.flag(body, "turbo_enabled")' in reader,         "Lua が拾っていない"


# --- 4. パーティ表の列幅 -----------------------------------------------

def test_strength_and_agility_have_addresses():
    """★★ **すばやさは「つよさ」の画面のキャプチャから特定した**（2026-07-31）★★

    依頼者が「つよさ」を開いた状態でセーブしてくれたので、
    画面の数字を手がかりに RAM を探せた。あかり（0番目）で **9項目すべて一致**:

      さいだいHP 101 / さいだいMP 0 / 経験値 60357 /
      ちから 81 / すばやさ 59 / こうげき力 146 / しゅび力 104 /
      いまのHP 89 / LV 21

    ★位置も筋が通る。経験値（+3〜+5 の3バイト）と こうげき力（+8）の
      **隙間にぴったり収まる**（+6 と +7）。説明の付かない空きが残らない。
    """
    import yaml

    text = (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
            / "memory_map.yaml").read_text(encoding="utf-8")
    fields = yaml.safe_load(text)["addresses"]["party"]["fields"]

    assert fields["strength"]["offset"] == 0x0636
    assert fields["agility"]["offset"] == 0x0637
    # ★前後と地続きであること（隙間が空いたら読み方が違う）
    assert fields["attack"]["offset"] == 0x0638
    assert fields["experience"]["offset"] == 0x0633
    assert fields["experience"]["size"] == 3


def test_every_decision_point_records_a_reason():
    """★★ **「回復の出番なし。たたかう」だらけだった原因**（2026-07-31）★★

    > 選択が（回復の出番なし。たたかう）だらけな気がする。道具も使っているのに
    > ※MP不足でホイミ使わないみたいな判断が見えないきがする

    ⚠⚠ 判断を記録していたのは**回復を実行したときだけ**だった。
      しない理由（MP不足・回復不要・マホトーン）は
      **1戦闘に1回ログへ出すだけ**で、画面には何も届いていなかった。
      → 画面はいつも既定の文字列を出していた。

    ★直したこと:
      1. 回復**しない**ときも理由を記録する
      2. **道具を使ったとき**も記録する（「たたかう」と出ていた）
      3. ログに出さない理由（回復不要・呪文を覚えない）も**画面には出す**
    """
    src = _bridge()

    assert "function Bridge:_note_decision(member, action, reason)" in src
    # ★回復しないときも記録する
    assert 'self:_note_decision(m, "たたかう", why or quiet_why' in src
    # ★道具も記録する（回復だけが判断ではない）
    assert 'self:_note_decision(m, string.format("どうぐ: %s"' in src
    # ★ログには出さないが画面には出す理由
    assert '"全員のHPがしきい値以上（回復不要）"' in src
    assert '"呪文を覚えない（ローレシア）"' in src


def test_ai_decisions_are_per_member_and_never_drop_a_row():
    """★★ **3人ぶん出す**（行動者ごとに切り替えない）★★

    ⚠ 判断を1つの箱に入れていたので、**最後に入力した人で上書き**され、
      他の2人が見えなかった。それが「切り替わる」の正体。
    ★加入している人は**必ず1行出す**（行が消えると状態が読めない）。
    """
    src = _bridge()
    assert "self.ai_decisions[member.index]" in src
    assert '"ai_decisions":[' in src
    # ★戦闘ごとに捨てる（前の戦闘の判断が残ると誤解する）
    assert "self.ai_decisions = {}" in src


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None,
    reason="PySide6 が無い")
def test_the_ai_panel_shows_three_members_and_marks_the_actor():
    """★3人ぶん並べ、いま入力を求められている人に印を付ける。

    ⚠ **まだ判断していない**と「たたかう」を混ぜない
      （0 と不明を混ぜないのと同じ話）。
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from retroux.core.bridge.state_reader import GameState
    from retroux.ui.panels import AiPanel

    panel = AiPanel()
    panel.show()
    panel.update_state(GameState(
        in_battle=True, actor="samaltria",
        ai_decisions=[
            {"index": 0, "name": "lorasia", "action": "たたかう",
             "reason": "呪文を覚えない（ローレシア）"},
            {"index": 1, "name": "samaltria", "action": "たたかう",
             "reason": "MPが足りない（ホイミ / 残り2 < 必要3）"},
            {"index": 2, "name": "moonbrooke", "action": "ホイミ -> lorasia",
             "reason": "lorasia のHPが最大の50%未満"},
        ]))
    app.processEvents()

    rows = panel._member_rows
    assert all(r["who"].isVisible() for r in rows), "3人とも出ていない"
    assert "◀" in rows[1]["who"].text(), "行動者に印が無い"
    assert "◀" not in rows[0]["who"].text()
    # ★理由が人ごとに違うこと（1つの箱で上書きされていない）
    assert "MPが足りない" in rows[1]["reason"].text()
    assert "50%未満" in rows[2]["reason"].text()

    # ⚠ まだ判断していない人は「－」（「たたかう」と混ぜない）
    panel.update_state(GameState(
        in_battle=True, ai_decisions=[{"index": 0, "name": "lorasia"}]))
    app.processEvents()
    assert rows[0]["action"].text() == "－"
    assert not rows[1]["who"].isVisible(), "居ない人の行が残っている"


def test_overkill_avoidance_is_wired_and_conservative_by_default():
    """★★ **無駄撃ちを避ける**（2026-07-31 / 依頼者の要望）★★

    > 攻撃のときに、敵モンスターの残りHPを予測して、無駄な攻撃をしない
    > → 今は、左の敵に総攻撃をしている

    ⚠ 「左に総攻撃」の正体は、**優先する敵がいないと何も主張せず、
      カーソルが行0＝左端のまま**だったこと。

    ⚠⚠ 見込みダメージは**目安**（公開されている近似式）。外す向きが違う:
      過大 -> 早く次へ移る -> **倒しきれずに残る**
      過小 -> 重ねて攻撃（無駄は残るが安全）
      ★`overkill_margin` で安全側へ倒せる。依頼者の指定は **1.0**。

    ★動きの確認は `research/probes/active/overkill_test.lua`（実 Lua / 17項目）。
    """
    import yaml

    cfg = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "config.yaml").read_text(encoding="utf-8"))
    # ★bridge の `ai` はこの節（`target_priority` と同じ場所に置く）
    ai = cfg["auto_input"]
    assert "target_priority" in ai, "置き場が変わった（bridge の ai と揃える）"
    assert ai["overkill_avoid"] is True
    assert ai["overkill_margin"] == 1.0, "依頼者の指定は係数1.0"

    src = _bridge()
    # ★優先指定が無くても狙う行を決めること（＝左端に固まらない）
    #
    # ⚠ 行の見た目そのものを見ない（2026-08-07 に踏んだ）。
    #   ★呪文の狙い合わせで条件が1つ増え、2行に分かれたら落ちました。
    #     見たいのは「無駄撃ち回避があれば降りない」という**意図**です。
    # ⚠ コメントにも同じ文字列があります。★コード行だけを見ます。
    gate = next(
        (chunk for chunk in
         (src[i:i + 200] for i in range(len(src))
          if src.startswith("if #self.target_priority == 0", i))),
        "")
    assert gate, "⚠ 判定そのものが見つかりません"
    assert "not self.overkill_avoid" in gate, (
        "⚠ 無駄撃ち回避があっても降りてしまいます（★左端に固まる）")
    # ★ターンが変わったら予約を捨てる（持ち越すと誰も殴らなくなる）
    assert "total < self.overkill_hp_total" in src
    # ★戦闘ごとにも捨てる
    assert src.count("self.overkill_booked = {}") >= 2


def test_the_reverse_damage_estimate_exists_and_mirrors_the_forward_one():
    """★味方→敵のダメージ推定。**式は敵→味方と同じ**（対にする）。

    ⚠ 片方だけ直すと、脅威度と無駄撃ち判断が食い違う。
    """
    src = _source("retroux", "plugins", "dq2", "dq2.lua")
    assert "function DQ2:estimated_damage_to(member_index, monster_id)" in src
    assert "function DQ2:enemy_groups_hp()" in src
    # ★同じ式（守備力の半分を引いて2で割る）
    assert src.count("/ 2) / 2") >= 2, "式が対になっていない"
    # ⚠ 守備力が高いと 0 になりうる。**最低1にしない**（丸めて安心させない）
    assert src.count("if d < 0 then d = 0 end") >= 2


def test_gold_is_read_as_two_bytes_and_shown_outside_the_party_table():
    """★所持ゴールドは**パーティ共通**なので、人ごとの表に入れない（上段）。

    ⚠ **2バイト・リトルエンディアン。** 上位を忘れると 255 で頭打ちになる。

    ★`$0624` は「公開資料由来・未検証」だったが、2026-07-31 に
      「つよさ」の画面のキャプチャと突き合わせて確認できた:
        130 + 61×256 = 15746 ＝ 画面の「G: 15746」
    """
    import yaml

    text = (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
            / "memory_map.yaml").read_text(encoding="utf-8")
    gold = yaml.safe_load(text)["addresses"]["gold"]
    assert gold["addr"] == 0x0624
    assert gold["size"] == 2
    assert gold["confidence"] == "confirmed", "実測で確認したので confirmed"

    src = _bridge()
    # ★上位バイトを足していること（忘れると 255 で止まる）
    assert "memory.readbyte(gold_addr + 1) * 256" in src
    # ⚠ 人ごとの表に入れないこと
    from retroux.ui.panels import PartyPanel
    assert not any("G" == c or "ゴールド" in c for c in PartyPanel.COLUMNS)

    # ★置き場は**パーティ状態の見出し**（2026-07-31 / 依頼者の要望）。
    #   ⚠ 上段は状態・速度・AUTO・版で既に2行あり、増やすと高DPIで溢れる
    #     （R-5 で「いちばん溢れやすい」と分かっている場所）。
    # ⚠ `index("_build_party_panel")` だと**呼び出し側**に当たる。定義を探す
    win = _window()
    i = win.index("def _build_party_panel")
    j = win.index("def ", i + 10)
    assert "self._gold_value" in win[i:j], "パーティ状態の見出しに置いていない"


def test_the_crest_state_is_not_faked():
    """⚠⚠ **紋章はまだ出せない**（2026-07-31 に調べた）。

    ★DQ2 の紋章は5つだが、道具IDの空きは **0x36 と 0x3F の2つだけ**。
      つまり**持ち物ではない**（イベントフラグ側にある）。
      実際のセーブステートの持ち物を全部読んでも紋章は出てこなかった。

    ⚠ **空欄の枠を作らない。** 並べると「持っていない」に見えるので、
      在り処が分かるまで出さない（`docs/50-playbook.md`
      「分からないものは列を作らない」）。
    """
    from retroux.ui.panels import PartyPanel

    # ⚠ 表の列に無いことだけを見る。
    #   ★ソース全体を見ると「なぜ出さないか」の説明にも当たってしまう。
    for word in ("紋章", "もんしょう"):
        assert not any(word in c for c in PartyPanel.COLUMNS)

    import yaml
    m = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "memory_map.yaml").read_text(encoding="utf-8"))
    items = m.get("item_names") or m.get("items") or {}
    gaps = [i for i in range(0x01, 0x40) if i not in items]
    assert len(gaps) < 5, (
        "道具IDに5つ空きができた。紋章が持ち物である可能性を見直すこと")


def test_the_resistance_labels_use_dq2_spell_names():
    """⚠ **ルカニは DQ2 に無い**（依頼者の指摘 / 2026-07-31）。

    守備力を下げる呪文は**ルカナン**。DQ3 以降と混ざっていた。
    ★内部の名前 `defense_down` は ROM の耐性のビット位置の名前なのでそのまま。
    """
    for rel in (("retroux", "ui", "encounter_panel.py"),
                ("retroux", "ui", "monster_book_window.py")):
        text = _source(*rel)
        code = [ln for ln in text.splitlines()
                if not ln.strip().startswith("#")]
        joined = "\n".join(code)
        assert "ルカニ" not in joined, f"{rel[-1]} に ルカニ が残っている"
    assert "ルカナン" in _source("retroux", "ui", "encounter_panel.py")


def test_agility_is_abbreviated_with_the_speed_character():
    """⚠ すばやさの略は「素」ではなく **「速」**（依頼者の指摘）。

    「素」は素早さの1文字目だが、意味を持つのは「速」。
    """
    text = _source("retroux", "ui", "encounter_panel.py")
    assert '("速", row.agility)' in text
    assert '("素", row.agility)' not in text


def test_missing_stat_fields_do_not_crash_the_bridge():
    """⚠⚠ **古い `memory_map.yaml` のままでも落ちないこと。**

    項目が無いと `attempt to index field 'strength'` で
    **状態の書き出しごと止まる**（実際に Lua のテストが捕まえた）。
    ★表示のための処理で本体を止めない。読めないものは `null` を書く。
    """
    src = _bridge()
    assert "local function stat(name)" in src
    assert "if field == nil or field.offset == nil then return nil end" in src
    # ★nil を 0 にしない（0 は「弱い」に見える）
    assert '"strength":\' .. json_value(strength)' in src


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None,
    reason="PySide6 が無い")
def test_the_party_table_shows_the_four_status_values():
    """★ゲームの「つよさ」と同じ言葉で出す（2026-07-31 / 依頼者の要望）。

    ⚠ 「ちから」と「こうげき力」は**別物**（こうげき力 = ちから + 武器）。
      どちらも「攻撃」と書くと、装備の効果が読み取れなくなる。
    """
    from retroux.ui.panels import PartyPanel

    # ★★ 2026-08-09: 見出しは1文字（依頼者の指示「見切れるので努力したい」）★★
    #   ⚠ 言葉そのものは捨てません。**ツールチップ**でゲームと同じ言葉を出します。
    for short, word in (("力", "ちから"), ("速", "すばやさ"),
                        ("攻", "こうげき力"), ("守", "しゅび力")):
        assert short in PartyPanel.COLUMNS, short
        assert word in PartyPanel.COLUMN_TIPS[short], word
    # ⚠ 紛らわしい短縮名に戻さないこと
    assert "攻撃" not in PartyPanel.COLUMNS
    assert "守備" not in PartyPanel.COLUMNS


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None,
    reason="PySide6 が無い")
def test_an_unknown_stat_is_shown_as_a_dash_not_zero():
    """⚠ 届いていない値を **0** と出さない（0 は「弱い」に見える）。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from retroux.core.bridge.state_reader import Member
    from retroux.ui.panels import PartyPanel

    panel = PartyPanel()
    panel.update_party([Member(name="a", level=1, hp=1, max_hp=1)])
    app.processEvents()

    for label in ("力", "速", "攻", "守"):
        col = PartyPanel.COLUMNS.index(label)
        assert panel._table.item(0, col).text() == "-", label


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None,
    reason="PySide6 が無い")
def test_the_party_name_column_does_not_eat_the_width():
    """⚠ 和名は**4文字まで**なので、名前の列を伸ばす意味が無い。

    ★中身ぶんに詰めて左詰めにし、余りは**最後の列**に持たせる。
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QHeaderView

    app = QApplication.instance() or QApplication([])
    from retroux.ui.panels import PartyPanel

    panel = PartyPanel()
    header = panel._table.horizontalHeader()

    for i, name in enumerate(PartyPanel.COLUMNS):
        assert header.sectionResizeMode(i) == \
            QHeaderView.ResizeMode.ResizeToContents, f"{name} が中身ぶんでない"
    assert header.stretchLastSection(), "余りを最後の列に持たせていない"
    _ = app



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の検査は
#       assert "self.ai_decisions[member.index]" in src
#   のように、**書き方**しか見ていません。
#   ★添字をひとつ間違えれば、字面はそのままで**最後の人だけ**になります。
#
# ⚠ それが 2026-07-31 に依頼者が見た「判断が切り替わる」の正体でした。
# =====================================================================

import os          # noqa: E402
import subprocess  # noqa: E402
import sys         # noqa: E402

_DEC_HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
                / "ai_decisions_test.lua")
_DEC_RUNNER = (PROJECT_ROOT / "research" / "probes" / "reusable"
               / "lua_run.py")


@pytest.fixture(scope="module")
def decisions_lua():
    if not (_DEC_RUNNER.exists() and _DEC_HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(_DEC_RUNNER), str(_DEC_HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _dec_ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeで判断の記録が全部通る(decisions_lua):
    assert "すべて合格" in decisions_lua, decisions_lua


def test_判断の記録の検査の数が足りている(decisions_lua):
    count = sum(1 for line in decisions_lua.splitlines()
                if line.startswith("OK "))
    assert count >= 20, f"OK が {count} 件しかありません\n{decisions_lua}"


def test_3人ぶんが同時に残る(decisions_lua):
    """⚠⚠ **2026-07-31 の不具合そのもの。** 1つの箱だと最後の人で上書き。"""
    assert _dec_ok(decisions_lua, "★3人ぶんが同時に残る"), decisions_lua
    assert _dec_ok(decisions_lua, "★他の人は変わらない"), decisions_lua


def test_ターン番号が一緒に残る(decisions_lua):
    """★古い判断と見分けるために要ります。"""
    assert _dec_ok(decisions_lua, "★そのときのターン番号が入る"), decisions_lua
    assert _dec_ok(decisions_lua, "★古い行のターンは変わらない"), decisions_lua


def test_記録づくりが落ちても理由は残る(decisions_lua):
    """★判断の状態づくりは**記録だけの機能**。落ちても本体を止めません。"""
    assert _dec_ok(decisions_lua, "⚠ 記録づくりが落ちても行は残る"), decisions_lua


def test_落ちたことを毎フレーム言わない(decisions_lua):
    """⚠⚠ ログが埋まると、**本当に見たい警告が見えなくなります**。"""
    assert _dec_ok(decisions_lua, "★落ちたことを1回言う"), decisions_lua
    assert _dec_ok(decisions_lua, "⚠⚠ 2回目以降は言わない"), decisions_lua
