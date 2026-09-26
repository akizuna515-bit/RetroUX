"""★勇者が知っていて、まだ行っていない場所（RX3-0113 / 2026-09-10）。

## ⚠⚠ なぜ濾し器が要るのか

★ゲームは「戻れる町」を RAM（`$0750`）に持ち、⚠ ROM には **20 件の地名がそのまま**
入っています（`rom_names.place`）。

```text
アリアハン レーベ ロマリア カザーブ ノアニール アッサラーム イシス ポルトガ
バハラタ ダーマ ランシール ジパング エジンベア サマンオサ スー ラダトーム
ドムドーラ メルキド マイラ リムルダール
```

⚠⚠ **素で出すと、初見のプレイに終盤までの地名を渡します。**
→ ★出してよいのは「**勇者が知っている**」場所だけです。

```text
World Knowledge（ROM / Guide Master）  ★正本（⚠ 消さない）
  → ★Player Knowledge の濾し器          ⚠⚠ ここ
    → 勇者会議の「行ってみる？」
```

⚠ 同じ考えの先例が `council.known_topic`（RX3-0117）です。★あちらは Topic、こちらは場所。

## ★出してよい条件（依頼者 2026-09-10 / `docs/20-decision-log.md`）

```text
① 記録済みの会話の本文に、その名前が出た        ⚠ 勇者が**聞いて**知っている
② 勇者が知っている Topic が、その場所を指している ⚠ 勇者が**辿り着いて**知っている
```

⚠ 除外: ★もう行った場所 ／ ⚠ 条件を満たさない場所（= **ROM にあるだけ**）

## ★2 種類の場所

```text
町（ルーラの 20 件）  ★名前は ROM、⚠ 行ったかは `$0750` と `location_book` の両方で見る
その他（塔・洞窟）    ★名前は Guide Master、⚠ 行ったかは `location_book` だけ
```

⚠⚠ **`$0750` は「町」にしか立ちません。** ★洞窟へ行っても bit は立たないので、
「ゲームの記録に無い = 行っていない」とは**言えません**（`compare_visited` の注記）。
"""
from __future__ import annotations

import dataclasses

#: ★出どころ（⚠ 画面には出さない。★なぜ出したかを説明するため）
BY_TALK = "talk"        #: 会話に名前が出た
BY_TOPIC = "topic"      #: 知っている話が指している

#: ★人が読む言い方（⚠ 内部の語をそのまま出さない / RX3-0123 と同じ作法）
WHY_TEXT = {
    BY_TALK: "話に出た",
    BY_TOPIC: "追っている話に出てくる",
}


@dataclasses.dataclass(frozen=True)
class Reachable:
    """★行ってみる価値のある場所 1 件。"""

    name: str
    location_id: str | None = None    #: ⚠ 解けなければ None（★名前だけで出す）
    why: tuple = ()                   #: ★`BY_TALK` / `BY_TOPIC`
    rura_index: int | None = None     #: ★ルーラで戻れる町なら、その索引

    @property
    def why_text(self) -> str:
        return " / ".join(WHY_TEXT.get(w, w) for w in self.why)


# ----------------------------------------------------------------------
# ★材料（⚠ どれも「無ければ空」。★推測しない）
# ----------------------------------------------------------------------

def spoken_names(conversations: dict | None = None) -> str:
    """★記録済みの会話を 1 本につないだ文（⚠ 名前の照合に使うだけ）。"""
    if conversations is None:
        import json

        from .. import paths

        try:
            conversations = json.loads(
                paths.work("dq3-knowledge", "npc-conversations.json")
                .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
    out = []
    for key, rows in (conversations or {}).items():
        if "/" not in str(key):
            continue
        for row in rows or []:
            got = (row or {}).get("text")
            if got:
                out.append(str(got))
    return " ".join(out)


#: ★短い名前は誤って当たる（⚠ `concepts.MIN_ALIAS` と同じ考え）
MIN_NAME = 3

def _is_hiragana(ch: str) -> bool:
    return "ぁ" <= ch <= "ゟ"


def spoken(name: str, talk: str, reading: str | None = None) -> bool:
    """★その名前が、記録済みの会話に出たか。

    ⚠⚠ **素の一致では当たりません。** ★ROM の地名表は**カタカナ**、
      会話の復号は**ひらがな**が混ざります（実測 2026-09-10）。

    ```text
    ROM   レーベ    30ec 30fc 30d9   ⚠ ベ はカタカナ
    会話  レーべ    30ec 30fc 3079   ⚠ べ はひらがな
    ```

    → ★`concepts.fold`（カタカナ → ひらがな）を通してから照合します。
    ⚠ 2 文字以下は誤って当たるので見ません。

    ⚠⚠ 2026-09-12（RX3-0178）: 部分一致だけでは、ロマリアの兵士の
      「アりアハンから**まいら**れた おかたでは？」が町の「マイラ」に当たり、
      まだ名前も聞いていない町を「行ける所」に出していました（ネタバレ）。
    → ★名前のすぐ後ろが**ひらがな**なら、`concepts.FOLLOWERS`（助詞と区切りの 1 字）のときだけ当たりにします
      （★文の終わり・記号・空白・カタカナの後ろはそのまま当たり）。
      ⚠ 同じ決まりを 2 か所に書かない（★会話の Fact と同じ `FOLLOWERS` を使う）。
    """
    if not talk:
        return False
    from .concepts import FOLLOWERS, fold

    body = fold(talk)
    # ★★ 読み（かな）でも探す（RX3-0292 / 2026-09-18）。
    #   ⚠⚠ 名簿は漢字まじり（岬の洞窟）、会話は全部かな（みさきのどうくつ）。
    #   ★`fold` はカタカナ → ひらがなだけなので、⚠ 漢字は**永久に当たりません**。
    for key in [k for k in (name, reading) if k and len(k) >= MIN_NAME]:
        key = fold(key)
        at = body.find(key)
        while at >= 0:
            rest = body[at + len(key):]
            if not rest or not _is_hiragana(rest[0]) or rest[0] in FOLLOWERS:
                return True
            at = body.find(key, at + 1)
    return False


def all_place_names(master) -> set:
    """★名簿にある**すべて**の地名（⚠ 知らない話の場所も含む / RX3-0292）。

    ⚠ これ自体は画面に出しません。★「会話で名前を聞いたか」を調べる**相手**として使うだけです
      （⚠ 聞いていない名前は出ない = ネタバレにならない）。
    """
    topics = master.topics.values() if isinstance(master.topics, dict) else master.topics
    got: set = set()
    for topic in topics:
        got |= {str(n) for n in (topic.related_location_names or ()) if n}
    return got


def topic_places(book, master) -> set:
    """★勇者が知っている Topic が指している地名（⚠ `unknown` の話は入れない）。"""
    from . import council as C

    known = C.known_topic(book)
    topics = master.topics.values() if isinstance(master.topics, dict) else master.topics
    got: set = set()
    for topic in topics:
        if not known(topic.topic_id):
            continue
        # ⚠⚠ RX3-0186（2026-09-12 依頼者「ゆうしゃ会議で解決積み（ナジミの塔とか）が残存してしまっている。」）:
        #   ★解決した話の場所は「行ってみる？」に出さない（⚠ 同じ場所が進行中の話にもあれば、そちらから出る）
        if _resolved(book, topic.topic_id):
            continue
        got |= {str(n) for n in topic.related_location_names if n}
    return got


def _resolved(book, topic_id) -> bool:
    """★その話が解決済みか（⚠ 状態が読めなければ「解決していない」= 今までどおり出す）。"""
    try:
        return book.state(topic_id).status == "resolved"
    except Exception:                                      # noqa: BLE001
        return False


def rura_towns(rom_path=None) -> list:
    """★ルーラの 20 件（`(索引, map_id, 名前)`）。⚠ ROM が読めなければ空。"""
    from . import rom_names as RN

    try:
        maps = RN.place_maps(rom_path)
    except Exception:                                      # noqa: BLE001
        return []
    out = []
    for i, map_id in enumerate(maps or []):
        name = RN.place(i, rom_path)
        if name:
            out.append((i, int(map_id), str(name)))
    return out


# ----------------------------------------------------------------------
# ★本体
# ----------------------------------------------------------------------

def _visited_ids(book) -> set:
    """★行った場所の location_id（⚠ `location_book` が正本 / RX3-0080）。"""
    try:
        return {r.location_id for r in book.all_locations() if r.visited}
    except Exception:                                      # noqa: BLE001
        return set()


#: ★Guide Master の地名 → ゲームが自分で言う名前（RX3-0192 / 2026-09-13）
#:
#:   ⚠⚠ Guide Master の地名は**漢字**、場所の記録の名前は**ゲームの文**（かな）から付く（RX3-0188）。
#:     ★同じ場所でも綴りが違い、「行った」と分からず「行ってみる？」に残っていた。
#:   ⚠ 漢字 → かなを推測で変えない。★ゲームの文で確かめた組だけ書く。
#:
#:   エルフの隠れ里  map 132 の挨拶「ここは エルフのかくれむらよ。」（npc-conversations / RX3-0188 の Evidence）
GUIDE_NAME_ALIASES = {
    "エルフの隠れ里": ("エルフのかくれむら",),
}


def _name_to_id(book) -> dict:
    """★fold(名前) → location_id（⚠ 名前が分かっているものだけ）。"""
    from .concepts import fold

    got = {}
    try:
        rows = book.all_locations()
    except Exception:                                      # noqa: BLE001
        return got
    for row in rows:
        for name in (row.display_name, getattr(row, "name", None)):
            if name:
                got.setdefault(fold(str(name)), row.location_id)
    return got


def _lookup(by_name: dict, name: str):
    """★名前（と、ゲームが言う別の名前）から location_id。⚠ カタカナ / ひらがなの違いは畳む。"""
    from .concepts import fold

    for got in (name,) + GUIDE_NAME_ALIASES.get(name, ()):
        loc = by_name.get(fold(got))
        if loc is not None:
            return loc
    return None


def collect(location_book, guide_book=None, guide_master=None, *,
            conversations=None, rom_path=None) -> list:
    """★勇者が知っていて、まだ行っていない場所。

    ⚠⚠ **ROM の 20 件を素で返しません。** ★条件を満たしたものだけです。
    ⚠ 材料が無い所は**黙って飛ばします**（★落とさない / 画面は続く）。
    """
    visited = _visited_ids(location_book)
    by_name = _name_to_id(location_book)
    talk = spoken_names(conversations)
    from_topic: set = set()
    if guide_book is not None and guide_master is not None:
        try:
            from_topic = topic_places(guide_book, guide_master)
        except Exception:                                  # noqa: BLE001
            from_topic = set()

    #: ★名前 → 候補（⚠ 町とその他をここで 1 本にする）
    seen: dict = {}

    def add(name: str, why: str, rura_index=None) -> None:
        loc = _lookup(by_name, name)
        if loc is not None and loc in visited:
            return                          # ★もう行った（⚠ 出さない）
        got = seen.get(name)
        whys = tuple(got.why) if got is not None else ()
        if why not in whys:
            whys = whys + (why,)
        seen[name] = Reachable(name=name, location_id=loc, why=whys,
                               rura_index=rura_index if rura_index is not None
                               else (got.rura_index if got else None))

    # --- ★町（ルーラの 20 件）------------------------------------------
    for index, map_id, name in rura_towns(rom_path):
        loc = "L%d" % map_id
        if loc in visited:
            continue                        # ★もう行った
        if spoken(name, talk):
            add(name, BY_TALK, index)
        if name in from_topic:
            add(name, BY_TOPIC, index)

    # --- ★その他（塔・洞窟。⚠ Guide Master が知っている名前だけ）---------
    #   ★★ 会話で名前を聞いた所も出す（RX3-0292 / 2026-09-18）。
    #     ⚠⚠ ここは長らく `BY_TOPIC` だけでした。★決まり ①（会話に名前が出た）は
    #       20 件の町にしか効いておらず、⚠ 塔・洞窟は「聞いても出ない」ままでした。
    #     ★読み（かな）の表を使って、かな同士で照合します（`place_readings`）。
    from .place_readings import load as _readings

    readings = _readings()
    # ⚠ 名簿が読めなければ、今までどおり `from_topic` だけ（★落とさない）
    every = all_place_names(guide_master) if guide_master is not None else set()
    heard = {n for n in every if spoken(n, talk, readings.get(n))}
    for name in sorted(set(from_topic) | heard):
        loc = _lookup(by_name, name)
        if loc is not None and loc in visited:
            continue
        # ⚠⚠ 名前が解けない所は「行ったか分からない」。
        #   ★それでも出します（⚠ 勇者は名前を知っているので、隠す理由が無い）。
        if name in from_topic:
            add(name, BY_TOPIC)
        if name in heard:
            add(name, BY_TALK)

    return sorted(seen.values(), key=lambda r: (r.rura_index is None, r.rura_index or 0, r.name))


# ----------------------------------------------------------------------
# ★ゲームの記録との突き合わせ（RX3-0113 / Acceptance ③）
# ----------------------------------------------------------------------

def compare_visited(rura_hex: str | None, location_book, *, rom_path=None,
                    stride: int = 3, players: int = 4, bits: int = 20) -> dict:
    """★ゲームの `$0750` と、こちらの記録を突き合わせる。

    ```text
    ゲームにあって、こちらに無い  ⚠⚠ **訪問を取りこぼした**（★気づきたいのはここ）
    こちらにあって、ゲームに無い  ★正常（⚠ 洞窟や塔は 20 件の外。bit が立たない）
    ```

    ⚠ 直しません。★食い違いを返すだけです（黙って書き換えない）。
    """
    out = {"game_only": [], "ours_only": [], "both": [], "ok": False}
    if not rura_hex:
        return out                          # ⚠ 材料が届いていない（★異常ではない）
    try:
        raw = bytes.fromhex(str(rura_hex))
    except ValueError:
        return out
    if len(raw) < players * stride:
        return out

    #: ★誰か 1 人でも飛べれば「行った」（⚠ 死んでいた人は落ちる）
    known: set = set()
    for p in range(players):
        word = int.from_bytes(raw[p * stride:(p + 1) * stride], "little")
        known |= {i for i in range(bits) if word >> i & 1}

    towns = rura_towns(rom_path)
    if not towns:
        return out
    visited = _visited_ids(location_book)
    for index, map_id, _name in towns:
        loc = "L%d" % map_id
        in_game, in_ours = index in known, loc in visited
        if in_game and in_ours:
            out["both"].append(loc)
        elif in_game:
            out["game_only"].append(loc)    # ⚠⚠ こちらが取りこぼした
        elif in_ours:
            out["ours_only"].append(loc)    # ★ありうる（洞窟から入った等）
    out["ok"] = True
    return out


__all__ = ["Reachable", "collect", "compare_visited", "rura_towns",
           "spoken_names", "topic_places", "BY_TALK", "BY_TOPIC", "WHY_TEXT"]
