"""ゲーム内の言い回し → 正規の Concept（RX3-0440 / 2026-09-27）。

## ★立ち位置

```text
data/dq3/hero-memo.yaml         勇者が**何を気にするか**（★正規の名前だけを書く）
data/dq3/concept-aliases.yaml   ゲーム内の**表現**をどの Concept として扱うか（★ここ）
```

★例: 会話に「ひあがらせるつぼ」と出たら、★品「かわきのつぼ」を聞いたことにする。

```text
会話の本文 → Matcher（★別名も名前として持つ）→ Concept（正規の id）→ heard Fact
```

⚠⚠ Fact に残るのは**正規の Concept だけ**です（★別名の表現は Fact にならない）。

## ★読み方

```text
読むのは Matcher を作るとき（★勇者会議を開いた / [更新] を押したとき）
⚠ 更新時刻が変わっていなければ**読み直さない**（★会話のたびにファイルを読まない）
```
"""
from __future__ import annotations

import pathlib

from dq3.knowledge.concepts import MIN_ALIAS, fold

#: ★正本（⚠ 人が書く）
DEFAULT_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "dq3" / "concept-aliases.yaml"

#: ★節の名前 → Concept の種類（⚠ 増やすときはここだけ）
SECTIONS = {"items": "item", "places": "place", "monsters": "monster", "spells": "spell"}
TOP_LEVEL = ("schema_version",) + tuple(SECTIONS)
#: ★1 つの正規 Concept に書ける項目
ENTRY_KEYS = ("heard_aliases",)

#: ★読んだ回数（⚠ 検査が「変わっていなければ読み直さない」を確かめるため）
PARSES = 0
_CACHE: dict[str, tuple[int, dict]] = {}


def load(path=None) -> dict:
    """★YAML を読む（⚠ 更新時刻が同じなら前の結果 / 無ければ空）。"""
    global PARSES
    import yaml

    target = pathlib.Path(path) if path else DEFAULT_PATH
    try:
        stamp = target.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _CACHE.get(str(target))
    if cached and cached[0] == stamp:
        return cached[1]
    from dq3.yaml_strict import DuplicateKey, load_strict

    try:
        # ⚠ 重複キーは黙って上書きさせない（RX3-0441 / ★読めない扱いにして門番に出させる）
        doc = load_strict(target.read_bytes()) or {}
    except (yaml.YAMLError, DuplicateKey):
        doc = {}
    PARSES += 1
    doc = doc if isinstance(doc, dict) else {}
    _CACHE[str(target)] = (stamp, doc)
    return doc


def entries(doc: dict) -> list[tuple[str, str, str]]:
    """★(種類, 正規の名前, 別名) の並び（⚠ 形の壊れたものは飛ばす / 検査は `problems`）。"""
    got = []
    for section, kind in SECTIONS.items():
        block = doc.get(section)
        if not isinstance(block, dict):
            continue
        for canonical, body in block.items():
            if not isinstance(canonical, str) or not canonical.strip() or not isinstance(body, dict):
                continue
            for alias in body.get("heard_aliases") or []:
                if isinstance(alias, str) and alias.strip():
                    got.append((kind, canonical.strip(), alias.strip()))
    return got


def heard_alias_index(doc: dict | None = None) -> dict[str, tuple[str, str]]:
    """★畳んだ表現 → (種類, 正規の名前)。⚠ **正規の名前そのもの**も入れる。

    ```text
    {"ひあがらせるつぼ": ("item", "かわきのつぼ"), "かわきのつぼ": ("item", "かわきのつぼ")}
    （★鍵は `fold` 済み。カタカナは ひらがな に畳まれる）
    ```
    ⚠ 2 つの Concept に当たる表現は入れない（★どちらか決められない / `problems` が ERROR）。
    """
    doc = load() if doc is None else doc
    got: dict[str, tuple[str, str]] = {}
    clash: set[str] = set()
    for kind, canonical, alias in entries(doc):
        for text in (canonical, alias):
            key = fold(text)
            if key in got and got[key] != (kind, canonical):
                clash.add(key)
            got.setdefault(key, (kind, canonical))
    return {k: v for k, v in got.items() if k not in clash}


def problems(doc: dict, known=None) -> list[tuple[str, str, str]]:
    """★検査（level, where, text）。

    `known(kind, name) -> bool` … 正規の名前が引けるか（⚠ 渡さなければ見ない）。

    ```text
    ERROR    知らない項目 / 形が違う / 空 / 同じ Concept の中で重複 / 2 つの Concept に同じ表現
             / 正規の名前が引けない / 3 文字未満（⚠ 照合しない）
    INFO     正規の名前と同じ表現を書いている / 表現が 1 つも無い
    ```
    """
    got: list[tuple[str, str, str]] = []
    if not isinstance(doc, dict):
        return [("ERROR", "concept-aliases", "いちばん外が辞書ではありません")]
    for key in doc:
        if key not in TOP_LEVEL:
            got.append(("ERROR", str(key), "知らない項目（★書けるのは %s）" % " / ".join(TOP_LEVEL)))
    if doc.get("schema_version") != 1:
        got.append(("ERROR", "schema_version", "`schema_version: 1` がありません"))
    owner: dict[str, str] = {}
    for section, kind in SECTIONS.items():
        block = doc.get(section)
        if block is None:
            continue
        if not isinstance(block, dict):
            got.append(("ERROR", section, "`正規の名前: {heard_aliases: [...]}` の形で書いてください"))
            continue
        for canonical, body in block.items():
            where = "%s.%s" % (section, canonical)
            if not isinstance(canonical, str) or not canonical.strip():
                got.append(("ERROR", where, "正規の名前が空か文字ではありません"))
                continue
            if not isinstance(body, dict):
                got.append(("ERROR", where, "`heard_aliases:` を持つ辞書で書いてください"))
                continue
            extra = sorted(set(body) - set(ENTRY_KEYS))
            if extra:
                got.append(("ERROR", where, "知らない項目: %s（★書けるのは heard_aliases だけ）" % extra))
            if known is not None and not known(kind, canonical):
                got.append(("ERROR", where, "正規の名前が引けません（★ROM の名前 / location-names.csv の name）"))
            aliases = body.get("heard_aliases")
            if aliases is None:
                aliases = []
            if not isinstance(aliases, list):
                got.append(("ERROR", where, "`heard_aliases` は並びで書いてください"))
                continue
            if not aliases:
                got.append(("INFO", where, "表現が 1 つもありません"))
            seen: set[str] = set()
            for alias in aliases:
                if not isinstance(alias, str) or not alias.strip():
                    got.append(("ERROR", where, "表現が空か文字ではありません: %r" % (alias,)))
                    continue
                key = fold(alias)
                if len(key) < MIN_ALIAS:
                    got.append(("ERROR", where, "`%s` は短すぎて照合しません（★%d 文字以上）"
                                % (alias, MIN_ALIAS)))
                if key in seen:
                    got.append(("ERROR", where, "`%s` が同じ Concept の中で重複しています" % alias))
                seen.add(key)
                if key == fold(canonical):
                    got.append(("INFO", where, "`%s` は正規の名前と同じです（★書かなくても当たります）" % alias))
                other = owner.get(key)
                if other is not None and other != where:
                    got.append(("ERROR", where, "`%s` が %s にも登録されています（⚠ どちらへ解くか決められない）"
                                % (alias, other)))
                owner.setdefault(key, where)
    return got
