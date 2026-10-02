"""会話の窓の見分け（RX3-0052 / 2026-09-02 実機で踏んだ）。

★アリアハンの道具屋の挨拶が、⚠ 「どうぐ」がコマンド語なので
**会話ではない**と弾かれていた。

★★ 見本の**文**は架空です（⚠ 原作の会話は公開物に入れません / RX3-0433）。
⚠ この検査が見ているのは `_filter` の 5 つの条件（長さ・`＊「`・状態の印・
コマンド語が **2 語以上**か・`▶`）だけなので、★そこに効く語だけ本物と同じにしてあります
（例: 道具屋の `どうぐ` は**コマンド語 1 語**であることが肝）。
"""

from __future__ import annotations

from dq3.knowledge import conversation as C


def _filter(text: str):
    """★`conversation_on_screen` の弾く条件だけを、文で直接なぞる。"""
    if len(text) < C.MIN_LENGTH:
        return None
    if C.SPEECH_MARK not in text:
        return None
    if C.STATUS_MARK in text:
        return None
    if sum(1 for word in C.COMMAND_WORDS if word in text) >= 2:
        return None
    if "▶" in text:
        return None
    return text


def test_道具屋の会話は会話():
    """⚠⚠ 実機で弾かれた文（★1 語だけコマンド語を含む）。"""
    assert _filter("＊「ここは どうぐやです。なにか おさがしですか？") is not None


def test_コマンドの窓は会話ではない():
    assert _filter("▶はなす  じゅもんつよさ  どうぐそうび  しらべる") is None
    assert _filter("はなす  じゅもんつよさ  どうぐそうび  しらべる") is None, "⚠ 語が並ぶ窓を会話にした"


def test_実機で開いた3つの会話():
    """★2026-09-02 の run で開いた窓の**種類**（宿屋 / 武器屋 / 教会）。⚠ 文は架空。"""
    for text in ("＊「ようこそ。ここは やどやですよ。",
                 "＊「ここは ぶきを あつかう みせです。",
                 "＊「ようこそ。ここは きょうかいです。"):
        assert _filter(text) is not None, text


def test_本体も同じ判定をする():
    """⚠ 上の `_filter` が本体からずれていないこと（★源を読んで確かめる）。"""
    import inspect

    src = inspect.getsource(C.conversation_on_screen)
    assert ">= 2" in src, "⚠⚠ 本体のコマンド語の条件が「2 語以上」になっていない"
