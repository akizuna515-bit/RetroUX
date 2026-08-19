"""回復が効かなかったときの言い分け（2026-08-06）。

実機のモンキー実行（24戦）で、こう出ました:

    ⚠ 唱えたのにHPが増えませんでした
      （samaltria の ホイミ / moonbrooke のHP 36 -> 0 / MP 51 -> 48 / 時間切れ）

## ⚠⚠ これは**こちらの不具合ではありません**

★HP が `36 -> 0` なら、唱えるより先に相手が倒されています。
DQ2 の仕様どおりの空振りで、追うべき相手は**回復の実装ではなく
戦況判断**（もっと早く回復すべきだったか）です。

⚠ ところが文言が「増えませんでした」だけだと、
**呪文が届いていない不具合**に見えます。★追う相手を間違えます。

## ★ 3つに言い分ける

    HP が 0        -> 回復が間に合わなかった（唱える前に倒れた）
    HP が減った    -> 回復より攻撃が上回った
    HP が同じ      -> 唱えたのに増えなかった（★これだけが本当に謎）

⚠⚠ **「HPが同じ」だけを不具合の候補として残します。**
  満タン・行のずれなど、まだ分かっていない原因がここに入ります。
"""

from __future__ import annotations

import pathlib

BRIDGE = (pathlib.Path(__file__).resolve().parents[1]
          / "retroux" / "emulator" / "fceux" / "bridge.lua")


def _source() -> str:
    return BRIDGE.read_bytes().decode("utf-8")


def test_倒れた場合を別の文言で出す():
    """★★ **これが今回の修正そのもの。**"""
    source = _source()
    assert "回復が間に合いませんでした（唱える前に倒れた）" in source


def test_削り負けた場合も別扱いにする():
    """⚠ HP が減っているなら、回復が足りなかっただけです。"""
    assert "回復より攻撃が上回りました（HPが減っている）" in _source()


def test_本当に増えなかった場合だけ元の文言を残す():
    """★ここだけが「まだ分かっていない」の置き場です。"""
    assert "⚠ 唱えたのにHPが増えませんでした" in _source()


def test_3つの理由が別々の手がかりを持つ():
    """⚠⚠ **同じ手がかり文字列だと、ログを絞り込めません。**

    ★`heal: ...` は後からログを機械で数えるための印です。
    """
    source = _source()
    hints = ("heal: target died first", "heal: outpaced by damage",
             "heal: cast but no hp gain")
    for hint in hints:
        assert f'"{hint}"' in source, f"⚠ {hint} がありません"
    assert len(set(hints)) == 3


def test_判定はHPの前後だけで決めている():
    """⚠ 「倒れた」を別の場所（生存ビットなど）から取りに行かないこと。

    ★戦闘が終わった直後は、状態ビットが当てになりません。
      HP の前後の値だけで言い分けられるなら、それがいちばん確かです。
    """
    source = _source()
    start = source.find("回復が間に合いませんでした")
    assert start > 0
    window = source[max(0, start - 400):start]
    assert "if now <= 0 then" in window, "⚠ HPで判定していません"
