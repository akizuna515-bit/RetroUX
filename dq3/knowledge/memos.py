"""ゆうしゃメモを残す場所（RX3-0016 V0 / 2026-08-30）。

★★ **プレイヤーが実際に得たことだけ** ★★

⚠⚠ `world-model.json` の「ROM 上の正解」をここへ流し込みません。
  ★勇者メモは**遊んで知ったこと**の記録です。ROM から先回りして入れると、
  ⚠ 知らないはずのことを知っている画面になります（No-Spoiler が崩れる）。

## ★1 メモ 1 行の追記（依頼者の指示 2026-08-30）

    work/dq3-knowledge/memos.jsonl

⚠ DB 化は目的にしません。★NPC・道具・出来事の逆引きが本格化してから
判断します。

## ⚠ なぜ追記型か

★遊んでいる最中に増えます。⚠ 全部を読み直して書き戻す形にすると、

```text
⚠ 途中で落ちたときに、**それまでのぶんごと消える**
⚠ 書いている最中に読むと、半端な JSON になる
```

★1 行足すだけなら、⚠ 落ちても**その 1 行が欠けるだけ**です。

## ⚠⚠ 壊れた行があっても、残りは読む

★手で消したり、書いている途中で電源が落ちたりします。
⚠ 1 行が読めないだけで**全部を失わない**ようにします
（★何件落としたかは `failed` に残します。⚠ 黙って捨てません）。
"""

from __future__ import annotations

import dataclasses
import datetime
import io
import json
import os
import pathlib

from ..ui.models import Memo, MemoBook

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★既定の置き場（⚠ `work/` なので Git には入らない）
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "memos.jsonl")

#: ★source（⚠ 過剰に作り込まない / 依頼者の指示）
CONVERSATION = "conversation"
DISCOVERY = "discovery"
MANUAL = "manual"
UNKNOWN = "unknown"
NPC_TALK = "npc_talk"          #: ★聞き込みで NPC と話した会話（RX3-0058）
#: ★宝箱で入手したもの（RX3-0261 / ★`event_id` = `chest:<宝箱>` で宝箱ごとに 1 件）
CHEST = "chest"
#: ★「しらべる」で手に入れた隠し道具（RX3-0281 / ★`event_id` = `hidden:<通し番号>`）
#:
#:   ⚠⚠ 2026-09-20（RX3-0312）: ★`view_model` は前から `source="search"` を渡していたのに、
#:     ここに無かったので **黙って `unknown` に落ちて**いました
#:     （`memos.py` の `source if source in SOURCES else UNKNOWN`）。
#:   ★実データの裏取り: `memos.jsonl` の `source == "unknown"` の **4 件が全部
#:     「しらべる：… を入手」**で、`hidden-items.json` の新規 4 件と一致しました。
SEARCH = "search"
#: ★持ち物が増えたことで気づいた品（RX3-0312 / ★`event_id` = `item:<品番>`）
#:
#:   ★宝箱でも「しらべる」でもない道（★イベントで人から渡される / 買う / 拾う）。
#:   ⚠ 依頼者「ひかりのたまの取得イベントが拾えない ※竜の女王から与えられる」。
ITEM = "item"

SOURCES = (CONVERSATION, DISCOVERY, MANUAL, UNKNOWN, NPC_TALK, CHEST, SEARCH, ITEM)


def _now() -> str:
    """★いまの時刻（ISO8601 / 秒まで）。

    ⚠⚠ **これは「現実の時計」です。** ★セーブステートを戻しても巻き戻りません。
      → ⚠ 並べ替えに使わないこと（★並びは `order`）。
      ★冒険ログで「いつ遊んだか」を人へ見せるためだけに持ちます（RX3-0148）。
    """
    return datetime.datetime.now().isoformat(timespec="seconds")


def _speaker_or_none(got):
    """★話者ラベル（⚠⚠ `＊` は**記録しない** / RX3-0118）。

    ⚠ `＊「` はゲーム本文の会話開始記号です。★これを話者として残すと、
    画面が `＊` を人の名前のように出します（⚠ 実際に出ていました）。
    """
    from ..ui.models import TALK_MARK

    text = (got or "").strip()
    return None if (not text or text == TALK_MARK) else text


#: ★話者の字の長さの上限（★見た目の字は 1〜2 字 / `＊` / `？`）。⚠ これより後ろの「 は本文の中
_LABEL_MAX = 2


def talk_body(text) -> str | None:
    """★会話のメモの本文（★先頭の話者の字と「 を除き、⚠ 聞き込みの行が足す末尾の」も除く / RX3-0236）。

    ```text
    ＊「こんにちは。      → こんにちは。     （★手で話した会話）
    兵「こんにちは。」    → こんにちは。     （★聞き込み / `TownService.memo_text`）
    ？「こんにちは。」    → こんにちは。     （⚠ 話者が分からなかった）
    ```

    ⚠ 会話でなければ None（★地図のメモなどに触らない）。
    """
    got = (text or "").strip()
    at = got.find("「")
    if at < 0 or at > _LABEL_MAX:
        return None
    body = got[at + 1:]
    return body[:-1] if body.endswith("」") else body


def talk_key(text, *, location_id=None, npc_id=None):
    """★「同じ相手が同じことを言った」と見分ける鍵（RX3-0294 / 2026-09-18）。

    ⚠⚠ **同じ台詞が 2 件入っていました**（★聞き込みと、手で話した会話）:

    ```text
    囚「<同じ本文>」   ★聞き込み（⚠ 末尾に 」 が付く）
    ＊「<同じ本文>     ★手で話した（⚠ 付かない）
    ```

    ⚠⚠ **見本に原作の台詞を書きません**（RX3-0433 / 2026-10-01）。
      ★`docs/00-project-policy.md` §3 / ⚠ この docstring は配布物に入ります。

    ⚠ 違うのは**頭の札**と、聞き込みの側だけに付く**末尾の 」** だけです。
    ★`talk_body` で両方を外してから比べます。

    ## ⚠⚠ 相手（`npc_id`）を鍵に入れる理由

      ★「場所 + 本文」だけにすると、⚠ **別の人**を巻き込みます（実測 12 組）:

      ```text
      L11  ぐうぐう‥‥。            npc 1/2/3/5/7/8   ★寝ている人が 6 人
      L1   ようこそ ロマりアのおしろに！ npc 0/1          ★2 人が同じ挨拶
      ```

    ⚠ 相手が分からない行（`npc_id` が無い）は **None** を返します
      → ★畳みません（⚠ 同じ相手だと確かめられないものを推測で消さない）。

    ⚠ 会話のメモでなければ None（★地図・宝箱のメモに触らない）。
    """
    body = talk_body(text)
    if body is None or npc_id is None:
        return None
    try:
        who = int(npc_id)
    except (TypeError, ValueError):
        who = str(npc_id)
    return (location_id, who, body)


def _fold(memos):
    """★同じ鍵の 2 件目以降を落とす。戻り値: `(残った一覧, 落とした数)`。

    ⚠ 残すのは**先に記録したほう**（★話者の札が付いている聞き込みの行が多い）。
    """
    out, seen, dropped = [], set(), 0
    for memo in memos:
        key = talk_key(memo.text, location_id=memo.location_id,
                       npc_id=memo.npc_id)
        if key is not None:
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
        out.append(memo)
    return out, dropped


def _speaker_unknown(memo) -> bool:
    from ..ui.models import TALK_MARK, UNKNOWN_SPEAKER

    return (memo.speaker or "").strip() in ("", TALK_MARK, UNKNOWN_SPEAKER)


class MemoStore:
    """ゆうしゃメモの置き場。★足すのと引くのだけ。

    ⚠ 並べ替えや絞り込みは `MemoBook` が持っています（★二重に持たない）。
    """

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path or DEFAULT_PATH)
        self._memos: list[Memo] = []
        self.failed = 0
        #: ★読むときに畳んだ二重の数（RX3-0294 / ⚠ ファイルは減りません）
        self.folded = 0
        self.last_error: str | None = None
        #: ★直前の `add_if_new` が「？」の行に話者を埋めたなら、その `Memo`（RX3-0236）
        self.last_filled: Memo | None = None
        self.reload()

    # --- ★読む ------------------------------------------------------------

    def reload(self) -> None:
        """★読み直す。⚠ 無ければ**空で始める**（★エラーにしない）。"""
        self._memos = []
        self.failed = 0
        fields = {f.name for f in dataclasses.fields(Memo)}
        try:
            text = io.open(self.path, encoding="utf-8").read()
        except OSError:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("dict ではない")
                # ⚠ 知らない欄は捨てる（★古い記録も新しい記録も読めるように）
                self._memos.append(
                    Memo(**{k: v for k, v in row.items() if k in fields}))
            except (ValueError, TypeError) as exc:
                # ⚠⚠ 1 行が読めないだけで全部を失わない。★数は残す
                self.failed += 1
                self.last_error = str(exc)
        self._memos.sort(key=lambda m: m.order)
        # ★★ 既にある二重を畳む（RX3-0294）。⚠ **ファイルは書き換えません**
        #   （★依頼者の記録。行は残したまま、画面に出さないだけ）。
        #   ⚠ 何行畳んだかは残す（★黙って減らさない）。
        #   ⚠⚠ 通し番号は**畳む前**の最大から進める。★畳んだ行の番号を使い回すと、
        #     `_rewrite_line` が**その行を書き換えて**しまう（★検査で捕まえた）。
        self._max_order = max((m.order for m in self._memos), default=0)
        self._memos, self.folded = _fold(self._memos)

    # --- ★足す ------------------------------------------------------------

    @property
    def next_order(self) -> int:
        """★次の通し番号。

        ⚠⚠ **時刻を並び順の正本にしません**（依頼者の指示）。
          ★セーブステートを巻き戻すとゲーム内時刻は戻りますが、
          ⚠ 勇者メモの記録順は戻ってはいけません。
        """
        # ⚠ 畳んだ行の番号も数に入れる（RX3-0294 / ★`_max_order` は畳む前の最大）
        return max(max((m.order for m in self._memos), default=0),
                   getattr(self, "_max_order", 0)) + 1

    def add(self, text: str, *, location_id=None, map_id=None,
            source: str = UNKNOWN, raw_digest=None,
            npc_id=None, item_id=None, event_id=None, speaker=None):
        """★1 件足して、⚠ **その場で 1 行書き足す**。

        戻り値は足した `Memo`。⚠ 書けなかったときも `Memo` は返します
        （★画面には出る。⚠ 残らなかったことは `failed` で分かる）。
        """
        memo = Memo(
            order=self.next_order, text=text,
            location_id=location_id, map_id=map_id,
            npc_id=npc_id, item_id=item_id, event_id=event_id,
            # ★書いた時刻（RX3-0148）。⚠ 並べるのは `order` のまま
            #   （★セーブを戻すと時計は巻き戻らない）。
            at=_now(),
            source=source if source in SOURCES else UNKNOWN,
            raw_digest=raw_digest, speaker=_speaker_or_none(speaker))
        self._memos.append(memo)
        self._append(memo)
        return memo

    def add_if_new(self, text: str, *, raw_digest=None, **rest):
        """★同じものを二度書かない。⚠ 戻り値は足した `Memo` か `None`。

        ## ⚠⚠ これが無いと、同じ会話が毎フレーム増えます

          ★画面を見て記録する作りなので、⚠ 同じ窓が出ているあいだ
          **何度も同じ文を読みます**。

        ★見分けは `raw_digest` **と** 文の両方で行います。

        ## ⚠⚠ 2026-08-31: `raw_digest` だけでは足りませんでした

          ★実機で **同じ文が 2 件入りました**（`memos.jsonl` の 16 / 17）。

          ```text
          16 ＊「まちのそとを あるくとき … しれぬ。   digest 2a95c393c606be93
          17 ＊「まちのそとを あるくとき … しれぬ。   digest 8c0403bcba6c6940
          ```

          ⚠ 生タイルは ▼ の点滅などで**1 ドット違う**ので、
          digest だけを鍵にすると別物になります。
          → ★**文と地点が同じなら、digest が違っても足しません。**

        ## ★★ 2026-09-13（RX3-0236）: 「？」で覚えた行には話者を埋める

          ⚠ 依頼者「うまく働かず話者が？で記憶されたら、 次話したら上書きされる」（★期待）。
          ⚠ これまでは同じ本文なら黙って足さず、⚠ 「？」の行が残り続けた（聞き込みの行は別物として重複した）。
          → ★同じ地点・同じ本文を、話者の分かった状態で聞いたら、その行に話者を埋める（`fill_speaker` / 新しい行は足さない）。
        """
        location_id = rest.get("location_id")
        # ★★ 出来事の印（`event_id`）があれば、それだけで見分ける（RX3-0261 / 宝箱ごとに 1 件）。
        #   ⚠ 本文 + 場所で見ると、同じ場所の同じ品の**別の宝箱**が消える（⚠ 本文を変えて避けない）
        event_id = rest.get("event_id")
        if event_id:
            self.last_filled = None
            if any(m.event_id == event_id for m in self._memos):
                return None
            return self.add(text, raw_digest=raw_digest, **rest)
        self.last_filled = self.fill_speaker(text, location_id=location_id, speaker=rest.get("speaker"),
                                             npc_id=rest.get("npc_id"))
        if self.last_filled is not None:
            return None
        # ★★ 同じ相手の同じ台詞は足さない（RX3-0294）。
        #   ⚠⚠ `_key` は**生の本文**を見るので、札（`囚「` / `＊「`）と
        #     末尾の 」 が違うだけの同じ台詞をすり抜けていた。
        talk = talk_key(text, location_id=location_id, npc_id=rest.get("npc_id"))
        if talk is not None:
            for memo in self._memos:
                if talk_key(memo.text, location_id=memo.location_id,
                            npc_id=memo.npc_id) == talk:
                    return None
        keys = {self._key(text, raw_digest, location_id),
                self._key(text, None, location_id)}
        for memo in self._memos:
            if self._key(memo.text, memo.raw_digest, memo.location_id) in keys:
                return None
            if self._key(memo.text, None, memo.location_id) in keys:
                return None
        return self.add(text, raw_digest=raw_digest, **rest)

    def migrate(self, rows) -> int:
        """★昔の記録（`player-knowledge.json` の中の配列）を**一度だけ移す**。

        ## ⚠⚠ なぜ「見るだけ」にしないか

          ★最初は「両方を読んで混ぜる」ようにしました。⚠ その結果、
          **`order` が衝突しました**（昔の 1 と、新しく足した 1）。

          ```text
          [(1, '昔のメモ'), (1, '井戸の底に何かある')]   ⚠⚠ どちらが先か決まらない
          ```

          ⚠ `order` は「巻き戻しても壊れない並び」のためにあるので、
          ★**重複したら意味を失います**。

        → ★正本を 1 つにします。⚠ 昔のぶんは、元の順を保ったまま
          新しい番号を振り直して足します。

        戻り値は移した件数。⚠ 既にあるものは移しません。
        """
        fields = {f.name for f in dataclasses.fields(Memo)}
        moved = 0
        known = {self._key(m.text, m.raw_digest, m.location_id)
                 for m in self._memos}
        for row in sorted(rows or [], key=lambda r: r.get("order") or 0):
            if not isinstance(row, dict):
                continue
            got = {k: v for k, v in row.items() if k in fields}
            key = self._key(got.get("text"), got.get("raw_digest"),
                            got.get("location_id"))
            if key in known:
                continue
            known.add(key)
            got.pop("order", None)
            memo = Memo(order=self.next_order, **got)
            self._memos.append(memo)
            self._append(memo)
            moved += 1
        return moved

    def fill_speaker(self, text: str, *, location_id=None, speaker=None, npc_id=None):
        """★「？」で覚えた会話のメモに、話者を埋める（RX3-0236）。戻り値は書き換えた `Memo` か `None`。

        ⚠ 埋めるのは: 同じ地点・同じ本文（`talk_body`）・⚠ 話者が分からない行だけ。
        ⚠ 新しい話者が分からない（`？` / `＊` / 空）なら何もしない（★推測で名乗らせない）。
        ⚠ 書けなかったら、画面の中身も変えない（★記録と画面を食い違わせない）。
        """
        from ..ui.models import UNKNOWN_SPEAKER

        new = _speaker_or_none(speaker)
        body = talk_body(text)
        if new is None or new == UNKNOWN_SPEAKER or body is None:
            return None
        for i, memo in enumerate(self._memos):
            if memo.location_id != location_id or talk_body(memo.text) != body or not _speaker_unknown(memo):
                continue
            got = memo.text
            if got.strip().startswith(UNKNOWN_SPEAKER + "「"):
                got = new + got.strip()[len(UNKNOWN_SPEAKER):]        # ★焼き込んだ「？」も直す（聞き込みの行）
            filled = dataclasses.replace(memo, text=got, speaker=new,
                                         npc_id=memo.npc_id if memo.npc_id is not None else npc_id)
            if not self._rewrite_line(filled):
                return None
            self._memos[i] = filled
            return filled
        return None

    def remove_conversations(self, location_id: str, map_ids=()) -> int:
        """★その場所の**会話のメモ**（npc_talk・conversation）だけ消す（RX3-0235 / 指示書 §10・§15）。戻り値: 消した行の数。

        ★場所は `location_id`（⚠ location_id の無い昔の行は `map_ids` で見る）。⚠ discovery・手で書いたメモは残す。
        ★ほかの行はバイトのまま残す（壊れた行も / 改行コードも元のまま）。★一時ファイルへ 1 回書いてから置き換える。
        ⚠ 書けなければ例外（★消したつもりで残す、を黙ってしない）。
        """
        maps = {int(m) for m in (map_ids or ())}

        def hit(row) -> bool:
            if not isinstance(row, dict) or row.get("source") not in (CONVERSATION, NPC_TALK):
                return False
            loc = row.get("location_id")
            return loc == location_id if loc is not None else row.get("map_id") in maps

        if not self.path.exists():
            return 0
        raw = self.path.read_bytes().decode("utf-8")
        eol = "\r\n" if "\r\n" in raw else "\n"
        keep, removed = [], 0
        for ln in raw.split(eol):
            try:
                row = json.loads(ln)
            except ValueError:
                row = None
            if row is not None and hit(row):
                removed += 1
                continue
            keep.append(ln)
        if removed:
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_bytes(eol.join(keep).encode("utf-8"))
            os.replace(tmp, self.path)
            self.reload()
        return removed

    def _rewrite_line(self, memo: Memo) -> bool:
        """★その `order` の 1 行だけを書き換える（RX3-0236）。

        ⚠ 追記型の例外。★ほかの行はバイトのまま残す（壊れた行・知らない欄も / 改行コードも元のまま）。
        ★一時ファイルへ書いてから置き換える（⚠ 途中で落ちても全部を失わない）。
        ⚠ 同じ `order` が 2 行ある / 見つからない → 書かない。
        """
        try:
            raw = self.path.read_bytes().decode("utf-8")
            eol = "\r\n" if "\r\n" in raw else "\n"
            lines = raw.split(eol)
            hits = []
            for i, ln in enumerate(lines):
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("order") == memo.order:
                    hits.append((i, row))
            if len(hits) != 1:
                return False
            i, row = hits[0]
            row.update(text=memo.text, speaker=memo.speaker, npc_id=memo.npc_id)
            lines[i] = json.dumps(row, ensure_ascii=False)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_bytes(eol.join(lines).encode("utf-8"))
            os.replace(tmp, self.path)
            return True
        except (OSError, UnicodeDecodeError) as exc:
            self.failed += 1
            self.last_error = str(exc)
            return False

    @staticmethod
    def _key(text, raw_digest, location_id):
        return (raw_digest or ("t:" + (text or "")), location_id)

    def _append(self, memo) -> bool:
        """⚠ 1 行だけ書き足す。★失敗しても落とさない（数だけ残す）。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(dataclasses.asdict(memo), ensure_ascii=False)
            with io.open(self.path, "a", encoding="utf-8", newline="") as fh:
                fh.write(line + "\n")
            return True
        except OSError as exc:
            self.failed += 1
            self.last_error = str(exc)
            return False

    # --- ★引く ------------------------------------------------------------

    def book(self) -> MemoBook:
        """★逆引きは `MemoBook` に任せる（⚠ 同じ処理を 2 か所に書かない）。"""
        return MemoBook(list(self._memos))

    def __len__(self) -> int:
        return len(self._memos)

    def __iter__(self):
        return iter(self._memos)

    def recent(self, n: int = 3):
        return self.book().recent(n)

    def of_location(self, location_id: str):
        return self.book().of_location(location_id)

    def of_map(self, map_id: int):
        return self.book().of_map(map_id)
