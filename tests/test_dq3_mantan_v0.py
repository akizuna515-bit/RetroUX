"""まんたん v0 を実機なしで動かす（RX3-0015 / 2026-08-27）。

★★ ここが要 ★★

依頼者「満タンは HP をチェックして、9 割切ってたら僧侶がホイミ」

⚠⚠ 戦闘の呪文では**推測で書いて 5 回失敗した**。
★今回は依頼者に**普通に回復してもらった記録**から手順を起こしている
（`work/dq3-probe/battle_record.txt` の f=221601-222024）。

## ⚠ ここで固定すること

- 想定の窓が出ていなければ**押さない**
- 全員回復済みなら**何もせず終わる**
- MP が足りなければ**何もせず終わる**
- ⚠ 窓が出なければ**止まる**（★押し続けない）
- ⚠ 止まったあとは 1 つも押さない
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_mantan_v0_test.lua"
TARGET = ROOT / "dq3" / "phase0" / "mantan_v0.lua"
#: ★押す仕組みと速度は共有部分へ移した（RX3-0018 / 2026-08-29）
CORE = ROOT / "dq3" / "phase0" / "core.lua"
DEV = ROOT / "dq3" / "phase0" / "dev.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"
#: ★★ フィールドのコマンド窓が写っているセーブ（⚠ **中身で選ぶ**）。
#:
#:   ## ⚠⚠ 2026-08-31: ここだけ番号で名指ししていました
#:
#:     ★`DQ3_J.fc9` と書いてあり、依頼者がそこへ戦闘の終わり際を
#:     撮り直した瞬間に **15 件がまとめて落ちました**。
#:     ⚠ `RX3-0028` で番号をやめたはずが、このファイルだけ残っていました。
def _state():
    from dq3_states import FIELD_MENU_PLAIN, one
    # ★RX3-0280: コマンド窓の枠がそろった画面だけ（⚠ 呪文の窓まで開いた fc1 では A で窓が出ても見つからない）
    return one(FIELD_MENU_PLAIN)

def _sandbox() -> pathlib.Path:
    """★走行ごとの隔離先（`conftest.py` が決める）。"""
    got = os.environ.get("RETROUX_TEST_SANDBOX")
    return pathlib.Path(got) if got else (
        ROOT / "work" / "_test_sandbox")

# ⚠ 隔離先は**走行ごとに変わる**（RX-0114 / 2026-08-30）。
#   ★`conftest.py` が `RETROUX_TEST_SANDBOX` を立てる。
#   ⚠ 直書きすると、並列で走ったとき隣の走行の書いたものを読む。
SANDBOX = _sandbox() / "work"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists()
         and TARGET.exists()),
    reason="Lua が無い")


def _prepare() -> None:
    """★本物のフィールド画面を、Lua が読める形で置く。

    ⚠ **スクロールを反映した画面**を渡す（`dq3rom/ppu.py`）。
    ★生のネームテーブル 1 枚では、折り返した窓を取り落とす。
    """
    from retroux.core.bgmap import savestate as ss

    from dq3.phase0.generate_lua import build, write_lua
    from dq3rom import ppu

    write_lua(build())                                   # ⚠ 生成し忘れ防止
    (SANDBOX / "dq3-probe").mkdir(parents=True, exist_ok=True)
    (SANDBOX / "dq3-probe" / "mantan_v0.log").write_text("", encoding="utf-8")

    chunks = ss.load(_state()).chunks
    ram = chunks["RAM"]
    (SANDBOX / "dq3-probe" / "field_ram.txt").write_text(
        "\n".join(f"{0x0700 + i:04X} {ram[0x0700 + i]:02X}"
                  for i in range(0x100)) + "\n", encoding="utf-8")

    # ★★ そのセーブの**本当のスクロール**を渡す（⚠ 数値を足場に直書きしない）
    #
    #   ⚠⚠ 足場は `48, 32` と書いてありました。★昔の `fc9` で測った値です。
    #     セーブが変わると窓の位置がずれ、⚠ 「(6,2) で見つけていない」で
    #     15 件がまとめて落ちました（2026-08-31）。
    sc = ppu.scroll_of(chunks)
    (SANDBOX / "dq3-probe" / "field_scroll.txt").write_text(
        "%d %d %d" % (sc.x, sc.y, sc.nametable) + chr(10), encoding="utf-8")

    screen = ppu.screen_of(chunks)
    lines = [" ".join(f"{b:02X}" for b in screen[y * 32:(y + 1) * 32])
             for y in range(30)]
    (SANDBOX / "dq3-probe" / "field_nametable.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    # ⚠⚠ **生の 2 面ぶん**も渡す（★スクロールしていても窓を見つけられるか）。
    #   実機ではここで詰まった: 窓の位置は「画面」の座標なので、
    #   生のネームテーブルをそのまま見ると**永久に見つからない**。
    ntar = bytes(chunks["NTAR"])
    (SANDBOX / "dq3-probe" / "field_ntar.txt").write_text(
        chr(10).join(ntar[i:i + 32].hex(" ") for i in range(0, 2048, 32))
        + chr(10), encoding="utf-8")


@pytest.fixture(scope="module")
def result() -> str:
    _prepare()
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    # ⚠⚠ 2026-09-07（RX-0135）〜 09-17（RX3-0280）: ここが「rc ≠ 0 → skip（セーブが無い）」だった。
    #   ★実際はセーブは選べていて足場が 3) で落ちていたのに、16 件が skip = 緑に見えた（10 日間）。
    #   → ★セーブが無いときは `_state()`（`dq3_states.one`）が**その場で赤**にする。ここでは落ちたら落ちたと言う。
    assert done.returncode == 0, "⚠⚠ 足場が落ちました（★skip にしない / RX3-0280）" + chr(10) + both[-1500:]
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, f"⚠ 最後まで行っていません\n{result}"


def test_OKが全部出ている(result):
    """⚠ 途中で静かに減っていないか。"""
    count = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert count >= 20, f"⚠ OK が {count} 件しかありません\n{result}"


def test_戦闘中は押さずに待つ(result):
    """★RX3-0164（2026-09-17）: 判定は battle_state（$32 == $FD かつ $60B7 & $20 / RX3-0166）。"""
    for line in ("OK ★RX3-0164 戦闘中に M を押しても何も押さず、待つ",
                 "OK ★RX3-0164 実行中に戦闘へ入ったら、押さずに待つ（止めない）"):
        assert line in result, "⚠ " + line + " が出ていません\n" + result[-1500:]


def test_要らないときは1つも押さない(result):
    """★★ ここが安全側の要。

    ⚠ 「とりあえず開いてみる」をやらせない。
    """
    for line in ("OK 既定は OFF で、ボタンを 1 つも押さない",
                 "OK 全員回復済みなら、1 つも押さずに終わる",
                 "OK MP が足りなければ、1 つも押さずに終わる"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_窓が無ければ押さないし止まる(result):
    """⚠⚠ 戦闘で 5 回失敗した教訓。★想定の画面でなければ手を出さない。"""
    for line in ("OK 窓が無いときは、開けようとする A 以外を押さない",
                 "OK 窓が出なければ止まる（★押し続けない）",
                 "OK 止まったあとは 1 つも押さない"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_画面が読めなければ止まる(result):
    assert "OK 画面が読めなければ止まる" in result, result


def test_僧侶が居なければ止まる(result):
    assert "OK 僧侶が居なければ止まる" in result, result


def test_設定と生成が食い違わない():
    """⚠ YAML を直したのに生成し忘れる、を防ぐ。"""
    from dq3.phase0.generate_lua import MODULE, OUT_DIR, build, write_lua

    before = (OUT_DIR / f"{MODULE}.lua").read_text(encoding="utf-8")
    write_lua(build())
    assert (OUT_DIR / f"{MODULE}.lua").read_text(encoding="utf-8") == before


def test_呪文名がタイル列になっている():
    """⚠ 名前のまま渡すと画面と比べられない。

    ★ホイミ = `50 3E 52`（実測 / `battle_record.txt` の f=221718）。
    """
    from dq3.phase0.generate_lua import build

    data = build()
    assert data["mantan"]["spell_tiles"] == [0x50, 0x3E, 0x52]


def test_まひを治す呪文と道具の並び():
    """★RX3-0252（依頼者「save7 まひを満タンで直したい。まんげつそう or キアリク」）。

    ★キアリク = `41 3D 32 42`（⚠ キアリー `41 3D 32 7F` と 4 文字目だけ違う）/
      まんげつそう = `29 38 13 1C 19 0D` / 道具番号 108（ROM の名前表）。
    ⚠ 並びが無いと Lua は押さずに止まる（`spell_tiles_missing` / `item:words_missing`）。
    """
    from dq3.phase0.generate_lua import build

    m = build()["mantan"]
    assert m["spell_tiles_by_id"][53] == [0x41, 0x3D, 0x32, 0x42]
    assert m["spell_tiles_by_id"][52] == [0x41, 0x3D, 0x32, 0x7F]
    assert m["moon_tiles"] == [0x29, 0x38, 0x13, 0x1C, 0x19, 0x0D]
    assert m["moon_id"] == 108


def test_窓の位置は実測から来ている():
    """⚠ 決め打ちの数字ではなく、**profile が正本**であること。"""
    import json

    profile = json.loads(
        (ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
        .read_text(encoding="utf-8"))
    field = profile["field"]
    assert field["windows"]["command"] == [6, 2]
    assert field["windows"]["caster"] == [10, 4]
    assert field["windows"]["spell"] == [20, 2]
    assert field["windows"]["target"] == [4, 6]
    assert "battle_record" in field["evidence"], "⚠ 根拠が書かれていない"


def test_2列であることが記録されている():
    """⚠⚠ じゅもん へは `right`。★`down` ではない（実測）。"""
    import json

    profile = json.loads(
        (ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
        .read_text(encoding="utf-8"))
    assert "2 列" in profile["field"]["_columns_note"]
    lua = TARGET.read_text(encoding="utf-8")
    assert "2 列" in lua, "⚠ 実装側にも残す（★下だと思って直されないように）"


def test_カーソルが届かなければ止まる(result):
    """⚠⚠ 依頼者「M を押すと、その方向にはなにもいないが連打される」（2026-08-27）。

    ★フィールドでは、その連打が**歩き**になる。⚠ いちばん危ない壊れ方。
    → `move_to` に**押した回数の上限**を入れた。
    """
    for line in ("OK 点滅していれば寄せに行く（★",
                 "OK 届かなければ止まる（★連打しない）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_点滅していないものは押しに行かない(result):
    """★★ 依頼者「カーソルが点滅している、というのを捕まえられない？」（2026-08-27）。

    ⚠ 画面に ▶ は複数出る。★静止した ▶ を本物と勘違いして、何も進まなかった。
    → **点滅している 1 つだけ**を本物とみなす形に作り直した。

    ⚠⚠ ここで見るのは 2 つ。**押さない**ことと、**待ち続けない**こと。
    ★片方だけ確かめると、もう片方（永遠に待つ）を見落とす。
    """
    for line in ("OK 点滅しているカーソルが無ければ、方向キーを押さない",
                 "OK 点滅が見つからなければ止まる（★待ち続けない）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_角1マスでは窓と認めない(result):
    """⚠ `0x79` は地形にもある値。★角だけ見ると誤認する。"""
    assert "OK 角 1 マスだけでは窓と認めない（★地形と区別する）" in result, result


def test_実装に上限と横線の判定がある():
    """★消されたら気づきたい 2 つ。"""
    lua = TARGET.read_text(encoding="utf-8")
    assert "MAX_MOVES" in lua, "⚠ カーソルの上限が消えています（★連打に戻ります）"
    assert "cursor_stuck" in lua, "⚠ 届かないときに止まる道が無い"
    assert "EDGE_TOP" in lua, "⚠ 角だけで窓と認めています（★地形と区別できません）"

    assert "cursor_not_blinking" in lua, (
        "⚠⚠ 点滅が無いまま待ち続ける道が残っています")
    assert "no_blink" in lua, (
        "⚠⚠ 点滅切れの勘定を `waited` と共用しています"
        "（★`need_window` が毎フレーム 0 に戻します）")

def test_窓を開けるAは間をあける(result):
    """⚠⚠ 依頼者「話すが選択されてしまう」（2026-08-27）。

    ★A を押しても窓は**すぐ出ない**（実測 25 フレーム / f=221005 → f=221030）。
    ⚠ 間隔が短いと「まだ出ていない」と見て**もう一度 A を押し**、
    その 2 回目が開いたメニューの「はなす」を選んでいた。

    ⚠ この検査は最初「A が 1 回しか押されず」空回りしていた。
    ★**何回押されたか**も一緒に見るようにした（`0 件は通っていないだけ`）。
    """
    assert "OK 窓を開ける A は間をあける" in result, result
    m = re.search(r"間をあける（(\d+) 回 / 最短 (\d+) フレーム）", result)
    assert m, "⚠ 回数と間隔が出ていません" + chr(10) + result
    assert int(m.group(1)) >= 3, "⚠ A が %s 回しか押されていない" % m.group(1)
    assert int(m.group(2)) >= 40, "⚠ 間隔が %s フレームしかない" % m.group(2)


def test_押しは届いたら離す(result):
    """⚠⚠ 依頼者（2026-08-27）:

        「ボタンを反応したレジスタというかメモリもあるとおもうんだよね。
         そこが反応するまで押すとか試験すればめくらうちにならない」

    ★ROM `$CB5F` `STA $14,X` が「新しく押されたボタン」。逆アセンブルに
    最初から映っていたのに、⚠ **固定フレーム数のめくら撃ち**にしていた。

    ⚠ 1 フレーム押しでは A がすり抜けた（実機）。★`$CB16` は
    「NMI を待った直後に 1 回だけ読む」ので、ラグ（実測 25.9%）と
    すれ違うと無かったことになる。

    ⚠⚠ 長く押すのも駄目。`$CB4C` `LDY #$08` で **8 フレームから連射**。
    """
    for line in ("OK 返事が来るまで押し続ける（★",
                 "OK 押しが届かなければ、そう記録する（★黙って進めない）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result
    m = re.search(r"返事が来るまで押し続ける（★(\d+) フレーム）", result)
    assert m, result
    held = int(m.group(1))
    # ★足場は 4 フレーム後に返事をする。⚠ それより短ければめくら撃ち
    assert held >= 4, "⚠⚠ %d フレームしか押していない（★返事を待っていません）" % held
    assert held <= 7, "⚠⚠ %d フレーム押している（★8 で連射に入ります）" % held


def test_実装が入力の受け取りを見ている():
    """★`$14` を見ずに固定フレーム数へ戻ったら赤くする。

    ⚠ 2026-08-29（`RX3-0018`）に、押す仕組みは `core.lua` へ移した。
    ★性質は変わっていないので、**移した先**で見る。
    ⚠ こちらは「ちゃんとそこへ渡しているか」を見る。
    """
    core = CORE.read_text(encoding="utf-8")
    assert "INPUT_NEW" in core, "⚠⚠ 押しが届いたかを見ていません（★めくら撃ちです）"
    assert "0x14" in core, "⚠ 番地が消えています"
    assert "hold_max" in core, "⚠ 押し続ける上限が無い（★連射に入ります）"
    assert "届かなかった" in core, "⚠ 届かないとき黙っています"

    lua = TARGET.read_text(encoding="utf-8")
    assert "BUTTONS.press(ME," in lua, "⚠⚠ 共有の押す仕組みへ渡していません"
    assert "HOLD_MAX" in lua, "⚠ 上限の設定を渡していません"


def test_実装が窓を待つ形になっている():
    """★短い間隔の A が戻っていないこと。"""
    lua = TARGET.read_text(encoding="utf-8")
    assert "press_open" in lua, "⚠ 窓を待つ押し方が消えています"
    assert "OPEN_GAP" in lua, "⚠ 間隔の設定が消えています"
    body = lua[lua.index('if step == "open" then'):]
    body = body[:body.index(chr(10) + "  ---")]
    assert 'press("A")' not in body, (
        "⚠⚠ 短い間隔で A を押し直しています（★「はなす」を選んでしまいます）")

def test_スクロールしていても窓を見つけられる(result):
    """⚠⚠ 2026-08-27 実機で詰まった**本当の原因**。

    窓の位置（`profile` の `field.windows`）は**画面**の座標。
    ★スクロールしていると、生のネームテーブルでは別の場所にある。

        `DQ3_J.fc9`（スクロール 48,32）:
          ★組み立てた画面   (6,2) = 79 77  → 窓
          ⚠ 生のNT0そのまま (6,2) = F5 F5  → 地形

    ⚠ 生のまま読んでいたので窓が**永久に見つからず**、A を押し続け、
    ★開いたメニューで「はなす」が選ばれていた（依頼者の報告どおり）。

    ⚠ 昨日 probe 側では直したのに、**製品側に入れ忘れていた**。
    """
    for line in ("OK 材料はスクロールした面（生のままでは窓が見つからない）",
                 "OK スクロールしていても窓を画面の座標で見つけられる"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_実装が組み立てた画面を読んでいる():
    """★生の面を直接読む形に戻っていないこと。"""
    lua = TARGET.read_text(encoding="utf-8")
    assert "screen_reader.read()" in lua, (
        "⚠⚠ 組み立てた画面を読んでいません（★スクロールで窓を見失います）")
    assert "dq3/phase0/screen.lua" in lua, "⚠ 画面を組み立てる部品を読んでいない"
    assert "ppu.readbyterange" not in lua, (
        "⚠ 生の面を直接読んでいます（★部品に任せる）")

def test_止まったら画面を残す(result):
    """⚠⚠ 2026-08-27: `target_window_missing` で止まったが、

    **何が出ていたのか分からず**、推測で直しかけた。
    ★止まった理由だけでは足りない。そのときの画面をまるごと残す。
    """
    assert "OK 止まったら、そのときの画面をまるごと残す" in result, result


def test_対象は窓ではなく点滅で見る():
    """⚠⚠ 2026-08-27 実機（2 回目）: **窓を待ってはいけなかった**。

    止まったときの画面が答えを持っていた::

        y=10  76 00 72 5B 57 45 49 …   ← x=12 に 72（▶）、右は「エルシト」
              ↑ 窓(10,4) の中

    ⚠ フィールドでは、対象の一覧は**新しい窓ではない**。
    ★「誰の呪文か」を選んだ窓 (10,4) が、そのまま対象の一覧になる。

    ⚠ 「新しい窓が出る」は**戦闘の記録から持ってきた思い込み**だった。
    戦闘は相手が敵なので窓が増えるが、★フィールドは相手が仲間なので使い回す。

    ⚠⚠ この検査は、以前は逆のこと（`seen_windows` で新しい窓を待て）を
    固定していた。★実機で否定されたので**書き換えた**
    （[[project_retroux_stale_claim_pinned_by_test]] と同じ型）。
    """
    lua = TARGET.read_text(encoding="utf-8")
    body = lua[lua.index('if step == "target" then'):]
    body = body[:body.index(chr(10) + "  ---")]
    assert "seen_windows" not in body, (
        "⚠⚠ また新しい窓を待っています（★フィールドでは窓は増えません）")
    assert "track.active()" in body, (
        "⚠⚠ 点滅している ▶ を見ていません（★唯一確かな合図です）")
    assert "target_not_offered" in body, (
        "⚠ ▶ が人を指さないまま待ち続ける道が残っています")
    assert "track.report()" in body, (
        "⚠ どこが点滅していたかを記録していない（★次に詰まったとき何も分かりません）")

def test_始める前に開いた窓を閉じる(result):
    """⚠⚠ 2026-08-27 実測: 前に失敗した状態が**そのまま残っていた**。

    「誰の呪文か」窓が開いたまま、★カーソルが (12,10) にいた。
    ⚠ その状態から始めると、カーソルの位置が想定と全く違う。
    """
    for line in ("OK 開いている窓が無ければ、そのまま始める",
                 "OK 開いたままの窓は B で閉じてから始める"):
        assert any(line in ln for ln in result.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + result)


def test_呪文もカーソルを寄せてから押す():
    """⚠⚠ **ここが最後の詰まりだった。**

    止まったときの画面（`mantan_v0.log`）:

        ホイミ (22,4) / ⚠ カーソル (12,10) = 「誰の呪文か」窓の中

    ★カーソルを寄せずに A を押していたので、「エルシトを選び直す」だけで
    何も進まなかった。⚠ 他の段は寄せていたのに、呪文の段だけ抜けていた。
    """
    lua = TARGET.read_text(encoding="utf-8")
    body = lua[lua.index('if step == "spell" then'):]
    body = body[:body.index(chr(10) + "  ---")]
    assert "move_to(" in body, (
        "⚠⚠ 呪文の段でカーソルを寄せていません（★何も進みません）")
    assert body.index("move_to(") < body.index("press_open"), (
        "⚠ 押してから寄せています（★順序が逆）")

def test_終わるときに窓を閉じて返す():
    """⚠⚠ 2026-08-27 実機: 回復には成功したが、**窓が全部開いたまま**終わった。

    依頼者「最後、俺が A ボタンを押して窓を全部閉じた」。
    ★遊びの続きは人がやるので、**始めた形に戻して**返すのが筋。

    ⚠ 閉じるのは **B**。★A だと、開いている一覧の項目を選んでしまう。
    """
    lua = TARGET.read_text(encoding="utf-8")
    assert 'step = "cleanup"' in lua, "⚠⚠ 窓を開けっぱなしで終わっています"
    body = lua[lua.index('if step == "cleanup" then'):]
    body = body[:body.index(chr(10) + "  if step ==", 10)]
    assert 'press_open("B")' in body, "⚠⚠ A で閉じています（★項目を選んでしまいます）"
    assert "window_corners" in body, "⚠ 窓が消えたかを見ていない"


def test_自分で開けていない窓は閉じない():
    """★★ ⚠⚠ **人の操作を奪わない。**

    人が開けたメニューを見ている最中に M を押されることがある。
    ⚠ そこで勝手に B を叩いたら、★遊んでいる人の操作を横取りすることになる。

    ⚠ 過去に `joypad.set` の後勝ちで**人の入力を消した**ことがある
    （`RX-0088`）。★同じ性質の事故なので、字面でも固定しておく。
    """
    lua = TARGET.read_text(encoding="utf-8")
    assert "we_opened" in lua, (
        "⚠⚠ 自分で開けたかを見ていません（★人の窓まで閉じます）")
    # ★開けた印は `open` 段で立つこと
    body = lua[lua.index('if step == "open" then'):]
    body = body[:body.index(chr(10) + "  ---")]
    assert "we_opened = true" in body, "⚠ 開けた印が `open` 段で立っていない"

def test_ターボのまま返さない(result):
    """★★ 依頼者「いま速度は通常なのでターボでやるようにしたい」（2026-08-27）。

    ⚠⚠ **いちばん危ないのは「ターボのまま返す」こと。**
    ★そうなると人がまともに操作できない。

    ⚠ 終わったときも、止まったときも、M で切ったときも戻すこと。
    ★3 つとも足場で見る（1 つでも漏らすと放置される）。
    """
    for line in ("OK まんたんを始めるとターボになる",
                 "OK 止まったら通常速度へ戻す",
                 "OK M で切ったら通常速度へ戻す",
                 "OK 終わったら通常速度へ戻す"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_速度を戻す道が全部ある():
    """⚠ 出口が 1 つでも漏れると、★ターボのまま放置される。

    ⚠ 2026-08-29（`RX3-0018`）に、閉じるときの出口は `on_exit` になった。
    ★戻し方は `set_speed(false)` と `SPEED.reset()` の 2 通りある
    （⚠ `reset` は手で入れたターボごと戻す。閉じるときはそれが正しい）。
    """
    lua = TARGET.read_text(encoding="utf-8")
    assert "set_speed" in lua, "⚠⚠ 速度を触っていません"
    for where in ("MANTAN_V0_STOP", "MANTAN_V0_DONE", "local function on_exit"):
        i = lua.index(where)
        near = lua[max(0, i - 400):i + 400]
        assert ("set_speed(false)" in near) or ("SPEED.reset()" in near), (
            "⚠⚠ %s の出口で速度を戻していません（★ターボのまま返します）" % where)

    # ★1 本で動かすときも、終わりに必ず戻すこと
    dev = DEV.read_text(encoding="utf-8")
    assert "HOST.speed.reset()" in dev, "⚠⚠ 1 本の側が速度を戻していません"
