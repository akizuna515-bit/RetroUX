"""賢者の「呪文の系統を選ぶ窓」（RX3-0293 / 2026-09-18）。

⚠⚠ 依頼者「save1 けんじゃの『まほうつかいと僧侶』の呪文選択に対応できていない」。

★実測（依頼者の `save1` の画面を `dq3rom.ppu.screen_of` で読んだ）:

```text
窓(4,18)  ハンソロ ／ たたかう ／ じゅもん …     ★戦闘コマンド窓
窓(4,22)  じゅもん ／ ▶まほうつかい ／ そうりょ   ⚠⚠ これが未対応の窓
```

⚠ この窓には呪文名が 1 つも無いので、`pick_spell` は探し続けて `spell_not_found` で止まる。

★決めたこと（本 WI の Decision）:

```text
見分け   画面に「まほうつかい」と「そうりょ」が**両方**出ていたら系統の窓
         ⚠ 職業から当てにいかない（★転職した人で外れる）
どちら   ROM のブロック（4-7 = 魔法使い / 8-11 = 僧侶 / RX3-0125）
規則の数 ★`ai/catalog.lua` に **1 つだけ**（⚠ 自動戦闘とまんたんが同じものを呼ぶ）
```
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3.phase0 import generate_lua as GL

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
AUTO = ROOT / "dq3" / "phase0" / "auto_v0.lua"
MANTAN = ROOT / "dq3" / "phase0" / "mantan_v0.lua"
CATALOG = ROOT / "dq3" / "phase0" / "ai" / "catalog.lua"
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★呪文の番号は名前から ROM（`rom_names`）で引く（RX3-0293）
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


def _profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _charset():
    from retroux.core.text import Charset

    return Charset(_profile()["text"]).table


def _body(path: pathlib.Path) -> str:
    """★註を外した本文（⚠ 註に書いただけを「やった」と数えない）。"""
    return chr(10).join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                        if not ln.lstrip().startswith("--"))


# --- ★語（profile が正本）------------------------------------------------

def test_系統の語はprofileが持つ():
    """⚠ Lua にも Python にも直書きしない（★同じ語が 2 か所に散らない）。"""
    fam = _profile()["battle"]["spell_families"]
    assert fam["mage"] and fam["pilgrim"], fam
    assert fam["mage"] != fam["pilgrim"]


def test_語はタイル列にして渡す():
    """⚠ 名前のまま Lua へ渡すと画面と比べられない（★ほかの語と同じ扱い）。"""
    got = GL._spell_families(_profile()["battle"], _charset())
    assert set(got) == {"mage", "pilgrim"}
    for key, seq in got.items():
        assert seq and all(isinstance(v, int) for v in seq), (key, seq)
    assert got["mage"] != got["pilgrim"]


def test_語が読めなければ入れない():
    """⚠ 字形の無い文字が混じったら**入れない**（★Lua は押さずに止まる）。"""
    got = GL._spell_families({"spell_families": {"mage": "★", "pilgrim": "そうりょ"}},
                             _charset())
    assert "mage" not in got, "⚠⚠ 画面に出ない並びを渡している"
    assert "pilgrim" in got


def test_語が無くても生成は落ちない():
    assert GL._spell_families({}, _charset()) == {}


def test_生成物に系統の語が入る():
    """★`build()` の出口まで通っていること（⚠ 作っただけで繋ぎ忘れない）。"""
    got = GL.build()
    assert set(got["spell_family_tiles"]) == {"mage", "pilgrim"}
    # ⚠ 旧い鍵を消していないこと（★同じところで 1 度消しかけた）
    assert got["cursor_tile"] is not None and got["menu_tiles"]


@needs_rom
def test_設定の呪文には番号も付ける():
    """⚠ 系統を決めるのに**呪文の番号**が要る（★名前だけでは決められない）。"""
    got = GL.build()["auto_battle"]["commands"]
    used = [v for v in got.values() if v.get("primary") == "spell"
            or v.get("fallback") == "spell"]
    assert used, "★見本の設定に呪文を使う人が居ない"
    for spec in used:
        assert spec.get("spell_tiles"), spec
        assert isinstance(spec.get("spell_id"), int), (
            "⚠⚠ 呪文の番号が付いていない（★賢者の系統を決められない）: %r" % (spec,))


def test_呪文の番号は名前から引く():
    """⚠ ROM が無ければ None（★推測で番号を置かない）。"""
    from dq3.knowledge import rom_names as RN

    name = RN.spell(26)
    if name is None:
        return                               # ★ROM が無い環境（⚠ ここでは落とさない）
    assert GL._spell_id(name) == 26
    assert GL._spell_id("そんな呪文はない") is None


# --- ★規則は 1 か所（⚠ 書き写さない）-------------------------------------

def test_系統の規則はcatalogに1つだけ():
    """⚠⚠ 「同じ判定を 2 か所に書いて片方だけ直っていた」を繰り返さない。"""
    cat = _body(CATALOG)
    assert "FAMILY_BLOCKS" in cat and "function Catalog.family_of" in cat
    # ★ブロックの割り当ては Python 側が正本（⚠ 数がずれたら気づけるように）
    from dq3rom import spell_flags as SF

    for name, want in (("mage", SF.MAGE_BLOCKS), ("pilgrim", SF.PILGRIM_BLOCKS)):
        lua = "%s = {%s}" % (name, ", ".join(str(n + 1) for n in want))
        assert lua in cat, (
            "⚠⚠ Lua のブロックが Python（`dq3rom/spell_flags.py`）と違う: " + lua)
    for path in (AUTO, MANTAN):
        assert "FAMILY_BLOCKS" not in _body(path), (
            "⚠⚠ 系統の規則を %s に書き写している" % path.name)


def test_両方出ていて初めて系統の窓():
    """⚠ 片方だけの行に釣られない（★つよさの窓などに 1 語だけ出ることはある）。"""
    for path in (AUTO, MANTAN):
        body = _body(path)
        assert "rows.mage == nil or rows.pilgrim == nil" in body, (
            "⚠⚠ %s が **片方だけ**でも系統の窓と数えている" % path.name)


def test_自動戦闘は呪文を探す前に系統を見る():
    """⚠⚠ 作っただけで**呼び忘れる**を防ぐ（★この計画で何度も踏んだ形）。"""
    body = _body(AUTO)
    assert "function AIX.spell_family" in body
    # ⚠⚠ 2026-09-18: ここは最初 `AIX.spell_family(nt, plan)` を探していたが、
    #   ★**定義のほう**に当たって、呼び出しを消しても緑のままだった（壊す実験で判明）。
    #   → ★呼び出しの形（`= AIX.spell_family(...)`）で探す。
    hook = body.find("= AIX.spell_family(nt, plan)")
    assert hook > 0, "⚠⚠ pick_spell から系統を見ていない"
    # ★呪文の一覧を探すより**前**に呼ぶこと（⚠ あとだと spell_not_found で止まる）
    find = body.find("local list_tiles =")
    assert 0 < hook < find, "⚠⚠ 呪文を探したあとで系統を見ている（★順番が逆）"


def test_まんたんにも系統の段がある():
    """⚠ 同じ窓はフィールドにも出る（★唱える人を決めたあとに挟まる）。"""
    body = _body(MANTAN)
    assert "function MX.family_row" in body
    assert 'step = "family"' in body, "⚠⚠ 唱える人のあとに系統の段が無い"
    assert 'if step == "family" then' in body


def test_押しても変わらなければ止まる():
    """⚠⚠ 永久に押し続けない（★「押しても変わらないなら押さない」）。"""
    body = _body(AUTO)
    assert "spell_family_stuck" in body
    assert "AIX.FAMILY_PRESS_MAX" in body


def test_系統が分からなければ押さない():
    for path in (AUTO, MANTAN):
        assert "spell_family_unknown" in _body(path), path.name


def test_止まる理由は人の言葉になる():
    """⚠⚠ 表に無いと、★人には「うまくいきませんでした」しか出ない。

    ⚠ `test_dq3_action_summaries.py` の照合は `stop("...")` の**literal** しか拾えない。
    ★ここは `stop(why)` のように**変数で渡す**理由も数える（= その穴をふさぐ）。
    """
    import re

    from dq3.events import reasons as RS

    for path, table in ((AUTO, RS.BATTLE), (MANTAN, RS.MANTAN)):
        used = set(re.findall(r'"(spell_family_[a-z_]+)"', _body(path)))
        assert used, "⚠ %s に系統の理由が無い（★この検査は空回り）" % path.name
        missing = sorted(used - set(table))
        assert not missing, (
            "⚠⚠ %s の理由が `dq3/events/reasons.py` にありません: %s" % (path.name, missing))
