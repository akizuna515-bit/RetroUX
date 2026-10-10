"""倒したかは、経験値が落ち着いてから決める（RX3-0303 / 2026-09-20）。

⚠⚠ 依頼者「バラモスを倒した時、勇者メモから消えない(save9)」。

★実測（依頼者の記録）:

```text
会った 109 種 / 倒した 108 種
⚠⚠ 「会ったが倒していない」は **132（バラモス）ただ 1 匹**
T017 バラモス討伐  active のまま（★だから勇者会議から消えない）
```

→ ★戦闘フラグが落ちた**瞬間**に 1 回だけ経験値を見て、⚠ まだ書かれていなかった。

⚠ 「会った」は今までどおり**すぐ**覚えます（★取りこぼさない）。
★「倒した」だけ、⚠ **しばらく待って**から決めます。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.ui import view_model as VM                            # noqa: E402

BOSS = 132          #: ★バラモス（⚠ 実データで確かめた番号）
#: ★ゾーマ（姿が 2 つ）と オルテガ（⚠ どれも ROM の経験値が 0 / RX3-0450）
ZOMA_FIRST, ZOMA_SECOND, ORTEGA = 133, 134, 135


class _Book:
    """★敵の記録の代わり（⚠ 本物の記録には触らない）。"""

    def __init__(self) -> None:
        self.met: set = set()
        self.defeated: set = set()
        self.saves = 0

    def record_battle(self, groups, won: bool) -> int:
        added = 0
        for g in groups or ():
            key = g.get("id")
            if key is None:
                continue
            key = int(key)
            if key not in self.met:
                self.met.add(key)
                added += 1
            if won and key not in self.defeated:
                self.defeated.add(key)
                added += 1
        return added

    def save(self, force: bool = False) -> bool:
        self.saves += 1
        return True


class _VM:
    """★戦闘の記録に要る口だけを持つ見本（⚠ 実機も本物の記録も要らない）。

    ⚠ `Dq3ViewModel` を継承しません（★`enemy_names` は property で差し替えられない）。
    ★見たいのは「いつ倒したと決めるか」だけなので、★本物の**判断の関数を借りて**きます。
    """

    BATTLE_SETTLE_TICKS = VM.Dq3ViewModel.BATTLE_SETTLE_TICKS
    _note_battle_start = VM.Dq3ViewModel._note_battle_start
    _note_battle_groups = VM.Dq3ViewModel._note_battle_groups
    _note_battle_end = VM.Dq3ViewModel._note_battle_end
    _settle_battle = VM.Dq3ViewModel._settle_battle
    _finish_battle = VM.Dq3ViewModel._finish_battle
    # ★経験値が増え得ない相手の見分け（RX3-0450）
    _exp_can_grow = VM.Dq3ViewModel._exp_can_grow
    _party_alive = VM.Dq3ViewModel._party_alive

    def __init__(self) -> None:                                # noqa: D107
        self.enemy_names = _Book()
        self.exp = 0
        self._pending_battle = None
        self._battle_settle = None
        self.overlays = 0
        #: ★パーティの生き死に（⚠ 既定は生きている）
        self.party = [{"hp": 10, "max_hp": 20}]
        #: ★敵 id → ROM の経験値（⚠ ROM を読まない / ★実測の値を写してある）
        #:   ⚠⚠ 公開木には ROM が無いので、**本物の表を引くと検査が落ちます**（2026-09-28 に踏んだ）。
        self.exp_table = {BOSS: 65535, ZOMA_FIRST: 0, ZOMA_SECOND: 0, ORTEGA: 0, 5: 40}

    def _enemy_exp(self, enemy_id):
        return self.exp_table.get(int(enemy_id))

    def _total_exp(self) -> int:
        return self.exp

    def _raw_party(self):
        return self.party

    def write_enemy_overlay(self):
        self.overlays += 1
        return None

    def _note_spells(self) -> None:
        pass


@pytest.fixture()
def vm():
    return _VM()


def _fight(vm, exp_before=1000):
    """★戦闘に入る（⚠ 群が届いたところまで）。"""
    vm.exp = exp_before
    vm._note_battle_start()
    vm._note_battle_groups([{"id": BOSS, "n": 1}])


# --- ★今までどおり -------------------------------------------------------

def test_その場で経験値が増えていれば倒した(vm):
    _fight(vm)
    vm.exp = 1000 + 9000                       # ★もう書かれている
    vm._note_battle_end()
    assert BOSS in vm.enemy_names.defeated


def test_逃げたら倒したにしない(vm):
    """⚠ 経験値が増えないまま待ちが尽きる（★逃げた・全滅した）。"""
    _fight(vm)
    vm._note_battle_end()
    assert BOSS in vm.enemy_names.met, "⚠ 会ったことは覚える"
    assert BOSS not in vm.enemy_names.defeated
    for _ in range(vm.BATTLE_SETTLE_TICKS + 2):
        vm._settle_battle()
    assert BOSS not in vm.enemy_names.defeated, "⚠⚠ 逃げたのに倒したことにした"
    assert vm._battle_settle is None, "⚠ いつまでも見張っている"


# --- ★これが直したかったこと ---------------------------------------------

def test_経験値が遅れて届いても倒したにする(vm):
    """★★ 依頼者のバラモスの場面（⚠ フラグが落ちた時点では 0）。"""
    _fight(vm)
    vm._note_battle_end()                      # ⚠ まだ経験値が書かれていない
    assert BOSS in vm.enemy_names.met
    assert BOSS not in vm.enemy_names.defeated
    vm._settle_battle()                        # ★まだ届かない
    assert BOSS not in vm.enemy_names.defeated
    vm.exp = 1000 + 9000                       # ★ここで届いた
    vm._settle_battle()
    assert BOSS in vm.enemy_names.defeated, "⚠⚠ 遅れて届いた経験値を見ていない"


def test_待ちが尽きる直前でも間に合う(vm):
    """⚠ 最後の 1 回でも拾う（★`_note_battle_end` 自身も 1 回数えている）。"""
    _fight(vm)
    vm._note_battle_end()
    while vm._battle_settle and vm._battle_settle[2] > 1:
        vm._settle_battle()
    assert vm._battle_settle is not None, "⚠ もう見張っていない（★この検査が空回り）"
    vm.exp = 1000 + 1
    vm._settle_battle()
    assert BOSS in vm.enemy_names.defeated


def test_待ちが尽きたあとは拾わない(vm):
    """⚠ いつまでも見張らない（★次の戦闘と混ざる）。"""
    _fight(vm)
    vm._note_battle_end()
    for _ in range(vm.BATTLE_SETTLE_TICKS + 1):
        vm._settle_battle()
    vm.exp = 99999
    vm._settle_battle()
    assert BOSS not in vm.enemy_names.defeated


def test_会ったのはすぐ覚える(vm):
    """⚠ 「倒した」を待つせいで、★「会った」まで遅れないこと。"""
    _fight(vm)
    vm._note_battle_end()
    assert BOSS in vm.enemy_names.met


def test_2度記録しても壊れない(vm):
    """★`_finish_battle` は 2 度呼ばれる（⚠ 集合に足すだけ）。"""
    _fight(vm)
    vm._note_battle_end()
    vm.exp = 1000 + 5
    vm._settle_battle()
    assert vm.enemy_names.defeated == {BOSS} and vm.enemy_names.met == {BOSS}


def test_次の戦闘が始まったら前の見張りは残らない(vm):
    """⚠⚠ 前の戦闘の見張りが残っていると、★次の戦闘の経験値で前の敵を倒したことにする。"""
    _fight(vm)
    vm._note_battle_end()
    assert vm._battle_settle is not None
    # ★次の戦闘（⚠ 別の敵）
    vm.exp = 2000
    vm._note_battle_start()
    vm._note_battle_groups([{"id": 5, "n": 3}])
    vm.exp = 2000 + 40
    vm._note_battle_end()
    assert 5 in vm.enemy_names.defeated
    assert BOSS not in vm.enemy_names.defeated, (
        "⚠⚠ 前の戦闘の見張りが、★次の経験値で誤って当たった")


# --- ★★ 経験値が 0 のボス（RX3-0450 / 2026-09-28）-------------------------------
#
#   ⚠⚠ 実測: ROM の敵の表で **ゾーマ(133・134) と オルテガ(135) は EXP 0**。
#     ★「経験値が増えたか」で勝ちを見ていたので、⚠ 待ち時間を延ばしても**永久に**
#       「倒した」になりませんでした（★依頼者の記録で 132/133/134/135 が欠けていた）。

def test_経験値が増えない相手は生き残ったかで見る(vm):
    vm.exp = 1000
    vm._note_battle_start()
    vm._note_battle_groups([dict(id=ZOMA_SECOND, n=1)])
    vm.exp = 1000                                   # ⚠ 増えない（★ROM の EXP が 0）
    vm._note_battle_end()
    assert ZOMA_SECOND in vm.enemy_names.defeated, "⚠⚠ 経験値 0 のボスを倒せない"
    assert vm._battle_settle is None, "⚠ 増えるはずのない経験値を待たない"


def test_全滅したら倒したにしない(vm):
    vm.party = [dict(hp=0, max_hp=20), dict(hp=0, max_hp=18)]
    vm.exp = 1000
    vm._note_battle_start()
    vm._note_battle_groups([dict(id=ORTEGA, n=1)])
    vm._note_battle_end()
    assert ORTEGA in vm.enemy_names.met
    assert ORTEGA not in vm.enemy_names.defeated, "⚠⚠ 全滅を勝ちにした"


def test_経験値が増える相手は今までどおり待つ(vm):
    """⚠ 逃げた通常の敵を勝ちにしない（★経験値で見る道は変えていない）。"""
    _fight(vm)
    vm._note_battle_end()
    assert vm._battle_settle is not None, "⚠ 経験値を待たなくなった"
    assert BOSS not in vm.enemy_names.defeated


def test_姿を変える相手は両方の姿を覚える(vm):
    """⚠⚠ 群を**上書き**していたので、★戦闘中に id が変わると前の姿が消えていた。

    ★実測: ゾーマ 133 は「会った」にも入っていなかった（⚠ 134 だけ入っていた）。
    """
    vm.exp = 1000
    vm._note_battle_start()
    vm._note_battle_groups([dict(id=ZOMA_FIRST, n=1)])
    vm._note_battle_groups([dict(id=ZOMA_SECOND, n=1)])   # ★姿が変わった
    vm._note_battle_end()
    assert vm.enemy_names.met == {ZOMA_FIRST, ZOMA_SECOND}, "⚠⚠ 前の姿が消えた"
    assert vm.enemy_names.defeated == {ZOMA_FIRST, ZOMA_SECOND}


def test_同じ姿が何度届いても増えない(vm):
    vm.exp = 1000
    vm._note_battle_start()
    for _ in range(4):
        vm._note_battle_groups([dict(id=ZOMA_SECOND, n=1)])
    groups, _before = vm._pending_battle
    assert len(groups) == 1, "⚠ 同じ id を何度も足した"


def test_ROMでボスの経験値が0であること():
    """★上の見本の値が**本物と合っている**こと（⚠ ROM が無ければ skip）。

    ⚠⚠ 見本だけだと「表の写しが古い」に気づけません（★この repo が何度も踏んだ形）。
    """
    from dq3.knowledge import enemies_seen as ES

    try:
        rows = {eid: dict(ES.master_of(eid) or ()) for eid in (BOSS, ZOMA_FIRST, ZOMA_SECOND, ORTEGA)}
    except Exception as err:                               # noqa: BLE001
        pytest.skip("⚠ 敵の表が読めません（★ROM が無い）: %s" % err)
    if not all(rows.values()):
        pytest.skip("⚠ 敵の表が読めません（★ROM が無い）")
    assert rows[ZOMA_FIRST].get("EXP") == 0, "⚠ ゾーマの経験値が 0 でなくなった"
    assert rows[ZOMA_SECOND].get("EXP") == 0
    assert rows[ORTEGA].get("EXP") == 0
    assert int(rows[BOSS].get("EXP") or 0) > 0, "⚠ バラモスの経験値が 0 になった（★見本を直す）"
    # ★本物の判定も、見本と同じ答えを出すこと
    real = VM.Dq3ViewModel._enemy_exp
    assert real(ZOMA_SECOND) == 0 and int(real(BOSS)) > 0


# --- ★★ 戦闘 → 記録 → 読み直し → 勇者メモが片づく（RX3-0447 / 2026-10-03）-------------
#
#   ⚠ 上の検査は「倒したと決めるか」まで（★記録の代わりは `_Book`）。
#   ★依頼者の症状は「倒した: ゾーマ が成立しない」なので、⚠ **本物の記録**を通して
#     保存 → 読み直し → Progress の Fact → 勇者メモの条件まで 1 本でつなぐ。
#   ⚠ ROM の名前辞書は差し替える（★名前と id の対応は test_dq3_acquired_once が ROM で見ている）。

ZOMA_MEMO = ("schema_version: 1\nleads:\n  - id: last_boss\n    memo: ためし\n"
             "    appears_when:\n      - フラグ: ship_obtained\n"
             "    retires_when:\n      - 倒した: ゾーマ\n")


def _boss_index():
    from dq3.knowledge.concepts import fold

    return {("monster", fold("ゾーマ")): [(ZOMA_FIRST, "ゾーマ"), (ZOMA_SECOND, "ゾーマ")]}


def _zoma_resolved(tmp_path, monkeypatch, book) -> list:
    """★記録（`EnemyBook`）から勇者会議の「片づいた」までを回す。"""
    from dq3.knowledge import concepts as C
    from dq3.knowledge import hero_memo as HM
    from dq3.knowledge import progress as PG
    from tests.test_dq3_hero_memo_council import _council
    from tests.test_dq3_hero_memo_scenario import _write

    monkeypatch.setattr(HM, "_index", lambda rom_path=None: _boss_index())
    got = PG.Progress(path=tmp_path / "progress.json")
    got.note_defeated(book.defeated)
    flag = {"fact_id": C.fact_id_of("event:ship_obtained", "set", None, "story"),
            "subject": "event:ship_obtained", "predicate": "set", "object": None,
            "source_observation_id": "story", "confidence": 1.0}
    memo = _write(tmp_path, ZOMA_MEMO)
    view = _council(tmp_path, memo, [flag, *got.facts()]).evaluate(save=False)
    return [c["topic_id"] for c in view.resolved]


def test_ゾーマを倒すと読み直したあとも勇者メモが片づく(tmp_path, monkeypatch):
    from dq3.knowledge.enemies_seen import EnemyBook

    vm = _VM()
    vm.enemy_names = EnemyBook(tmp_path / "enemy-names.json")
    vm.exp = 1000
    vm._note_battle_start()
    vm._note_battle_groups([dict(id=ZOMA_FIRST, n=1)])
    vm._note_battle_groups([dict(id=ZOMA_SECOND, n=1)])   # ★姿が変わる
    vm.exp = 1000                                           # ⚠ 経験値は増えない
    vm._note_battle_end()
    assert vm.enemy_names.save(force=True)

    again = EnemyBook.load(tmp_path / "enemy-names.json")   # ★起動し直したのと同じ
    assert {ZOMA_FIRST, ZOMA_SECOND} <= again.defeated, "⚠⚠ 読み直すと倒した記録が消えた"
    assert _zoma_resolved(tmp_path, monkeypatch, again) == ["last_boss"]


def test_ゾーマに全滅したら勇者メモは片づかない(tmp_path, monkeypatch):
    """★対照（⚠ 何をしても片づく形になっていないこと）。"""
    from dq3.knowledge.enemies_seen import EnemyBook

    vm = _VM()
    vm.enemy_names = EnemyBook(tmp_path / "enemy-names.json")
    vm.party = [dict(hp=0, max_hp=20)]
    vm.exp = 1000
    vm._note_battle_start()
    vm._note_battle_groups([dict(id=ZOMA_SECOND, n=1)])
    vm._note_battle_end()
    vm.enemy_names.save(force=True)

    again = EnemyBook.load(tmp_path / "enemy-names.json")
    assert ZOMA_SECOND in again.met and ZOMA_SECOND not in again.defeated
    assert _zoma_resolved(tmp_path, monkeypatch, again) == []
