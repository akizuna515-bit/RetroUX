"""画面の字の写しが食い違わないこと（RX3-0327 / 2026-09-20）。

依頼者 2026-09-20:

    調査でラベルの写しが複数あることが分かっている。
    少なくとも Python設定画面 / 右画面 / Luaログ / coverage集計 / E2E / docs を同時に修正する。

## ⚠⚠ 同じ名前が 3 系統ある

```text
作戦  Python `dq3/battle_ai/settings.py` … ★正本
      Lua    `dq3/phase0/ai/pipeline.lua` … ⚠ 写し（戦闘ログの 1 行目）
役割  Python `settings.py` / Lua `pipeline.lua` / Lua `auto_v0.lua` / 集計 `coverage.py`
```

★2026-09-20 の調査で、⚠ **MP 制約の `save` が既にずれて**いました
（画面「半分程度残す」／ログ「温存」）。★機械で突き合わせる検査が無かったためです。

⚠ この検査は「同じ字か」だけを見ます（★どんな字にするかは決めません）。
"""
from __future__ import annotations

import pathlib
import re

from dq3.battle_ai import coverage as C
from dq3.battle_ai import settings as S

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "dq3" / "phase0" / "ai" / "pipeline.lua"
AUTO = ROOT / "dq3" / "phase0" / "auto_v0.lua"


def _lua_table(path: pathlib.Path, name: str) -> dict:
    """★Lua の `local NAME = {a = "…", b = "…"}` を読む（⚠ 1 つだけあること）。"""
    src = path.read_text(encoding="utf-8")
    hits = re.findall(r"local\s+%s\s*=\s*\{(.*?)\}" % name, src, re.S)
    assert len(hits) == 1, "⚠ %s の %s が %d 個" % (path.name, name, len(hits))
    return dict(re.findall(r'(\w+)\s*=\s*"([^"]+)"', hits[0]))


def test_作戦の名前はPythonとLuaで同じ():
    """⚠⚠ 片方だけ直すと、★戦闘ログだけ古い名前で出ます。"""
    got = _lua_table(PIPELINE, "STRATEGY_LABEL")
    assert got == S.STRATEGY_LABELS, (
        "⚠⚠ 作戦の名前がずれている\n  Python: %s\n  Lua   : %s" % (S.STRATEGY_LABELS, got))


def test_役割の名前はPythonとLuaで同じ():
    """⚠ 役割は写しが 3 枚あります（`pipeline.lua` / `auto_v0.lua` / `coverage.py`）。"""
    pipeline = _lua_table(PIPELINE, "ROLE_LABEL")
    auto = _lua_table(AUTO, "ROLE_UI")
    assert pipeline == auto, "⚠ Lua の 2 枚がずれている\n  %s\n  %s" % (pipeline, auto)
    # ★集計が数えている語も同じ集合であること
    assert set(C.ROLES) == set(pipeline.values()), (
        "⚠ 集計の語がずれている\n  集計: %s\n  Lua : %s" % (sorted(C.ROLES), sorted(pipeline.values())))


def test_MP制約の名前はPythonとLuaで同じ():
    """⚠⚠ ここが**実際にずれていた**ところです（RX3-0333 / 2026-09-21）。

    ```text
    ★画面        「半分程度残す」   `settings.py` MP_LABELS
    ⚠ 戦闘ログ   「温存」           `pipeline.lua` MP_LABEL
    ```

    ★作戦だけ突き合わせていて、⚠ MP 制約には検査がありませんでした。
    """
    got = _lua_table(PIPELINE, "MP_LABEL")
    assert got == S.MP_LABELS, (
        "⚠⚠ MP 制約の名前がずれている\n  Python: %s\n  Lua   : %s" % (S.MP_LABELS, got))


def test_MP制約の集計はPythonの名前から作る():
    """⚠ `coverage.py` が名前を写していないこと（★写すと改名の漏れ先になる）。"""
    assert set(C.MP_POLICIES) == set(S.MP_LABELS.values())
    assert C.WATCH["MP 制約"] == (S.MP_LABELS[S.MP_SAVE],), (
        "⚠ 「0 なら知らせる」の語が古い: %s" % (C.WATCH["MP 制約"],))


def test_MP制約の昔の名前の読み替えを消さない():
    """⚠⚠ 消すと、★「温存」と書かれた過去の run が数えられません。"""
    want = S.MP_LABELS[S.MP_SAVE]
    assert C.MP_ALIASES.get("温存") == want, "⚠ 「温存」の読み替えが無い"
    # ★読み替え先は必ず「いまの名前」（⚠ 古い字を書き写さない）
    assert set(C.MP_ALIASES.values()) == {want}
    # ⚠ いまの名前を読み替え元にしない（★自分自身へ向けない）
    assert want not in C.MP_ALIASES, "⚠ いまの名前を読み替えの元にしている"


def test_作戦の集計はPythonの名前から作る():
    """⚠ `coverage.py` が名前を写していないこと（★写すと改名の漏れ先になる）。"""
    assert set(C.STRATEGIES) == set(S.STRATEGY_LABELS.values())


def test_昔の名前の読み替えを消さない():
    """⚠⚠ 消すと、★過去の実機 run が全部「その他」に落ちます。"""
    want = S.STRATEGY_LABELS[S.LEVELING]
    for old in ("レベル上げ", "速攻"):
        assert C.STRATEGY_ALIASES.get(old) == want, "⚠ %s の読み替えが無い" % old
    # ★読み替え先は必ず「いまの名前」（⚠ 古い字を書き写さない）
    assert set(C.STRATEGY_ALIASES.values()) == {want}


def test_最短撃破という名前になっている():
    """★依頼者 2026-09-20「速攻 → 最短撃破」。⚠ 内部の語は `leveling` のまま。"""
    assert S.STRATEGY_LABELS[S.LEVELING] == "最短撃破"
    assert S.LEVELING == "leveling", "⚠⚠ 内部の語を変えると保存も生成物も過去ログも壊れます"


def test_画面に出る字をソースへ写していない():
    """⚠ 正本は `settings.py` だけ（★RX3-0198 の約束）。"""
    bad = []
    for path in sorted((ROOT / "dq3" / "ui").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        for label in S.STRATEGY_LABELS.values():
            if any('"%s"' % label in ln for ln in code):
                bad.append("%s に %s" % (path.name, label))
    assert not bad, "⚠⚠ 作戦の名前を画面へ写している: %s" % bad
