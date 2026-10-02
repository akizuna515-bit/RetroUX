"""画面が使う形をここで作る（RX3-0019 / 2026-08-29）。

★★ ここが唯一の関所 ★★

指示書 §10:

    RetroUX 内部で知っていること  ≠  UI へ出してよいこと

⚠⚠ **`world-model.json`（ROM から起こした「正解」）を読みません。**
★読んでよいのは「プレイヤーが実際に見た・聞いた・訪れた」ものだけです。

    world-model.json（ROM の正解）   ⚠ ここでは触らない
            ↓ ★通してよいものだけ
    player knowledge                  ★プレイヤーが得たもの
            ↓
    ここ                              ★LocationView / Memo を作る
            ↓
    画面

`tests/test_dq3_ui.py` が「ここが world-model を読んでいない」ことを見ます。

## ⚠ 変換を一段挟む（指示書 §18）

    ROM 解析 → Domain Model → UI ViewModel → UI

★画面は ROM の番地も生データも見ません。
"""

from __future__ import annotations

import json
import pathlib

from retroux.core.bridge.state_reader import GameState, StateReader

from .models import UNKNOWN, VISITED, LocationView, MemoBook

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★Lua が書く「いまの値」。⚠ 上書きなので、読めない一瞬がある
DEFAULT_STATE = paths.lazy_work("state.json")

#: ★プレイヤーが得たことだけを貯める場所（⚠ ROM の正解ではない）
DEFAULT_KNOWLEDGE = paths.lazy_work("dq3-knowledge", "player-knowledge.json")


class _Dq3Member:
    """★`retroux` の `Member` に、DQ3 だけの項目を足した包み。

    ⚠ 元の欄はそのまま見えます（`hp` / `max_hp` / `level` …）。
    """

    #: ★`state.json` の名前 → ここでの名前
    #:   ⚠ `defence`（英）と `defense`（米）がずれているので、ここで吸収する
    EXTRA = ("luck", "wisdom", "stamina", "job_tile", "attack", "defence",
             "exp", "to_next")

    #: ★★ 装備から作り直す欄（RX3-0284 / 2026-09-18）
    #:
    #:   ⚠⚠ `state.json` の `attack` / `defence` は RAM の `$07F1` / `$07E9` で、
    #:   ★**戦闘バンクしか書きません**（= 町で装備を替えても次の戦闘まで古い）。
    #:   ⚠ すばやさも「ほしふるうでわで 2 倍」が入っていません。
    #:   → ★`derived_stats` がゲームと同じ式で作り直した値を優先します。
    #:   ⚠ ROM が読めないときは `derived` が None になり、今までどおり RAM の値。
    DERIVED = ("attack", "defence", "agility")

    def __init__(self, member, raw, derived=None) -> None:
        self._member = member
        self._raw = raw or {}
        self.derived = derived

    def __getattr__(self, name):
        derived = self.__dict__.get("derived")
        if derived is not None and name in self.DERIVED:
            return getattr(derived, name)
        if name in self.EXTRA:
            value = self._raw.get(name)
            if value is None and name == "defence":
                value = self._raw.get("defense")
            return value
        return getattr(self._member, name)


class Dq3ViewModel:
    """`state.json` と Player Knowledge から、画面が使う形を作る。

    ⚠ Qt を import しません（★画面が無くても検査できるように）。
    """

    def __init__(self, state_path=None, knowledge_path=None,
                 memo_path=None, seen_path=None, explored_path=None) -> None:
        self.state_path = pathlib.Path(state_path or DEFAULT_STATE)
        self.knowledge_path = pathlib.Path(knowledge_path or DEFAULT_KNOWLEDGE)
        self._reader = StateReader(self.state_path)
        # ★見た升の置き場（⚠ None なら `SeenMap` の既定＝`work/` の本物）。
        #   ⚠⚠ 検査は**必ず渡すこと**（★渡さないと本物を読みます / RX3-0027）。
        self.seen_path = pathlib.Path(seen_path) if seen_path else None
        # ★探索済みの置き場（RX3-0205）。⚠ 渡さなければ見た升の隣（★検査が本物を書かない）/ 製品は既定
        self.explored_path = (pathlib.Path(explored_path) if explored_path
                              else (self.seen_path.parent / "explored.json" if self.seen_path else None))
        # ★宝箱の記録の置き場（RX3-0207）。⚠ 見た升の隣（★検査が本物を書かない）/ 製品は既定
        self.chests_path = self.seen_path.parent / "chests.json" if self.seen_path else None
        # ★「しらべる」で取った隠し道具の置き場（RX3-0281 / ⚠ 宝箱と同じ決まり）
        self.hidden_items_path = self.seen_path.parent / "hidden-items.json" if self.seen_path else None
        # ★★ ⚠⚠ メモは**追記型の置き場**が正本（RX3-0016 V0 / 2026-08-30）★★
        #
        #   ⚠ 以前は `player-knowledge.json` の中に配列で持っていました。
        #     ★遊びながら増えるものを全部読み直して書き戻す形は、
        #     ⚠ 途中で落ちたときに**それまでのぶんごと消えます**。
        #
        #   ★`work/dq3-knowledge/memos.jsonl` に 1 メモ 1 行で足します。
        #   ⚠ 昔の記録（knowledge.json の中の memos）も読みます。
        from ..knowledge.memos import MemoStore

        self.memo_path = pathlib.Path(memo_path) if memo_path else (
            self.knowledge_path.parent / "memos.jsonl")
        self._store = MemoStore(self.memo_path)
        self._memos = MemoBook()
        self._visited: set[str] = set()
        self._names: dict[str, str] = {}
        self._heard: dict[str, int] = {}
        self._found: dict[str, int] = {}
        self.reload_knowledge()

    # --- ★いまの状態 ---------------------------------------------------

    def state(self) -> GameState:
        """⚠ 読めないときは**前回の値**が返る（★画面が点滅しないように）。"""
        return self._reader.read()

    def party(self):
        """★4 人ぶん。⚠ DQ3 だけの項目は**生の JSON から**足す。

        ⚠⚠ `retroux` の `Member` に `luck` や職業の欄はありません。
        ★`retroux/` は DQ3 都合で変更しない約束（`RX3-0011`）なので、
        ここで**包み直して**足します。
        """
        from ..knowledge import derived_stats

        members = list(self.state().party)
        extra = self._raw_party()
        out = []
        for i, m in enumerate(members):
            more = extra[i] if i < len(extra) else {}
            # ★装備こみの こうげき力 / しゅび力 / すばやさ（RX3-0284）
            #   ⚠ ROM も袋も無ければ None（★今までどおり RAM の値を出す）
            out.append(_Dq3Member(m, more, derived_stats.compute(more)))
        return out

    def _raw(self) -> dict:
        """⚠ `state.json` をそのまま読む（★`GameState` が落とす欄を拾うため）。

        ⚠⚠ `retroux/` は DQ3 都合で変更しない約束（`RX3-0011`）なので、
        DQ3 だけの欄（職業・運のよさ・居場所の種別）はここで拾います。

        ⚠⚠ 読めないときは**前回の値**を返します（RX3-0170 / ★`state()` と同じ約束）。
          Lua は `state.json` を「消してから置き換える」ので、読んだ瞬間に無いことがある。
          ★Turbo 中は毎秒 100 回近く書き直すので、⚠ 聞き込みが「場所が読めません」で止まった（実機）。
        """
        try:
            got = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return getattr(self, "_last_raw", None) or {}
        if not isinstance(got, dict):
            return getattr(self, "_last_raw", None) or {}
        self._last_raw = got
        return got

    def _raw_party(self):
        """⚠ `state.json` をそのまま読む（★`Member` が落とす欄を拾うため）。"""
        rows = self._raw().get("party")
        return rows if isinstance(rows, list) else []

    def gold(self):
        """⚠ 届いていなければ `None`（★0 と区別する）。"""
        return getattr(self.state(), "gold", None)

    def party_names(self) -> list[str]:
        """★4 人ぶん（指示書 §13）。⚠ 居ない枠は出さない。"""
        return [m.name for m in self.party()]

    def in_battle(self) -> bool:
        return bool(self.state().in_battle)

    # --- ★戦っている敵（RX3-0021）----------------------------------------

    @property
    def enemy_names(self):
        """★これまでに**画面で見た**敵の名前と、会った / 倒した。

        ⚠ 遅らせて読む（★起動を重くしない）。
        """
        got = getattr(self, "_enemy_names", None)
        if got is None:
            from dq3.knowledge.enemies_seen import EnemyBook

            got = self._enemy_names = EnemyBook.load()
        return got

    def enemy_groups(self):
        """いま出ている敵。⚠ 戦闘中でなければ空。

        戻り値: `[{"id": 0, "n": 1, "name": "…"}, …]`

        ⚠⚠ **名前は「画面で見て覚えた」ものだけ**（`RX3-0011` 決定 ③）。
          ★知らない敵は、知らないと分かる出し方にします。
        """
        raw = self._raw()
        groups = raw.get("enemies")
        if not isinstance(groups, list) or not groups:
            return []
        # ★画面が来ていれば、名前を覚える（⚠ 窓が出ていないときは来ない）
        from dq3.knowledge import rom_names
        from dq3.knowledge.enemies_seen import unhex

        tiles = unhex(raw.get("screen"))
        if tiles and self.enemy_names.learn(groups, tiles):
            self.enemy_names.save()
        out = []
        for group in groups:
            key = group.get("id")
            out.append({
                "id": key,
                "n": group.get("n") or 0,
                # ★ROM から起こした名前を先に（primary）、⚠ ROM が無ければ画面で読めた名前（RX3-0069 §8）
                "name": (rom_names.monster(key) or self.enemy_names.names.get(int(key))
                         if key is not None else None),
                # ⚠⚠ **倒した敵の中身だけ**（★No-Spoiler / 依頼者の選択）
                "known": self.enemy_names.knows_details(key),
            })
        # ★いまの戦闘を覚えておく（⚠ 終わったあとも出すため）
        self._last_battle = out
        return out

    # --- ★★ 戦闘が終わっても、直近の敵を出す（RX3-0025）------------------

    def battle_view(self):
        """画面に出す敵。戻り値 `(敵の一覧, いま戦っているか)`。

        依頼者 2026-08-30:「戦闘が終わっても直近のモンスター情報を
        表示させたい」。

        ⚠⚠ **終わったものを「いま戦っている」と見せません。**
          ★2 つ目の戻り値で見分けます。
        """
        fighting = self.in_battle()
        if fighting:
            # ⚠⚠ **ここで自分で覚える。** ★画面に「呼び忘れ」の余地を残さない
            #   （⚠ 順番に呼ばせる作りにすると、片方を忘れて静かに壊れる）。
            self._note_battle_start()
            got = self.enemy_groups()
            if got:
                self._note_battle_groups(got)
                return (got, True)
            # ⚠ 戦闘の入りかけで、まだ届いていない（★前のを出したまま）
            return (getattr(self, "_last_battle", []), True)
        # ★戦闘が終わった。⚠ ここで「勝ったか」を見て覚える
        self._note_battle_end()
        return (getattr(self, "_last_battle", []), False)

    def _total_exp(self) -> int:
        """★パーティの経験値の合計（⚠ 勝ったかを見分けるため）。"""
        total = 0
        for row in self._raw_party():
            try:
                total += int(row.get("exp") or 0)
            except (TypeError, ValueError):
                continue
        return total

    #: ★経験値が書かれるのを待つ回数（RX3-0303 / ⚠ 画面の更新ごとに 1 減る ≒ 秒 2〜3 回）
    BATTLE_SETTLE_TICKS = 24

    def _exp_can_grow(self, groups) -> bool:
        """★この戦闘で経験値が増えるはずか（RX3-0450 / 2026-09-28）。

        ## ⚠⚠ ROM の経験値が **0** の相手がいる

          ★実測（ROM の敵の表）:

          ```text
          132 バラモス   EXP 65535
          133 ゾーマ     EXP 0      ⚠⚠ 増えない
          134 ゾーマ     EXP 0      ⚠⚠ 増えない
          135 オルテガ   EXP 0      ⚠⚠ 増えない
          136 カンダタ   EXP 2200   ★増える（だから記録に入っていた）
          ```

          ⚠ 「勝ったか」を**経験値が増えたか**だけで見ていたので、★この 3 匹は
            どれだけ待っても「倒した」になりませんでした（⚠ 待ち時間を延ばしても直りません）。

        → ★経験値が増え得ない戦闘では、⚠ **生き残ったか**で見ます（下の `_party_alive`）。
        """
        known = False
        for one in groups or ():
            if not isinstance(one, dict):
                continue
            try:
                exp = self._enemy_exp(int(one.get("id")))
            except (TypeError, ValueError):
                continue
            if exp is None:
                return True                    # ⚠ 分からないなら今までどおり経験値で見る
            known = True
            if int(exp) > 0:
                return True
        return not known                       # ★全部 0 なら増えない（⚠ 空なら今までどおり）

    @staticmethod
    def _enemy_exp(enemy_id: int):
        """★その敵の ROM の経験値（⚠ 分からなければ None / ★検査は差し替える）。"""
        from dq3.knowledge import enemies_seen as ES

        try:
            row = ES.master_of(int(enemy_id))
        except Exception:                                  # noqa: BLE001 - ★ROM が無い環境
            return None
        return dict(row or ()).get("EXP") if row is not None else None

    def _party_alive(self) -> bool:
        """★誰か生きているか（⚠ 全滅と見分けるため / RX3-0450）。"""
        for row in self._raw_party():
            if not isinstance(row, dict):
                continue
            if not (row.get("max_hp") or row.get("hp_max") or 0):
                continue                       # ⚠ 居ない枠
            try:
                if int(row.get("hp") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _note_battle_end(self) -> None:
        """★戦闘が終わったら、会った / 倒した を覚える。

        ⚠⚠ 「倒した」は**経験値が増えたか**で見ます。
          ★逃げた・全滅したときは増えないので、これで見分けられます。

        ## ⚠⚠ 戦闘フラグが落ちた**瞬間**では決めない（RX3-0303 / 2026-09-20）

          ★依頼者「バラモスを倒した時、勇者メモから消えない」。
          ⚠ 実測: バラモス（132）は「**会った**」に入っているのに「倒した」に無い。
          ⚠⚠ 「会ったが倒していない」は **132 ただ 1 匹**でした。

          ```text
          → 戦闘フラグが落ちた時点で、★経験値がまだ書かれていなかった
             （⚠ そのとき 1 回だけ見て「勝っていない」と決めていた）
          ```

          → ★フラグが落ちたあとも**しばらく経験値を見て**、増えたら「倒した」にします。
          ⚠ 「会った」は今までどおり**すぐ**覚えます（★取りこぼさない）。
        """
        pending = getattr(self, "_pending_battle", None)
        if pending is not None:
            groups, before = pending
            self._pending_battle = None
            if not self._exp_can_grow(groups):
                # ★経験値が増え得ない相手（★ゾーマ・オルテガ）→ ⚠ 生き残ったかで見る（RX3-0450）
                self._battle_settle = None
                self._finish_battle(groups, self._party_alive())
                self._note_spells()
                return
            # ★まず「会った」を覚える（⚠ 勝ったかは、このあと見張る）
            self._finish_battle(groups, self._total_exp() > before)
            if self._total_exp() <= before:
                self._battle_settle = [groups, before, self.BATTLE_SETTLE_TICKS]
            else:
                self._battle_settle = None
        self._settle_battle()

    def _settle_battle(self) -> None:
        """⚠ 戦闘のあと、経験値が増えるのを少しだけ待つ（RX3-0303）。"""
        got = getattr(self, "_battle_settle", None)
        if not got:
            return
        groups, before, left = got
        if self._total_exp() > before:
            self._battle_settle = None
            self._finish_battle(groups, True)       # ★遅れて届いた = 倒した
            return
        got[2] = left - 1
        if got[2] <= 0:
            self._battle_settle = None              # ⚠ 逃げた・全滅した（★増えないまま）

    def _finish_battle(self, groups, won: bool) -> None:
        """★1 つの戦闘を記録に落とす（⚠ 2 度呼ばれてよい / 集合に足すだけ）。"""
        if self.enemy_names.record_battle(groups, won):
            self.enemy_names.save()
            # ★倒した敵を Lua へ（★次の戦闘の「初見か」に使う / RX3-0166）
            self.write_enemy_overlay()
        # ★呪文の結果（RX3-0271）: ⚠ 倒したかを覚えた**後**に（★図鑑のことばは倒した敵にだけ添える）
        self._note_spells()

    def _note_spells(self) -> None:
        """★この戦闘で唱えた呪文の結果を、図鑑の記録と行動履歴へ（RX3-0271）。

        ⚠ 見張り（`spell_watch`）は画面が渡す（★無ければ何もしない = 検査が本物の記録に触らない）。
        """
        watch = getattr(self, "spell_watch", None)
        if watch is None:
            return
        try:
            watch.flush(self.enemy_names)
        except Exception:                                   # noqa: BLE001 ⚠ 記録で画面を止めない
            pass

    def write_enemy_overlay(self):
        """★倒したことのある敵の番号を Lua へ渡す（⚠ 失敗しても画面は止めない）。"""
        try:
            from dq3.phase0 import enemy_book_overlay as EO

            return EO.write_overlay(self.enemy_names)
        except Exception as err:                          # noqa: BLE001 - ★画面を止めない
            self._enemy_overlay_error = str(err)
            return None

    def _note_battle_start(self) -> None:
        """★戦闘に入ったところを覚える（⚠ 経験値の「前」を押さえる）。"""
        if getattr(self, "_pending_battle", None) is None:
            self._pending_battle = ([], self._total_exp())

    def _note_battle_groups(self, groups) -> None:
        """⚠ 群が届いたら、覚えている戦闘へ足す。

        ## ⚠⚠ 上書きしていたので、姿を変える相手が消えていた（RX3-0450 / 2026-09-28）

          ★もとは `self._pending_battle = (groups, ...)` と**置き換えて**いました。
          ⚠ 画面の更新は 0.5 秒に 1 回なので、★戦闘中に敵の id が変わると
            **最後に見えた姿だけ**が記録に渡ります。
          ⚠ 実測: ゾーマ（133 → 134）のうち **133 は「会った」にも入っていませんでした**。
          → ★戦闘の間に見えた群を**全部ためます**（⚠ 同じ id は 1 回だけ）。
        """
        pending = getattr(self, "_pending_battle", None)
        if pending is None or not groups:
            return
        seen, before = pending
        merged = list(seen)
        known = {g.get("id") for g in merged if isinstance(g, dict)}
        for one in groups:
            if not isinstance(one, dict):
                continue
            if one.get("id") not in known:
                merged.append(one)
                known.add(one.get("id"))
        self._pending_battle = (merged, before)

    # --- ★勇者メモ ------------------------------------------------------

    def reload_knowledge(self) -> None:
        """★プレイヤーが得たものを読み直す。

        ⚠ まだ無ければ**空**で始める（★エラーにしない）。
        `RX3-0016` が貯め始めたら、そのまま増える。
        """
        raw = {}
        try:
            raw = json.loads(self.knowledge_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        # ⚠ 昔の記録（knowledge.json の中の配列）は、★一度だけ移します。
        #   ⚠⚠ 「両方を見る」にすると `order` が衝突します（実際に踏んだ）。
        self._store.reload()
        self._store.migrate(raw.get("memos"))
        self._memos = MemoBook(list(self._store))
        # ★出ている会話を繋いで持つ（⚠ 窓が消えるまで書かない）
        self._talk = None
        self._talk_digest = None
        self._visited = set(raw.get("visited_locations") or [])
        self._names = dict(raw.get("location_names") or {})
        self._heard = {k: int(v) for k, v in (raw.get("heard_counts") or {}).items()}
        self._found = {k: int(v) for k, v in (raw.get("found_counts") or {}).items()}

    @property
    def memos(self) -> MemoBook:
        return self._memos

    # --- ★★ 行ってみる？（RX3-0310）---------------------------------------
    #
    #   ⚠⚠ 画面から直接台帳を触らせません（★`add_memo` と同じ決まり）。
    #   ★勇者メモは**変えません**。⚠ ここは別の台帳です。

    @property
    def go_list(self):
        """★「行ってみる？」の台帳（⚠ 初めて呼んだときに読む）。"""
        got = getattr(self, "_go_list", None)
        if got is None:
            from ..knowledge.go_list import GoList

            got = self._go_list = GoList.load(getattr(self, "_go_list_path", None))
        return got

    def add_go_item(self, text: str, *, source_memo_id=None, source_location_id=None,
                    target_location_id=None):
        """★勇者メモから選んだ文を「行ってみる？」に足す（⚠ 元のメモは変えない）。"""
        book = self.go_list
        made = book.add(text, source_memo_id=source_memo_id,
                        source_location_id=source_location_id,
                        target_location_id=target_location_id)
        if made is not None:
            book.save()
        return made

    def go_items(self, *, done: bool = False) -> list:
        """★一覧（★既定は「まだ行っていない」分だけ / ⚠ DONE は消さずに隠す）。"""
        book = self.go_list
        return book.done_items() if done else book.active_items()

    def complete_go_item(self, item_id: str) -> bool:
        """★「行った」（⚠ 消さずに DONE にする / 依頼者 §11）。"""
        if not self.go_list.complete(item_id):
            return False
        self.go_list.save()
        return True

    def reopen_go_item(self, item_id: str) -> bool:
        if not self.go_list.reopen(item_id):
            return False
        self.go_list.save()
        return True

    def edit_go_item(self, item_id: str, text: str) -> bool:
        """★あとから文を直す（RX3-0317 / ⚠ 出典は変えない）。"""
        if not self.go_list.edit(item_id, text):
            return False
        self.go_list.save()
        return True

    def dismiss_reachable(self, location_id, *, restore: bool = False) -> bool:
        """★自動で出た「行ってみる？」を消し込む（RX3-0313 / ⚠ 記録は消さない）。

        ⚠⚠ 依頼者「既に完了している部分は…消し込みたい」。
        ★自動の分（`reachable.collect`）は毎回計算する派生なので、
        ⚠ **「消した」という人の判断だけ**を覚え、出すときに省きます。
        """
        book = self.go_list
        ok = book.restore(location_id) if restore else book.dismiss(location_id)
        if ok:
            book.save()
        return ok

    def _complete_go_on_arrival(self, location_id) -> list:
        """★その場所に初めて着いた → 行き先の決まっている分を終える（依頼者 §10）。

        ⚠ `target_location_id` が `None` の項目は**終えません**（★人が手で終える）。
        """
        got = self.go_list.complete_arrival(location_id)
        if got:
            self.go_list.save()
        return got

    def add_memo(self, text: str, *, source: str = "manual",
                 location_id=None, map_id=None, raw_digest=None, npc_id=None,
                 speaker=None, item_id=None, event_id=None):
        """★メモを 1 件足す。⚠ **ここが唯一の入口**。

        ## ⚠⚠ 画面から直接 `MemoStore` を触らせません

          ★いまの居場所を補うのはここの仕事です。⚠ 画面がそれぞれ
          補うと、**窓ごとに違う地点が入ります**。

        ⚠ 同じものは二度足しません（★`add_if_new`）。
        """
        at = self.position() if (location_id is None or map_id is None) else None
        if at is not None:
            kind, got_map, _x, _y = at
            if map_id is None:
                map_id = got_map
            if location_id is None and got_map is not None:
                from ..knowledge.seen_map import is_local

                location_id = "%s%s" % ("L" if is_local(kind) else "w", got_map)
        # ★item_id / event_id（RX3-0261 / 宝箱）。⚠ 渡さない呼び方は今までどおり
        extra = {k: v for k, v in (("item_id", item_id), ("event_id", event_id)) if v is not None}
        made = self._store.add_if_new(
            text, source=source, location_id=location_id, map_id=map_id,
            raw_digest=raw_digest, npc_id=npc_id, speaker=speaker, **extra)
        if made is not None:
            self._memos.add(made)
        elif getattr(self._store, "last_filled", None) is not None:
            # ★「？」の行に話者を埋めた（RX3-0236）→ ★画面の束も読み直す（⚠ 新しい行ではないので None のまま）
            self._memos = MemoBook(list(self._store))
        return made

    @property
    def memo_failures(self) -> int:
        """⚠ 読めなかった / 書けなかった件数（★黙って捨てない）。"""
        return self._store.failed

    def recent_memos(self, n: int = 3):
        """★MAP の下に出す直近 N 件（指示書 §7）。"""
        return self._memos.recent(n)

    # --- ★地点情報（⚠ ここが関所） --------------------------------------

    def place_name(self, map_id) -> str | None:
        """★map 番号 → 場所の名前（⚠ 知らなければ None / RX3-0094）。

        ⚠⚠ **画面はこれだけを呼びます。** 名前の出どころ（Master / 会話 / ROM / 仮名）を
        画面ごとに書き分けると、★片方だけ古くなります（⚠ 2026-09-07 に実際に起きた:
        店とメモは名前、地図は「地図 0」）。
        """
        if map_id is None:
            return None
        try:
            view = self.location_view("L%d" % int(map_id))
        except Exception:                                  # noqa: BLE001
            return None
        return view.name if (view.is_known and view.name) else None

    def location_view(self, location_id: str) -> LocationView:
        """★地点情報ポップアップに出す形（指示書 §5）。

        ⚠⚠ **訪れていない場所の中身は入れません。**
        ★名前すら、知らなければ `None` のままにします（`RX3-0013`: DQ3 の ROM に
        地名の平文は無く、訪れて初めて分かる）。
        """
        known = location_id in self._visited
        memos = self._memos.of_location(location_id)
        # ★名前は `location_book` から取る（⚠ 地名の判定を機能ごとに書かない / RX3-0080 §20）
        name = None
        if known and location_id[1:].isdigit():
            name = self.location_book.get_location_name(int(location_id[1:]), detailed=True)
        return LocationView(
            location_id=location_id,
            # ⚠ 訪れていないなら名前も出さない（★ROM から引いてこない）
            name=name or (self._names.get(location_id) if known else None),
            knowledge=VISITED if known else UNKNOWN,
            memo_count=len(memos),
            heard_count=self._heard.get(location_id, 0) if known else 0,
            found_count=self._found.get(location_id, 0) if known else 0,
            # ★直近 3 件だけ（指示書 §5.1）。
            # ⚠ 並びは `MemoBook.newest()`、字面は `Memo.line`（★4 番目の画面 /
            #   RX3-0118 で 3 つ直したときに、ここだけ見落としていた）
            highlights=[m.line for m in MemoBook(memos).newest(3)],
        )

    def known_locations(self) -> list[str]:
        """★地図に出してよい地点（指示書 §11）。

        ⚠ ROM にある全地点を返しません。★訪れたものだけ。
        """
        return sorted(self._visited)

    # --- ★地図の現在地 --------------------------------------------------

    # --- ★街ナビ（RX3-0058）: state.json の材料。⚠ 番地は Lua と service だけが知る ------
    talk_tag = None          #: ★聞き込み中の相手（{label, npc_id, map_id}）。★会話の文をこの形で残す
    last_talk_text = None    #: ★直近に勇者メモへ流した会話の文（★聞き込みの heard 用）
    _nav_pages_used = None   #: ★メモにした `nav.talk_pages` の鍵（seq, talk_frame）。⚠ 同じページを 2 度使わない

    def nav_status(self):
        got = self._raw().get("nav")
        return got if isinstance(got, dict) else None

    def restock_status(self):
        """★補充の進み具合（RX3-0066 / RX3-0119）。⚠ 届いていなければ None。"""
        got = self._raw().get("restock")
        return got if isinstance(got, dict) else None

    def item_status(self):
        """★道具を使う進み具合（RX3-0159）。⚠ 届いていなければ None。"""
        got = self._raw().get("item")
        return got if isinstance(got, dict) else None

    def last_talk(self):
        got = self._raw().get("last_talk")
        return got if isinstance(got, dict) else None

    def npc_appearance_hex(self):
        """★見た目の枠 → 見た目 id の表（WRAM `$6ABE` / RX3-0304）。⚠ 届いていなければ `None`。"""
        got = self._raw().get("npc_appearance")
        return got if isinstance(got, str) and got else None

    def npc_table_hex(self):
        got = self._raw().get("npc_tbl")
        return got if isinstance(got, str) else None

    def time_byte(self):
        got = self._raw().get("time_byte")
        return int(got) if isinstance(got, int) else None

    def facing(self):
        """★勇者が向いている方角（0=上 / 1=右 / 2=下 / 3=左）。⚠ 届いていなければ `None`。

        ★会話の相手を決めるのに使います（RX3-0133）。⚠ 番地は Lua と profile だけが知っています。
        """
        got = self._raw().get("facing")
        return int(got) % 4 if isinstance(got, int) else None

    def auto_status(self):
        """★自動戦闘の判断（`state.json.auto` / RX3-0147）。⚠ 届いていなければ空。

        ⚠⚠ **理由の全文はここに来ません**（★ログのまま）。
        ここに来るのは「戦況・必要な役割・各人の手」だけです。
        """
        got = self._raw().get("auto")
        return got if isinstance(got, dict) else {}

    def rura_bits(self):
        """★ゲーム自身が持つ「戻れる町」の生ビット（`$0750` / RX3-0113）。

        ⚠⚠ **どの町かはここでは決めません。** ★12 バイトの 16 進をそのまま返し、
        意味づけ（ルーラ表と突き合わせる）は `knowledge/reachable.py` の仕事です。
        ⚠ Lua が載せていなければ `None`（★異常ではない）。
        """
        got = self._raw().get("rura")
        return got if isinstance(got, str) and got else None

    def conversation_open_now(self) -> bool:
        """★いま会話の窓が出ているか（⚠ 「B を押した」ではなく画面で見る）。"""
        tiles = self._screen_tiles()
        if not tiles:
            return False
        from ..knowledge.conversation import conversation_on_screen

        return conversation_on_screen(tiles) is not None

    def position(self):
        """いまどこに居るか。⚠ 届いていなければ `None`（★0 と区別する）。

        戻り値: `(種別, 地図番号, x, y)`

        ⚠⚠ **世界地図とローカルで座標の意味が違います。**
          ★Lua 側（`dq3/phase0/dev.lua` の `where()`）が、種別に応じて
          `$2A/$2B`（世界）と `$30/$31`（ローカル）を選んで送ってきます。
          ⚠ 地図番号は**ローカルのときだけ**入ります
          （★世界地図では `$8B` に前の値が残っているので、送りません）。
        """
        # ⚠⚠ `loc_kind` は `retroux` の `GameState` に無い欄なので、
        #   ★生の JSON から拾う（`retroux/` は DQ3 都合で変更しない）。
        raw = self._raw()
        kind = raw.get("loc_kind")
        x, y = raw.get("map_x"), raw.get("map_y")
        if kind is None or x is None or y is None:
            return None
        return (int(kind), raw.get("map_id"), int(x), int(y))

    def world_edges(self):
        """★入口・出口の升（RX3-0275）。★Lua（`world_edges.lua`）が毎フレーム見たもの。⚠ 無ければ None。

        戻り値: `(入口の升, 出口の升)`。★入口はローカルに居る間、出口は世界地図に居る間だけ届く。
        ⚠ 0.5 秒おきの `position()` では、町へ入る 1〜2 歩手前・出たあと歩いた升になる。
        """
        try:
            raw = self._raw() or {}
        except Exception:                                    # noqa: BLE001 ★届いていないだけ
            return None, None

        def pair(kx, ky):
            x, y = raw.get(kx), raw.get(ky)
            return (int(x), int(y)) if isinstance(x, int) and isinstance(y, int) else None

        return pair("entry_x", "entry_y"), pair("exit_x", "exit_y")

    # --- ★ゲーム内のタイルの絵（RX3-0043）--------------------------------

    @property
    def tile_art(self):
        """★★ 地図の升を、ゲーム内のタイルで描くための絵。

        ⚠⚠ **出せなければ `None`**（★画面は色ブロックのまま）。
          材料は実行時の RAM / PPU にしかなく、`dq3/phase0/map_art.lua` が
          `work/dq3-probe/` へ置きます。⚠ FCEUX が動いていなければ空です。

        ## ⚠ 毎回作り直しません

          ```text
          地図が同じ           ★覚えた絵をそのまま返す
          地図が変わった       ⚠ 作り直す（★64 升ぶんの 16x16）
          材料がまだ無い       ★None（⚠ 例外にしない）
          ```

          ⚠ ファイルの更新時刻で見ます。★中身を毎回読み直すと、
            1 秒に 2 回 8KB を展開することになります。
        """
        import os

        from dq3.knowledge import tile_art as mod

        root = self.tile_art_dir
        try:
            stamp = os.stat(root / mod.RUNTIME_JSON).st_mtime_ns
        except OSError:
            return None                   # ⚠ まだ書かれていない
        if stamp == getattr(self, "_tile_art_for", None):
            return getattr(self, "_tile_art", None)
        got = mod.from_runtime(root)
        self._tile_art_for = stamp
        self._tile_art_runtime = got
        self._tile_art = got.art if got is not None else None
        return self._tile_art

    @property
    def tile_art_dir(self):
        """★材料の置き場。⚠ 検査から差し替えられます（RX3-0027 と同じ約束）。"""
        got = getattr(self, "_tile_art_dir", None)
        if got is None:
            # ⚠⚠ ここは repo 直下を直に指していました（★隔離が効かない / 2026-09-10）。
            #   ★書き先は `dq3/paths.py` の 1 か所を通します（RX3-0128）。
            from dq3 import paths as P3

            got = self._tile_art_dir = P3.work("dq3-probe")
        return got

    @tile_art_dir.setter
    def tile_art_dir(self, value) -> None:
        self._tile_art_dir = pathlib.Path(value)
        self._tile_art_for = None         # ⚠ 置き場が変わったら覚え直す

    @property
    def tile_art_runtime(self):
        """⚠ 実機が書いた地図そのもの（★突き合わせ用。画面は使わない）。"""
        self.tile_art                     # ★読み込みを起こす
        return getattr(self, "_tile_art_runtime", None)

    # --- ★見た升を貯める（RX3-0023）--------------------------------------

    @property
    def seen(self):
        """★これまでに**画面で見た**升。⚠ 遅らせて読む（起動を重くしない）。

        ⚠⚠ 置き場は**外から渡せます**（RX3-0027 / 2026-08-30）。
          ★渡さないとき（＝製品）はこれまでどおり `work/` の既定。

          ⚠ 以前はここだけ受け取れず、検査が**本物のデータ**を読んでいました。
          ★依頼者が遊ぶまでは `work/` が空だったので緑で、
          ⚠ 遊んだ翌日に赤くなりました（★「まっさらでの緑」は当てにならない）。
        """
        got = getattr(self, "_seen", None)
        if got is None:
            from dq3.knowledge.seen_map import SeenMap

            got = self._seen = SeenMap.load(self.seen_path)
        return got

    # --- ★探索済みの升（RX3-0205 / ダンジョン探索MAP v1 Phase A）-------------

    @property
    def explored(self):
        """★探索済みの升（★勇者と同じ層として画面に見えた升 / ⚠ 遅らせて読む）。"""
        got = getattr(self, "_explored", None)
        if got is None:
            from dq3.knowledge.explored_map import ExploredMap

            got = self._explored = ExploredMap.load(self.explored_path)
        return got

    def note_explored(self, kind, map_id, x, y) -> int:
        """★いま映っていて勇者と同じ層の升を「探索済み」にする（RX3-0205）。戻り値: 増えた数。

        ⚠ ローカル（町・洞窟・塔）だけ（★世界地図は層を持たない / 見た升がそのまま探索済み）。
        ⚠ 今の地図の実機の升（map_art）が無ければ記録しない（★前の地図の値で層を決めない / RX3-0046）。
        """
        from dq3.knowledge import explored_map as EM
        from dq3.knowledge.seen_map import is_local, map_key

        if not is_local(kind):
            return 0
        live = self.tile_art_runtime
        if live is None or live.kind != kind or live.map_id != map_id:
            return 0
        added = self.explored.mark_cells(map_key(kind, map_id), EM.visible_cells(live, x, y))
        if added:
            self.explored.save()
        return added

    # --- ★宝箱（RX3-0207 / ダンジョン探索MAP v1 Phase C）--------------------

    @property
    def chests(self):
        """★見つけた・開けた宝箱の記録（⚠ 遅らせて読む / ★ROM とのつなぎは dq3/knowledge/chest_book）。"""
        got = getattr(self, "_chests", None)
        if got is None:
            from dq3.knowledge.chest_book import ChestBook

            got = self._chests = ChestBook.load(self.chests_path)
        return got

    def note_chests(self, kind, map_id) -> int:
        """★探索済みの升にある宝箱を「見つけた」、印が立った宝箱を「開けた」にする。戻り値: 変わった数。

        ⚠ ローカル（町・洞窟・塔）だけ。★印は state.json の `chest_bits`（Lua / `$608E`〜）。
        """
        from dq3.knowledge.seen_map import is_local, map_key

        if not is_local(kind) or map_id is None:
            return 0
        if not hasattr(self, "chests_path"):
            # ⚠⚠ 置き場が決まっていない入れ物（★__init__ を通っていない検査）→ 記録しない
            #   （⚠ 既定の置き場 = work/ の本物へ書いてしまうため）
            return 0
        bits = self._raw().get("chest_bits")
        changed = self.chests.update(map_id, self.explored.cells(map_key(kind, map_id)), bits)
        if changed:
            self.chests.save()
        return changed

    def chest_marks(self, map_id) -> list:
        """★MAP に出す宝箱（x, y, 状態）。⚠ 見つけたものだけ。"""
        return self.chests.marks(map_id)

    def note_chest_memos(self) -> list:
        """★★ いま開いた宝箱を勇者メモへ 1 件ずつ（RX3-0261 / 依頼者「どこで何を入手したか」）。戻り値: 足した Memo。

        ```text
        材料     `chests.json` の記録（★`ChestBook.take_opened` = いま開いた宝箱だけ）
        文       `chest_book.memo_text`（場所　宝箱：品 を入手 / 魔物だった / からっぽだった）
        場所     場所の台帳の名前（★階は Master の名前か `#3` / ⚠ 推測しない）
        見分け   event_id = chest:<宝箱>（⚠ 本文 + 場所で見ると同じ品の別の宝箱が消える）
        ```
        ⚠ 過去に開けた宝箱（読み込んだ記録）・見つけたときにもう開いていた宝箱は流さない。
        ⚠ セーブを読み直しても、開けた記録は OPENED のまま → ★同じ宝箱で 2 度は出ない。
        """
        book = getattr(self, "_chests", None)
        if book is None or not hasattr(self, "chests_path"):
            return []                  # ⚠ まだ宝箱を 1 度も見ていない / 置き場の無い入れ物（検査）
        from dq3.knowledge import chest_book as CB

        out = []
        for rec in book.take_opened():
            map_id = rec.get("map_id")
            place, location_id = None, None
            try:
                loc = self.location_book.get_location(map_id)
                location_id = loc.location_id
                place = self.location_book.get_location_name(map_id, detailed=True)
            except Exception:                                  # noqa: BLE001 ★場所が分からないだけ
                pass
            item = rec.get("item_id") if rec.get("reward") == "item" else None
            made = self.add_memo(CB.memo_text(rec, place), source="chest",
                                 location_id=location_id or ("L%s" % map_id), map_id=map_id,
                                 item_id=None if item is None else str(item),
                                 event_id="chest:%s" % rec.get("object_id"))
            if made is not None:
                out.append(made)
        return out

    @property
    def hidden_items(self):
        """★「しらべる」で取った隠し道具の記録（RX3-0281 / ⚠ 遅らせて読む）。"""
        got = getattr(self, "_hidden_items", None)
        if got is None:
            from dq3.knowledge.hidden_items import HiddenItemBook

            path = getattr(self, "hidden_items_path", None)
            got = self._hidden_items = HiddenItemBook.load(path)
        return got

    def note_hidden_memos(self) -> list:
        """★★ いま「しらべる」で取った隠し道具を勇者メモへ（RX3-0281）。戻り値: 足した Memo。

        ```text
        材料   state.json の `chest_bits` の **26 バイト目**（★通し番号 200〜207 / Lua の dev.lua）
        升     `search_spots`（★map / x / y / 品番）→ 場所の名前は場所の台帳から
        文     `hidden_items.memo_text`（★「<場所>　しらべる：<道具の名前> を入手」）
               ⚠⚠ 見本に原作の地名・道具名を書きません（RX3-0433 / 2026-10-01）
        見分け event_id = hidden:<通し番号>（⚠ 同じ品が別の升にあっても消えない）
        ```
        ⚠ 初めて印を見たときに既に立っていた分は流しません（★前から取ってあった分）。
        ⚠ セーブを読み直しても、記録は残るので 2 度は出ません。
        """
        if not hasattr(self, "hidden_items_path"):
            return []                  # ⚠ 置き場の無い入れ物（★検査）→ 本物の work/ へ書かない
        from dq3.knowledge import hidden_items as HI

        book = self.hidden_items
        if book.update(self._raw().get("chest_bits")):
            book.save()
        rows = book.take_new()
        if not rows:
            return []
        spots = HI.spots()
        out = []
        for rec in rows:
            spot = spots.get(int(rec["serial"]))
            map_id = None if spot is None else spot.map_id
            place, location_id = None, None
            if map_id is not None:
                try:
                    loc = self.location_book.get_location(map_id)
                    location_id = loc.location_id
                    place = self.location_book.get_location_name(map_id, detailed=True)
                except Exception:                              # noqa: BLE001 ★場所が分からないだけ
                    pass
            name = None
            if spot is not None:
                try:
                    from dq3.knowledge import rom_names

                    name = rom_names.item(spot.item_id)
                except Exception:                              # noqa: BLE001 ★名前が引けないだけ
                    pass
            made = self.add_memo(HI.memo_text(name, place), source="search",
                                 location_id=location_id or (None if map_id is None else "L%s" % map_id),
                                 map_id=map_id,
                                 item_id=None if spot is None else str(spot.item_id),
                                 event_id="hidden:%d" % int(rec["serial"]))
            if made is not None:
                out.append(made)
        return out

    #: ★宝箱・しらべる が「その品は自分が出した」と言ってくるのを待つ回数（RX3-0312）
    #:
    #:   ⚠⚠ 印（`chest_bits`）と持ち物（`party[].items`）は**同じ更新で揃うとは限りません**。
    #:     ★先に持ち物が増えると、⚠ 宝箱の品まで「入手：…」で二重に出ます。
    #:   → ★少し待ってから決めます（`_settle_battle` と同じ作法 / RX3-0303）。
    ITEM_SETTLE_TICKS = 12

    def note_item_memos(self, new_ids=(), *, claimed=()) -> list:
        """★★ 持ち物が増えたことで気づいた品を勇者メモへ（RX3-0312）。戻り値: 足した Memo。

        ⚠⚠ 依頼者「ひかりのたまの取得イベントが拾えない ※竜の女王から与えられる」。

        ```text
        ★今まで  勇者メモへ書く口は 宝箱 と しらべる の 2 本だけ
                  ⚠ どちらも「印が立った」がきっかけ → 会話で渡される品はどちらも立たない
        ★これから 持ち物が増えたことに気づいたら、⚠ 宝箱・しらべる が名乗り出るのを待ち、
                  ★誰も名乗らなければ「入手：…」として残す
        ```

        ⚠ 場所は**メモを作った瞬間の現在地**です（★宝箱のように「そこで取った」とは言えません）。
        ⚠ `event_id = item:<品番>` なので、★同じ品を 2 度は書きません。
        """
        queue = getattr(self, "_item_settle", None)
        if queue is None:
            queue = self._item_settle = {}
        for raw in claimed or ():                 # ★宝箱・しらべるが出した品は取り消す
            try:
                queue.pop(int(raw), None)
            except (TypeError, ValueError):
                continue
        for raw in new_ids or ():
            try:
                key = int(raw)
            except (TypeError, ValueError):
                continue
            queue.setdefault(key, self.ITEM_SETTLE_TICKS)
        if not queue:
            return []
        ready = []
        for key in list(queue):
            queue[key] -= 1
            if queue[key] <= 0:
                del queue[key]
                ready.append(key)
        out = []
        for item_id in ready:
            made = self._add_item_memo(item_id)
            if made is not None:
                out.append(made)
        return out

    def _add_item_memo(self, item_id: int):
        """★1 件ぶんの「入手：…」（⚠ 名前や場所が引けなくても落ちない）。"""
        from dq3.knowledge import progress as PG

        name = None
        try:
            from dq3.knowledge import rom_names

            name = rom_names.item(int(item_id))
        except Exception:                                  # noqa: BLE001 ★名前が引けないだけ
            pass
        place, location_id, map_id = None, None, None
        at = self.position()
        if at is not None and at[1] is not None:
            from ..knowledge.seen_map import is_local

            if is_local(at[0]):
                map_id = int(at[1])
                try:
                    location_id = self.location_book.get_location(map_id).location_id
                    place = self.location_book.get_location_name(map_id, detailed=True)
                except Exception:                          # noqa: BLE001 ★場所が分からないだけ
                    location_id = "L%d" % map_id
        return self.add_memo(PG.memo_text(name, place), source="item",
                             location_id=location_id, map_id=map_id,
                             item_id=str(int(item_id)), event_id="item:%d" % int(item_id))

    # --- ⚠⚠ 名前の候補は外しました（RX3-0309 / 2026-09-20）-------------------
    #
    #   ★ここには `name_candidates()`（会話の記録 + 勇者メモから名前の候補を作る）が
    #     ありました。⚠ 依頼者の指示で **命名は手入力に一本化**しました。
    #
    #   ★残っているもの: 仮名（`location_book.provisional_for`）/ 人が付けた名前 /
    #     付け直し（`location_book.rename`）/ 挨拶から地名を覚える（`locations.greeting_place`）。
    #   ⚠ 会話の記録（`concepts.observations`）は**消していません**
    #     — ★勇者会議・Guide・聞き込みが同じものを読んでいます。

    def note_here(self):
        """★★ いまいる場所を「訪れた」ことにする（RX3-0016 V0）★★

        ## ⚠⚠ 誰も書いていませんでした

          `visited_locations` は **読む所しかありませんでした**。
          ★`location_view` は `location_id in self._visited` で
          「知っているか」を決めるので、⚠ **永遠に「？」のまま**でした。

          ⚠ エラーは出ません。★地点情報が**一度も出ない**という顔で出ます。

        ## ★はじめての場所は、メモにも残す

          ⚠⚠ **ROM から地名を引いてきません。** DQ3 の ROM に地名の平文は無く
          （`RX3-0013`）、★出してよいのは「人が Master に書いた名前」「会話で聞いた名前」
          「自分で付けた仮名」だけです（No-Spoiler / `RX3-0080` 指示書 §19）。

        ## ⚠⚠ 発見は **location_id** で数える（`RX3-0080` 指示書 §14）

          ★アリアハン城の 1F → 2F → B1 は **map_id が違うだけで同じ場所**です。
          ⚠ map_id で数えると、階を移るたびに「見つけた」とメモが増えます。

        戻り値: ★はじめての場所なら足した `Memo`、⚠ そうでなければ `None`。
        """
        at = self.position()
        if at is None:
            return None
        kind, map_id, x, y = at
        book = self.location_book
        from ..knowledge.seen_map import is_local

        # ★入口・出口の升（RX3-0275）。⚠ 0.5 秒おきの位置では町の 1〜2 歩手前になる
        edges = getattr(self, "world_edges", None)
        entry_at, exit_at = edges() if edges is not None else (None, None)
        if not is_local(kind) or map_id is None:
            # ★世界地図は「地点」ではない。⚠ ただし**升は覚える**（仮名の方角に使う）
            # ⚠⚠ 2026-09-20（RX3-0315）: ここは長らく **kind 0 だけ**でした。
            #   ★アレフガルド（kind 2）の地点は「最後に居た**上の世界**の升」を持ち、
            #   ⚠ 緑の丸が下の世界の地図に**まったく違う升**で出ていました。
            from ..knowledge.location_book import WORLD_KINDS

            if kind in WORLD_KINDS:
                book.note_world(x, y, exit_xy=exit_at, kind=kind)
                book.save()
            return None
        # ★★ 「その場所に初めて着いたか」（RX3-0310）
        #   ⚠⚠ `got["first"]` は「台帳にその行が**新しくできた**」です。
        #     ★Master から先に行ができていると `first` は False になります。
        #   → ★着いたかどうかは **`visited` が False だったか**で見ます。
        before = book.locations.get(book.location_id_of(map_id))
        was_visited = bool(before is not None and before.visited)
        got = book.enter(map_id, world_xy=entry_at)
        loc = got["location"]
        if not was_visited:
            # ★行き先の決まっている「行ってみる？」を終える（⚠ 決まっていない分は触らない）
            self._complete_go_on_arrival(loc.location_id)
        # ★既存の `visited_locations`（`L<map_id>`）も保つ（⚠ visit Fact / Guide Rule が使う）
        map_key = "L%d" % map_id
        if map_key not in self._visited:
            self._visited.add(map_key)
            self.save_knowledge()
        book.save()
        if not got["first"] or loc.memo_done:
            return None                  # ⚠ 同じ場所の別の階では増やさない
        book.mark_memo_done(loc.location_id)
        book.save(force=True)
        from ..knowledge.location_book import memo_text

        return self.add_memo(memo_text(got["name"] or "この場所", got["provisional"]),
                             source="discovery", location_id=loc.location_id, map_id=map_id)

    def note_conversation(self):
        """★★ 画面に出ている文を、勇者メモに残す（RX3-0016 V0）★★

        ## ⚠⚠ 戦っている間は拾いません

          ★戦闘中の窓（敵の一覧・コマンド）まで拾うと、
          ⚠ メモが「スライムー1ひき」で埋まります（★実際にそうなった）。
          戦闘の中身は `enemies_seen` の仕事です。

        ## ⚠ 同じ窓は二度書きません

          ★窓は出ているあいだ何フレームも同じです。⚠ 生タイルの指紋
          （`raw_digest`）で見分けます。

        ## ⚠⚠ **窓が閉じてから書きます**（★2026-08-31 実機で直した）

          ★画面を見て記録するので、⚠ 文が流れ込んでいる途中も読みます。
          そのまま足すと、**同じ会話が断片で 4 件**入りました。

          ```text
          26 ＊「ゆうやけの そらを みるとき  あやしげな かげ
          27 …しれぬ。＊「ちか
          28 あやしげな かげには …そのかげま          ⚠ 送られて頭が欠けた
          29 なにか いるかも しれぬ。…ちかづくことだな。
          ```

          ★見本は架空の文です（⚠ 原作の会話は配布物に入れません / RX3-0433）。

          → ★出ているあいだは**繋いで持っておき**、窓が消えたときに
            `＊「` ごとに切って足します（⚠ 上の 4 件は 2 件になります）。

        戻り値: ★足した `Memo`、⚠ 無ければ `None`。
        """
        if self.in_battle():
            return self._flush_talk()
        # ★★ 聞き込みの会話は、街ナビが話し終えるまで書かない（RX3-0229 / 2026-09-13）。
        #   ⚠ 0.5 秒おきの読みでは Turbo のページが飛び、重ならない断片を「別の文」とみなして
        #     1 人の話が 3 件に割れていた（依頼者「2 段目から 以降が残っていない」）。
        #   ★話し終えたら `nav.talk_pages`（Lua が 4 フレームおきに拾ったページ）で 1 件にする。
        waiting = self._nav_talk_running()
        tiles = self._screen_tiles()
        if not tiles:
            return None if waiting else self._flush_talk()
        from ..knowledge.conversation import (conversation_on_screen,
                                              join_continuation)

        got = conversation_on_screen(tiles)
        if got is None:
            # ★窓が閉じた → ここで書く（⚠ 街ナビがまだ送っている間は待つ）
            return None if waiting else self._flush_talk()
        text, digest = got
        if self._talk is None:
            self._talk, self._talk_digest = text, digest
            return None
        merged = join_continuation(self._talk, text)
        if merged is None:
            if waiting:
                # ★同じ人の続き（⚠ ページが飛んで重ならないだけ）。★割らずに持っておく
                self._talk, self._talk_digest = self._talk + text, digest
                return None
            # ⚠ 別の文が始まった。★前のを書いてから、新しいのを持つ
            made = self._flush_talk()
            self._talk, self._talk_digest = text, digest
            return made
        self._talk, self._talk_digest = merged, digest
        return None

    def _nav_talk_running(self) -> bool:
        """★聞き込みで街ナビが話しかけ〜送りの途中か（RX3-0229）。⚠ 分からなければ False。"""
        if not self.talk_tag:
            return False
        nav = self.nav_status() or {}
        return bool(nav.get("active")) and nav.get("phase") in ("talk", "close")

    def _take_nav_pages(self):
        """★街ナビが拾ったページを 1 本の文にする（RX3-0229）。⚠ 使えなければ `None`。

        ★聞き込み（`talk_tag`）で、街ナビが話し終えたあとだけ使う。⚠ 1 回の会話につき 1 度だけ
        （★鍵は `seq` と `talk_frame`）。戻り値は `(文, 指紋)`。
        """
        if not self.talk_tag:
            return None
        nav = self.nav_status() or {}
        if nav.get("active") and nav.get("phase") in ("talk", "close"):
            return None                              # ⚠ まだ拾っている途中
        pages = nav.get("talk_pages")
        if not isinstance(pages, list) or not pages:
            return None
        key = (nav.get("seq"), nav.get("talk_frame"))
        if key == self._nav_pages_used:
            return None
        # ★読めなくても使ったことにする（⚠ 毎回の読みで同じページを解き直さない）
        self._nav_pages_used = key
        from ..knowledge.conversation import text_of_pages

        return text_of_pages(pages)

    def _flush_talk(self):
        """★持っている会話を 1 件として足す（⚠ 無ければ何もしない）。

        ⚠⚠ 2026-08-31: `＊「` で**切っていました**。★依頼者の指摘どおり、
          `＊「` は話し手が変わる印ではないので、**1 会話 = 1 メモ**にします。
        """
        text, digest = self._talk, self._talk_digest
        self._talk, self._talk_digest = None, None
        # ★★ 聞き込みは街ナビのページを正本にする（RX3-0229）。⚠ 画面の読みは 0.5 秒おきで欠ける。
        #   ★ページが無い（手で話した / 古い Lua / 窓が読めない）ときは今までどおり。
        #   ⚠ `getattr`: 検査の小さな偽物（`_flush_talk` だけ借りる）にはこの口が無い
        take = getattr(self, "_take_nav_pages", None)
        paged = take() if take is not None else None
        if paged is not None:
            text, digest = paged
        if not text:
            return None
        from ..knowledge.conversation import tidy_message

        got = tidy_message(text)
        if not got:
            return None
        # ★挨拶「Xの むらに ようこそ」を聞いたら、この map の名前として覚える
        #   （RX3-0076 / Location Naming v1。⚠ ROM から地名は引かない。★聞いたものだけ）
        self._learn_place_name(got)
        tag = self.talk_tag
        if tag:
            # ★聞き込みの会話は「見た目の字「…」」の 1 行（指示書 §15-2）。★heard には本文を残す
            from ..knowledge.town_service import TownService

            # ⚠⚠ RX3-0184（2026-09-12）: ここは `= got` で**上書き**していました。
            #   ★1 人の会話が 2 つ以上の文に分かれると、⚠ 会話の台帳には**最後の文だけ**が残った
            #   （★ある町の人の 2 文のうち**前半が消え**、後半だけになった）。
            #   ⚠⚠ 註に原作の台詞を書きません（RX3-0433 / 2026-10-01）。
            #   → ★同じ相手の間はつなぐ（★`town_bar` が相手ごとに None へ戻す）
            self.last_talk_text = got if not self.last_talk_text else self.last_talk_text + got
            # ★npc_id も残す（⚠ 2026-09-05 まで null だった。★heard の台帳と突き合わせられるように / RX3-0077）
            label = tag.get("label") or None
            return self.add_memo(TownService.memo_text(label or "？", got), source="npc_talk",
                                 raw_digest=digest, map_id=tag.get("map_id"), npc_id=tag.get("npc_id"),
                                 speaker=label)
        # ★★ 手で話した会話でも、相手が分かるなら残す（RX3-0133 / 2026-09-09）。
        #
        #   ⚠⚠ ここは長らく「相手が分からない」として `話者なし` にしていました。
        #     ★画面には `？「…` と出ます（依頼者「老人と会話したが、ハテナになっている」）。
        #   ★向き（`$0644`）と NPC の**いまの位置**が分かれば、目の前の人は決まります。
        #   ⚠ 決まらなければ、これまでどおり**空のまま**にします（★推測で名乗らせない）。
        speaker, npc_id, map_id = self._talker_now()
        return self.add_memo(got, source="conversation", raw_digest=digest,
                             speaker=speaker, npc_id=npc_id,
                             map_id=map_id if speaker else None)

    def _talker_now(self):
        """★いま目の前に居る人の見た目の字（⚠ 分からなければ `(None, None, None)`）。"""
        try:
            at = self.position()
            facing = self.facing()
            if at is None or facing is None:
                return None, None, None
            kind, map_id, x, y = at
            if kind == 0 or kind == 2:
                return None, None, None            # ⚠ 世界地図には話す相手が居ない
            from ..knowledge.town_service import TownService

            service = getattr(self, "_town_service", None)
            if service is None:
                service = self._town_service = TownService()
            npc = service.npc_in_front(map_id, self.time_byte(), self.npc_table_hex(),
                                       (x, y), facing)
            if npc is not None:
                return service.appearance_label(npc["appearance_id"]), npc.get("npc_id"), map_id
            # ★★ 表がどれか分からない場面でも、**見た目だけ**は出す（RX3-0304 / 2026-09-20）。
            #   ⚠⚠ 依頼者「王様とイベントセリフを話すが、？になっている」（★玉座は UNKNOWN）。
            #   ⚠ `npc_id` は**決めません**（★表が分からない = 誰かは決められない / 推測しない）。
            got = service.appearance_in_front(self.npc_table_hex(), self.npc_appearance_hex(),
                                              (x, y), facing)
            if got is None:
                return None, None, None
            return got["label"], None, map_id
        except Exception:                                  # noqa: BLE001 - ★分からなければ空でよい
            return None, None, None

    def equip_members(self) -> list:
        """★装備比較の材料（⚠ 職業・性別・袋。★居ない枠は入れない / RX3-0083）。

        ⚠ 袋と職業は Lua が `state.json` へ送っています（`party[].items` / `party[].class_gender`）。
          ★送られていない項目は**そのまま欠けたまま**にします（⚠ 推測で埋めない）。

        ⚠⚠ 番地やビットの意味を**ここでは持ちません**。★`item_info` に聞きます
          （`test_UIはROMの正解を読まない`: 画面から `dq3rom` を直に触らない）。
        """
        from ..knowledge import item_info as II

        out = []
        for row in self._raw_party():
            if not isinstance(row, dict):
                continue
            if not (row.get("max_hp") or row.get("hp_max") or 0):
                continue                       # ⚠ 居ない枠
            class_id, female = II.split_class_gender(row.get("class_gender"))
            out.append({
                "name": row.get("name"),
                "class_id": class_id,
                "female": female,
                "inventory": list(row.get("items") or ()),
            })
        return out

    def ai_members(self) -> list:
        """★戦闘 AI の役割提案の材料（RX3-0127）。⚠ 居ない枠は入れない。

        ★`spells`（8 バイト）と `class_gender` と `attack` を**そのまま**渡します。
          意味の解釈は `dq3/battle_ai/settings.suggest_roles` → `spell_info` が引き受けます
          （⚠ 画面は `dq3rom` を直に触らない）。
        """
        out = []
        for i, row in enumerate(self._raw_party()):
            if not isinstance(row, dict):
                continue
            if not (row.get("max_hp") or row.get("hp_max") or 0):
                continue                       # ⚠ 居ない枠
            got = dict(row)
            got["slot"] = "p%d" % (i + 1)
            out.append(got)
        return out

    @property
    def location_book(self):
        """★場所の名前を取る**唯一の入口**（RX3-0080 / 指示書 §20）。"""
        got = getattr(self, "_location_book", None)
        if got is None:
            from ..knowledge.location_book import LocationBook

            # ⚠⚠ 置き場は **`knowledge_path` と同じフォルダ**にします。
            #   ★決め打ちにすると、検査が**本物の記録を書き換え**ます
            #   （2026-09-05 に実際に踏んだ。⚠ `RX3-0053` の「検査が本物のセーブ保護を止めた」と同じ形）。
            from ..knowledge.locations import NAMES_PATH

            # ★`location-names.csv` の name を既定の名前にする（RX3-0439）
            got = self._location_book = LocationBook.load(
                path=self.knowledge_path.parent / "location-book.json", names_path=NAMES_PATH)
        return got

    def _learn_place_name(self, text: str) -> str | None:
        """★挨拶から地名を覚える（⚠ いま居る map に結ぶ。★世界地図では覚えない）。

        ★2026-09-05（RX3-0080）: 覚えた名前は **Location へも昇格**させます。
        ⚠ `location_id` は変えません（★過去のメモ・訪問記録との繋がりを切らない）。
        """
        from ..knowledge import locations as LOC

        at = self.position()
        if at is None:
            return None
        kind, map_id, _x, _y = at
        from ..knowledge.seen_map import is_local

        if not is_local(kind) or map_id is None:
            return None
        got = LOC.learn_from_text(self._names, text, map_id)
        if got:
            self.save_knowledge()
        # ⚠⚠ `learn_from_text` は「既に覚えていれば None」を返します（RX3-0101）。
        #   ★台帳への反映は**それに関係なく**やります（⚠ 一度きりにしない）。
        place = LOC.greeting_place(text)
        if place and place[0]:
            book = self.location_book
            if book.promote(book.location_id_of(map_id), place[0], source="dialogue",
                            location_type=place[1]):
                book.save(force=True)
        return got

    def flush_conversation(self):
        """⚠ 画面を閉じるときに呼ぶ（★持ったままにしない）。"""
        return self._flush_talk()

    def _screen_tiles(self):
        """⚠ Lua が送ってきた画面（★16 進の文字列）をタイル列へ戻す。"""
        raw = self._raw().get("screen")
        if not isinstance(raw, str) or len(raw) < 2:
            return []
        try:
            return [int(raw[i:i + 2], 16) for i in range(0, len(raw), 2)]
        except ValueError:
            return []

    def save_knowledge(self) -> bool:
        """★訪れた場所などを残す。⚠ 書けなくても落とさない。

        ⚠ メモは**ここには入りません**（★`memos.jsonl` が正本）。
        """
        body = {
            "visited_locations": sorted(self._visited),
            "location_names": self._names,
            "heard_counts": self._heard,
            "found_counts": self._found,
        }
        try:
            self.knowledge_path.parent.mkdir(parents=True, exist_ok=True)
            self.knowledge_path.write_text(
                json.dumps(body, ensure_ascii=False, indent=1),
                encoding="utf-8")
            return True
        except OSError:
            return False

    def note_seen(self) -> int:
        """★いま映っている升を「見た」ことにする。

        ⚠⚠ **ここを呼ばないと、地図は永遠に真っ黒のまま。**
          ★呼ぶのは画面の定期処理（`Dq3MainWindow.refresh`）。
          ⚠ Lua 側ではない（★遊ぶだけのときは記録しない、で構わない）。

        ⚠ 地図の大きさはまだ渡していない（★ROM 側とつなぐのは次の段）。
          負の座標だけは捨てられる。

        戻り値: ★新しく見た升の数。
        """
        from dq3.knowledge.seen_map import map_key

        at = self.position()
        if at is None:
            return 0
        kind, map_id, x, y = at
        # ⚠⚠ 種別ごとに別の鍵（★混ぜると世界の記録が街に化ける）
        added = self.seen.mark_view(map_key(kind, map_id), x, y)
        # ★探索済み（RX3-0205）: 映った升のうち、勇者と同じ層の升だけ（⚠ 見た升とは別の記録）
        self.note_explored(kind, map_id, x, y)
        # ★宝箱（RX3-0207）: 探索済みの升にある宝箱を見つけた / 印が立ったら開けた
        self.note_chests(kind, map_id)
        # ⚠ 増えたときだけ書く。★間隔は `SeenMap` が守る
        if added:
            self.seen.save()
        return added
