"""聞き込みの 1 人ぶんの会話は全部の文を台帳へ（RX3-0184）/ 手で話した会話も勇者会議の材料（RX3-0185）。

⚠⚠ 2026-09-12 依頼者「カンダタの情報や、まほうのカギの情報（言葉）を得たが、勇者会議の画面が変わっていない」。
★調べると、カザーブの冒険者の**1 つ目の文**が会話の台帳から**消えていた**
（★1 人の会話が 2 つの文に分かれると、最後の文だけを台帳へ書いていた）。
⚠ 手で話した会話（まほうのカギの話）は勇者メモにしか無く、勇者会議が読んでいなかった。

★見本の文は**架空**です（⚠ 原作の会話は公開物に入れません / RX3-0433）。
⚠ ただし**名前と道具の名前**（`カンダタ` / `まほうのカギ`）は、★勇者会議が拾うかを
見るための材料なので本物のまま残してあります（★名前は ROM の表から出ます）。
"""
from __future__ import annotations

import json

import pytest

from dq3.knowledge import concepts as C
from dq3.knowledge import conversation as cv
from dq3.ui.view_model import Dq3ViewModel
from dq3rom import screen as sc
from dq3rom import window as win

FIRST = "＊「わたしは カンダタを さがして ここまできた。"
SECOND = "＊「どこかの とうに かくれているはずだ。"


class _VM:
    """★`_flush_talk` が触るものだけ（⚠ 画面も FCEUX も要らない）。"""

    def __init__(self, tag=None):
        self._talk, self._talk_digest = None, None
        self.talk_tag = tag
        self.last_talk_text = None
        self.memos = []

    def _learn_place_name(self, _text):
        return None

    def add_memo(self, text, **kw):
        self.memos.append((text, kw))
        return text

    def _talker_now(self):
        return None, None, None


def _say(vm, text):
    vm._talk, vm._talk_digest = text, "d-%d" % len(vm.memos)
    return Dq3ViewModel._flush_talk(vm)


def test_聞き込みの会話は全部の文を残す():
    vm = _VM(tag={"label": "冒", "npc_id": 8, "map_id": 20})
    _say(vm, FIRST)
    _say(vm, SECOND)
    got = vm.last_talk_text or ""
    assert "カンダタ" in got, "⚠⚠ 1 つ目の文が消えた（★最後の文だけが台帳へ行く）"
    assert "かくれているはず" in got
    assert len(vm.memos) == 2, "★勇者メモは今までどおり文ごとに 1 行"


def test_手で話した会話はつながない():
    """★聞き込みでないとき（talk_tag なし）は、今までどおり last_talk_text を触らない。"""
    vm = _VM(tag=None)
    _say(vm, FIRST)
    assert vm.last_talk_text is None


def _write(tmp_path, conv, memos):
    (tmp_path / "npc-conversations.json").write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "memos.jsonl").write_text(
        "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in memos), encoding="utf-8")
    return tmp_path / "npc-conversations.json"


def test_手で話した会話も勇者会議の材料になる(tmp_path):
    path = _write(tmp_path, {"20/8": [{"text": SECOND, "text_hash": "abc"}]}, [
        {"text": "＊「まほうのカギが あれば とおれるように なるだろう。", "source": "conversation", "map_id": 43},
        {"text": "冒「わたしは カンダタを さがして ここまできた。」", "source": "npc_talk", "map_id": 20, "npc_id": 8},
        {"text": "冒「どこかの とうに かくれているはずだ。」", "source": "npc_talk", "map_id": 20, "npc_id": 8},
        {"text": "★カザーブを見つけた", "source": "location"},
    ])
    texts = [o.text for o in C.observations(path)]
    assert any("まほうのカギ" in t for t in texts), "⚠⚠ 手で話した会話が勇者会議に届かない"
    assert any("カンダタ" in t for t in texts), "★台帳から消えたページも勇者メモから拾う"
    assert sum("かくれているはず" in t for t in texts) == 1, "⚠ 台帳にある本文を 2 度数えている"
    assert not any("見つけた" in t for t in texts), "⚠ 会話でないメモを材料にしている"


def test_台帳にまとめて入った会話はメモから数えない(tmp_path):
    """★RX3-0184 のあとは 1 人の会話が 1 行につながる。⚠ メモの文ごとの行を別に数えない。"""
    path = _write(tmp_path, {"20/8": [{"text": FIRST + SECOND, "text_hash": "abc"}]}, [
        {"text": "冒「わたしは カンダタを さがして ここまできた。」", "source": "npc_talk"},
        {"text": "冒「どこかの とうに かくれているはずだ。」", "source": "npc_talk"},
    ])
    assert len(C.observations(path)) == 1


# --- ★★ RX3-0229: 街ナビが拾ったページで 1 人の話を 1 件にする ------------------
#
# ⚠⚠ 2026-09-13 依頼者「save1 老人の話が 2 段目から 以降話が続いているが、メモに残っておらず
#   後で見てもわからない ※長尺メッセージの時にうまくとれてない？」
# ★実機の記録では 1 人の話が 3 件に割れ、途中のページは消えていた（#445（★2 段目の途中））。
# ★見本は合成（⚠ 語は実機の話に似せただけ / 濁点の無い字だけで組む）。ページの境で「あくと|うに」が割れる。

PAGE_Y = 19
PAGE1 = ["＊「わしの むすめの タニアを あくと"]
PAGE2 = ["うに つれさられた。", "＊「そこにおる わかものは"]
PAGE3 = ["＊「そこにおる わかものは", "タニアの おっと。"]      # ★送られて 1 行重なる
WHOLE = "＊「わしの むすめの タニアを あくとうに つれさられた。＊「そこにおる わかものはタニアの おっと。"
#: ★0.5 秒おきの読みが見た断片（⚠ 実機ではこれが 1 件目のメモになった）
SAMPLED = "＊「わしの むすめの タニアを あくと"
TAG = {"label": "老", "npc_id": 5, "map_id": 30}


@pytest.fixture(scope="module")
def rev():
    """★文字 → タイル番号（⚠ 同じ絵が複数あるので最初の 1 つ）。"""
    charset = cv._charset()
    assert charset is not None, "⚠ 文字表が読めない（★この検査は空回り）"
    out: dict[str, int] = {}
    for code, ch in charset.table.items():
        out.setdefault(ch, code - sc.PATTERN_BASE)
    return out


def _page(lines, rev, more=False) -> dict:
    """★Lua の `page_snapshot` と同じ形（`y` = 窓の上辺の行 / `hex` = そこから画面の下まで）。

    ★窓の中は「空白の行（濁点の置き場）＋ 字の行」を繰り返す（実機の会話の窓と同じ並び）。
    """
    cols = sc.COLUMNS
    scr = [0x10] * (cols * sc.ROWS)                 # ★窓の外（地図のつもり）
    x0, x1 = 1, 30
    y1 = PAGE_Y + 2 * len(lines) + 1

    def put(x, y, v):
        scr[y * cols + x] = v

    for y in range(PAGE_Y, y1 + 1):
        for x in range(x0, x1 + 1):
            put(x, y, 0x00)                         # ★0x100 = ␣（空白）
    for x in range(x0 + 1, x1):
        put(x, PAGE_Y, win.EDGE_TOP)
        put(x, y1, win.EDGE_BOTTOM)
    for y in range(PAGE_Y + 1, y1):
        put(x0, y, win.EDGE_LEFT)
        put(x1, y, win.EDGE_RIGHT)
    put(x0, PAGE_Y, win.TOP_LEFT)
    put(x1, PAGE_Y, win.TOP_RIGHT)
    put(x0, y1, win.BOTTOM_LEFT)
    put(x1, y1, win.BOTTOM_RIGHT)
    for j, line in enumerate(lines):
        for i, ch in enumerate(line):
            if ch == " ":
                continue
            assert ch in rev, "⚠ 文字表に無い字で見本を組んだ: %r" % ch
            put(x0 + 1 + i, PAGE_Y + 2 + 2 * j, rev[ch])
    if more:
        put(x1 - 1, y1 - 1, 0x73)                   # ★▼（⚠ 本文には入らない）
    return {"y": PAGE_Y, "hex": "".join("%02X" % t for t in scr[PAGE_Y * cols:])}


class _NavVM(_VM):
    """★`_flush_talk` / `note_conversation` ＋ 街ナビの状態（⚠ 画面も FCEUX も要らない）。"""

    _nav_pages_used = None
    _take_nav_pages = Dq3ViewModel._take_nav_pages
    _nav_talk_running = Dq3ViewModel._nav_talk_running
    note_conversation = Dq3ViewModel.note_conversation
    _flush_talk = Dq3ViewModel._flush_talk

    def __init__(self, tag, nav, screen=None):
        super().__init__(tag)
        self.nav = nav
        self.screen = screen or []

    def nav_status(self):
        return self.nav

    def in_battle(self):
        return False

    def _screen_tiles(self):
        return self.screen


def _pages(rev):
    return [_page(PAGE1, rev, more=True), _page(PAGE2, rev, more=True), _page(PAGE3, rev)]


def _done(pages, seq=7):
    return {"seq": seq, "talk_frame": 1200, "active": False, "phase": "done",
            "reason": "talk_done", "talk_pages": pages}


def test_ページの文はページの境でつながる(rev):
    """★読み方は今と同じ（`dq3rom.window`）。⚠ `＊「` の無い 2 枚目も拾い、送りの重なりは 1 回だけ。"""
    got = cv.text_of_pages(_pages(rev))
    assert got is not None, "⚠ ページが 1 枚も読めない"
    text, digest = got
    assert text == WHOLE, text
    assert "▼" not in text
    assert len(digest) == 16


def test_長い話は街ナビのページで1件にする(rev):
    vm = _NavVM(TAG, _done(_pages(rev)))
    vm._talk, vm._talk_digest = SAMPLED, "d-sampled"
    assert vm._flush_talk() is not None
    assert len(vm.memos) == 1, "⚠⚠ 1 人の話が %d 件に割れた" % len(vm.memos)
    text, kw = vm.memos[0]
    assert "あくとうに" in text, "⚠⚠ ページの境で切れたまま: %r" % text
    assert "おっと" in text, "⚠⚠ 最後のページが残っていない: %r" % text
    assert vm.last_talk_text == WHOLE, "★聞き込みの台帳（heard）にも全文"
    assert kw["raw_digest"] != "d-sampled", "★指紋はページから"
    assert kw["source"] == "npc_talk" and kw["npc_id"] == 5


def test_同じページは2度使わない(rev):
    vm = _NavVM(TAG, _done(_pages(rev)))
    vm._flush_talk()
    vm._talk, vm._talk_digest = SAMPLED, "d-2"
    vm._flush_talk()
    assert sum("おっと" in t for t, _ in vm.memos) == 1, vm.memos


def test_ページを使わないと断片だけになる(rev, monkeypatch):
    """⚠⚠ 壊す実験: ページを見ない形へ戻すと、依頼者の症状（「…あくと」で切れる）が出る。"""
    monkeypatch.setattr(_NavVM, "_take_nav_pages", lambda self: None)
    vm = _NavVM(TAG, _done(_pages(rev)))
    vm._talk, vm._talk_digest = SAMPLED, "d-sampled"
    vm._flush_talk()
    assert vm.memos and "あくとうに" not in vm.memos[0][0], "⚠ 壊しても通る（★この検査は空回り）"


def test_街ナビが送っている間は割らない(rev):
    """★0.5 秒おきの読みでページが飛び、重ならない断片が見えても、話し終えるまで書かない。"""
    pages = _pages(rev)
    running = {"seq": 7, "talk_frame": 1200, "active": True, "phase": "close", "talk_pages": pages[:1]}
    vm = _NavVM(TAG, running, cv.page_tiles(pages[0]))
    assert vm.note_conversation() is None
    vm.screen = cv.page_tiles(pages[2])            # ⚠ 2 枚目を読み飛ばした（★重ならない）
    assert vm.note_conversation() is None, "⚠⚠ 送っている途中で別の文として書いた（★1 人の話が割れる）"
    vm.screen = []                                 # ★窓が消えた（⚠ 街ナビはまだ B を押している）
    assert vm.note_conversation() is None
    assert vm.memos == []
    vm.nav = _done(pages)                          # ★話し終えた
    assert vm.note_conversation() is not None
    assert len(vm.memos) == 1 and vm.last_talk_text == WHOLE, vm.memos


def test_ページが無ければ今までどおり(rev):
    """★古い Lua / 窓が読めない: `talk_pages` が無い → 画面の読みで書く。"""
    vm = _NavVM(TAG, {"seq": 7, "talk_frame": 1, "active": False, "phase": "done"})
    vm._talk, vm._talk_digest = SAMPLED, "d-sampled"
    vm._flush_talk()
    assert vm.last_talk_text == SAMPLED


def test_手で話した会話はページを使わない(rev):
    """⚠ 聞き込みでない（`talk_tag` なし）ときは、前の聞き込みのページを持ち込まない。"""
    vm = _NavVM(None, _done(_pages(rev)))
    vm._talk, vm._talk_digest = "＊「てで はなした ことば。", "d-hand"
    vm._flush_talk()
    assert len(vm.memos) == 1 and "おっと" not in vm.memos[0][0], vm.memos


# --- ★★ RX3-0272: 送りの途中の 1 枚で濁点が落ちる ------------------------------
#
# ⚠⚠ 2026-09-14 依頼者「ポポタと話した時、聞き込みと通常ヒアリングで濁点の取り方が違う（ホカハマス、ポカパマズ）」
# ★実機（隔離先の save1 で毎フレーム控えた / work/evidence/20260914_200911-talk-marks-poet2）:
#   DQ3 は窓を**1 フレームに 1〜2 行ずつ上へ写して**送る（2 回で字の 1 行ぶん）。
#   ⚠ 途中の 1 枚は、いちばん上の字の行の上が枠 → その行だけ濁点が無い。
#   ★字の行の上は「自分の濁点の行 / 字の行 / 枠」のどれか（⚠ 別の行の濁点は乗らない）。
# ★見本は合成（⚠ 語は作り文 / 濁点・半濁点をどの行にも入れる）。

SCROLL_Y = 18
SCROLL_LINES = ["＊「ぼくは ざんねんだ。", "＊「ごはんを たべたいが", "どこにも ぱんが ない。", "＊「ばあさんに きいてごらん。"]
SCROLL_NEW = ["＊「ぐずぐず しないで", "でかけよう。"]
SCROLL_WHOLE = "".join(SCROLL_LINES + SCROLL_NEW)
_MARK = {"゙": sc.DAKUTEN - sc.PATTERN_BASE, "゚": sc.HANDAKUTEN - sc.PATTERN_BASE}
_WIDTH = 28


def _encode(line, rev):
    """★字の 1 行 → （濁点の行, 字の行）のタイル。★濁点は 1 行上の別のマス（実機と同じ）。"""
    import unicodedata

    marks, chars = [0x00] * _WIDTH, [0x00] * _WIDTH
    for i, ch in enumerate(line):
        if ch == " ":
            continue
        d = unicodedata.normalize("NFD", ch)
        assert d[0] in rev, "⚠ 文字表に無い字で見本を組んだ: %r" % ch
        chars[i] = rev[d[0]]
        if len(d) > 1:
            marks[i] = _MARK[d[1]]
    return marks, chars


def _window(inner) -> dict:
    """★窓の中の行（タイルのまま）を 1 枚に（★Lua の `page_snapshot` と同じ形）。"""
    cols = sc.COLUMNS
    scr = [0x10] * (cols * sc.ROWS)
    x0, x1, y0 = 1, 30, SCROLL_Y
    y1 = y0 + len(inner) + 1

    def put(x, y, v):
        scr[y * cols + x] = v

    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            put(x, y, 0x00)
    for x in range(x0 + 1, x1):
        put(x, y0, win.EDGE_TOP)
        put(x, y1, win.EDGE_BOTTOM)
    for y in range(y0 + 1, y1):
        put(x0, y, win.EDGE_LEFT)
        put(x1, y, win.EDGE_RIGHT)
    put(x0, y0, win.TOP_LEFT)
    put(x1, y0, win.TOP_RIGHT)
    put(x0, y1, win.BOTTOM_LEFT)
    put(x1, y1, win.BOTTOM_RIGHT)
    for j, row in enumerate(inner):
        for i, v in enumerate(row):
            put(x0 + 1 + i, y0 + 1 + j, v)
    return {"y": y0, "hex": "".join("%02X" % t for t in scr[y0 * cols:])}


def _scrolled_pages(rev):
    """★DQ3 の送りを真似る: 上から 1 行ずつ下の行を写す × 2 回 → 空いた 2 行へ次の行を打つ。

    ⚠ 途中の 1 行ごとに 1 枚ずつ残す（★街ナビが残しうる途中の 1 枚を全部含む = いちばん厳しい並び）。
    """
    rows = []
    for line in SCROLL_LINES:
        rows += list(_encode(line, rev))
    pages = [_window(rows)]
    for new in SCROLL_NEW:
        for _pass in range(2):
            for r in range(len(rows)):
                rows[r] = list(rows[r + 1]) if r + 1 < len(rows) else [0x00] * _WIDTH
                pages.append(_window(rows))
        rows[-2], rows[-1] = _encode(new, rev)
        pages.append(_window(rows))
    return pages


def test_送りの途中のページでも濁点を落とさない(rev):
    pages = _scrolled_pages(rev)
    texts = [cv.page_text(cv.page_tiles(p)) or "" for p in pages]
    # ★見本が症状を含んでいること（⚠ 含まなければこの検査は空回り）
    assert any(t.startswith("＊「ほくは") for t in texts), "⚠ 見本に「上の行の濁点が無い 1 枚」が無い"
    assert any(t.startswith("＊「こはんを") for t in texts), "⚠ 見本に 2 行目が上に来た途中の 1 枚が無い"
    got = cv.text_of_pages(pages)
    assert got is not None
    assert got[0] == SCROLL_WHOLE, "⚠⚠ 濁点が落ちた（★聞き込みの「ホカハマス」）: %r" % got[0]


def _dq3_frames(rev):
    """★DQ3 の窓の 1 フレームごと（★実機 f0176〜f0188 / f0448〜f0500 の並び）。

    ```text
    送り  上の 1 行 → 2 行ずつ → いちばん下を空ける（★これを 2 回で字の 1 行ぶん）
    打つ  1 字ずつ（★濁点のマス → 字のマスの順）
    ```

    ⚠⚠ 行を打ち終えたら**すぐ**送る（★止まるのはページの終わりの ▼ だけ / 実機 f0459 → f0460）。
      → 打ち終えた行を含む最初の 1 枚は、もう送りの途中（上の行の濁点が無い）。
      ⚠ 打ち終えてから止まる見本では、この 1 枚がつなぎの「前」にならず、古いつなぎでも通ってしまった。
    """
    rows = []
    for line in SCROLL_LINES[:-1]:
        rows += [list(r) for r in _encode(line, rev)]
    rows += [[0x00] * _WIDTH, [0x00] * _WIDTH]
    n = len(rows)
    frames = [[list(r) for r in rows]] * 8                # ★前のページの B のあと（★ここから打つ）
    chunks = [[0]] + [list(range(i, min(i + 2, n))) for i in range(1, n, 2)]

    def type_line(line):
        marks, chars = _encode(line, rev)
        for i in range(_WIDTH):
            for row, tiles in ((n - 2, marks), (n - 1, chars)):
                if tiles[i]:
                    rows[row][i] = tiles[i]
                    frames.append([list(r) for r in rows])

    type_line(SCROLL_LINES[-1])
    for new in SCROLL_NEW:
        for _pass in range(2):
            for chunk in chunks:
                for r in chunk:
                    rows[r] = list(rows[r + 1]) if r + 1 < n else [0x00] * _WIDTH
                frames.append([list(r) for r in rows])
        type_line(new)
    frames += [[list(r) for r in rows]] * 8              # ★ページの終わり（▼ を待つ）
    return frames


def _nav_pages(frames, offset):
    """★nav_v0 の拾い方: 4 フレームおきに見て、空白でない字が書き換わったら前の 1 枚を残す（★窓が消えたら最後の 1 枚も）。"""
    kept, prev = [], None
    for f, rows in enumerate(frames + [None]):
        if rows is not None and f % 4 != offset:
            continue
        if prev is not None and (rows is None or any(a != 0x00 and a != b
                                                     for ra, rb in zip(prev, rows) for a, b in zip(ra, rb))):
            if not kept or kept[-1] != prev:
                kept.append(prev)
        prev = rows
    return [_window(r) for r in kept]


@pytest.mark.parametrize("offset", range(4))
def test_街ナビの拾い方でも濁点を落とさない(rev, offset):
    """⚠⚠ 実機では、残すページは 4 フレームおき → 濁点を採った途中の 1 枚が残らないことがある（★ずらし 0〜3 全部）。"""
    got = cv.text_of_pages(_nav_pages(_dq3_frames(rev), offset))
    assert got is not None
    assert got[0] == SCROLL_WHOLE, "⚠⚠ 濁点が落ちた（ずらし %d）: %r" % (offset, got[0])


def test_街ナビの見本は濁点の無いページを含む(rev):
    """★見本が症状を含むこと（⚠ 含まなければ上の検査は空回り）。"""
    whole = cv.base_form(SCROLL_WHOLE)
    bare = []
    for offset in range(4):
        for page in _nav_pages(_dq3_frames(rev), offset):
            text = cv.page_text(cv.page_tiles(page)) or ""
            if text and cv.base_form(text) in whole and text not in SCROLL_WHOLE:
                bare.append(text)
    assert bare, "⚠ 残したページに濁点の欠けたものが 1 枚も無い"


def test_濁点は1字ずつ採る():
    """★行ごとに多いほうを採ると、もう片方にしか無い濁点を捨てる（RX3-0272）。"""
    assert cv.richer("ホカハマスでの", "ポカパマズての") == "ポカパマズでの"
    assert cv.richer("はしょ", "ばしょ") == "ばしょ"
    assert cv.richer("ばしょ", "はしょ") == "ばしょ"
    assert cv.richer("あいう", "かきく") == "あいう", "⚠ 違う文は字を混ぜない（★今までどおり多いほう）"


def test_含まれるページからも濁点を採る():
    """★前のページ（送りの途中 = 濁点が無い）に丸ごと含まれる次のページが、濁点を持っている。"""
    assert cv.join_continuation("＊「ほくは ざんねんた。＊「こはんを", "＊「ぼくは ざんねんだ。") == \
        "＊「ぼくは ざんねんだ。＊「こはんを"


def test_形の違うページは読まない():
    assert cv.page_tiles({"y": 40, "hex": "00"}) is None
    assert cv.page_tiles({"y": 19, "hex": "ZZ"}) is None
    assert cv.page_tiles({"y": 19, "hex": "0"}) is None
    assert cv.page_tiles({"y": 29, "hex": "00" * 64}) is None      # ⚠ 画面の下を越える
    assert cv.text_of_pages("not a list") is None
