"""同じ絵を 2 つの かな で使い回している分を直す（RX3-0093 / 2026-09-06）。

★★ DQ3 は り と リ に**同じ絵を 1 つしか持っていません** ★★

```text
符号 0x32   ひらがなの語   てつのやり / どくばり / ふなのりのほね
            カタカナの語   オりハルコン / ザオりク / アりアハン / ロマりア
```

⚠⚠ だから「文字表の穴を埋める」では直りません。⚠ さらに「カタカナが混じって
いたら直す」も**危険**です。★実データに、かな と カタカナ が混ざった名前が
20 件以上あり（はぐれメタル / キメラのつばさ / ちいさなメダル）、⚠ 素朴な規則は
**これを壊します**。

★ここでの決まりは 1 つだけです。

    語のなかに「曖昧でないひらがな」（★カタカナの絵が別にある字）が
    1 つも無いときだけ、曖昧な字をカタカナに直す。

⚠ 曖昧な字の一覧は**文字表から機械的に**出します（★手で並べない）。

⚠⚠ `retroux/` には置きません（★`RX3-0011` の前提: DQ3 の作業で retroux を変えない）。
"""
from __future__ import annotations

import unicodedata

#: ★ひらがなの符号の範囲と、カタカナへの差（⚠ 字そのものは書かない）
_HIRA_LO, _HIRA_HI, _KATA_GAP = 0x3041, 0x3096, 0x60


def _base(ch: str) -> str:
    return unicodedata.normalize("NFD", ch)[0] if ch else ch


def _is_hiragana(ch: str) -> bool:
    return bool(ch) and _HIRA_LO <= ord(ch) <= _HIRA_HI


def to_katakana(ch: str) -> str:
    """★ひらがな → カタカナ（⚠ 濁点は付いたまま）。"""
    got = "".join(chr(ord(c) + _KATA_GAP) if _is_hiragana(c) else c
                  for c in unicodedata.normalize("NFD", ch))
    return unicodedata.normalize("NFC", got)


def ambiguous_kana(known) -> set:
    """★文字表が「カタカナの相手を持たない」ひらがな（= 絵を使い回している字）。"""
    known = set(known or ())
    out = set()
    for ch in known:
        if not _is_hiragana(_base(ch)):
            continue
        kata = to_katakana(ch)
        if kata != ch and kata not in known:
            out.add(ch)
    return out


def katakana_word(name: str, known, ambiguous=None) -> str:
    """★語のなかに曖昧でないひらがなが 1 つも無いときだけ、曖昧な字を直す。

    ⚠⚠ 両端（ROM から復号した名前 / 画面から読んだ名前）で**同じ関数**を通すこと。
    ★ずらすと突き合わせが必ず割れます。
    """
    if not name:
        return name
    known = set(known or ())
    amb = set(ambiguous) if ambiguous is not None else ambiguous_kana(known)
    amb_bases = {_base(c) for c in amb}
    clear_bases = {_base(c) for c in known if _is_hiragana(_base(c))} - amb_bases
    bases = [_base(c) for c in name]
    if any(b in clear_bases for b in bases):
        return name                        # ⚠ ひらがなが確かに混ざっている → 触らない
    if not any(b in amb_bases for b in bases):
        return name                        # ★直すところが無い
    return "".join(to_katakana(c) if b in amb_bases else c for c, b in zip(name, bases))
