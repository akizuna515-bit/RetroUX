"""画面に出ている窓の文を読む（RX3-0016 V0 / 2026-08-30）。

★★ **プレイヤーが実際に見た文だけ** ★★

⚠⚠ ROM から台詞を先に取り出して並べるのではありません。
  ★画面に出たものを、出た順に拾います（No-Spoiler）。

## ⚠ 切り出しは 1 か所（`dq3rom.window`）

★Lua 側は「窓が出ているか」の安い見分けしかしません。
⚠ どこからどこまでが窓かを両方で決めると、**片方だけ直したときに
食い違います**（2026-08-29 に実際に踏んだ）。

## ⚠⚠ 生のタイルへ戻れるようにする

DQ3 の文字コード表はまだ直る見込みがあります（★濁点が 1 行上のマスに
あり、合成を間違えると別の語になる）。⚠ 文字だけ残すと、表を直しても
**読み直せません**。→ ★`raw_digest` に生タイルの指紋を残します。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"

COLUMNS, ROWS = 32, 30

#: ⚠ 文字表が読めなかった理由（★黙って空を返さないため）
charset_error: str | None = None

#: ⚠ 文字表が「空白」「知らない字」に使う印
#:
#:   ⚠⚠ `▼`（継続行の矢印）も落とします（★2026-08-31 / 実機の会話）。
#:     ★「まだ続きがある」という**操作の合図**であって、文ではありません。
#:     ⚠ 残すと「…かもしれぬ。▼」がそのままメモに入ります。
#:   ★「続きがあるか」を使いたくなったら、生タイル（0x73）で見ること
#:     （`auto_v0.lua` の `find_more` と同じ）。
FILLER = ("␣", "·", "　", "▼")

#: ★これより短い文は拾わない（⚠ 「はい／いいえ」やコマンド窓を弾く）
MIN_LENGTH = 6

#: ⚠ コマンドの窓は会話ではない（★出てくる語で弾く）
COMMAND_WORDS = ("はなす", "しらべる", "つよさ", "そうび", "じゅもん",
                 "どうぐ", "さくせん", "とじる", "たたかう", "にげる",
                 "はい", "いいえ", "ぼうぎょ")

#: ★★ 会話の印（⚠ 2026-08-31 実機）
#:
#:   ★DQ3 の台詞は必ず `＊「` で始まります。⚠ この印が無い窓を拾ったせいで、
#:     メモに**会話でないもの**が入りました。
#:
#:       18 'あかり  ハンソロ  エルシト  ロミオ'   ⚠ パーティの名前の行
#:       23 'G  244'                              ⚠ ゴールドの窓
#:
#:   ⚠ 「：」で弾く仕掛けは**すり抜けます**（★名前の行には「：」が無い）。
#:
#: ⚠⚠ **この印が無い文は、いま全部落とします。**
#:   ★「〜をてにいれた！」のような**台詞でないメッセージ**も落ちます。
#:   ⚠ 見分けが付くまでの当面の割り切りです（`RX3-0034`）。
SPEECH_MARK = "＊「"

#: ★継続とみなす重なりの最小の長さ（⚠ 短いと別の文を繋いでしまう）
OVERLAP_MIN = 8

#: ⚠⚠ 「パーティの状態」の窓を弾く印（★実測）
#:
#:   ★依頼者のセーブ 8 本すべてで、いちばん上の窓はこれでした。
#:
#:       H27H21H22H14M9M0M15M1ゆ：4せ：5そ：5ま：5
#:
#:   ⚠ HP/MP と職業の頭文字が並ぶ窓です。★会話に「：」は出ません。
STATUS_MARK = "："


def _charset():
    """⚠ 文字表は profile から（★ここに文字を書かない）。

    ## ⚠⚠ ここで黙って `None` を返して、1 度やられました

      ★profile の場所を間違えていたとき、`windows_on_screen` は
      **静かに空を返し**ました。⚠ 「窓 0 件」に見えるだけで、
      ★**一度も読めていなかった**のです。

      → ⚠ 読めないことは `charset_error` に残します（★黙らない）。
    """
    global charset_error

    from retroux.core.text import Charset

    try:
        spec = json.loads(PROFILE.read_text(encoding="utf-8")).get("text")
    except (OSError, ValueError) as exc:
        charset_error = "⚠ 文字表が読めません（%s）: %s" % (PROFILE, exc)
        return None
    if not spec:
        charset_error = "⚠ profile に文字表がありません: %s" % PROFILE
        return None
    charset_error = None
    return Charset(spec)


#: ⚠ 濁点・半濁点（★NFD にすると 1 文字ぶん後ろに付く）
DAKUTEN = ("゙", "゚")


def base_form(text: str) -> str:
    """★濁点・半濁点を落とした形（⚠ 見比べる用。★保存には使わない）。

    ## ⚠⚠ なぜ要るか（2026-08-31 実機）

      ★DQ3 は濁点を**1 行上の別のマス**に描きます。窓が折り返していると、
      同じ行が「濁点つき」と「濁点なし」の 2 通りで読めることがあります。

      ```text
      ＊「まちのそとを あるくとき  あやしげな ばしょには
                                   あやしけな はしょには   ⚠ 同じ行
      ```

      ⚠ 素で見比べると**別の行**に見えるので、★濁点を外して比べます。
    """
    got = unicodedata.normalize("NFD", text)
    return "".join(c for c in got if c not in DAKUTEN)


def _dakuten_count(text: str) -> int:
    return sum(1 for c in unicodedata.normalize("NFD", text) if c in DAKUTEN)


def richer(a: str, b: str) -> str:
    """★同じ行の 2 通りから、⚠ **1 字ずつ**濁点の付いたほうを採る（RX3-0272）。

    ## ⚠⚠ 2026-09-14: 行ごと「濁点が多いほう」を採っていました

      ★DQ3 は窓を**1 フレームに 1 行ずつ**上へ送ります（隔離先の save1 で毎フレーム控えた）。
      送りの途中の 1 枚は、いちばん上の字の行の上が枠 → ⚠ **その行だけ濁点が無い**。
      別の 1 枚は別の所が欠ける → ⚠ 数で片方を採ると、もう片方にしか無い濁点を捨てます。

      ```text
      A  ポカパマズさまも … アりアハンでの … オルテガ   ★どちらも本物の画面
      B  ホカハマスさまも … アりアハンでの … オルテガ   ⚠ 送りの途中（上の行の濁点が無い）
      ```

      ★字の行の上は「自分の濁点の行 / 字の行 / 枠」のどれか（⚠ 別の行の濁点が乗ることは無い / 実測）
      → 付いているほうを 1 字ずつ採っても、⚠ 無い濁点を作りません。
    ⚠ 濁点を外した形か長さが違うときは、今までどおり濁点の多いほう（★字の対応が取れない）。
    """
    if len(a) != len(b) or base_form(a) != base_form(b):
        return a if _dakuten_count(a) >= _dakuten_count(b) else b
    return "".join(y if base_form(x) == base_form(y) and _dakuten_count(y) > _dakuten_count(x) else x
                   for x, y in zip(a, b))


def _drop_repeats(rows: list) -> list:
    """⚠ 濁点を外すと同じになる行を 1 本にまとめる（★濁点の多いほうを残す）。"""
    out: list = []
    seen: dict = {}
    for row in rows:
        key = base_form(row)
        if key in seen:
            i = seen[key]
            out[i] = richer(out[i], row)
            continue
        seen[key] = len(out)
        out.append(row)
    return out


def _tidy(text: str) -> str:
    for mark in FILLER:
        text = text.replace(mark, "")
    return text.strip()


def digest_of(raw: bytes) -> str:
    """★生タイルの指紋。⚠ 同じ窓を二度書かないための鍵でもある。"""
    return hashlib.sha256(bytes(raw)).hexdigest()[:16]


def windows_on_screen(tiles):
    """★画面に出ている窓を `(文, 生タイルの指紋)` で返す。

    ⚠ 窓が無ければ空。★エラーにしません（歩いているだけの間は毎回空）。
    """
    if not tiles or len(tiles) < COLUMNS * ROWS:
        return []
    charset = _charset()
    if charset is None:
        return []
    from dq3rom import screen as sc
    from dq3rom import window as win

    raw = bytes(t & 0xFF for t in tiles)
    out = []
    for box in win.find_windows(raw):
        # ⚠⚠ **文字にするのも `dq3rom.window` に任せる。**
        #
        #   ★2026-08-31 に実機の会話で踏んだ形（RX3-0016）:
        #   ここは `read_screen` の行を自分で切り貼りしていたので、
        #   ⚠ **濁点だけの行が本文に混ざった**。
        #
        #       ⚠ 「゛＊「レーベのむらに ようこそ。」
        #       ⚠ 「まちのそとを あるくとき゛゛あやしげな…」
        #
        #   ★`window.text_of` は最初からこれを落としていて、
        #   検査もあった（`test_濁点だけの行は残らない`）。
        #   ⚠⚠ **同じ判定を 2 か所に書いて、片方だけ直っていた。**
        text, _unknown = win.text_of(box, raw, charset)
        # ⚠⚠ **行ごとに見てから繋ぐ**（★折り返した窓は同じ行を 2 度返す）
        rows = [r for r in (_tidy(r) for r in text.split(chr(10))) if r]
        joined = _tidy("".join(_drop_repeats(rows)))
        if joined:
            flat = bytes(t for row in box.tiles for t in row)
            out.append((joined, digest_of(flat)))
    return out


def conversation_on_screen(tiles):
    """★会話らしい窓を 1 つだけ返す（⚠ 無ければ `None`）。

    戻り値は `(文, 生タイルの指紋)`。

    ## ⚠ コマンドの窓は会話ではありません

      ★「はなす／しらべる／…」が出ている窓を拾うと、⚠ **メモが
      コマンド名で埋まります**。出てくる語で弾きます。

    ## ⚠ 短すぎるものも拾いません

      ★「はい」「いいえ」だけの窓は、記録しても意味がありません。

    ## ⚠⚠ **この見分けは、まだ実機で確かめていません**

      ★依頼者のセーブ 8 本には、**会話の窓が 1 つもありません**
      （戦闘・メニュー・呪文の一覧だけ）。⚠ つまり「会話を正しく拾えるか」は
      **1 度も試せていません**。

      ★弾く条件は、**実際に見えた窓から作った**ものです。

      ```text
      ⚠ パーティの状態   H27H21H22H14M9M0M15M1ゆ：4せ：5そ：5ま：5
      ⚠ 戦闘のコマンド   ▶たたかう にげる ぼうぎょ どうぐ
      ⚠ 呪文の一覧       ▶ホイミ
      ⚠ 敵の一覧         スライムー1ひき おおがらすー2ひき
      ```

      ⚠ **会話の窓を含むセーブステートを 1 本いただければ確かめられます。**
    """
    for text, digest in windows_on_screen(tiles):
        if len(text) < MIN_LENGTH:
            continue
        if SPEECH_MARK not in text:
            continue                      # ⚠ 会話の印が無い（★上の註）
        if STATUS_MARK in text:
            continue                      # ⚠ パーティの状態の窓
        # ⚠⚠ 2026-09-02（RX3-0052 / 実機）: 「＊「ここは どうぐやです。」が**弾かれた**。
        #   ★「どうぐ」がコマンド語なので、会話の文まで捨てていた。
        #   → ★コマンドの窓は語が**並ぶ**（2 語以上）。1 語だけなら会話の中の言葉。
        if sum(1 for word in COMMAND_WORDS if word in text) >= 2:
            continue
        if "▶" in text:
            continue                      # ⚠ 選ぶ窓（★カーソルが出ている）
        return (text, digest)
    return None


# --- ★★ 継続（⚠ 2026-08-31 実機の 8 件から起こした）------------------------

def join_continuation(prev: str, new: str) -> str | None:
    """★流れ込んでいる途中の文を 1 本に繋ぐ。⚠ 別の文なら `None`。

    ## ⚠⚠ なぜ要るか（★実機の記録そのまま）

      ```text
      26 ＊「まちのそとを あるくとき  あやしげな ばしょ
      27 ＊「まちのそとを … しれぬ。＊「とお
      28 あやしげな ばしょには … そのばしょま      ⚠ 送られて頭が欠けた
      29 なにか あるかも しれぬ。… いくことだな。
      ```

    ## ★見分け方（⚠ **濁点を外して**比べる）

      ```text
      ① new が prev で始まる      → ★伸びた
      ② new が prev に含まれる    → ⚠ 変わっていない
      ③ prev の末尾が new の先頭と OVERLAP_MIN 以上重なる → ★送られた
      それ以外                    → ⚠ 別の文
      ```

      ⚠ 濁点は 1 行上のマスなので、★同じ行でも付いたり落ちたりします。
      素で比べると「別の文」と判断して、**同じ行が 2 度入ります**。
    """
    if not prev:
        return new or None
    if not new:
        return prev
    bp, bn = base_form(prev), base_form(new)
    if bn.startswith(bp):
        # ★重なっている所は、濁点の多いほうを採る
        return richer(prev, new[:len(prev)]) + new[len(prev):]
    if bn in bp:
        # ★含まれている所も 1 字ずつ濁点を採る（RX3-0272 / ⚠ 送りの途中の 1 枚が先に来ることがある）
        i = bp.find(bn)
        if len(bp) != len(prev) or len(bn) != len(new):
            return prev                   # ⚠ 字の対応が取れない（★今までどおり）
        return prev[:i] + richer(prev[i:i + len(new)], new) + prev[i + len(new):]
    limit = min(len(prev), len(new))
    for size in range(limit, OVERLAP_MIN - 1, -1):
        if bp[-size:] == bn[:size]:
            head = prev[:len(prev) - size]
            return head + richer(prev[len(prev) - size:], new[:size]) + new[size:]
    return None


# --- ★★ 街ナビが拾ったページ（RX3-0229 / 2026-09-13）------------------------

def page_tiles(page) -> list[int] | None:
    """★`nav.talk_pages` の 1 枚（`{"y": 行, "hex": 行 y から下の 16 進}`）を 32x30 の画面へ戻す。

    ⚠ 形が違えば `None`（★黙って別の文にしない）。窓の外は 0 で埋める（★窓の読み方は変えない）。
    """
    if not isinstance(page, dict):
        return None
    y, raw = page.get("y"), page.get("hex")
    if not isinstance(y, int) or not isinstance(raw, str) or not 0 <= y < ROWS:
        return None
    if len(raw) % 2 or len(raw) > (ROWS - y) * COLUMNS * 2:
        return None
    try:
        body = [int(raw[i:i + 2], 16) for i in range(0, len(raw), 2)]
    except ValueError:
        return None
    tiles = [0] * (COLUMNS * ROWS)
    tiles[y * COLUMNS:y * COLUMNS + len(body)] = body
    return tiles


def page_text(tiles) -> str | None:
    """★1 枚の会話の文（⚠ 無ければ `None`）。

    ★`conversation_on_screen` と同じ弾き方。⚠ ただし `＊「` の無い窓も拾います
    （★長い話の 2 枚目以降は、文の途中から始まる）。印のある窓があればそちらを採ります。
    """
    fallback = None
    for text, _digest in windows_on_screen(tiles):
        if STATUS_MARK in text or "▶" in text:
            continue
        if sum(1 for word in COMMAND_WORDS if word in text) >= 2:
            continue
        if SPEECH_MARK in text:
            return text
        if fallback is None:
            fallback = text
    return fallback


def join_pages(texts) -> str:
    """★ページの文を 1 本につなぐ（⚠ 重なりは 1 回だけ / 重ならなければそのまま後ろへ）。

    ★隣どうしで `join_continuation` を使います（★送られたページは前のページの末尾と重なる）。
    ⚠ 前のページに丸ごと含まれるページ（★B が効かなかった）は足しません（★濁点だけは採る）。

    ## ⚠⚠ 2026-09-14（RX3-0272）: 次と比べる「前」を、濁点を採る前の生のページにしていました

      ★重なりで濁点を採っても、⚠ 次のつなぎは生のページ（送りの途中 = 上の行の濁点が無い）から作り直すので、
      ⚠ **採った濁点を上書きして消していた**（依頼者「聞き込みだと ホカハマス / 手で話すと ポカパマズ」）。
      → ★「前」は、つないだ文の末尾（★濁点を採った後）にする。
    """
    acc, prev = "", ""
    for text in texts:
        if not text:
            continue
        if not prev:
            acc, prev = text, text
            continue
        merged = join_continuation(prev, text)
        if merged is None:
            acc, prev = acc + text, text
        elif merged != prev:
            acc = acc[:len(acc) - len(prev)] + merged
            # ★伸びた → 末尾の今のページ分（★濁点を採った後）/ 濁点だけ足した → つないだもの全部
            prev = merged[len(merged) - len(text):] if len(merged) != len(prev) else merged
    return acc


def text_of_pages(pages) -> tuple[str, str] | None:
    """★ページの列を `(文, 指紋)` にする（⚠ 1 枚も読めなければ `None`）。

    ★指紋はページの生タイルぜんぶから作る（★文字表を直しても同じ会話だと分かる）。
    """
    if not isinstance(pages, list):
        return None
    texts, raw = [], bytearray()
    for page in pages:
        tiles = page_tiles(page)
        if tiles is None:
            continue
        raw.extend(t & 0xFF for t in tiles)
        got = page_text(tiles)
        if got:
            texts.append(got)
    joined = join_pages(texts)
    if not joined:
        return None
    return joined, digest_of(bytes(raw))


def tidy_message(text: str) -> str:
    """★保存する形にする。⚠ **切り分けません**（1 会話 = 1 メモ）。

    ## ⚠⚠ 2026-08-31: `＊「` で切っていました

      ★依頼者「継続行の場合、別メッセージで扱われる」。
      ⚠ `＊「` は**話し手が変わる印ではありません**。同じ人の続きにも付きます。

      ```text
      ＊「まちのそとを … しれぬ。＊「とおくから … いくことだな。
      → ⚠⚠ これで **1 人の話**（★2 件に割らない）
      ```

    ⚠ 頭に印より前の欠片があれば落とします（★送られた後の半端な文）。
    """
    if not text:
        return ""
    at = text.find(SPEECH_MARK)
    if at < 0:
        return ""
    return text[at:].strip()
