"""実プレイの「起きたこと」を Fact にする（RX3-0076 / 2026-09-05）。

★★ 会話（RX3-0070）だけでは Topic は片づかない。**手に入れた・倒した・行った**を見る ★★

```text
所持品   RAM $076C（1 人 8 枠 / bit7 = 装備中 / FF = 空き）→ state.json の party[].items
         ★セーブステート 18 本で並びを確認（2026-09-05）
撃破     EnemyBook.defeated（★戦闘に勝ったときの敵 id）
到達     player-knowledge.json の visited_locations（★L<map_id>）
        ↓ ここ
Fact     item:<id> obtain / monster:<id> defeat / location:L<n> visit（confidence 1.0）
物語     state.json の story_XXXX（★data/dq3/story-flags.csv で意味づけ）→ event:<flag_id> set（RX3-0211）
```

## ⚠⚠ 守ること

```text
★一度持ったら覚える     ⚠ 使って無くなっても「手に入れた」は消えない（まほうのたま など）
★fact_id は安定         ⚠ 同じ品を何度見ても同じ id（→ Topic State は二度数えない）
⚠ 居ない枠は読まない     ★hp_max 0 の枠の $076C は 0 で埋まっている（= ひのきのぼう に見える）
⚠ 推測しない            ★RAM に無いもの（船・転職・ラーミア）は Fact にしない
```
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "progress.json")

#: ★所持品の空き（⚠ $FF）
EMPTY_SLOT = 0xFF


@dataclasses.dataclass
class Progress:
    """★これまでに起きたこと（⚠ Git の外 / playdata の作法）。"""

    items_ever: set = dataclasses.field(default_factory=set)
    defeated: set = dataclasses.field(default_factory=set)
    visited: set = dataclasses.field(default_factory=set)
    #: ★立ったことのある物語の旗（RX3-0211 / ★一度立ったら覚える）
    story: set = dataclasses.field(default_factory=set)
    #: ★★ 一度でも手に入れた品（RX3-0443 / 2026-09-28）
    #:
    #:   ⚠⚠ `items_ever` は**持ち物を覗いたときに見えた品**です。★拾ってすぐ使った・渡した品は
    #:   1 度も見えないことがあり、⚠ 実測で **7 種**が抜けていました（ガイアのつるぎ / さとりのしょ /
    #:   レッド・イエローオーブ など）。★そこで**入手した瞬間の記録**（勇者メモの宝箱・しらべる・入手）
    #:   からも集めます（`acquired_items`）。
    #:   ⚠ こちらも減りません（★`入手した:` の材料）。
    acquired: set = dataclasses.field(default_factory=set)
    path: pathlib.Path | None = None
    _dirty: bool = False
    #: ★★ 一度でも持ち物を見たか（RX3-0312）
    #:
    #:   ⚠⚠ これが無いと、**初めて数えた瞬間に 70 件以上が「いま手に入れた」**になります。
    #:   ★`HiddenItemBook.initialized` と同じ作法です。
    items_seen: bool = False
    #: ★いま増えた品（★`take_new_items()` で受け取ると空になる / ⚠ 初回の分は入らない）
    just_got: list = dataclasses.field(default_factory=list)

    # --- ★取り込む ---------------------------------------------------------

    def note_party(self, party_rows) -> int:
        """★state.json の party[].items から「持っている品」を覚える。⚠ 増えた数を返す。

        ★★ 2026-09-20（RX3-0312）: ⚠ 依頼者「ひかりのたまの取得イベントが拾えない」。

        ```text
        ★持ち物としては拾えていた   progress.json の items_ever に 114 が在る
        ⚠ 取得イベントにならない    勇者メモへ書く口は 宝箱 と しらべる の 2 本だけで、
                                    どちらも「印が立った」がきっかけ
                                    → ⚠ 竜の女王が会話で渡す品は、どちらの印も立たない
        ```

        → ★ここで「**いま増えた品**」を覚え、⚠ 画面がそれを勇者メモにします。
        """
        rows = list(party_rows or ())
        if not rows:
            return 0                                  # ⚠ 空を「持ち物を見た」と数えない
        first = not self.items_seen
        added = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            for raw in row.get("items") or ():
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue
                if value == EMPTY_SLOT or value < 0:
                    continue
                item_id = value & 0x7F           # ★bit7（装備中）を落とす
                if item_id not in self.items_ever:
                    self.items_ever.add(item_id)
                    added += 1
                    if not first:                # ⚠ 初めて数えた分は「いま手に入れた」ではない
                        self.just_got.append(item_id)
        if first:
            self.items_seen = True
            self._dirty = True
        self._dirty |= bool(added)
        return added

    def take_new_items(self) -> list:
        """★いま増えた品を受け取る（⚠ 受け取ると空になる / `ChestBook.take_opened` と同じ作法）。"""
        got, self.just_got = list(self.just_got), []
        return got

    def note_defeated(self, enemy_ids) -> int:
        added = 0
        for raw in enemy_ids or ():
            try:
                key = int(raw)
            except (TypeError, ValueError):
                continue
            if key not in self.defeated:
                self.defeated.add(key)
                added += 1
        self._dirty |= bool(added)
        return added

    def note_visited(self, location_ids) -> int:
        added = 0
        for loc in location_ids or ():
            if isinstance(loc, str) and loc and loc not in self.visited:
                self.visited.add(loc)
                added += 1
        self._dirty |= bool(added)
        return added

    def note_story(self, state) -> int:
        """★物語の旗（RX3-0211）: 一度立った旗は覚える（⚠ 表 data/dq3/story-flags.csv で意味づけ / 推測しない）。"""
        from .story import flags_set

        added = 0
        for flag_id in flags_set(state if isinstance(state, dict) else {}):
            if flag_id not in self.story:
                self.story.add(flag_id)
                added += 1
        self._dirty |= bool(added)
        return added

    def note_acquired(self, item_ids) -> int:
        """★入手した瞬間の記録から覚える（RX3-0443 / ⚠ 減らさない）。"""
        added = 0
        for raw in item_ids or ():
            try:
                item_id = int(raw)
            except (TypeError, ValueError):
                continue
            if item_id not in self.acquired:
                self.acquired.add(item_id)
                added += 1
        self._dirty |= bool(added)
        return added

    # --- ★Fact にする --------------------------------------------------------

    def acquired_ever(self) -> set:
        """★一度でも手に入れた品（★持ち物で見えた分 ＋ 入手の記録 / RX3-0443）。"""
        return set(self.items_ever) | set(self.acquired)

    def facts(self) -> list[dict]:
        """★Topic State に流す Fact（⚠ id は安定 / 同じ出来事は同じ fact_id）。"""
        from dq3.knowledge.concepts import Fact

        got = []
        for item_id in sorted(self.items_ever):
            got.append(Fact("item:%d" % item_id, "obtain", None, "inv:item:%d" % item_id, 1.0).to_json())
        # ★「一度でも手に入れた」（RX3-0443）。⚠ `持った:` とは別の predicate
        for item_id in sorted(self.acquired_ever()):
            got.append(Fact("item:%d" % item_id, "acquired", None,
                            "got:item:%d" % item_id, 1.0).to_json())
        for enemy_id in sorted(self.defeated):
            got.append(Fact("monster:%d" % enemy_id, "defeat", None, "battle:monster:%d" % enemy_id, 1.0).to_json())
        for loc in sorted(self.visited):
            got.append(Fact("location:%s" % loc, "visit", None, "visit:%s" % loc, 1.0).to_json())
        for flag_id in sorted(self.story):
            got.append(Fact("event:%s" % flag_id, "set", None, "story:%s" % flag_id, 1.0).to_json())
        return got

    # --- ★しまう・戻す ---------------------------------------------------------

    def save(self, force: bool = False) -> bool:
        """★書き出す。

        ## ⚠⚠ 自分の集合だけを書かない（RX3-0298 / 2026-09-19）

          ★書く人が **2 人**います（勇者会議と、画面の更新の `Watcher`）。
          ⚠ それぞれが別の `Progress` を持つので、★自分のぶんだけ書くと
          **相手が足したぶんが消えます**。

          → ★どれも「ずっと持っている集合」なので、⚠ **ファイルの中身と合わせて**書きます。
        """
        if not force and not self._dirty:
            return False
        target = self.path or DEFAULT_PATH
        disk = Progress.load(target)
        self.items_ever |= disk.items_ever
        self.items_seen = self.items_seen or disk.items_seen   # ★片方が見ていれば見たこと
        self.defeated |= disk.defeated
        self.visited |= disk.visited
        self.story |= disk.story
        self.acquired |= disk.acquired
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "game": "dq3",
                "items_ever": sorted(self.items_ever),
                "items_seen": bool(self.items_seen),
                "defeated": sorted(self.defeated),
                "visited": sorted(self.visited),
                "story": sorted(self.story),
                "acquired": sorted(self.acquired),
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(target)
        except OSError:
            return False
        self._dirty = False
        return True

    @classmethod
    def load(cls, path=None) -> "Progress":
        got = cls(path=pathlib.Path(path) if path else DEFAULT_PATH)
        try:
            data = json.loads(got.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return got
        got.items_ever = {int(x) for x in data.get("items_ever") or []}
        # ★★ 既にある記録は「見たことがある」とみなす（RX3-0312）。
        #   ⚠⚠ さもないと、**この直しを入れた最初の 1 回で 70 件以上が勇者メモに流れます**
        #     （★依頼者の記録には既に 74 種入っていた）。
        got.items_seen = bool(data.get("items_seen", bool(got.items_ever)))
        got.defeated = {int(x) for x in data.get("defeated") or []}
        got.visited = {str(x) for x in data.get("visited") or []}
        got.story = {str(x) for x in data.get("story") or []}
        got.acquired = {int(x) for x in data.get("acquired") or []}
        return got


class Watcher:
    """★遊んでいる間ずっと「手に入れた品」と「立った旗」を数える（RX3-0298 / 2026-09-19）。

    ## ⚠⚠ これが無いと、勇者会議を開いたときしか数えません

      ★`note_party` を呼ぶ道は `Council._progress` の 1 本だけでした。
      ⚠ そのため「取ってすぐ使った / 渡した / 捧げた」品は**1 度も記録に残りません**。

      ★実測（RX3-0297 / 依頼者の記録）: 6 つのオーブのうち **3 つが `items_ever` に無い**
      （⚠ 取ってから捧げるまでの間に、1 度も勇者会議を開いていなかった）。

    ## ★書き方

      ⚠ 毎回は書きません。★**増えたときだけ**書きます（`Progress._dirty`）。
      ⚠ 落ちても画面は続けます（★記録は次の更新で追いつく）。
    """

    def __init__(self, progress: Progress | None = None, path=None) -> None:
        self.progress = progress if progress is not None else Progress.load(path)
        #: ★足した数の合計（⚠ 検査と、あとで数えるため）
        self.added = 0
        #: ★書いた回数（⚠ 毎回書いていないことを確かめられるように）
        self.saves = 0

    def note(self, state) -> int:
        """★`state.json` の中身を 1 回ぶん数える。戻り値: 足した数。"""
        if not isinstance(state, dict):
            return 0
        got = self.progress.note_party(state.get("party") or ())
        got += self.progress.note_story(state)
        if got:
            self.added += got
            if self.progress.save():
                self.saves += 1
        return got


#: ★入手した瞬間が残る勇者メモの種類（★宝箱 / しらべる / 入手 / ⚠ 種類の名前が付いていない行）
ACQUIRE_SOURCES = ("chest", "search", "item", "unknown")


def acquired_items(memos_path=None) -> set:
    """★勇者メモの記録から「入手した品」を集める（RX3-0443）。

    ⚠⚠ `items_ever`（持ち物を覗いて見えた品）では**拾ってすぐ手放した品が抜けます**。
      ★実測（2026-09-28 / 依頼者の記録 1396 件）: 記録には入手の行があるのに
      `items_ever` に無い品が **7 種**（★ガイアのつるぎ / さとりのしょ / レッド・イエローオーブ 等）。

    ⚠ `item_id` は**文字列**で入っています（★2026-09-28 に実測。int と決め打つと 0 件になる）。
    ⚠ 記録が無ければ空（★公開版・まっさらな環境）。
    """
    from dq3.knowledge import concepts as C

    target = pathlib.Path(memos_path) if memos_path else pathlib.Path(C.MEMOS)
    got: set = set()
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return got
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("source") not in ACQUIRE_SOURCES:
            continue
        raw = str(row.get("item_id") or "").strip()
        if raw.isdigit():
            got.add(int(raw))
    return got


def load_all(path=None, memos_path=None) -> Progress:
    """★記録を読み、⚠ **入手の記録も取り込んだ** Progress（RX3-0443 / 保存はしない）。

    ⚠⚠ 素の `Progress.load()` だけだと `acquired` が空のままで、★`入手した:` が
      「1 度も成立していない」に見えます（2026-09-28 に門番で踏んだ）。
    ★読むだけの道具（門番・時系列の監査）はこちらを使ってください。
    """
    got = Progress.load(path)
    got.note_acquired(acquired_items(memos_path))
    return got


def gather(vm=None, progress: Progress | None = None, state=None, enemy_book=None,
           visited=None, memos_path=None) -> Progress:
    """★いまの実プレイから Progress を更新する（⚠ vm があれば vm から取る）。"""
    got = progress if progress is not None else Progress.load()
    # ★入手の記録（⚠ 持ち物を覗いた記録だけでは抜ける / RX3-0443）
    got.note_acquired(acquired_items(memos_path))
    if vm is not None:
        try:
            state = state if state is not None else vm._raw()
        except Exception:                                  # noqa: BLE001
            state = state or {}
        if enemy_book is None:
            enemy_book = getattr(vm, "enemy_names", None)
        if visited is None:
            visited = getattr(vm, "_visited", None)
    if isinstance(state, dict):
        got.note_party(state.get("party") or [])
        got.note_story(state)                        # ★物語の旗（RX3-0211）
    if enemy_book is not None:
        got.note_defeated(getattr(enemy_book, "defeated", ()) or ())
    if visited:
        got.note_visited(visited)
    return got


def load_state(path=None) -> dict:
    """⚠ vm が無いとき（CLI）に state.json を直に読む。"""
    target = pathlib.Path(path) if path else paths.runtime("state.json")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_visited(path=None) -> set:
    target = pathlib.Path(path) if path else paths.work("dq3-knowledge",
                                                    "player-knowledge.json")
    try:
        return set(json.loads(target.read_text(encoding="utf-8")).get("visited_locations") or [])
    except (OSError, ValueError, AttributeError):
        return set()


def memo_text(item_name: str | None, place: str | None = None) -> str:
    """★勇者メモの 1 行（★宝箱・しらべる と同じ形 / RX3-0312）。

    ```text
    龍の女王の城　入手：ひかりのたま
    ```
    ⚠ 場所の名前が無ければ「入手：…」だけ（★名前を推測しない）。
    """
    what = "入手：%s" % (item_name or "？")
    return ("%s　%s" % (place, what)) if place else what
