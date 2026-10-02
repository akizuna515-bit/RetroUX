"""呪文の結果 ― ログの観測と、図鑑の「あなたの記録」（RX3-0271 / 2026-09-14）。

```text
Lua  dq3/phase0/spell_watch.lua   ゲーム自身の耐性の判定（JP bank 4 $A3EF）の入口と出口を見る → spell_watch.log
Py   dq3/ui/spell_watch.py        戦闘が終わったら読む → 図鑑の回数（EnemyBook.tries）＋ 行動履歴に 1 行（battle.spell）
```

★依頼者 2026-09-14「S10 は提案通りでOK」（報告 `docs/design/dq3-resistance-analysis.md` §10）:
⚠ 観測だけ / ⚠ 1 回の失敗で「耐性」と書かない / ★図鑑のことばは倒した敵にだけ / ⚠ AI の確率は出さない。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_spell_watch_test.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"


def _bank4(addr: int) -> int:
    return 4 * 0x4000 + (addr - 0x8000)


def test_見張る番地はROMの判定の入口と出口():
    """★Lua が見る 4 か所が、耐性の判定の入口と 3 つの出口であること（⚠ 番地だけを信じない）。"""
    if not ROM.exists():
        pytest.skip("ROM が無い")
    from dq3.testing.npc_rom import _prg

    prg = _prg(None)
    assert prg[_bank4(0xA3EF):_bank4(0xA3EF) + 5] == bytes.fromhex("8565AD6B6A")   # STA $65 / LDA $6A6B（入口）
    assert prg[_bank4(0xA40B):_bank4(0xA40B) + 3] == bytes.fromhex("C55960")   # CMP $59 / RTS（乱数で決めた）
    assert prg[_bank4(0xA40E):_bank4(0xA40E) + 2] == bytes.fromhex("1860")     # CLC / RTS（効かない）
    assert prg[_bank4(0xA410):_bank4(0xA410) + 2] == bytes.fromhex("3860")     # SEC / RTS（効いた）
    lua = (ROOT / "dq3" / "phase0" / "spell_watch.lua").read_text(encoding="utf-8")
    assert "0xA3EF, 0xA40D, 0xA40E, 0xA410" in lua
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert 'load_feature("spell_watch")' in dev, "⚠ 製品が見張りを読んでいない"


def test_Luaの見張りが判定の結果を1行ずつ書く():
    if not (DLL.exists() and RUNNER.exists()):
        pytest.skip("Lua を動かせない")
    done = subprocess.run([sys.executable, str(RUNNER), str(HARNESS)], cwd=str(ROOT), capture_output=True,
                          timeout=120, text=True, encoding="utf-8", errors="replace", env=dict(os.environ))
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0 and "すべて合格" in both, both


def test_行を読んで戦闘と呪文と敵ごとにまとめる():
    from dq3.ui import spell_watch as SW

    lines = ["SPELL_RESULT battle=3 enemy=0 index=6 spell=34 ok=1",
             "SPELL_RESULT battle=3 enemy=0 index=6 spell=34 ok=0",
             "SPELL_RESULT battle=3 enemy=0 index=6 spell=34 ok=1",
             "SPELL_RESULT battle=3 enemy=5 index=1 spell=9 ok=0",
             "ゴミの行", "SPELL_RESULT battle=x"]
    got = [o for o in (SW.parse(ln) for ln in lines) if o is not None]
    assert len(got) == 4
    rows = SW.summarize(got)
    assert rows[0] == {"battle": 3, "spell": 34, "enemy": 0, "index": 6, "tried": 3, "ok": 2}
    assert rows[1]["tried"] == 1 and rows[1]["ok"] == 0
    assert SW.resist_key(6) == "sleep" and SW.resist_key(1) == "ice_spells" and SW.resist_key(99) is None


def _book(tmp_path, defeated=()):
    from dq3.knowledge.enemies_seen import EnemyBook

    book = EnemyBook(path=tmp_path / "enemy-names.json")
    book.met = {0, 5} | set(defeated)
    book.defeated = set(defeated)
    return book


def test_図鑑の回数はしまって戻せる(tmp_path):
    from dq3.knowledge.enemies_seen import EnemyBook

    book = _book(tmp_path)
    book.record_spell(0, "sleep", True)
    book.record_spell(0, "sleep", False)
    book.record_spell(5, "ice_spells", False)
    assert book.save()
    back = EnemyBook.load(tmp_path / "enemy-names.json")
    assert back.tries == {0: {"sleep": [2, 1]}, 5: {"ice_spells": [1, 0]}}


class _Writer:
    def __init__(self):
        self.got = []

    def emit(self, type, source, data, level="info"):
        self.got.append((type, source, data))


def test_戦闘の終わりに図鑑へ足し_行動履歴へ1件(tmp_path):
    """★図鑑のことばは**倒した敵にだけ**（⚠ 会っただけの敵には添えない = No-Spoiler）。"""
    from dq3 import events as EV
    from dq3.ui import spell_watch as SW

    if not ROM.exists():
        pytest.skip("ROM が無い")
    log = tmp_path / "spell_watch.log"
    log.write_text("SPELL_RESULT battle=1 enemy=0 index=6 spell=34 ok=1\n"
                   "SPELL_RESULT battle=1 enemy=5 index=6 spell=34 ok=0\n", encoding="utf-8")
    writer = _Writer()
    watch = SW.SpellWatcher(log, writer=writer, from_end=False)
    book = _book(tmp_path, defeated=(0,))
    results = watch.flush(book)
    assert book.tries[0]["sleep"] == [1, 1] and book.tries[5]["sleep"] == [1, 0]
    assert len(writer.got) == 1 and writer.got[0][0] == EV.BATTLE_SPELL and writer.got[0][1] == EV.SRC_SPELL
    by_enemy = {r["enemy"]: r for r in results}
    assert len(by_enemy) == 2
    known = [r for r in results if r["book"] is not None]
    assert len(known) == 1, "⚠⚠ 倒していない敵に図鑑のことばを添えた: %r" % results
    assert watch.flush(book) == [], "⚠ 同じ判定を 2 度まとめた"


def test_行動履歴の文は回数だけ_耐性とは書かない():
    from dq3 import action_log as AL
    from dq3 import events as EV
    from dq3.events import formatter as F

    ev = EV.Event(EV.BATTLE_SPELL, EV.SRC_SPELL, {"result": EV.SUCCESS, "results": [
        {"spell": "ラリホー", "enemy": "スライム", "tried": 3, "ok": 2, "book": None},
        {"spell": "ヒャド", "enemy": "テスト", "tried": 2, "ok": 0, "book": "効かない"}]})
    action, _status, body, _detail = F.summary_of(ev)
    assert action == "spell" and AL.ACTION_LABELS["spell"] == "呪文の結果"
    assert body == "ラリホー → スライム：3回中2回 効いた / ヒャド → テスト：2回中0回 効いた（図鑑: 効かない）"
    assert "耐性" not in body and AL.is_user_safe(body)
    assert F.product_line(ev).startswith("呪文の結果：")


def test_戦闘の終わりに見張りがあればまとめる_無ければ何もしない():
    from dq3.ui.view_model import Dq3ViewModel

    called = []
    fake = types.SimpleNamespace(spell_watch=types.SimpleNamespace(flush=lambda book: called.append(book)),
                                 enemy_names="BOOK")
    Dq3ViewModel._note_spells(fake)
    assert called == ["BOOK"]
    Dq3ViewModel._note_spells(types.SimpleNamespace(enemy_names="BOOK"))     # ⚠ 見張りが無くても落ちない
    broken = types.SimpleNamespace(spell_watch=types.SimpleNamespace(flush=lambda book: 1 / 0), enemy_names=None)
    Dq3ViewModel._note_spells(broken)                                        # ⚠ 見張りが落ちても画面は止めない
    main = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "view_model.spell_watch = SpellWatcher(writer=self.action_watch.writer)" in main


def test_戦闘の終わりの流れで呪文の結果をまとめる_倒したかを覚えた後():
    """★`_note_battle_end` が「会った / 倒した」を覚えた**後**で `_note_spells` を呼ぶ（★図鑑のことばは倒した敵にだけ）。"""
    from dq3.ui.view_model import Dq3ViewModel

    order = []
    book = types.SimpleNamespace(record_battle=lambda groups, won: order.append(("battle", won)) or 1,
                                 save=lambda: None)
    fake = types.SimpleNamespace(_pending_battle=([{"id": 0}], 10), _total_exp=lambda: 20, enemy_names=book,
                                 _battle_settle=None,
                                 write_enemy_overlay=lambda: None, _note_spells=lambda: order.append("spells"))
    # ⚠ 2026-09-20（RX3-0303）: 「倒した」は待って決めるようになったので、
    #   ★`_finish_battle` / `_settle_battle` も借りる（⚠ 呼ぶ順は変えていない）
    fake._finish_battle = lambda groups, won: Dq3ViewModel._finish_battle(fake, groups, won)
    fake._settle_battle = lambda: Dq3ViewModel._settle_battle(fake)
    # ⚠ 2026-09-28（RX3-0450）: 経験値が増え得ない相手の見分けも借りる（★呼ぶ順は変えていない）
    fake._exp_can_grow = lambda groups: Dq3ViewModel._exp_can_grow(fake, groups)
    fake._party_alive = lambda: Dq3ViewModel._party_alive(fake)
    fake._raw_party = lambda: [{"hp": 10, "max_hp": 20}]
    # ⚠ ROM を読まない（★公開木には ROM が無い / 見本の敵 id は 0）
    fake._enemy_exp = lambda enemy_id: 100
    Dq3ViewModel._note_battle_end(fake)
    assert order == [("battle", True), "spells"], order


def test_図鑑のあなたの記録_会った敵なら倒していなくても出す(tmp_path):
    from dq3.knowledge import monster_book as mb
    from dq3.ui import monster_book_window as win

    book = _book(tmp_path)
    book.names = {5: "テスト"}
    book.record_spell(5, "ice_spells", False)
    book.record_spell(5, "sleep", True)
    book.record_spell(5, "sleep", True)
    rows = mb.tries_rows(book, 5)
    assert [r[0] for r in rows] == ["ヒャド", "ラリホー"], "⚠ 依頼者の表の並びでない: %r" % (rows,)
    entry = mb.entry_of(book, 5, art_lookup=lambda _k: None)
    lines = dict(win.summary_lines(entry))
    assert lines.get("試した") == "ヒャド 1回中0回 効いた / ラリホー 2回中2回 効いた", lines
    assert "中身" in lines, "⚠ 倒していない敵の中身を出した"
