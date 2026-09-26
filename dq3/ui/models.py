"""勇者メモと地点情報の**形**（RX3-0019 / 2026-08-29）。

★★ なぜ UI から分けるのか ★★

依頼者の指示書 §8:

    重要なのは、将来的に
      ・地点からメモを引く
      ・アイテムから関連メモを引く
      ・NPC から関連会話を引く
    といった逆引きができるよう、**UI 専用の文字列リストにしてしまわないこと。**

⚠ 画面に出す文字列だけを持つと、あとから引けません。★ここは Qt を import しません。

## ⚠⚠ 「知らないことを出さない」の境目（指示書 §10）

    RetroUX 内部で知っていること  ≠  UI へ出してよいこと

★ROM から起こした `world-model.json` は**ここに入れません**。
⚠ 入れてよいのは「プレイヤーが実際に見た・聞いた・訪れた」ものだけです。
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field


#: ★地点をどこまで知っているか（指示書 §11）。
#:
#: ⚠ 今回は `VISITED` / `UNKNOWN` の 2 つから始める。
#:   ★`HEARD` / `DISCOVERED` は `RX3-0016`（Player Knowledge）が入ってから。
#:   ⚠ 先に 4 値を名乗ると、埋まっていないのに埋まったように見える。
UNKNOWN = "UNKNOWN"
HEARD = "HEARD"
DISCOVERED = "DISCOVERED"
VISITED = "VISITED"

KNOWLEDGE_ORDER = (UNKNOWN, HEARD, DISCOVERED, VISITED)

#: ★いま実際に出せるもの（⚠ 上の 4 つのうち、中身が伴っているのはこれだけ）
KNOWLEDGE_AVAILABLE = (UNKNOWN, VISITED)

#: ★人に見せる言葉
KNOWLEDGE_LABEL = {
    UNKNOWN: "未訪問",
    HEARD: "話に聞いた",
    DISCOVERED: "発見済み",
    VISITED: "訪問済み",
}


#: ★ゲーム本文の**会話開始記号**（⚠⚠ 話者ではありません / RX3-0118）
TALK_MARK = "＊"

#: ★話者が分からないときに出す字（⚠⚠ `＊` へフォールバックしない）
UNKNOWN_SPEAKER = "？"

#: ★会話開始記号の並び（⚠ **この 2 文字のときだけ**落とす / RX3-0120）
SPEECH_MARK = TALK_MARK + "「"


def strip_speech_marks(text: str) -> str:
    """★続きの段に付く `＊` を落とす（RX3-0120 / 2026-09-08）。

    ```text
    ⚠ いま  老「はなしは すでに きいておる。＊「さあ この まほうのたまで…
    ★こう  老「はなしは すでに きいておる。「さあ この まほうのたまで…
    ```

    ## ⚠⚠ 全文一括で消してはいけない

      ★`text.replace("＊", "")` は、⚠ 本文の中で**意味を持つ** `＊` まで消します。
      → ★落とすのは `＊` が `「` の**直前にあるとき**だけ。

    ## ⚠ 落とすのは**表示のときだけ**

      ★記録（`memos.jsonl` / `npc-conversations.json`）は触りません。
      ⚠ DQ3 の本文では `＊「` が台詞の開始記号なので、★一次情報として残します。
    """
    return (text or "").replace(SPEECH_MARK, "「")


#: ★★ 話者と本文の区切り（RX3-0253 / 2026-09-13 依頼者「勇者メモでかぎ括弧「」双方不要
#:   （今の処理で対応がとれてないので、ない方がすっきりする」）。⚠ 記録は書き換えない（★表示のときだけ）
SPEAKER_GAP = "　"
#: ★記録の頭の「字「」（★話者つきで記録した会話 / RX3-0118）。⚠ 字は 1〜3 字（？ も）
_SPEAKER_HEAD = re.compile(r"^([^\s「」＊]{1,3})「")


def speech_line(speaker: str, body: str) -> str:
    """★会話の 1 行を「字　本文」にする（RX3-0253）。⚠ 「」は開き・閉じとも出さない。

    ```text
    記録  老「はなしは すでに きいておる。＊「さあ この まほうのたまで…とくがよい！」
    表示  老　はなしは すでに きいておる。　さあ この まほうのたまで…とくがよい！
    ```
    ⚠ 本文の中で意味を持つ `＊`（★「＊ の しるし」）は残す（★消すのは `「` の直前の `＊` だけ / RX3-0120）。
    """
    got = strip_speech_marks(body or "")
    got = got.replace("「", SPEAKER_GAP).replace("」", "")
    got = re.sub(r"[ 　]*" + SPEAKER_GAP + r"[ 　]*", SPEAKER_GAP, got).strip(" 　")
    return "%s%s%s" % (speaker, SPEAKER_GAP, got)


@dataclass(frozen=True)
class Memo:
    """勇者が冒険中に得たこと 1 件（指示書 §8）。

    ⚠ すべての欄が埋まる必要はありません。★埋まらないものは `None` のまま。
    """

    order: int
    """★並び。⚠ 時刻ではなく通し番号にする。

    セーブステートを戻すと時刻は巻き戻らないが、★順番なら壊れない。
    """

    text: str
    """★人が読む文。⚠ これ**だけ**を残す実装にしないこと（下の `raw_digest`）。"""

    location_id: str | None = None
    map_id: int | None = None
    npc_id: str | None = None
    item_id: str | None = None
    event_id: str | None = None

    at: str | None = None
    """★書いた時刻（ISO8601 / RX3-0148 / 2026-09-10）。⚠ 昔の行は `None`。

    ## ⚠⚠ `order` の代わりではありません

    ```text
    order  ★ゲームの中の順   ⚠ セーブを戻しても壊れない（★並べるのはこちら）
    at     ★現実の時計       ⚠ セーブを戻すと**進んだまま**（★冒険ログ用）
    ```

    ⚠ 並べ替えに使わないこと。★「いつ遊んだか」を人へ見せるためだけです。
    """

    source: str = "unknown"
    """★どこから来たか（`conversation` / `discovery` / `manual`）。"""

    speaker: str | None = None
    """★話した相手の見た目のラベル（`商` `兵` など / RX3-0118）。

    ⚠⚠ **`＊` を入れないこと。** ★`＊「` はゲーム本文の会話開始記号であって、
    話者ではありません。⚠ 分からないときは `None` のままにし、
    画面は `speaker_label`（= `？`）を出します。
    """

    raw_digest: str | None = None
    """★元の生タイルへ戻るための鍵。

    ⚠⚠ DQ3 の文字コード表はまだ `high-confidence` で、**直る見込み**がある
    （★濁点が 1 行上のマスにあり、合成を間違えると別の語になる）。
    生の記録が残っていれば、表を直したあとで**読み直せる**。
    """

    def matches_location(self, location_id: str) -> bool:
        return self.location_id is not None and self.location_id == location_id

    # --- ★3 ビュー共通の見え方（RX3-0118） -------------------------------
    #
    # ⚠⚠ 画面ごとに整形を書かないこと。★MAP の 3 行・[すべて]・[メモ詳細] は
    #   **ここだけ**を呼びます（⚠ 片方だけ直ると、また食い違います）。

    @property
    def speaker_label(self) -> str:
        """★誰の話か（⚠ 分からなければ `？`。⚠⚠ `＊` は話者にしない）。"""
        got = (self.speaker or "").strip()
        if not got or got == TALK_MARK:
            return UNKNOWN_SPEAKER
        return got

    @property
    def line(self) -> str:
        """★一覧に出す 1 行。

        ⚠ 会話メモは `商「…」` の形（★話者は本文に入っている）。
        ⚠⚠ 古い記録は `＊「…」` のまま残っているので、★出すときに直します
        （⚠ 記録そのものは書き換えません / 一次証跡）。

        ★続きの段に付く `＊` も、ここで落とします（RX3-0120）。
        """
        got = (self.text or "").strip()
        if got.startswith(SPEECH_MARK):
            # ★先頭は話者に置き換える（RX3-0118）/ ★「」は出さない（RX3-0253）
            return speech_line(self.speaker_label, got[len(SPEECH_MARK):])
        head = _SPEAKER_HEAD.match(got)
        if head is not None:
            # ★話者つきで記録した会話（`商「…」`）→ 「字　本文」（RX3-0253）
            return speech_line(head.group(1), got[head.end():])
        # ⚠ 2 段目から先の `＊「` は、★ただの続きなので印だけ落とす（RX3-0120）
        return strip_speech_marks(got)


@dataclass(frozen=True)
class LocationView:
    """地点情報ポップアップに出すもの（指示書 §5）。

    ⚠⚠ **ROM 由来の「正解」をここへ入れないこと。**
    ★作ってよいのは `dq3/ui/view_model.py` だけ（そこが唯一の関所）。
    """

    location_id: str
    name: str | None = None
    """⚠ 名前を知らなければ `None`。★画面は「？」と出す。

    DQ3 の ROM には地名の平文が無く（`RX3-0013`）、★訪れて初めて分かる。
    """

    knowledge: str = UNKNOWN
    memo_count: int = 0
    heard_count: int = 0
    found_count: int = 0
    highlights: list[str] = field(default_factory=list)
    """★直近または重要な 1〜3 件（指示書 §5.1）。"""

    def __post_init__(self) -> None:
        if self.knowledge not in KNOWLEDGE_ORDER:
            raise ValueError("⚠ 知らない状態: %r" % (self.knowledge,))

    @property
    def label(self) -> str:
        return KNOWLEDGE_LABEL.get(self.knowledge, self.knowledge)

    @property
    def display_name(self) -> str:
        """★名前を知らないときは、地名を**出さない**（指示書 §10）。"""
        return self.name if self.name else "？"

    @property
    def is_known(self) -> bool:
        return self.knowledge != UNKNOWN


class MemoBook:
    """勇者メモの束（★逆引きできる形 / 指示書 §8）。

    ⚠ 画面はここから取り出すだけ。★並べ替えや絞り込みはここが持つ。
    """

    def __init__(self, memos=None) -> None:
        self._memos: list[Memo] = list(memos or [])

    def __len__(self) -> int:
        return len(self._memos)

    def __iter__(self):
        return iter(self._memos)

    def add(self, memo: Memo) -> None:
        self._memos.append(memo)

    def newest(self, n=None, *, map_id=None) -> list[Memo]:
        """★新しい順（⚠⚠ **並べ替えはここ 1 か所** / RX3-0118）。

        ⚠ MAP の 3 行・[すべて]・[メモ詳細]・地図画面の 4 つが、
        ★それぞれ `sorted(...)` を書いていました（⚠ うち 1 つは**古い順**）。
        → ★入口を 1 本にします。⚠ 画面側で並べ直さないこと。

        `n`      … ★先頭から何件か（⚠ `None` なら全部）
        `map_id` … ★その地図のものだけ（⚠ `None` なら絞らない）
        """
        got = self._memos if map_id is None else [m for m in self._memos if m.map_id == map_id]
        rows = sorted(got, key=lambda m: m.order, reverse=True)
        return rows if n is None else rows[:max(0, int(n))]

    def recent(self, n: int = 3) -> list[Memo]:
        """★直近 N 件（指示書 §7）。⚠ `order` の大きいほうが新しい。"""
        return self.newest(n)

    def maps(self) -> list[int]:
        """★メモのある地図（⚠ [メモ詳細] の MAP 選択に使う）。"""
        return sorted({m.map_id for m in self._memos if m.map_id is not None})

    def of_location(self, location_id: str) -> list[Memo]:
        """★地点から引く（指示書 §8）。"""
        return [m for m in self._memos if m.matches_location(location_id)]

    def of_map(self, map_id: int) -> list[Memo]:
        return [m for m in self._memos if m.map_id == map_id]

    def of_item(self, item_id: str) -> list[Memo]:
        """⚠ いまは空で返る（★`RX3-0016` で `item_id` が埋まってから効く）。"""
        return [m for m in self._memos if m.item_id == item_id]

    def of_npc(self, npc_id: str) -> list[Memo]:
        """⚠ 同上。★引ける形だけ先に作っておく。"""
        return [m for m in self._memos if m.npc_id == npc_id]

    def as_dicts(self) -> list[dict]:
        return [dataclasses.asdict(m) for m in self._memos]

    @classmethod
    def from_dicts(cls, rows) -> "MemoBook":
        fields = {f.name for f in dataclasses.fields(Memo)}
        out = []
        for row in rows or []:
            # ⚠ 知らない欄は黙って捨てる（★古い記録も読めるように）
            out.append(Memo(**{k: v for k, v in row.items() if k in fields}))
        return cls(out)
