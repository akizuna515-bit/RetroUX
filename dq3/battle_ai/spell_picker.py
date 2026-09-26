"""★AI が候補にする呪文の一覧（RX3-0370 / 2026-09-22）。

⚠⚠ 依頼者「勇者がギガデインを使いすぎる。AI 判断は難しいので、
  **使わない呪文をモード毎に設定**するのが良い（★別画面、呪文・消費 MP を表示して
  チェックボックスで選択。★AI が使わない呪文はそもそも表示しない）」。

## ★「AI が使う呪文」の決まりは **1 か所**にしかありません

`dq3/phase0/ai/roles.lua` の `Roles.caps` が、覚えている呪文を箱に分けます。

```text
heal      s.kind == "heal"
revive    s.kind == "revive"
attack    s.kind == "attack"
instant   s.kind == "instant" かつ effect == "beat"        （★ザキ・ザラキ）
drain     s.kind == "instant" かつ effect == "robmagic"     （★マホトラ）
support   SUPPORT_KINDS[s.kind] または SUPPORT_EFFECTS[effect]
```

⚠⚠ **ここに同じ決まりを書き写しません。** ★`roles.lua` から**読み出します**
（⚠ 2 か所に書くと、片方だけ直って画面と AI がずれます / `RX3-0248` の教訓）。
★食い違ったら `tests/test_dq3_spell_picker.py` が赤くなります。

## ⚠ 「覚えている呪文」だけを出します

★全 50 種を並べても選べません。⚠ いまのパーティが覚えているものだけ。
→ ★転職・レベルアップで増えたら、次に窓を開いたときに増えます。
  （⚠ 除外は「使わない呪文の ID」で持つので、★増えた呪文は自動で「使う」側）
"""
from __future__ import annotations

import dataclasses
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROLES_LUA = ROOT / "dq3" / "phase0" / "ai" / "roles.lua"

#: ★箱の名前 → 画面の言葉（⚠ `roles.lua` の箱と同じ順で出す）
BUCKET_LABELS = {
    "attack": "攻撃",
    "instant": "即死",
    "heal": "回復",
    "revive": "蘇生",
    "support": "支援",
    "drain": "MP吸収",
}


@dataclasses.dataclass(frozen=True)
class Rule:
    """★`roles.lua` から読み出した「どの呪文を使うか」。"""

    support_kinds: frozenset
    support_effects: frozenset
    beat_effect: str

    def bucket(self, kind: str, effect) -> str | None:
        """★その呪文が入る箱（⚠ どこにも入らなければ None ＝ AI は使わない）。"""
        effect = effect or ""
        if kind in ("heal", "revive", "attack"):
            return kind
        if kind == "instant":
            if effect == self.beat_effect:
                return "instant"
            if effect == "robmagic":
                return "drain"
        if kind in self.support_kinds:
            return "support"
        if kind == "instant" and effect in self.support_effects:
            return "support"
        return None


def _names(src: str, var: str) -> frozenset:
    """★`local X = {a = true, b = true}` から名前を取る。"""
    hit = re.search(r"local\s+%s\s*=\s*\{([^}]*)\}" % re.escape(var), src)
    if hit is None:
        return frozenset()
    return frozenset(re.findall(r"(\w+)\s*=\s*true", hit.group(1)))


def rule(path=None) -> Rule:
    """★★ `roles.lua` から決まりを読み出す（⚠ 写さない）。

    ⚠ 読めない形になっていたら `ValueError`。★黙って既定値に落ちません
    （★落ちると「画面には出るが AI は使わない」呪文が生まれます）。
    """
    src = pathlib.Path(path or ROLES_LUA).read_text(encoding="utf-8")
    kinds = _names(src, "SUPPORT_KINDS")
    effects = _names(src, "SUPPORT_EFFECTS")
    beat = re.search(r'local\s+BEAT_EFFECT\s*=\s*"(\w+)"', src)
    if not kinds or not effects or beat is None:
        raise ValueError("⚠⚠ roles.lua から呪文の決まりを読めません（★形が変わった？）")
    return Rule(support_kinds=kinds, support_effects=effects, beat_effect=beat.group(1))


@dataclasses.dataclass(frozen=True)
class Row:
    """★画面の 1 行。"""

    spell_id: int
    name: str
    mp: int
    bucket: str
    #: ★覚えている人の枠（`p1` など / ⚠ 並びはパーティ順）
    who: tuple

    @property
    def bucket_label(self) -> str:
        return BUCKET_LABELS.get(self.bucket, self.bucket)


def rows_for(members, rom_path=None, *, rule_path=None) -> list[Row]:
    """★★ いまのパーティが覚えていて、⚠ **AI が候補にする**呪文だけ。

    `members` … `state.json` の party（★`spells` 8 バイトと `class_gender` が要る）
    ⚠ 呪文を読めない環境では**空**（★推測で並べない）。

    ★並びは「箱 → MP の高い順 → ID」。⚠ ギガデインのような重い呪文が上に来ます
      （★依頼者が探しているのはそこ）。
    """
    from ..knowledge import spell_info as SI

    got = rule(rule_path)
    who: dict[int, list] = {}
    for i, m in enumerate(members or ()):
        if not isinstance(m, dict):
            continue
        slot = m.get("slot") or "p%d" % (i + 1)
        for sid in SI.learned_for(m, rom_path):
            who.setdefault(int(sid), []).append(slot)
    out = []
    for sid, slots in who.items():
        info = SI.info(sid, rom_path)
        if info is None:
            continue
        bucket = got.bucket(info.kind, info.effect)
        if bucket is None:
            continue                       # ⚠ AI が使わない呪文は**出さない**（依頼者の指示）
        out.append(Row(spell_id=sid, name=info.label, mp=int(info.mp or 0),
                       bucket=bucket, who=tuple(slots)))
    order = list(BUCKET_LABELS)
    out.sort(key=lambda r: (order.index(r.bucket) if r.bucket in order else 99,
                            -r.mp, r.spell_id))
    return out
