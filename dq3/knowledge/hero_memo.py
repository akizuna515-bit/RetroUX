"""人が書いた「気になること」を勇者会議の材料に組み立てる（RX3-0432 / 2026-09-27）。

## ★立ち位置

```text
data/dq3/hero-memo.yaml        ★Layer 1 人が書く正本（⚠ これだけが手書き）
        +
ROM の名前辞書 / story-flags.csv / location-names.csv   ★Layer 2 解析データ
        ↓
   ここ（compile）              ⚠⚠ **ファイルを作りません**（★メモリの中だけ）
        ↓
   {topic_id: Topic} ＋ [Rule]  ★既存の TopicBook がそのまま食べる形
        ↓
   Council.evaluate()           ⚠ 判定の仕組みは**変えません**
```

⚠⚠ **なぜ中間ファイルを作らないか**: ★正本が 2 つになると、⚠ どちらが新しいか
分からなくなります（★旧 `topic-rules.csv` がまさにその形でした / RX3-0432）。
⚠ 名前の解決には**利用者の ROM が要る**ので、どうせ実行時にしかできません。

## ★人が書くのは 4 つだけ

```text
memo           ★覚えておきたいこと（⚠ 画面にこのまま出る）
appears_when   ★気になり始める観測   → weight 50 の Rule（★出るだけ）
retires_when   ★気にならなくなる観測 → weight 100 の Rule（★片づく）
about          ★どこの話か（⚠ 名前で書く）
```

★任意で `scenario:`（何の話として気にしているか）。⚠ 定義はいちばん外の
`scenarios: {id: {title: …}}` で、★**title だけ**。scenario の状態は持たず、
カードの状態から毎回導きます（`scenario_view.py`）。

## ⚠ 条件に書ける言い方は 5 つだけ

★実在する Fact の predicate に 1:1 で対応します（⚠ それ以外は書けません）。

```text
聞いた: <道具・呪文・敵・場所>  → heard    ★会話にその名前が出た
持った: <道具>                → obtain    ⚠ いま持っているか
入手した: <道具>              → acquired  ★一度でも手に入れたか（⚠ 戻らない）
倒した: <敵>                  → defeat
行った: <場所>                → visit
フラグ: <flag_id>             → set
```
"""
from __future__ import annotations

import dataclasses
import pathlib
import re

from dq3 import ownership as _own
from dq3.knowledge import guide
from dq3.knowledge import guide_master

#: ★★ 正本（⚠ 人が書く唯一のファイル）★★
#
#   ★**user 側にあればそれを読みます**（案 A / `RX3-0472` / 2026-10-01）:
#
#     <write_root>/work/user-data/data/dq3/hero-memo.yaml   ★在ればこちら
#     <program_root>/data/dq3/hero-memo.yaml                ★無ければ見本
#
#   ⚠⚠ 配布 ZIP はこの見本を**毎回入れ替えます**。★書き足したものを残したい人は
#     user 側へ置いてください（⚠ 初回に自動で写しません / 依頼者 2026-09-30）。
#   ⚠ `lazy_resolve` なので、★使う瞬間に引き直します（既定引数に固めない / RX3-0215）。
DEFAULT_PATH = _own.lazy_resolve("data/dq3/hero-memo.yaml")

#: ★言い方 → (predicate, 引ける名前の種類)
VOCABULARY: dict[str, tuple[str, tuple[str, ...]]] = {
    "聞いた": ("heard", ("item", "monster", "spell", "place", "word")),
    "持った": ("obtain", ("item",)),
    # ★一度でも手に入れたら成立し、⚠ **戻りません**（RX3-0443）。
    #   ★使った・渡した・イベントで消えた品でも「分かったこと」を巻き戻さない。
    "入手した": ("acquired", ("item",)),
    "倒した": ("defeat", ("monster",)),
    "行った": ("visit", ("place",)),
    "フラグ": ("set", ("flag",)),
}

REQUIRED = ("id", "memo", "appears_when", "retires_when")
OPTIONAL = ("all_of", "retires_all", "about", "why", "map_id", "scenario", "done")
#: ★いちばん外に書ける項目（⚠ 知らない項目は ERROR / 綴り違いの `scenarioes:` を黙って捨てない）
TOP_LEVEL = ("schema_version", "scenarios", "leads")
#: ★scenario の定義に書ける項目（⚠⚠ **title だけ** / 2026-09-27 依頼者の確定）
#:   ⚠ order / sequence / priority / parent / prerequisite / next / appears_when は**持たせない**
#:   （★scenario は束ねる文脈で、進行を制御しない）
SCENARIO_KEYS = ("title",)
ID_RE = re.compile(r"^[a-z0-9_]+$")

#: ★出るだけの重み / ⚠ 片づく重み（`guide.RESOLVE_WEIGHT` が 100）
APPEAR_WEIGHT = 50


class HeroMemoError(Exception):
    """⚠ 原本が読めない・形が違う。"""


@dataclasses.dataclass(frozen=True)
class Lead:
    """★人が書いた「気になること」1 件。"""

    lead_id: str
    memo: str
    #: ★出る条件を平らにしたもの（(言い方, 書かれた名前) / ⚠ 検査・書き出し用）
    appears_when: tuple[tuple[str, str], ...] = ()
    retires_when: tuple[tuple[str, str], ...] = ()
    #: ★`retires_when` を**全部**満たして初めて片づく（⚠ 既定はどれか 1 つ）
    retires_all: bool = False
    #: ★どこの話か（⚠ 複数書ける / `、` `・` `,` で区切る）
    about: tuple[str, ...] = ()
    why_kind: str = ""
    why_note: str = ""
    map_id: int | None = None
    #: ★何の話として気にしているか（`scenarios:` の id / ⚠ 無ければ単独のカード）
    scenario: str = ""
    #: ★片づいたときに出す文（RX3-0437 / ⚠ 任意。無ければ memo を出す）
    #:   ★「そのとき勇者が知ったこと」だけを書く（⚠ まだ出ていないカードの話は書かない）
    done: str = ""
    #: ★出る条件の組（RX3-0436）。**組のどれか 1 つ**が全部そろえば出る
    #:   `- 聞いた: X` は 1 本だけの組 / `- all_of: [...]` は n 本の組 / `- any_of: [...]` は 1 本の組を n 個
    #:   ⚠ 空なら `appears_when` を 1 本ずつの組とみなす（★手で作った Lead のため）
    appear_groups: tuple[tuple[tuple[str, str], ...], ...] = ()

    def groups(self) -> tuple[tuple[tuple[str, str], ...], ...]:
        return self.appear_groups or tuple((cond,) for cond in self.appears_when)


@dataclasses.dataclass
class Compiled:
    """★組み立てた結果（⚠ 解けなかったものも捨てずに残す）。"""

    topics: dict[str, guide_master.Topic] = dataclasses.field(default_factory=dict)
    rules: list[guide.Rule] = dataclasses.field(default_factory=list)
    #: ⚠ 解けなかった条件（★(lead_id, 言い方, 書かれた名前, 理由)）
    unresolved: list[tuple[str, str, str, str]] = dataclasses.field(default_factory=list)
    #: ⚠ 読むときに飛ばした件（★`strict=False` のとき / 黙って捨てない）
    problems: list[str] = dataclasses.field(default_factory=list)
    #: ★画面の下流（`card_of` / `reachable`）が `GuideMaster` を要るので、同じ形で渡す
    #:  ⚠ こうしておけば**窓を 1 行も変えずに**動きます。
    path: pathlib.Path | None = None
    #: ★scenario id → title（⚠ `Topic` は旧 Guide Master と共用なので、対応は**ここで**持つ）
    scenarios: dict[str, str] = dataclasses.field(default_factory=dict)
    #: ★lead_id → scenario id（⚠ 単独のカードは入らない）
    scenario_of: dict[str, str] = dataclasses.field(default_factory=dict)
    #: ★lead_id → 片づいたときの文（`done:` / ⚠ 書いたカードだけ）
    done_of: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.unresolved

    def as_master(self) -> guide_master.GuideMaster:
        """★`GuideMaster` と同じ入れ物にする（⚠ 下流を変えないため）。"""
        return guide_master.GuideMaster(topics=self.topics, path=self.path,
                                       columns=(), problems=[])


# --- ★読む -------------------------------------------------------------------

def _conditions(raw, where: str) -> tuple[tuple[str, str], ...]:
    got = []
    for cond in raw or []:
        if not isinstance(cond, dict) or len(cond) != 1:
            text = cond if isinstance(cond, str) else ""
            # ⚠⚠ いちばん多い書き間違い（2026-09-27 に 6 件）: **全角コロン**
            if "：" in text:
                raise HeroMemoError(
                    "⚠⚠ %s が**全角コロン `：`** になっています"
                    "（★半角の `: ` に直してください）: %r" % (where, text))
            raise HeroMemoError("⚠ %s の条件の形が違います: %r" % (where, cond))
        verb, written = next(iter(cond.items()))
        if verb not in VOCABULARY:
            raise HeroMemoError(
                "⚠⚠ %s に知らない言い方 `%s`（★使えるのは %s）"
                % (where, verb, " / ".join(VOCABULARY)))
        got.append((verb, str(written or "").strip()))
    return tuple(got)


#: ★条件の組の書き方（RX3-0436）。⚠ 入れ子・NOT・個数・式は**作らない**
GROUP_KEYS = ("all_of", "any_of")


def _group_key(entry) -> str | None:
    if isinstance(entry, dict) and len(entry) == 1:
        key = next(iter(entry))
        return key if key in GROUP_KEYS else None
    return None


def _appear_groups(raw, where: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    """★`appears_when` → 条件の組の並び（⚠ 組どうしは OR / 組の中は AND）。

    ```yaml
    appears_when:
      - 聞いた: A            # ★1 本の組
      - all_of:              # ★B と C が**両方**そろったら
          - 聞いた: B
          - 行った: C
      - any_of:              # ★D か E（⚠ 並べて書くのと同じ）
          - 聞いた: D
          - 聞いた: E
    ```
    """
    groups = []
    for i, entry in enumerate(raw or []):
        key = _group_key(entry)
        if key is None:
            groups.extend((cond,) for cond in _conditions([entry], "%s[%d]" % (where, i)))
            continue
        inner = entry[key]
        here = "%s[%d].%s" % (where, i, key)
        if not isinstance(inner, list) or not inner:
            raise HeroMemoError("⚠ %s は条件の並びで書いてください" % here)
        if any(_group_key(c) for c in inner):
            raise HeroMemoError("⚠⚠ %s の中に all_of / any_of は書けません（★入れ子は作らない）" % here)
        conds = _conditions(inner, here)
        if key == "all_of":
            if len(conds) < 2:
                raise HeroMemoError("⚠ %s は条件を 2 つ以上書いてください（★1 つなら all_of は要らない）" % here)
            groups.append(conds)
        else:
            groups.extend((cond,) for cond in conds)
    return tuple(groups)


#: ★`about` の区切り（⚠ 人は「アリアハン、レーベ」と書く / 2026-09-27 実測）
ABOUT_SEPARATORS = "、・,／/　 "


def _places_written(raw) -> tuple[str, ...]:
    """★`about` を場所の並びにする。

    ⚠⚠ 人は「アリアハン、レーベ」と**1 つの文字列**で書きます（★実測）。
      → ★区切って複数として扱います（⚠ 並びで書いてもよい）。
    """
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw]
    else:
        text = str(raw)
        for sep in ABOUT_SEPARATORS:
            text = text.replace(sep, "\n")
        items = [part.strip() for part in text.split("\n")]
    return tuple(x for x in items if x)


def scenario_titles(doc: dict) -> dict[str, str]:
    """★`scenarios:` のうち、形の合っているもの（id → title）。⚠ 壊れた定義は入れない。"""
    raw = doc.get("scenarios")
    if not isinstance(raw, dict):
        return {}
    got = {}
    for sid, body in raw.items():
        title = str(body.get("title") or "").strip() if isinstance(body, dict) else ""
        if title and ID_RE.match(str(sid)):
            got[str(sid)] = title
    return got


def scenario_problems(doc: dict) -> list[tuple[str, str, str]]:
    """★いちばん外と `scenarios:` の検査（⚠ 読み込みと門番の**両方がここを使う** / 判定は 1 か所）。

    返すのは (level, where, text)。level は ERROR / WARNING / INFO。

    ```text
    ERROR    知らない項目がいちばん外にある / scenario の形が違う / 未定義の scenario を参照
    WARNING  所属が 0 件の scenario（★書き忘れか、使わなくなった定義）
    INFO     所属が 1 件の scenario（★束ねる意味が薄いかもしれない）
    ```
    """
    got: list[tuple[str, str, str]] = []
    for key in doc:
        if key not in TOP_LEVEL:
            got.append(("ERROR", str(key),
                        "いちばん外に知らない項目（★書けるのは %s）" % " / ".join(TOP_LEVEL)))
    raw = doc.get("scenarios")
    names: set[str] = set()
    if raw is not None and not isinstance(raw, dict):
        got.append(("ERROR", "scenarios", "`scenarios` は `id: {title: …}` の形で書いてください"))
    elif isinstance(raw, dict):
        for sid, body in raw.items():
            where = "scenarios.%s" % sid
            names.add(str(sid))
            if not ID_RE.match(str(sid)):
                got.append(("ERROR", where, "scenario の id は英小文字・数字・`_` だけ"))
            if not isinstance(body, dict):
                got.append(("ERROR", where, "`title:` を持つ辞書で書いてください"))
                continue
            extra = sorted(set(body) - set(SCENARIO_KEYS))
            if extra:
                got.append(("ERROR", where,
                            "scenario に書けるのは title だけです: %s"
                            "（⚠ 順番・前提・出る条件は持たせません。★出る・片づくはカードで決まる）"
                            % extra))
            if not str(body.get("title") or "").strip():
                got.append(("ERROR", where, "`title` がありません（★必須）"))

    members = {name: 0 for name in names}
    leads = doc.get("leads") if isinstance(doc.get("leads"), list) else []
    for n, lead in enumerate(leads):
        if not isinstance(lead, dict) or lead.get("scenario") is None:
            continue
        sid = lead.get("scenario")
        where = "leads[%d] %s" % (n, lead.get("id") or "")
        if not isinstance(sid, str) or not sid.strip():
            got.append(("ERROR", where, "`scenario` は scenario の id を 1 つ書いてください"))
        elif sid.strip() not in names:
            got.append(("ERROR", where,
                        "scenario `%s` が `scenarios:` に定義されていません" % sid.strip()))
        else:
            members[sid.strip()] += 1
    for name, count in sorted(members.items()):
        if count == 0:
            got.append(("WARNING", "scenarios.%s" % name,
                        "所属するカードが 0 件です（★書き忘れか、使っていない定義）"))
        elif count == 1:
            got.append(("INFO", "scenarios.%s" % name, "所属するカードが 1 件だけです"))
    return got


def load(path=None, strict: bool = True, problems: list | None = None) -> list[Lead]:
    """★原本のカードだけを読む（⚠ scenario の定義も要るなら `load_document`）。"""
    return load_document(path, strict=strict, problems=problems)[1]


def load_document(path=None, strict: bool = True,
                  problems: list | None = None) -> tuple[dict[str, str], list[Lead]]:
    """★原本を読む。⚠ 無ければ**空**（★落ちない / 公開版に無い場合がある）。

    ## ⚠⚠ `strict=False` は「壊れた 1 件を飛ばして残りを出す」

    ★2026-09-27: 依頼者が 27 件書いたうち **1 件の `memo` が空**でした。
    ⚠ 素の `strict=True` だと**勇者会議が丸ごと暗くなります**（★27 件全部が消える）。
    → ★画面は残りを出し、⚠ 飛ばした理由は `problems` に**必ず残します**
      （★黙って捨てない / `guide_master.load(strict=False)` と同じ考え）。

    ⚠ 門番は `scripts/dq3_hero_memo_check.py`（★そちらは ERROR で止めます）。
    """
    import yaml

    from dq3.yaml_strict import DuplicateKey, load_strict

    target = pathlib.Path(path) if path else DEFAULT_PATH
    try:
        raw = target.read_bytes()
    except OSError:
        return {}, []
    try:
        # ⚠⚠ 素の `safe_load` は同じキーの 2 度目を黙って上書きする（RX3-0441）
        doc = load_strict(raw) or {}
    except DuplicateKey as exc:
        raise HeroMemoError(str(exc)) from exc
    except yaml.YAMLError as exc:
        raise HeroMemoError("⚠⚠ YAML として読めません: %s" % exc) from exc
    if not isinstance(doc, dict):
        raise HeroMemoError("⚠ いちばん外が辞書ではありません: %r" % type(doc).__name__)

    got = []
    problems = problems if problems is not None else []

    def bad(message: str) -> bool:
        """⚠ 問題を報せる。★`strict` なら止め、⚠ そうでなければ**飛ばして残す**。"""
        if strict:
            raise HeroMemoError(message)
        problems.append(message)
        return True

    # ★いちばん外と scenario の定義（⚠ 門番と同じ判定 / `scenario_problems`）
    #   ⚠ `strict=False` でも**カードは落としません**。未定義の scenario を指すカードは
    #     単独のカードとして出します（★1 か所の書き間違いで話を消さない）。
    for level, where, text in scenario_problems(doc):
        if level == "ERROR":
            bad("⚠⚠ %s %s" % (where, text))
    titles = scenario_titles(doc)

    for n, lead in enumerate(doc.get("leads") or []):
        where = "leads[%d]" % n
        if not isinstance(lead, dict):
            if bad("⚠ %s が辞書ではありません" % where):
                continue
        skip = False
        for key in REQUIRED:
            if not lead.get(key):
                skip = bad("⚠⚠ %s に `%s` がありません（★必須）" % (where, key)) or True
        unknown = set(lead) - set(REQUIRED) - set(OPTIONAL)
        if unknown:
            skip = bad("⚠ %s に知らない項目: %s" % (where, sorted(unknown))) or True
        if skip:
            continue
        if lead.get("all_of"):
            # ⚠⚠ **出る側には効きません**（2026-09-27 に実測 / RX3-0432）。
            #   ★出るかどうかは「どれか 1 本当たったか」で決まります。
            #   ⚠ 黙って無視すると「書いたのに効かない値」になるので、★ここで止めます。
            #   ★片づく側なら `retires_all: true` が**効きます**（実測済み）。
            if bad("⚠⚠ %s の `all_of: true` は**出る側には効きません**（RX3-0432）。"
                   "★消すか `false` にしてください。"
                   "⚠ 「全部そろって初めて**片づく**」なら `retires_all: true` が使えます"
                   % where):
                continue
        why = lead.get("why") if isinstance(lead.get("why"), dict) else {}
        try:
            groups = _appear_groups(lead.get("appears_when"), "%s appears_when" % where)
            appears = tuple(cond for group in groups for cond in group)
            if any(_group_key(c) for c in lead.get("retires_when") or []):
                raise HeroMemoError(
                    "⚠ %s retires_when に all_of / any_of は書けません"
                    "（★全部そろって片づくなら `retires_all: true`）" % where)
            retires = _conditions(lead.get("retires_when"), "%s retires_when" % where)
        except HeroMemoError as exc:
            if bad(str(exc)):
                continue
            raise
        got.append(Lead(
            lead_id=str(lead["id"]).strip(),
            memo=str(lead["memo"]).strip(),
            appears_when=appears,
            appear_groups=groups,
            retires_when=retires,
            retires_all=bool(lead.get("retires_all")),
            about=_places_written(lead.get("about")),
            why_kind=str(why.get("kind") or "").strip(),
            why_note=str(why.get("note") or "").strip(),
            map_id=lead.get("map_id"),
            done=str(lead.get("done") or "").strip(),
            scenario=(str(lead.get("scenario")).strip()
                      if str(lead.get("scenario") or "").strip() in titles else ""),
        ))
    ids = [l.lead_id for l in got]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        # ⚠⚠ 重複は**飛ばせません**（★どちらを残すか機械には決められない）。
        #   ★`strict=False` でも、⚠ ここは問題として残したうえで
        #     **後のほうを落として**画面は出します（★2 つ同じ話が並ぶのを避ける）。
        if strict:
            raise HeroMemoError("⚠⚠ `id` が重複しています: %s" % dup)
        problems.append("⚠⚠ `id` が重複しています: %s（★後のほうを使いません）" % dup)
        seen: set = set()
        kept = []
        for lead in got:
            if lead.lead_id in seen:
                continue
            seen.add(lead.lead_id)
            kept.append(lead)
        got = kept
    return titles, got


# --- ★名前を引く -------------------------------------------------------------

def _index(rom_path=None):
    from dq3.knowledge import guide_mapping

    return guide_mapping.name_index(rom_path)


def _places(rom_path=None) -> dict[str, str]:
    """★畳んだ地名 → `L<map 番号>`。"""
    from dq3.knowledge import concepts

    return {folded: location_id
            # ★ここは「名前で書けるか」を引くだけ（⚠ 会話の照合ではないので短い地名も採る / RX3-0442）
            for folded, location_id, _name in concepts.place_aliases(rom_path, min_len=1)}


def _flags() -> set[str]:
    from dq3.knowledge import story

    try:
        return {getattr(f, "flag_id", f) for f in story.load_flags()}
    except Exception:                                      # noqa: BLE001
        return set()


def _rule(lead: Lead, verb: str, written: str, *, weight: int, group: str,
          n: int, index, places, flags) -> list | str:
    """★1 条件 → Rule の並び。⚠ 解けなければ**理由の文字列**を返す。

    ⚠⚠ 2026-09-28（RX3-0444）: **同じ名前が 2 つの id に当たるときは 2 本返します**。
      ★門番は前から「全部に解きます」と言っていましたが、⚠ 実際は 1 つめだけでした
      （実測: `ゾーマ` = 133 / 134、`カンダタ` = 136 / 137 → ★片方を倒しても成立しない）。
      → ★`rule_id` の `#` の後ろを変えて返します（`completed()` / `appeared()` が OR に畳む）。
    """
    from dq3.knowledge.concepts import fold

    predicate, kinds = VOCABULARY[verb]
    # ⚠⚠ `TopicBook.completed()` は `rule_id` の **`#` の前**を「1 つの条件」と見ます。
    #   ★同じ名前が 2 つの id に当たるとき（`#0` `#1`）は OR にするための作りです。
    #   ⚠ ここを `<lead_id>#r0` にすると、★6 本が**同じ条件に畳まれて**
    #     「どれか 1 本で片づく」になります（2026-09-27 に実際にそうなった）。
    #   → ★条件ごとに前を変える（`<lead_id>-r0#0`）。
    kind_mark = "r" if weight >= guide.RESOLVE_WEIGHT else "a"
    condition = "%s-%s%d" % (lead.lead_id, kind_mark, n)

    def base(k: int = 0) -> dict:
        return dict(rule_id="%s#%d" % (condition, k), topic_id=lead.lead_id,
                    predicate=predicate, weight=weight, source="explicit",
                    match_mode="ALL" if group else "ANY", group=group,
                    notes="hero-memo: %s" % verb)

    if "flag" in kinds:
        if written not in flags:
            return "知らない flag_id（★story-flags.csv にあるのは %d 件）" % len(flags)
        return [guide.Rule(entity_kind="event", entity_name=written, **base())]

    if "place" in kinds:
        # ★逃げ道: 名前が無い場所は `L<map 番号>` と書ける（2026-09-27 / RX3-0432）
        #   ⚠ 依頼者が実際に `着いた: L41` と書いていた（★名前を付けていない場所）。
        #   ★内部 ID を書かせないのが方針だが、⚠ **書けないより書けるほうがよい**。
        location_id = (written if re.fullmatch(r"L\d+", written)
                       else places.get(fold(written)))
        if location_id:
            return [guide.Rule(entity_kind="location", location_id=location_id,
                               entity_name=written, **base())]
        if kinds == ("place",):
            return ("地名を引けません"
                    "（★ROM のルーラ表か location-names.csv の name に要る）")

    for kind in kinds:
        if kind in ("place", "word"):
            continue
        hits = index.get((kind, fold(written))) or []
        if hits:
            # ★同じ名前の id が複数あれば全部（⚠ `#0` `#1` … で OR になる / RX3-0444）
            got = [guide.Rule(entity_kind=kind, entity_id=int(entity_id),
                              entity_name=written, **base(k))
                   for k, (entity_id, _name) in enumerate(hits)]
            if predicate == "defeat":
                # ★ゲーム自身に「倒した」の旗があるなら、それも証拠にする（RX3-0451）。
                #   ⚠ ボスは戦闘の記録を取りこぼすことがある（★経験値 0 / 姿が変わる / RX3-0450）。
                #   ★同じ条件の別の当たり方（`#k`）なので、⚠ **どちらかで成立**します。
                from dq3.knowledge import story
                from dq3.knowledge.guide import Rule

                flag = story.defeat_flag_of(written)
                if flag:
                    got.append(Rule(entity_kind="event", entity_name=flag,
                                    **dict(base(len(got)), predicate="set")))
            return got
    if "word" in kinds:
        # ★一般の語（`concept-words.csv` / RX3-0436）。⚠ 名前で引けなかったときだけ
        word = _words().get(fold(written))
        if word:
            return [guide.Rule(entity_kind="word", entity_name=word, **base())]
    return "ROM の名前辞書で引けません（★綴りを確かめてください）" + alias_hint(written)


def alias_hint(written: str) -> str:
    """★会話の表現を書いていたら、正規の名前を教える（RX3-0440 / ⚠ 自動では置き換えない）。"""
    from dq3.knowledge import concept_aliases as CA
    from dq3.knowledge.concepts import fold

    hit = CA.heard_alias_index().get(fold(written))
    if hit and hit[1] != written:
        return ("。⚠ `%s` は Concept Alias の表現です → ★正規の名前 `%s` を書いてください"
                % (written, hit[1]))
    return ""


def _words() -> dict[str, str]:
    """★畳んだ語 → 書いた語（`concepts.word_aliases`）。"""
    from dq3.knowledge import concepts

    return dict(concepts.word_aliases())


def compile_leads(leads, rom_path=None) -> Compiled:
    """★Lead の並び → `{topic_id: Topic}` ＋ `[Rule]`。

    ⚠ 解けなかった条件は `unresolved` に残します（★黙って捨てない）。
    """
    got = Compiled()
    index, places, flags = _index(rom_path), _places(rom_path), _flags()

    for lead in leads:
        first = lead.memo.splitlines()[0].strip() if lead.memo else lead.lead_id
        got.topics[lead.lead_id] = guide_master.Topic(
            topic_id=lead.lead_id,
            title=first,
            # ★画面のいちばん上に出る文（⚠ `head_message` が最優先で使う）
            ui_head_hint=lead.memo,
            objective=lead.memo,
            # ⚠ 旧 schema の「攻略チャート」の列は**使いません**
            category="exploration",
            priority=50,
            related_location_names=lead.about,
            location_id=("L%d" % int(lead.map_id)) if lead.map_id else "",
            notes=lead.why_note,
            review_status=lead.why_kind,
        )
        n = 0
        for k, group in enumerate(lead.groups()):
            # ★1 本の組は ANY（⚠ どれか 1 本で出る）。★2 本以上の組は ALL（RX3-0436）:
            #   `TopicBook` が「組の条件が**全部**当たったか」で見える / 見えないを決める。
            appear_group = ("%s-appear%d" % (lead.lead_id, k)) if len(group) > 1 else ""
            made_rules, failed = [], []
            for verb, written in group:
                made = _rule(lead, verb, written, weight=APPEAR_WEIGHT, group=appear_group,
                             n=n, index=index, places=places, flags=flags)
                n += 1
                if isinstance(made, list):
                    made_rules.extend(made)
                else:
                    failed.append((lead.lead_id, verb, written, made))
            got.unresolved.extend(failed)
            if appear_group and failed:
                # ⚠⚠ 組の 1 本でも解けなければ、**組ごと**使いません。
                #   ★残りだけで組を作ると、AND が黙って短くなり「早すぎる」カードになる。
                continue
            got.rules.extend(made_rules)
        # ★`retires_all: true` なら「全部そろって初めて片づく」（⚠ 既定はどれか 1 つ）
        retire_group = ("%s-retire" % lead.lead_id) if lead.retires_all else ""
        for n, (verb, written) in enumerate(lead.retires_when):
            made = _rule(lead, verb, written, weight=guide.RESOLVE_WEIGHT,
                         group=retire_group,
                         n=n, index=index, places=places, flags=flags)
            if isinstance(made, list):
                got.rules.extend(made)
            else:
                got.unresolved.append((lead.lead_id, verb, written, made))
    return got


def build(path=None, rom_path=None, strict: bool = False) -> Compiled:
    """★読んで組み立てるまで（⚠ 原本が無ければ空の `Compiled`）。

    ⚠⚠ 既定は `strict=False`（★壊れた 1 件を飛ばして残りを出す）。
      ★人が書くファイルなので、⚠ 1 件の書き間違いで**画面を丸ごと暗くしません**。
      ⚠ 飛ばした理由は `Compiled.problems` に入ります（★黙って捨てない）。
    """
    problems: list = []
    titles, leads = load_document(path, strict=strict, problems=problems)
    got = compile_leads(leads, rom_path)
    got.problems = problems
    got.scenarios = titles
    got.scenario_of = {lead.lead_id: lead.scenario for lead in leads if lead.scenario}
    got.done_of = {lead.lead_id: lead.done for lead in leads if lead.done}
    got.path = pathlib.Path(path) if path else DEFAULT_PATH
    return got
