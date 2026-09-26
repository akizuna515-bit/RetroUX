"""セーブステートを「番号」ではなく**中身**で選ぶ（RX3-0028 / 2026-08-31）。

## ⚠⚠ なぜ要るか

  ★依頼者はセーブ 5〜9 を作業用に自由に使います（⚠ 当然の使い方）。
  ⚠ ところが検査は `DQ3_J.fc6` を「戦闘の画面」、`fc8` を「技のあとの
  メッセージ」として**名指し**していました。

  → ★2026-08-31 に会話中のセーブを撮ってもらった瞬間、**10 件が落ちました**。

  ⚠⚠ セーブは `tools/` にあり **Git 管理外**です。
  ★「いつでも変わりうるもの」を、不変の資料として名指ししてはいけません。

  （`RX3-0027` の「検査が `work/` の本物を読んでいた」と同じ形です。
   ★「遊ぶ前だけ緑」「撮り直す前だけ緑」。）

## ★使い方

    from dq3_states import pick, BATTLE, CONVERSATION

    @pytest.mark.parametrize("path", pick(BATTLE))
    def test_...(path): ...

## ⚠ 見つからないときの振る舞い

  ★セーブが **1 本も無い**環境（まっさらな clone）… `skip`
  ⚠⚠ セーブはあるが**その種類が無い**            … **赤**

  ⚠ 後者を skip にすると「0 件は通っていないだけ」になります。
"""

from __future__ import annotations

import pathlib

import pytest

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()

#: ★戦闘中（⚠ `$62 = 255`。★`docs/design/dq3-findings.md`）
BATTLE = "battle"
#: ★★ 戦闘の**コマンド待ち**（⚠ 「たたかう」が画面にある）。
#:
#:   ⚠ `BATTLE` だけでは足りません。★下位メニューに入っているセーブ
#:     （`fc3` / `fc4`）はコマンド窓が出ていないので、
#:     「窓が 3 つ」「カーソルは たたかう の行」は成り立ちません。
BATTLE_COMMAND = "battle_command"
#: ★★ 窓が**面をまたいで折り返している**（⚠ 縦スクロールのせい）。
#:
#:   ⚠ ネームテーブル 1 枚をそのまま読むと**見つからない**窓です。
#:   ★`RX3-0016` の最後の穴で、`test_折り返した会話窓が取れる` の材料。
WRAPPED = "wrapped"
#: ★会話の窓が取れる
CONVERSATION = "conversation"
#: ★戦闘でない（町・フィールド）
FIELD = "field"
#: ⚠ スクロールしている（★組み立ての検査に要る）
SCROLLED = "scrolled"
#: ⚠ 左上に**面 1** を映している（★`base` を 0 と決めつけない検査に要る）
NAMETABLE1 = "nametable1"
#: ★★ 戦闘の**終わり際**（⚠ `$62 = 1`）。
#:
#:   ⚠ 敵の HP は全部 0 になり、状態の**2 バイト目**も落ちます。
#:     ★1 バイト目は `$80` のまま残るので、「生きている」をどちらの
#:     バイトで見ているかを、このセーブだけが区別できます。
BATTLE_OVER = "battle_over"

#: ★★ フィールドのコマンド窓が出ている（⚠ 「はなす」がある）。
#:
#:   ⚠⚠ `test_dq3_mantan_v0.py` が `fc9` を**番号で名指し**していて、
#:     ★依頼者が撮り直した瞬間に 15 件が落ちました（2026-08-31）。
#:     `RX3-0028` で番号をやめたはずが、ここだけ残っていました。
FIELD_MENU = "field_menu"
#: ★★ コマンド窓が**それだけ**で出ている（⚠ 下の窓＝呪文・相手の窓が重なっていない / RX3-0280）。
#:
#:   ⚠⚠ 2026-09-17: `FIELD_MENU` の最初の 1 つ（fc1）は呪文の窓まで開いた画面で、コマンド窓の下辺が
#:     別の窓に**上書き**されていた。★まんたんの足場は「A でコマンド窓が出る」画面を前提にするので、
#:     窓の枠が**全部そろっている**セーブだけを選ぶ。
FIELD_MENU_PLAIN = "field_menu_plain"
#: ★コマンド窓の位置（★profile `field.windows.command` と同じ / 幅 12 × 高さ 8）
COMMAND_WINDOW = (6, 2, 12, 8)
#: ★窓の枠のタイル（⚠ 文字表は `dq3rom/profiles/` が正本）
FRAME = {"tl": 0x79, "top": 0x77, "tr": 0x7C, "left": 0x76, "right": 0x7B, "bl": 0x7A, "bottom": 0x7D, "br": 0x7E}

BATTLE_FLAG = 0x62

#: ★「たたかう」の生タイル（⚠ 文字表は `dq3rom/profiles/` が正本）
ATTACK_TILES = (0x1A, 0x1A, 0x10, 0x0D)

#: ★「はなす」の生タイル（⚠ 同上。`field.menu_tiles.talk`）
TALK_TILES = (36, 31, 23)


def _has(tiles, seq) -> bool:
    """★その並びが画面にあるか。"""
    n = len(seq)
    for y in range(30):
        row = tiles[y * 32:(y + 1) * 32]
        for x in range(33 - n):
            if tuple(row[x:x + n]) == seq:
                return True
    return False


def _frame_intact(tiles, x0, y0, w, h) -> bool:
    """★その矩形に窓の枠が**欠けなく**あるか（⚠ ほかの窓が重なると欠ける）。"""
    def t(x, y):
        return tiles[y * 32 + x]
    x1, y1 = x0 + w - 1, y0 + h - 1
    if (t(x0, y0), t(x1, y0), t(x0, y1), t(x1, y1)) != (FRAME["tl"], FRAME["tr"], FRAME["bl"], FRAME["br"]):
        return False
    # ⚠ 上辺は見ない（★DQ3 は上辺に名前を書く: `79 77 77 78 43 51 5A 83 77 …`）。★下辺と両側が欠けていなければよい
    return (all(t(x, y1) == FRAME["bottom"] for x in range(x0 + 1, x1))
            and all(t(x0, y) == FRAME["left"] and t(x1, y) == FRAME["right"] for y in range(y0 + 1, y1)))


def all_states() -> list[pathlib.Path]:
    """★ある DQ3 のセーブ全部（⚠ 番号順）。"""
    return sorted(FCS.glob("DQ3_J.fc[0-9]"))


def kinds_of(path: pathlib.Path) -> set[str]:
    """★そのセーブが何なのかを、**中身から**決める。"""
    from dq3rom import ppu
    from retroux.core.bgmap import savestate as ss

    chunks = ss.load(path).chunks
    scroll = ppu.scroll_of(chunks)
    tiles = ppu.compose(chunks["NTAR"], scroll, ppu.mirroring_of(chunks))

    got = set()
    if chunks["RAM"][BATTLE_FLAG] == 1:
        got.add(BATTLE_OVER)
    if chunks["RAM"][BATTLE_FLAG] == 0xFF:
        got.add(BATTLE)
        if _has(tiles, ATTACK_TILES):
            got.add(BATTLE_COMMAND)
    else:
        got.add(FIELD)
        # ⚠ 戦闘中は敵の窓を会話と読んでしまう（★弾くのは呼ぶ側の仕事）
        from dq3.knowledge.conversation import conversation_on_screen

        if conversation_on_screen(list(tiles)) is not None:
            got.add(CONVERSATION)
    if scroll.x or scroll.y:
        got.add(SCROLLED)
    # ★合成しないと見つからない窓があるか（⚠ 折り返し）
    from dq3rom import window as _win

    per_page = sum(len(_win.find_windows(chunks["NTAR"], base=b))
                   for b in (0, 0x400))
    if len(_win.find_windows(tiles)) > per_page:
        got.add(WRAPPED)
    if _has(tiles, TALK_TILES):
        got.add(FIELD_MENU)
        if _frame_intact(tiles, *COMMAND_WINDOW):
            got.add(FIELD_MENU_PLAIN)
    if scroll.nametable:
        got.add(NAMETABLE1)
    return got


def pick(kind: str, *, at_least: int = 1) -> list[pathlib.Path]:
    """★その種類のセーブを返す。

    ⚠ セーブが 1 本も無ければ `skip`、★あるのに種類が無ければ**赤**。
    """
    every = all_states()
    if not every:
        # ⚠⚠ `allow_module_level` が要る（2026-09-26 / RX3-0431 の公開木で発覚）。
        #   ★`test_dq3_render.py:24` は **module 直下**で `pick()` を呼びます。
        #   ⚠ 素の `skip` だと、そこで「skip ではなく **collection ERROR**」になり、
        #     ★セーブが無いだけの環境が**赤**に見えていました。
        pytest.skip("★DQ3 のセーブステートがありません（⚠ 同梱していません）",
                    allow_module_level=True)
    got = [p for p in every if kind in kinds_of(p)]
    if len(got) < at_least:
        pytest.fail(
            "⚠⚠ `%s` のセーブが %d 本しかありません（★%d 本要る）。%s"
            % (kind, len(got), at_least,
               "★どれかを撮り直してください: "
               + ", ".join(p.name for p in every)))
    return got


def one(kind: str) -> pathlib.Path:
    """★その種類のうち 1 本（⚠ 番号のいちばん若いもの）。"""
    return pick(kind)[0]


def pick_all(*kinds: str, at_least: int = 1) -> list:
    """★**全部の種類に当てはまる**セーブ。

    ## ⚠⚠ なぜ要るか（2026-08-31 に踏んだ）

      ★`WRAPPED`（折り返した窓がある）だけで選ぶと、⚠ **会話とは限りません**。
      依頼者がセーブを撮り直したら、選ばれたのが「パーティの状態の窓が
      折り返しているだけ」の画面になり、★会話を求める検査が落ちました。

      → ⚠ 「折り返していて、**かつ** 会話」と書けるようにします。
    """
    every = all_states()
    if not every:
        # ⚠ `pick()` と同じ理由（★module 直下から呼ばれても skip で止める）。
        pytest.skip("★DQ3 のセーブステートがありません（⚠ 同梱していません）",
                    allow_module_level=True)
    got = [p for p in every if set(kinds) <= kinds_of(p)]
    if len(got) < at_least:
        pytest.fail(
            "⚠⚠ %s を**同時に**満たすセーブが %d 本しかありません（★%d 本要る）。"
            % (" と ".join(kinds), len(got), at_least)
            + "★いまの中身: "
            + " / ".join("%s=%s" % (p.name, sorted(kinds_of(p))) for p in every))
    return got


def one_of(*kinds: str) -> pathlib.Path:
    """★全部の種類に当てはまるセーブを 1 本。"""
    return pick_all(*kinds)[0]
