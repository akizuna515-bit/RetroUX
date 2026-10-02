"""聞いた会話 → Concept → Relation →（根拠があれば）Fact（RX3-0070 / 2026-09-03）。

★★ 会話を「理解する」のではありません ★★

  ⚠ 目的は、**実際に聞いた短い発話**から、攻略上意味のある **ID と関係**を
    **誤認せずに**取り出せると示すことです。

```text
Observation（聞いた文＋どこで誰から）
   ↓ Matcher（★runtime の名前 / 方角 / 場所の型）
Concept（★item:<id> / direction:south / place_type:forest）
   ↓ 同じ発話の中の言い回し
Relation（★obtain_hint など）
   ↓ ⚠ 根拠が足りるときだけ
Fact（subject / predicate / object / 出典 / 確度）
```

## ⚠⚠ 守ること

```text
★名前を identity にしない      Concept は (kind, id)。名前は runtime の表示属性
⚠ Observation と Fact を混ぜない  「レーベで聞いた」は文脈。★「レーベにある」ではない
⚠⚠ 曖昧なら Fact を作らない     ★誤りを増やすより、作らないほうを選ぶ
```

## ★実測で分かったこと（⚠ 素の部分一致では当たらない）

```text
道具の表   ひらがなで綴られている（CHR タイル 0x110 台）
会話の文   同じ品を**カタカナ**で綴っている（0x140 台）
```

⚠⚠ **ROM 自身が 2 か所で綴りを変えています**（★復号の誤りではありません /
2026-09-03 に「かぎ」を含む品で実測）。
★字形表にカタカナの リ が無く ひらがな り を使い回す例もあり、
同じ語でも綴りが揺れます。
→ ★照合の前に**かなを畳みます**（`fold`）。⚠ これが無いと 1 件も当たりません。

## ⚠ ここに置いてよい言葉／いけない言葉

```text
★置く    方角（きた / みなみ …）と 場所の型（むら / もり …）＝ ふつうの日本語
⚠⚠ 置かない  敵 / 品 / 呪文の名前、会話の本文
          ★それらは実行時に ROM から起こす（`rom_names`）
```
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import unicodedata

from dq3.knowledge import rom_names

from .. import ownership as _own
from .. import paths

#: ★1 発話の区切り（⚠ DQ3 は「＊」で次の発話に移る）
UTTERANCE_MARK = "＊"

#: ⚠ 照合のときに落とす記号（★意味を持たない飾り）
DROP = "＊「」『』。、？！‥…・　 \t\n\r"

#: ⚠⚠ **`fold` は NFKC で正規化してから突き合わせます**（RX3-0296 / 2026-09-18）。
#:
#:   ★`DROP` は「見たままの字」で書いてあるので、⚠ NFKC で形が変わる字は
#:     **落ちずに生き残っていました**:
#:
#:   ```text
#:   ＊ → *      ？ → ?      ！ → !      ‥ → ..      … → ...
#:   fold("＊「こんにちは。") → "*こんにちは"   ⚠ 発話の区切り ＊ が落ちていない
#:   ```
#:
#:   → ★`DROP` も**同じ正規化を通して**から集合にします。
#:   ⚠ `‥`/`…` は `.` に開くので、★半角のピリオドも落ちます（⚠ ゲームの本文には出ない）。
#:
#:   ⚠ 全角のままの字を足す必要はありません。★`fold` は**本文を先に正規化する**ので、
#:     全角のまま突き合わせに届く字はありません（★壊す実験で確かめた / 足しても空振り）。
_DROP_SET = frozenset(unicodedata.normalize("NFKC", DROP))

#: ★方角（⚠ ふつうの日本語。原作固有の語ではない）
DIRECTIONS = {"きた": "north", "みなみ": "south", "ひがし": "east", "にし": "west"}

#: ★場所の型（⚠ 固有のダンジョン名は扱わない / 指示書 §6）
PLACE_TYPES = {
    "まち": "town", "むら": "village", "しろ": "castle", "とう": "tower",
    "どうくつ": "cave", "ほこら": "shrine", "もり": "forest",
}

#: ★「手に入れたか」を尋ねる言い回し（⚠ 語幹だけ）
OBTAIN_HINT_PHRASES = ("てにいれ",)

#: ⚠ 対象がはっきりしない「ほのめかし」（★Fact にしない / 指示書 §11）
GENERIC_HINT_PHRASES = ("かもしれ", "あやしげ", "らしい")

#: ⚠ 短い名前は誤って当たる（★3 文字以上だけ照合する）
MIN_ALIAS = 3

#: ★語のうしろに来てよい字（⚠ 助詞と区切り。これ以外なら語の途中とみなす）
#:
#:   ⚠⚠ 実測の誤り（2026-09-03）: ある品名の先頭 2 字が「とう」で place_type:tower に、
#:     「お…しております」系の動詞の中の 2 字が place_type:town になった。
#:   ★形態素解析は入れず、**うしろの 1 字**で切ります。
FOLLOWERS = "のにへでをがはとやかもまでよねさじだ"

#: ★Fact にしてよい確度（⚠ これ未満は Concept / Relation で止める / 指示書 §14）
#:
#:   1.0  実体が当たり、★言い回しも当たった
#:   0.5  ⚠ 分類の語だけ（★どれのことか決められない）
FACT_MIN_CONFIDENCE = 0.8

KINDS = ("monster", "item", "spell")

#: ★「聞いた」Fact にする Concept の型（⚠ `place_type` / `direction` は入れない）
#:
#:   ⚠⚠ 2026-09-27（RX3-0432）: ★`obtain_hint` だけでは**会話 884 件で 1 種**しか
#:     立ちませんでした（`OBTAIN_HINT_PHRASES` が `てにいれ` の 1 語だけで、
#:     ★同じ発話に実体名と両方要るため）。
#:   → ★「勇者がその名前を会話で**聞く機会があった**」を `heard` として出します。
#:     ⚠ 攻略ヒントかどうかは判定しません（★指示書 §6 / 依頼者 2026-09-27）。
HEARD_TYPES = KINDS + ("location", "word")

#: ★境目の印（⚠ 本文には出ない字）。`fold_marked` が `DROP` の字をこれに置き換える
BOUNDARY = "\x00"


def fold(text: str) -> str:
    """★照合のための正規化。⚠ カタカナを ひらがな に畳み、飾りを落とす。

    ⚠⚠ **これが無いと当たりません。** ★ROM 自身が、道具の表では
      ひらがな、会話ではカタカナ、と綴りを変えているためです（実測）。

    ⚠ 落とす記号は `_DROP_SET`（★`DROP` を**同じ正規化にかけたもの** / RX3-0296）。
    """
    got = unicodedata.normalize("NFKC", text or "")
    out = []
    for ch in got:
        if ch in _DROP_SET:
            continue
        code = ord(ch)
        # ⚠ カタカナ → ひらがな（★濁点つきも同じだけずれる）
        if 0x30A1 <= code <= 0x30F6:
            ch = chr(code - 0x60)
        out.append(ch)
    return "".join(out)


def fold_marked(text: str) -> str:
    """★`fold` と同じだが、⚠ 落とす字を**境目の印に置き換える**（消さない）。

    ## ⚠⚠ なぜ要るか（2026-09-27 / RX3-0432 の実測）

    ★`fold` は空白を**消す**ので、⚠ 離れた 2 語がつながって別の名前を作ります。

    ```text
    「はるか にし…」 → fold → "はるかにし"  ⚠⚠ ここに呪文 `ルカニ`（るかに）が入る
    ```

    ⚠ 実測: 会話 884 件で **2 件**がこれで誤爆していました。
    ★境目を残すと、⚠ **本物の当たりは 1 件も失わずに**（312→312）この 2 件だけ消えます。

    ⚠ 名前の側は `fold` のままにします（★印は名前に出ないので、
      境目をまたぐ当たりが自然に成立しなくなります）。
    """
    out = []
    for ch in unicodedata.normalize("NFKC", text or ""):
        if ch in _DROP_SET:
            out.append(BOUNDARY)
            continue
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            ch = chr(code - 0x60)
        out.append(ch)
    return "".join(out)


# --- ★型 ---------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Observation:
    """一次観測。★いつでも元へ戻れるように、文脈ごと持つ。"""

    observation_id: str
    text: str
    map_id: int | None = None
    npc_id: int | None = None
    talk_id: int | None = None
    frame: int | None = None
    window_type: str = "dialog"

    def utterances(self) -> list[str]:
        """★「＊」で切った 1 発話ずつ（⚠ 発話をまたいで組み合わせない / §9）。"""
        return [u for u in (p.strip() for p in self.text.split(UTTERANCE_MARK)) if u]

    def to_json(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Concept:
    """★会話の中に見つけた意味。⚠ 主キーは `(type, entity_id)`。"""

    type: str
    entity_id: int | None = None
    #: ⚠ `place_type` / `direction` のように id を持たないものの値
    value: str | None = None
    #: ★当たった runtime の名前（⚠ 表示のためだけ。鍵にしない）
    alias: str | None = None
    utterance: int = 0

    @property
    def concept_id(self) -> str:
        if self.entity_id is not None:
            return "%s:%d" % (self.type, self.entity_id)
        return "%s:%s" % (self.type, self.value)

    def to_json(self) -> dict:
        got = {"concept_id": self.concept_id, "type": self.type, "utterance": self.utterance}
        if self.entity_id is not None:
            got["entity_id"] = self.entity_id
        if self.value is not None:
            got["value"] = self.value
        if self.alias is not None:
            got["alias"] = self.alias
        return got


@dataclasses.dataclass(frozen=True)
class Relation:
    """★同じ発話の中で見つけた関係。⚠ Fact ではない。"""

    name: str
    utterance: int = 0
    evidence: str = ""

    def to_json(self) -> dict:
        return {"relation": self.name, "utterance": self.utterance, "evidence": self.evidence}


@dataclasses.dataclass(frozen=True)
class Fact:
    """⚠⚠ **根拠が足りるときだけ**作る（★指示書 §3.3）。

    ★`analyse` は候補を確度つきで作り、⚠ `FACT_MIN_CONFIDENCE` 未満は
      `facts` に入れず `rejected` に理由つきで残します（指示書 §18）。
    """

    subject: str
    predicate: str
    object: str | None
    source_observation_id: str
    confidence: float
    #: ⚠ 落ちたときの理由（★なぜ Fact にしなかったかを追えるように）
    reason: str = ""

    @property
    def fact_id(self) -> str:
        return fact_id_of(self.subject, self.predicate, self.object, self.source_observation_id)

    def to_json(self) -> dict:
        got = {"fact_id": self.fact_id, "subject": self.subject,
               "predicate": self.predicate, "object": self.object,
               "source_observation_id": self.source_observation_id,
               "confidence": self.confidence}
        if self.reason:
            got["reason"] = self.reason
        return got


# --- ★場所の名前（⚠ ROM のルーラ表 ＋ 人が承認した表）-------------------------

#: ★人が `name` を書く表（⚠ 由来は実プレイ / RX3-0432）
#:
#:   ⚠⚠ `locations.NAMES_PATH` が**同じ表を別に持っています**。
#:     ★どちらも `ownership.lazy_resolve()` を通すので、user 側の上書きが
#:     ⚠ **片方だけ効く**ことはありません（2026-10-01 / `RX3-0472`）。
LOCATION_NAMES = _own.lazy_resolve("data/dq3/location-names.csv")


#: ★ふつうの語で「話題」として聞いたか見る語（RX3-0436 / 例: オーブ）
#:   ⚠ 品・敵・呪文・場所の**名前ではない**一般の語だけ。★人が 1 行ずつ足す（推測で増やさない）
CONCEPT_WORDS = pathlib.Path(__file__).resolve().parents[2] / "data" / "dq3" / "concept-words.csv"


def word_aliases(path=None) -> list[tuple[str, str]]:
    """★(畳んだ語, 書いた語) の並び。⚠ 3 文字未満は当てない（`MIN_ALIAS`）。"""
    import csv

    got: dict[str, tuple[str, str]] = {}
    try:
        with open(path or CONCEPT_WORDS, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                word = (row.get("word") or "").strip()
                folded = fold(word)
                if word and len(folded) >= MIN_ALIAS:
                    got.setdefault(folded, (folded, word))
    except (OSError, ValueError):                   # ⚠ 無ければ語は無し
        pass
    return list(got.values())


#: ★利用者が**ゲームを遊びながら自分で付けた**地名（RX3-0432 / 2026-09-27 に気づいた）
#:  ⚠ `work/` にある実行時の記録。★repo には入りません。
PLAYER_KNOWLEDGE = paths.lazy_work("dq3-knowledge", "player-knowledge.json")


def place_aliases(rom_path=None, knowledge_path=None,
                  min_len: int = MIN_ALIAS) -> list[tuple[str, str, str]]:
    """★(畳んだ名前, `L<map 番号>`, 元の名前) の並び。⚠ 由来が明らかなものだけ。

    `min_len` … ★何文字から採るか（⚠ 既定は会話の照合と同じ `MIN_ALIAS`）。

    ## ⚠⚠ 2026-09-28（RX3-0442）: 「照合する」と「名前で書ける」を分けました

    ★短い名前を落とすのは**会話の中で誤って当たる**のを避けるためです（`MIN_ALIAS`）。
    ⚠ ところが同じ表を「勇者メモに名前で書けるか」にも使っていたため、
      ★**2 文字の地名は書きようがありませんでした**（実測: ルーラ表の 1 件）。
    → ★名前 → `location_id` を**引くだけ**の用（`hero_memo` / 門番）は `min_len=1` で呼びます。
      ⚠ 会話の照合（`Matcher.places`）は既定のままです。

    ```text
    ★ROM のルーラ表         利用者の ROM から（⚠ 20 件）
    ★location-names.csv     人が書いた表（⚠ 推測は書かない約束）
    ★player-knowledge.json  ⚠⚠ **利用者が遊びながら自分で付けた名前**
    ```

    ⚠⚠ **攻略サイト由来の名前は 1 つも入りません**（★どれも出どころが明らか）。

    ## ⚠⚠ 3 つめに気づくのが遅れました（2026-09-27）

    ★「地名が無い場所が 152 か所ある」と数えていましたが、⚠ **利用者は既に
    57 か所に名前を付けていました**（`player-knowledge.json` の `location_names`）。
    ★`LocationCatalog` は前から読んでいたのに、⚠ こちらが読んでいませんでした。

    ⚠ 同じ場所に複数の綴りが付くことがあります（★`ナジミの塔` と `ナジミのとう`）。
      → ★どちらも別の別名として入れます（⚠ 会話の照合は**ゲームの綴り**が要る）。
    """
    got: dict[str, tuple[str, str, str]] = {}

    def put(name, location_id):
        folded = fold(name or "")
        if name and len(folded) >= min_len:
            got.setdefault(folded, (folded, str(location_id), name))

    try:
        for index, map_id in enumerate(rom_names.place_maps(rom_path)):
            put(rom_names.place(index, rom_path), "L%d" % int(map_id))
    except Exception:                              # noqa: BLE001 - ★ROM が無ければ飛ばす
        pass
    try:
        import csv

        with open(LOCATION_NAMES, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                put((row.get("name") or "").strip(), row["location_id"])
    except (OSError, ValueError, KeyError):         # ⚠ 無ければ ROM の分だけ
        pass
    try:
        import json as _json

        target = pathlib.Path(knowledge_path) if knowledge_path else PLAYER_KNOWLEDGE
        raw = _json.loads(pathlib.Path(target).read_text(encoding="utf-8"))
        for location_id, name in (raw.get("location_names") or {}).items():
            put(str(name).strip(), location_id)
    except (OSError, ValueError, TypeError):       # ⚠ 記録が無ければ飛ばす
        pass
    return list(got.values())


# --- ★Matcher -----------------------------------------------------------------

class Matcher:
    """★runtime の名前辞書と、ふつうの日本語の語で照合する。

    ⚠ 名前は **ROM から実行時に**もらいます（`rom_names`）。
      ★repo には 1 語も持ちません。
    """

    def __init__(self, rom_path=None, kinds=KINDS, places=True) -> None:
        self.rom_path = rom_path
        #: ★畳んだ名前 → (kind, id, 元の名前)。⚠ 長いものから当てる
        self.aliases: list[tuple[str, str, int, str]] = []
        #: ★場所（⚠ id ではなく `L<map 番号>` を持つ / RX3-0432）
        #:  → ★`Concept(type="location", value="L68")` になり、
        #:    ⚠ `concept_id` が `location:L68` = **`visit` の Fact と同じ形**になる。
        self.places: list[tuple[str, str, str]] = place_aliases(rom_path) if places else []
        self.places.sort(key=lambda row: -len(row[0]))
        #: ★一般の語（`concept-words.csv` / RX3-0436）
        self.topic_words: list[tuple[str, str]] = word_aliases()
        data = rom_names._load(rom_path)
        if data is None:
            return
        for kind in kinds:
            for key, name in (data.get("names") or {}).get(kind, {}).items():
                folded = fold(name)
                if len(folded) < MIN_ALIAS:
                    continue                      # ⚠ 短すぎる名前は当てない
                self.aliases.append((folded, kind, int(key), name))
        self._add_concept_aliases(places)
        self.aliases.sort(key=lambda row: -len(row[0]))
        self.places.sort(key=lambda row: -len(row[0]))

    def _add_concept_aliases(self, places: bool) -> None:
        """★ゲーム内の言い回しを、**正規の Concept の名前**として足す（RX3-0440）。

        ★別名が当たったら、⚠ Concept は**正規の品**の id になる（⚠ 例の語はここに書かない / 本文と名前はソースに置かない）。
        → heard Fact に残るのは正規の Concept だけ（★別名の表現は Fact にならない）。
        ⚠ 正規の名前が引けない別名は足さない（★検査が ERROR にする / `concept_aliases.problems`）。
        """
        from dq3.knowledge import concept_aliases as CA

        by_name = {(kind, folded): (entity_id, name)
                   for folded, kind, entity_id, name in self.aliases}
        by_place = {folded: (location_id, name) for folded, location_id, name in self.places}
        for kind, canonical, alias in CA.entries(CA.load()):
            folded = fold(alias)
            if len(folded) < MIN_ALIAS:
                continue
            if kind == "place":
                hit = by_place.get(fold(canonical)) if places else None
                if hit:
                    self.places.append((folded, hit[0], hit[1]))
                continue
            hit = by_name.get((kind, fold(canonical)))
            if hit:
                self.aliases.append((folded, kind, int(hit[0]), hit[1]))

    @property
    def available(self) -> bool:
        return bool(self.aliases)

    def entities(self, utterance: str, index: int) -> tuple[list[Concept], list[tuple[int, int]]]:
        """★発話の中の実体と、その占めた範囲（⚠ 長い名前を先に取る）。

        ⚠⚠ 2026-09-27（RX3-0432）: 干し草の側を `fold_marked` にしました。
          ★離れた 2 語がつながって別の名前になる誤爆を消すためです（⚠ 実測 2 件）。
        """
        folded = fold_marked(utterance)
        got: list[Concept] = []
        taken: list[tuple[int, int]] = []

        def take(alias: str) -> tuple[int, int] | None:
            at = folded.find(alias)
            while at >= 0:
                span = (at, at + len(alias))
                if not any(a < span[1] and span[0] < b for a, b in taken):
                    taken.append(span)
                    return span
                at = folded.find(alias, at + 1)    # ⚠ もっと長い名前に含まれていた
            return None

        for alias, kind, entity_id, name in self.aliases:
            if take(alias):
                got.append(Concept(type=kind, entity_id=entity_id,
                                   alias=name, utterance=index))
        for alias, location_id, name in self.places:
            if take(alias):
                got.append(Concept(type="location", value=location_id,
                                   alias=name, utterance=index))
        # ★一般の語は**名前の中に出ても当てる**（⚠ `taken` を見ない / 場所も取らない）。
        #   ★語を含む品名を聞いたなら、その語が指すものも知った、とみなす（RX3-0436）。
        for alias, word in self.topic_words:
            if alias in folded:
                got.append(Concept(type="word", value=word, alias=word, utterance=index))
        return got, taken

    @staticmethod
    def _standalone(folded: str, word: str, taken: list[tuple[int, int]]) -> bool:
        """★その語が「語として」出ているか。

        ⚠⚠ 素の部分一致は誤ります（★2026-09-03 の実測）。
          品名の先頭 2 字が場所の型と同じ / 動詞の中に場所の型が入る、の 2 件。
        ★① 名前に重なっていない ② うしろが助詞か区切り、の両方を見ます。

        ⚠⚠ 2026-09-27（RX3-0432）: 渡される `folded` は `fold_marked` の結果です。
          ★`entities()` の `taken` と**同じ座標系**でないと重なりを見誤ります
          （⚠ 実際に取りこぼしました）。境目の印は「うしろが区切り」として扱います。
        """
        at = folded.find(word)
        while at >= 0:
            span = (at, at + len(word))
            overlapped = any(a < span[1] and span[0] < b for a, b in taken)
            after = folded[span[1]] if span[1] < len(folded) else ""
            if not overlapped and (after in ("", BOUNDARY) or after in FOLLOWERS):
                return True
            at = folded.find(word, at + 1)
        return False

    @classmethod
    def words(cls, utterance: str, index: int,
              taken: list[tuple[int, int]] | None = None) -> list[Concept]:
        """★方角と場所の型（⚠ id を持たない Concept）。

        ⚠ `entities()` と**同じ座標系**で見る（★`fold_marked`）。
        """
        folded = fold_marked(utterance)
        taken = taken or []
        got = []
        for table, kind in ((DIRECTIONS, "direction"), (PLACE_TYPES, "place_type")):
            for word, value in table.items():
                if cls._standalone(folded, word, taken):
                    got.append(Concept(type=kind, value=value, alias=word, utterance=index))
        return got


# --- ★解析 ---------------------------------------------------------------------

def analyse(observation: Observation, matcher: Matcher | None = None) -> dict:
    """★1 つの観測から Concept / Relation /（根拠があれば）Fact を出す。"""
    matcher = matcher if matcher is not None else Matcher()
    concepts: list[Concept] = []
    relations: list[Relation] = []
    #: ★確度つきの候補（⚠ ここから下限で振り分ける）
    candidates: list[Fact] = []
    tags: list[str] = []

    for index, utterance in enumerate(observation.utterances()):
        folded = fold(utterance)
        found, taken = matcher.entities(utterance, index)
        here = found + matcher.words(utterance, index, taken)
        concepts.extend(here)

        entities = [c for c in here if c.entity_id is not None]
        directions = [c for c in here if c.type == "direction"]
        places = [c for c in here if c.type == "place_type"]

        # --- ★「聞いた」（2026-09-27 / RX3-0432）-----------------------------
        #   ⚠⚠ 言い回しは**見ません**。★名前が会話に出たら「知る機会があった」。
        #     ⚠ 攻略ヒントかどうかの判定はしません（★依頼者 2026-09-27）。
        #   ★実測: これで 1 種 → **103 種**になりました（会話 884 件）。
        for concept in here:
            if concept.type in HEARD_TYPES:
                candidates.append(Fact(subject=concept.concept_id, predicate="heard",
                                       object=None,
                                       source_observation_id=observation.observation_id,
                                       confidence=1.0))

        # --- Pattern A: 実体 ＋「てにいれ」→ obtain_hint -----------------------
        phrase = next((p for p in OBTAIN_HINT_PHRASES if p in folded), None)
        if phrase and entities:
            relations.append(Relation("obtain_hint", index, phrase))
            for concept in entities:
                # ★実体が当たり、言い回しも当たった → 1.0（⚠ object は作らない）
                candidates.append(Fact(subject=concept.concept_id, predicate="obtain_hint",
                                       object=None,
                                       source_observation_id=observation.observation_id,
                                       confidence=1.0))

        # --- Pattern B: 方角 ＋ 場所の型 → direction（⚠ Fact にしない）---------
        if directions and places:
            relations.append(Relation("direction", index,
                                      "%s+%s" % (directions[0].alias, places[0].alias)))
            # ⚠⚠ **どの場所が南にあるか**は決められない（★指示書 §10 Pattern B）。
            #   ★候補は作るが、⚠ 確度 0.5 なので下限で落ちる（★落ちた理由を残す）。
            candidates.append(Fact(subject=places[0].concept_id, predicate="direction",
                                   object=directions[0].concept_id,
                                   source_observation_id=observation.observation_id,
                                   confidence=0.5,
                                   reason="⚠ 分類の語だけ（★どの場所かを決められない）"))

        # --- ⚠ ほのめかしだけ（★対象が無い）---------------------------------
        if not entities and any(p in folded for p in GENERIC_HINT_PHRASES):
            tags.append("generic_hint")

    return {
        "observation": observation.to_json(),
        "concepts": [c.to_json() for c in concepts],
        "relations": [r.to_json() for r in relations],
        "facts": [f.to_json() for f in candidates
                  if f.confidence >= FACT_MIN_CONFIDENCE],
        # ⚠ 落ちた候補（★なぜ Fact にしなかったかの記録 / 指示書 §18）
        "rejected": [f.to_json() for f in candidates
                     if f.confidence < FACT_MIN_CONFIDENCE],
        "tags": sorted(set(tags)),
    }


# --- ★実測の読み込み（⚠ work/ の記録。repo には無い）----------------------------

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONVERSATIONS = paths.lazy_work("dq3-knowledge", "npc-conversations.json")


MEMOS = paths.lazy_work("dq3-knowledge", "memos.jsonl")

#: ★勇者メモのうち、会話として勇者会議の材料にするもの（RX3-0185）
#:   `conversation` = 手で話した会話 / `npc_talk` = 聞き込み（★台帳に無いページもここには残っている / RX3-0184）
MEMO_SOURCES = ("conversation", "npc_talk")


def fact_id_of(subject, predicate, obj, observation_id) -> str:
    """★Fact の番号（⚠ 作り方は 1 か所 / RX3-0235 の移し替えでも同じ式を使う）。"""
    raw = "%s|%s|%s|%s" % (subject, predicate, obj, observation_id)
    return "fact-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def logical_fact_id(subject, predicate, obj) -> str:
    """★論理 Fact の番号（⚠ 観測を含めない = 同じ知識は 1 つ / RX3-0436）。"""
    raw = "%s|%s|%s" % (subject, predicate, obj)
    return "lfact-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def logical_facts(facts) -> tuple[list[dict], dict[str, str]]:
    """★観測ごとの Fact → 論理 Fact（RX3-0436）。

    ```text
    Observation   複数あってよい（★同じ名前を 4 人から聞いた）
    Fact          論理的に 1 つ（subject / predicate / object で決まる）
    ```

    ⚠ 履歴は消しません。論理 Fact は `source_observation_ids`（聞いた順）・
    `observation_fact_ids`・`count` を持ちます（★最初と最後は並びの両端）。

    戻り値: (論理 Fact の並び（最初に出た順）, 観測ごとの fact_id → 論理 fact_id)
    """
    got: dict[str, dict] = {}
    renames: dict[str, str] = {}
    for fact in facts:
        key = logical_fact_id(fact.get("subject"), fact.get("predicate"), fact.get("object"))
        renames[fact.get("fact_id")] = key
        one = got.get(key)
        if one is None:
            one = got[key] = dict(fact, fact_id=key, source_observation_ids=[],
                                  observation_fact_ids=[], count=0)
        if fact.get("fact_id") in one["observation_fact_ids"]:
            continue                                  # ⚠ 同じ観測の同じ Fact（発話 2 つ）は 1 回
        one["observation_fact_ids"].append(fact.get("fact_id"))
        one["source_observation_ids"].append(fact.get("source_observation_id"))
        one["count"] += 1
    return list(got.values()), renames


def _memo_observation_id(row: dict, n: int) -> str:
    """★勇者メモの会話の Observation の番号（RX3-0235 / 指示書 §14）。

    ⚠⚠ 以前は**行番号**（`memo-<行>`）→ 場所ごとに行を消すと、後ろのメモの Fact がすべて別の番号になり、
      Topic が同じ話を新しい Fact として数え直した（★更新回数が進む）。
    ★通し番号 `order`（MemoStore が振る / ⚠ 消しても振り直さない）で作る。⚠ order の無い昔の行は行番号のまま。
    """
    order = row.get("order")
    return "memo-o%d" % order if isinstance(order, int) and not isinstance(order, bool) else "memo-%d" % n


def legacy_memo_ids(memos_path=None) -> dict:
    """★新しい番号（order）→ 行番号の番号。★Topic の記録を 1 度だけ付け替えるため（`council` / RX3-0235）。"""
    try:
        lines = pathlib.Path(memos_path or MEMOS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out = {}
    for n, line in enumerate(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("source") in MEMO_SOURCES:
            new = _memo_observation_id(row, n)
            if new != "memo-%d" % n:
                out[new] = "memo-%d" % n
    return out


def _plain(text: str) -> str:
    """★照合用に、話し手の字・「＊」「「」」・空白を落とす（⚠ 本文は変えない）。"""
    body = text or ""
    if len(body) >= 2 and body[1] == "「" and body[0] not in "＊「":
        body = body[1:]                              # ★勇者メモの「兵「…」」の 1 字
    return "".join(ch for ch in body if ch not in "＊「」 　")


def observations(path=None, memos_path=None) -> list[Observation]:
    """★聞いた会話の記録（＋勇者メモの会話）を Observation にする。⚠ 無ければ空。

    ⚠⚠ RX3-0185（2026-09-12 依頼者「ききこみでなく、自前で会話を収集しても反映されるよね？」→ ⚠ されていなかった）:
      会話の台帳（npc-conversations.json）へ書くのは聞き込みだけで、⚠ **手で話した会話は勇者メモにしか無い**。
    → ★勇者メモの会話も読む。⚠ 台帳に同じ本文（の一部）があれば数えない（★同じ話を 2 度数えない）。
    ★`path` を渡されたら、勇者メモも**同じ置き場**から読む（★検査が本物のメモを読まない）。
    """
    target = pathlib.Path(path) if path else CONVERSATIONS
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    got = []
    for key, rows in (raw or {}).items():
        map_id = int(key.split("/")[0]) if "/" in key else None
        for row in rows or []:
            got.append(Observation(
                observation_id="obs-%s-%s" % (key.replace("/", "-"), row.get("text_hash", "")[:8]),
                text=row.get("text") or "", map_id=map_id,
                npc_id=row.get("npc_id"), talk_id=row.get("talk_id")))
    if memos_path is None:
        memos_path = target.parent / MEMOS.name if path else MEMOS
    return got + _memo_observations(memos_path, [_plain(o.text) for o in got])


def _memo_observations(path, known: list[str]) -> list[Observation]:
    """★勇者メモの会話 → Observation（⚠ 台帳にある本文と、同じメモの 2 度目は飛ばす）。"""
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    seen = list(known)
    out = []
    for n, line in enumerate(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("source") not in MEMO_SOURCES:
            continue
        text = str(row.get("text") or "")
        plain = _plain(text)
        if not plain or any(plain in other for other in seen):
            continue
        seen.append(plain)
        out.append(Observation(observation_id=_memo_observation_id(row, n), text=text,
                               map_id=row.get("map_id"), npc_id=row.get("npc_id")))
    return out


def main(argv=None) -> int:
    """★CLI: 聞いた会話を JSONL で出す（⚠ 原文は Observation 側にだけ置く）。"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="聞いた会話 → Concept / Relation / Fact")
    parser.add_argument("--source", default=None, help="npc-conversations.json の場所")
    parser.add_argument("--rom", default=None, help="ROM（★省くと既定）")
    parser.add_argument("--only-facts", action="store_true", help="★Fact が出たものだけ")
    args = parser.parse_args(argv)

    matcher = Matcher(args.rom)
    if not matcher.available:
        print("⚠ 名前辞書が使えません: %s" % rom_names.last_error, file=sys.stderr)
    rows = observations(args.source)
    if not rows:
        print("⚠ 聞いた会話の記録がありません", file=sys.stderr)
        return 1
    for observation in rows:
        got = analyse(observation, matcher)
        if args.only_facts and not got["facts"]:
            continue
        print(json.dumps(got, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
