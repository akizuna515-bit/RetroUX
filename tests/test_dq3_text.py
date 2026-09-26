"""DQ3 の文字コード表（RX3-0013 / 2026-08-25）。

## ★どうやって手に入れたか

ROM を探しても**素のかな列は見つからない**（テキストは圧縮されている）。
★そこで、セーブステートの **CHR-RAM（8192 バイト）**を 8x8 の 2bpp として描き、
字形を人が読んだ。DQ3 は CHR-RAM なので、フォントは**画面に出ている間ずっと常駐**する。

```text
索引 0x100  ␣ 0123456789 あいうえお
索引 0x110  かきくけこさしすせそたちつてとな
…
```

## ★DQ2 の仕組みをそのまま使う

`retroux/core/text.py` の `Charset` は `runs` / `single` という形の表を受け取る。
★DQ3 の表を同じ形にしたので、**DQ2 のコードを 1 行も変えずに**読める。
⚠ これは 2026-08-25 の決定「`retroux/` は import して使うだけ」の実例。

## ⚠ まだ確定していないこと

- 索引は **CHR のタイル索引**であって、⚠ ROM のバイト値と同じとは限らない
- ⚠ 濁点・半濁点の表し方（合成か、個別の字形か）
- ★小書き（ゃゅょ / ャ）は 8x8 では見分けにくい
"""

from __future__ import annotations

import json
import pathlib

import pytest

from retroux.core.text import Charset

PROFILE = (pathlib.Path(__file__).resolve().parents[1]
           / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")


@pytest.fixture(scope="module")
def charset() -> Charset:
    spec = json.loads(PROFILE.read_text(encoding="utf-8")).get("text")
    assert spec, "⚠ profile に text がない"
    return Charset(spec)


def test_DQ2の仕組みで読める(charset):
    """★`retroux/core/text.py` を**変更せずに**使えること。"""
    assert charset.usable
    assert len(charset.table) > 100


def test_五十音が順に並んでいる(charset):
    """★字形の並びが 50 音順であることが、この表の根拠そのもの。"""
    assert charset.decode([0x10B, 0x10C, 0x10D, 0x10E, 0x10F])[0] == "あいうえお"
    assert charset.decode(range(0x110, 0x115))[0] == "かきくけこ"
    assert charset.decode(range(0x130, 0x137))[0] == "よらりるれろわ"


def test_数字も読める(charset):
    assert charset.decode(range(0x101, 0x10B))[0] == "0123456789"


def test_読めないコードは黙って捨てない(charset):
    """⚠ 落とすと「なぜかここだけ短い」になる（DQ2 で踏んだ）。"""
    text, unknown = charset.decode([0x10B, 0x999, 0x10C])
    assert unknown == [0x999]
    assert "あ" in text and "い" in text


def test_確度を下げて書いてある():
    """⚠ 目で読んだ表を confirmed にしない。"""
    spec = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert spec["text"]["confidence"] == "high-confidence"
    assert spec["confidence"]["text_encoding"] == "high-confidence"
    assert spec["text"]["_unresolved"], "★分かっていない所を列挙しておく"

# --- ★★ 似たカタカナは、ひらがなとタイルを共有している ------------------
#
#   ⚠⚠ **これは不具合ではありません**（RX3-0029 / 2026-08-31）。
#     ★依頼者「おそらくメモリ節約のために似た文字を統合している」→ 実測で確認。


KANA = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
KATA = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
#: ⚠ 表に無いカタカナ（★どれもひらがなと字形がほとんど同じ）
SHARED = "ウケセチツヘヤユヨリワヲ"


def test_カタカナはひらがなとタイルを共有している(charset):
    """⚠⚠ **「文字表にカタカナを足す」直しをしないこと。**

    ★そんなタイルは ROM に無い。実測（`DQ3_J.fc7` の会話窓 y=20）::

        x= 9  tile=0x58 → レ
        x=10  tile=0x7F → ー
        x=11  tile=0x27 → へ    ⚠⚠ **ひらがなの「へ」**（上のマスに濁点）

    ★つまり「レーベ」は、ひらがなの「へ」のタイルで描かれている。
    ⚠ タイルが 1 つしか無い以上、**タイルだけからは区別できない**。

    ★区別したくなったら、前後の字から決める別の仕組みが要る。
      ⚠ `Memo` は `raw_digest` を残しているので、後から読み直せる。
    """
    got = set(charset.table.values())
    missing_kana = [c for c in KANA if c not in got]
    assert not missing_kana, "⚠ ひらがなが欠けている: %s" % "".join(missing_kana)

    missing_kata = "".join(c for c in KATA if c not in got)
    assert missing_kata == SHARED, (
        "⚠⚠ 共有している字の顔ぶれが変わりました: %r（★%r のはず）"
        % (missing_kata, SHARED))


@pytest.mark.xfail(reason="⚠ 基準にしていたセーブが失われた（RX-0135）。★観点は docs/audit/tests-waiting-savestates.md", strict=False)
def test_ヘは共有していることを実データで見る(charset):
    """★「似ているから」ではなく、**実際に共有しているのを見る**。"""
    from dq3rom import ppu
    from dq3_states import CONVERSATION, pick
    from retroux.core.bgmap.savestate import load

    table = charset.table
    assert "ヘ" not in table.values(), "⚠ カタカナの「ヘ」に番号が付いている"
    code = next(k for k, v in table.items() if v == "へ")

    # ★カタカナの語（レ ー ヘ）の中で、そのタイルが使われていること
    hit = 0
    for path in pick(CONVERSATION):
        chunks = load(path).chunks
        tiles = ppu.compose(chunks["NTAR"], ppu.scroll_of(chunks),
                            ppu.mirroring_of(chunks))
        raw = code - 0x100
        for i, v in enumerate(tiles):
            if v != raw or i % 32 < 2:
                continue
            before = [table.get(tiles[i - k] + 0x100) for k in (2, 1)]
            if before == ["レ", "ー"]:
                hit += 1
    assert hit, (
        "⚠⚠ カタカナの語の中で「へ」のタイルが見つからない（★空回り）")
