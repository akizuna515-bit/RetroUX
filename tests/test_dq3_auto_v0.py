"""Auto 戦闘 v0 を実機なしで動かす（RX3-0015 / 2026-08-25）。

★★ ここが要 ★★

偽の FCEUX API を置き、**依頼者が遊んで作った戦闘中のセーブステートの画面**を
そのまま食わせる。⚠ 実機を起動せずに「本物の画面で動くか」を見られる。

見張っているのは、指示書 §2.6「**不明なら入力しない**」が守れているか。

- 戦闘コマンド待ちでなければ押さない（★ただし止めもしない）
- カーソルが読めなければ押さない
- 画面が読めなければ**止まる**
- ⚠ `joypad.set` に `false` を送らない（送ると人の入力が消える）
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

NEWLINE = chr(10)
ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_auto_v0_test.lua"
TARGET = ROOT / "dq3" / "phase0" / "auto_v0.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"
#: ⚠⚠ 2026-09-17（RX3-0280）: ここは `tools/fceux/fcs/DQ3_J.fc2` を**番号で名指し**していた（★依頼者の本物のセーブ）。
#:   依頼者が撮り直して fc2 が町の画面になり、足場は「▶ が無い」で落ち、⚠ rc ≠ 0 → skip が 11 件を 10 日間隠した。
#:   → ★`work/test-savestates/` から**中身で**選ぶ（`RX3-0028` / まんたんの足場と同じ）
def _state() -> pathlib.Path:
    from dq3_states import BATTLE_COMMAND, one
    return one(BATTLE_COMMAND)

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
    """★本物の戦闘画面を、Lua が読める形で置く。"""
    from retroux.core.bgmap import savestate as ss

    from dq3.phase0.generate_lua import build, write_lua

    write_lua(build())                                   # ⚠ 生成し忘れ防止
    (SANDBOX / "dq3-probe").mkdir(parents=True, exist_ok=True)
    (SANDBOX / "dq3-probe" / "auto_v0.log").write_text("", encoding="utf-8")
    from dq3rom import ppu

    state = ss.load(_state())
    # ★画面と RAM は**同じセーブステート**から取る。
    #   ⚠ 別々にすると、名前が食い違って「誰の手番か」が決まらない（実際に踏んだ）。
    ram = state.chunks["RAM"]
    (SANDBOX / "dq3-probe" / "ram.txt").write_text(
        "\n".join(f"{0x0700 + i:04X} {ram[0x0700 + i]:02X}"
                  for i in range(0x100)) + "\n", encoding="utf-8")
    # ★スクロールを反映した画面（⚠ 生の 1 面では、スクロールしたセーブで ▶ の位置がずれる / まんたんの足場と同じ）
    nt = ppu.screen_of(state.chunks)
    lines = [" ".join(f"{b:02X}" for b in nt[y * 32:(y + 1) * 32])
             for y in range(30)]
    (SANDBOX / "dq3-probe" / "nametable.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    # ★★ 実機で撮った「ぼうぎょ が無い」窓（RX3-0020 / 2026-08-30）。
    #   ⚠ 合成ではなく**ゲームが実際に描いた並び**を使う。
    #   ★中身は `tests/data/` に置いてある（⚠ `work/` は Git 管理外なので、
    #     そこを読むと**まっさらな環境で黙って skip** になる）。
    real = ROOT / "tests" / "data" / "dq3_battle_no_defend.txt"
    rows = [ln for ln in real.read_text(encoding="utf-8").splitlines()
            if ln and not ln.startswith("#")]
    assert len(rows) == 30, "⚠ 実データが 30 行ではない: %d" % len(rows)
    (SANDBOX / "dq3-probe" / "no_defend.txt").write_text(
        NEWLINE.join(rows) + NEWLINE, encoding="utf-8")


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
    # ⚠⚠ RX3-0280: 「rc ≠ 0 → skip」は 11 件を 10 日間隠した。★セーブが無いときは `_state()` がその場で赤にする
    assert done.returncode == 0, "⚠⚠ 足場が落ちました（★skip にしない / RX3-0280）" + chr(10) + both[-1500:]
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, f"⚠ 最後まで行っていません\n{result}"


def test_OKが全部出ている(result):
    count = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert count >= 39, f"⚠ OK が {count} 件しかありません\n{result}"


def test_ログに行動が残る(result):
    """★あとで解析に使う（指示書 §7）。⚠ ログのために複雑にはしない。"""
    log = (SANDBOX / "dq3-probe" / "auto_v0.log").read_text(encoding="utf-8")
    # ⚠⚠ 2026-09-24（RX3-0429 / P-17）: `turn=` は**本当のターン数**になり、
    #   ★行動の通し番号は `act=` へ移しました（⚠ 以前は turn= が通し番号でした）。
    assert "AUTO_V0 turn=1 act=1 slot=p1 action=attack" in log, log
    assert "hp_mp=15/15 7/7" in log, "★行動のログに HP/MP が残っていない"
    assert "AUTO_V0_STOP reason=ppu_unavailable" in log, log


def test_行動の数え直しがfinishに入っている():
    """⚠⚠ 戦闘の終わりで **0 に戻す**（RX3-0153 / 2026-09-10 実測で発覚）。

    ★実測（直す前 / `work/dq3-probe/auto_v0.log`）:

    ```text
    AUTO_V0_DONE 戦闘が終わった（…） turns=8
    AUTO_V0_DONE 戦闘が終わった（…） turns=16   ⚠ 前の戦闘ぶんが乗ったまま
    AUTO_V0_DONE 戦闘が終わった（…） turns=24
    ```

    ⚠ これは**書いてあるか**の検査です（★戦闘の終わりまで動かすには実機が要る）。
      → 実機での確かめは WI RX3-0153 の `依頼者:` にあります。
    """
    src = TARGET.read_text(encoding="utf-8")
    body = src.split("local function finish(")[1].split(NEWLINE + "end")[0]
    assert "rounds=%d actions=%d" in body, "⚠⚠ 終わりの行が旧い書式のまま"
    assert "COUNT.reset()" in body, "⚠⚠ 数え直していない（★戦闘をまたいで増え続ける）"

    # ⚠ 呼んでいるだけでは足りない（★中身が空でも通ってしまう）
    reset = src.split("function COUNT.reset()")[1].split(NEWLINE + "end")[0]
    assert "COUNT.actions, COUNT.rounds, COUNT.last = 0, 0, nil" in reset, (
        "⚠⚠ reset が中身を 0 に戻していない")


def test_行動とターンを同じ規則で畳んでいる():
    """★Lua（`COUNT.add`）と Python（`battle_count.Live`）で**同じ規則**。

    ⚠ 片方だけ直すと静かに食い違います（★教訓「同じ判定を 2 か所に書いて…」）。
    """
    src = TARGET.read_text(encoding="utf-8")
    body = src.split("function COUNT.add(")[1].split(NEWLINE + "end")[0]
    assert "idx <= COUNT.last" in body, "⚠ 区切りの決め方が Python と違う"
    assert "COUNT.rounds = COUNT.rounds + 1" in body

    from dq3 import battle_count as BC
    live = BC.Live()
    for slot in ("p1", "p2", "p3", "p4", "p1"):
        live.feed(slot)
    assert (live.rounds, live.actions) == (2, 5)


def test_設定と生成が食い違わない():
    """⚠ YAML を直したのに生成し忘れる、を防ぐ（★DQ2 と同じ指紋の仕組み）。"""
    from dq3.phase0.generate_lua import MODULE, OUT_DIR, build, write_lua

    before = (OUT_DIR / f"{MODULE}.lua").read_text(encoding="utf-8")
    write_lua(build())
    assert (OUT_DIR / f"{MODULE}.lua").read_text(encoding="utf-8") == before


def test_知らないコマンドは生成の時点で弾く():
    """⚠ 指示書 §2.6「不明なら入力しない」。

    ★黙って attack に落とすと、利用者は「効いている」と勘違いする。
    設定を読んだ**その場で**例外にする。
    """
    from dq3.phase0.generate_lua import GenerateError, _commands

    charset = {0x10B: "あ"}
    with pytest.raises(GenerateError):
        _commands({"p1": {"primary": "item"}}, charset)      # ⚠ 未実装
    with pytest.raises(GenerateError):
        _commands({"p1": {"primary": "ゆうき"}}, charset)     # ⚠ 知らない語
    with pytest.raises(GenerateError):
        _commands({"p1": {"primary": "spell"}}, charset)     # ⚠ 呪文名が無い


def test_どうぐは落とし先の候補にも入れない():
    """★★ RX3-0020（2026-08-30）: **Phase 0 では どうぐ をやらない。**

    ⚠⚠ 「窓に無ければ次の候補へ落とす」を入れたので、★落とし先の表に
    `item` が紛れ込むと、**どうぐ を押して下位メニューで迷子になる**。
    ⚠ 戻り方を知らないので、そこから A を叩き続けることになる。

    ★`COMMAND_TILES` に入っているものだけが候補（⚠ 生成側の弾きと二重）。
    理由は `docs/20-decision-log.md`。
    """
    lua = TARGET.read_text(encoding="utf-8")
    i = lua.index("local COMMAND_TILES = {")
    table = lua[i:lua.index("}", i)]
    assert "MENU.attack" in table and "MENU.defend" in table
    assert "MENU.spell" in table
    assert "MENU.item" not in table, (
        "⚠⚠ どうぐ が候補に入っています（★下位メニューで迷子になります）")
    assert "MENU.flee" not in table, (
        "⚠⚠ にげる が候補に入っています（★勝手に逃げます）")


def test_短い書き方も細かい書き方も受ける():
    """★`p1: attack` と、primary/fallback/min_mp の両方。"""
    from dq3.phase0.generate_lua import _commands

    out = _commands({"p1": "defend"}, {})
    assert out["p1"] == {"primary": "defend", "fallback": "attack",
                         "min_mp": 0, "hp_below": 0}

    out = _commands({"p3": {"primary": "spell", "spell": "あ",
                            "min_mp": 4, "hp_below": 90, "fallback": "defend"}},
                    {0x10B: "あ"})
    assert out["p3"]["min_mp"] == 4
    assert out["p3"]["hp_below"] == 90
    assert out["p3"]["fallback"] == "defend"
    assert out["p3"]["spell_tiles"] == [0x0B]    # ★0x10B - 0x100


def test_HPで切り替わることを動かして確かめている(result):
    """★★ 2026-08-26: 字面から**挙動**へ入れ替えた。

    ⚠ それまでは生成した Lua に `actor.hp * 100 < actor.hp_max * below` が
    入っているかしか見ていなかった。★条件が逆でも・一度も通らなくても緑になる。

    いまは偽の RAM で HP を下げ、**ぼうぎょ の行へ動こうとするか**で見る。
    ⚠ 偽の画面はカーソルが動かないので「決定したか」では見られない。
    ★代わりに「**間違った行で A を押さない**」を見る。これが安全側の性質。
    """
    for line in ("OK HP が満タンなら primary（attack）のまま決定する",
                 "OK HP が 9 割を切ったら fallback（defend）へ向かう",
                 "OK ちょうど満タンは「割った」に入らない（★境目）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_窓に無いコマンドで止まることを動かして確かめている(result):
    """★同上。⚠ 「止まる」だけでなく **1 つも押さない**ことまで見る。"""
    for line in ("OK MP が足りなければ、止まらずに fallback へ（★唱えてから失敗しない）",
                 "OK 窓に無いコマンドは 1 つも押さずに止まる",
                 "OK 止まったあとは 1 つも押さない"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_コマンド窓の印は点滅しない(result):
    """★★ ⚠⚠ 2026-08-30 実機で分かったこと（RX3-0020）。

    ⚠ 「▶ は点滅する」を**画面全部に当てはめたのが誤り**だった。
    `work/dq3-probe/ppu_trace.txt` を数え直すと、はっきり分かれる::

        $2289 (9,20)   72×24 / 00×20  ★点滅している（呪文の一覧）
        $228D (13,20)  72×16 / 00×16  ★点滅している（対象）
        $22C5 (5,22)   72× 1 / 00× 0  ⚠⚠ 点いたきり（コマンド窓）

    ★点滅するのは**下位のメニュー**だけ。コマンド窓の ▶ は
    「いまここ」の目印として置きっぱなしになる。

    ⚠⚠ ここを点滅で探した版は、実機で **4 手番だけ動いて止まった**
    （★窓の描き直しがたまたま 72→00→72 に見えていただけ）。
    ⚠ 足場が ▶ を点滅させていたので、検査は緑のままだった。

    → ★コマンド窓は「**右にコマンドの語がある ▶**」で見つける。
      ⚠ 敵の窓の ▶ は右が敵の名前なので外れる。
    """
    for line in ("OK コマンド窓の静止した ▶ で決められる（★実測 $22C5 は 72 が 1 回だけ）",
                 "OK 静止した ▶ を本物としない（★点滅しているものだけを見る）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_窓に無いコマンドはfallbackへ落とす(result):
    """★★ `command_missing:p4=defend` の正体（RX3-0020 / 2026-08-30）。

    ⚠⚠ **「ぼうぎょ」は窓に無いことがある。**

    実機で撮った戦闘画面 123 枚（`work/dq3-probe/auto_v0_screens.txt`）の
    うち、窓が描き終わっている 24 枚を数えると::

        19 枚  たたかう / じゅもん / にげる / どうぐ   ⚠⚠ ぼうぎょ が無い
         4 枚  たたかう / にげる / ぼうぎょ / どうぐ   ★呪文を覚える前
         1 枚  たたかう / じゅもん / ぼうぎょ / どうぐ

    ★出るのは使えるコマンドだけ（実測 3〜4 項目）。⚠ 候補が 5 つになると
    **ぼうぎょ が押し出される**。

    → ⚠ 止まるのではなく `fallback` → `primary` の順に落とす。
      ★ただし**黙って**変えない（記録に理由を残す）。
    """
    for line in ("OK ぼうぎょ が窓に無ければ fallback へ落とす（★止まらない・記録に残る）",
                 "OK 落とし先まで窓に無ければ、1 つも押さずに止まる"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_2列の一覧でも目当ての呪文まで辿り着く(result):
    """★★ RX3-0020（2026-08-30）: ⚠ 呪文の一覧は **2 列**ある。

    実測（`work/dq3-probe/ppu_trace.txt`）。同じ y=20 の行に::

        $2289 = (9,20)   ★左の列
        $228D = (13,20)  ★右の列

    ⚠ 縦にしか動かさない実装だと、右の列の呪文は**永久に決まらない**。

    ⚠⚠ **足場のカーソルが動かなかったので、これが見えなかった。**
    ★十字キーで動くようにして、「辿り着いて決められるか」まで見る
    （⚠ それまでは「どちらへ動こうとしたか」しか見ていなかった）。
    """
    for line in ("OK 2 列の一覧でも、横に動いて目当ての呪文まで辿り着ける",
                 "OK じゅもん → 呪文 → 対象 の 3 段を通り切る"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_画面が動かないまま押し続けない(result):
    """⚠⚠ 実機で呪文が決まらなかったとき、これが起きていたはず。

    ★歯止め（`screen_frozen`）は**あった**。⚠ ただし上限 600 は
    「変わらなかった**回数**」で、間隔をあけて押すぶん実フレームはずっと多い。

        ★実測: 1,193 フレーム（約 20 秒）

    ⚠⚠ 2026-08-30（RX3-0020）: **5,409 → 1,193 に縮んだ。**
      ★`digest` がカーソルを数に入れなくなったため。
      ⚠ 以前は点滅で digest が毎回変わり、**実機ではこの歯止めが
        1 度も効いていなかった**（★足場だけが緑だった）。

    ⚠ 20 秒ボタンを押し続けるのは長い。★ただし**間違ったボタンは押さない**ので
    危険ではない。短くするかは、実機で確かめてから決める。
    """
    assert "OK 押しても画面が変わらなければ止まる（★永久に押し続けない）" in result, result
    assert "★実測: 画面が動かないと" in result, "⚠ 実測値が出ていません"

def test_ターボになることを動かして確かめている(result):
    """★依頼者「ターボ化」（2026-08-26）／「T でターボ戦闘オンオフ」（08-27）。

    ⚠ Lua から出せるのは **normal と turbo だけ**。★150% や 200% のような段階は
    メニューの `WM_COMMAND` が要る（`docs/research/fceux-speed-control.md`）。

    ⚠⚠ **止まったときに戻すこと**が要。★ターボのままだと人が操作できない。
    """
    for line in ("OK A で ON にすると同時にターボになる",
                 "OK A で OFF にすると普通の速さに戻る",
                 "OK 止まったら普通の速さに戻す",
                 "OK T でターボになる",
                 "OK もう一度 T で普通の速さに戻る"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_キーはDQ2に合わせる():
    """★★ 依頼者「DQ2 のキーバインドで動くようにしよう」（2026-08-27）。

    ⚠⚠ **`Q` は使えない。** FCEUX の「ムービーの読み取り専用切替」に予約済み
    （`retroux/config/default_keybindings.yaml`）。

    ★NES の A ボタンは **`F`**（2026-08-01 実機確認）なので、
    キーボードの `A` は空いている。
    """
    lua = TARGET.read_text(encoding="utf-8")
    assert 'edge("Q")' not in lua, (
        "⚠⚠ Q に戻っています（★FCEUX が予約済みで効きません）")
    assert "KEY_AUTO" in lua and "KEY_TURBO" in lua, "⚠ キーが直書きに戻っている"

    import yaml
    cfg = yaml.safe_load(
        (ROOT / "config" / "dq3_phase0.yaml").read_text(encoding="utf-8"))
    keys = cfg["dq3_phase0"]["keys"]
    assert keys["toggle_auto"] == "A", keys
    assert keys["toggle_turbo"] == "T", keys
    assert keys["mantan"] == "M", keys


def test_ターボは設定で切れる():
    """⚠ 戦闘を目で追いたい人もいる。★決め打ちにしない。"""
    import yaml

    text = (ROOT / "config" / "dq3_phase0.yaml").read_text(encoding="utf-8")
    assert "turbo_with_auto" in text, "⚠ 設定に出ていない"
    cfg = yaml.safe_load(text)
    auto = cfg["dq3_phase0"]["auto_battle"]
    assert auto["turbo_with_auto"] is True
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert "AUTO.turbo_with_auto ~= false" in lua, (
        "⚠ 設定を読んでいない（★決め打ちになっています）")

def test_勝利のあとの画面でも送る(result):
    """⚠⚠ 依頼者（2026-08-27）:

        「8 ゴールドを手に入れたあと、みんなの G と経験値を表示したところで止まった」

    ★セーブ 0 を調べたら、こちらの見立てが **2 つとも外れていた**::

        $62 = 2          ⚠ 「255 か 0」ではない（★戦闘の段階を持つ）
        ▼ (0x73) = 0 個  ⚠⚠ 継続矢印は出ていない

    ⚠ ▼ を待って永久に止まっていた。
    ★戦闘中（`$62` が 0 でない）で画面が止まっていれば、▼ が無くても A を送る。
    ⚠ `$62` が 0 でないので、A でフィールドのメニューは開かない（★安全の根拠）。
    """
    for line in ("OK ▼ が出ていれば A で送る（★レベルアップもこれで通る）",
                 "OK ▼ が無くても、戦闘中で画面が止まっていれば A を送る",
                 "OK 送っても進まなければ ",
                 "OK フィールドに戻ったら 1 つも押さない（★実機で 40 回叩いた）",
                 "OK フィールドに戻ったら普通に終わる"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_戦闘の外かどうかはDQ3自身の段階で見る():
    """★★ 戦闘の外（フィールド）に出たかは、DQ3 自身の段階で見る（RX3-0166）。

    ⚠⚠ 歴史（★どちらも実機で外れた）::

        2026-08-27  `$62` で判断 → フィールドで A を 40 回叩いた（★`$62` は 1〜7 / FF が残る）
        2026-09-11  画面のマス数 → 建物の中が 200〜400 マスで「戦闘」（RX3-0157 / RX3-0165）

    ★いまは `battle_state.lua` の段階（NONE / EXITING なら戦闘の外）。
    ⚠ 動く検査は `research/probes/active/dq3_auto_v0_test.lua`（5b / 5d）。ここは配線だけ。
    """
    lua = TARGET.read_text(encoding="utf-8")
    assert "memory.readbyte(0x62)" not in lua, "⚠⚠ `$62` で戦闘を見ています（★RX3-0165 で外れた）"
    assert "FIELD_TILES" not in lua and "count_tiles(" not in lua, (
        "⚠⚠ 画面のマス数で戦闘の外を見ています（★建物の中が戦闘になる）")
    body = lua[lua.index('if attack_y == nil then'):]
    assert 'ph == "NONE" or ph == "EXITING"' in body, "⚠ 段階で戦闘の外を見ていない"
    assert body.index('ph == "NONE" or ph == "EXITING"') < body.index("find_more"), (
        "⚠⚠ 戦闘の外の判定が後回しです（★先に押してしまいます）")


def test_送りすぎない():
    """⚠⚠ 実機で **40 回**叩いた。★数回で止めること。"""
    lua = TARGET.read_text(encoding="utf-8")
    assert "OUTRO_MAX_POKES" in lua, "⚠ 上限が無い（★永遠に押します）"
    assert "outro_max_pokes or 6" in lua, (
        "⚠⚠ 上限が 6 ではありません（★40 で実機を荒らしました）")
    assert "outro_stuck" in lua, "⚠ 進まないときに止まる道が無い"
