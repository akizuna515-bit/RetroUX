"""DQ3 の UI 初版（RX3-0019 / 2026-08-29）。

★★ ここで守ること ★★

⚠⚠ **ROM で分かっているだけの情報を、UI へ出さない**（指示書 §10）。

    RetroUX 内部で知っていること  ≠  UI へ出してよいこと

★守り方は「気をつける」ではなく**構造**です。
`dq3/ui/view_model.py` が唯一の関所で、⚠ そこが `world-model.json` を
読んでいないことをここで見ます。

⚠ **勇者メモを UI 専用の文字列リストにしない**（指示書 §8）。
★地点・地図・道具・NPC から**逆引きできる**形であること。

⚠ **戦闘の開始・終了で窓の大きさを変えない**（指示書 §2 / §20）。
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
UI = ROOT / "dq3" / "ui"
VIEW_MODEL = UI / "view_model.py"
MODELS = UI / "models.py"
POPUP = UI / "location_popup.py"
MAIN = UI / "main_window.py"
MAP = UI / "map_window.py"
BATTLE = UI / "battle_window.py"
WRITER = ROOT / "dq3" / "phase0" / "state_writer.lua"
DEV = ROOT / "dq3" / "phase0" / "dev.lua"

pytestmark = pytest.mark.skipif(not UI.is_dir(), reason="UI がまだ無い")


# --- ★データの形（⚠ Qt を使わずに確かめる）----------------------------

def test_勇者メモは逆引きできる形():
    """⚠⚠ **UI 専用の文字列リストにしない**（指示書 §8）。

    ★地点・地図・道具・NPC から引けること。
    """
    from dq3.ui.models import Memo, MemoBook

    book = MemoBook([
        Memo(order=1, text="東の岬に洞窟があるらしい", location_id="leb",
             map_id=9, source="conversation"),
        Memo(order=2, text="老人が盗賊の鍵を持っている", location_id="najimi",
             map_id=12, item_id="thief_key", npc_id="old_man"),
    ])
    assert [m.text for m in book.recent(1)] == ["老人が盗賊の鍵を持っている"]
    assert len(book.of_location("leb")) == 1
    assert len(book.of_map(12)) == 1
    assert len(book.of_item("thief_key")) == 1
    assert len(book.of_npc("old_man")) == 1
    assert book.of_location("どこでもない") == []


def test_メモは生の記録へ戻れる():
    """⚠ 文字にした時点の誤りを、あとから直せること。

    ★DQ3 は濁点が 1 行上のマスにあり、文字コード表はまだ `high-confidence`。
    """
    from dq3.ui.models import Memo

    assert "raw_digest" in {f for f in Memo.__dataclass_fields__}


def test_メモは順番で並ぶ():
    """⚠ 時刻ではなく通し番号（★セーブを戻しても壊れない）。"""
    from dq3.ui.models import Memo, MemoBook

    book = MemoBook([Memo(order=n, text=str(n)) for n in (3, 1, 2)])
    assert [m.text for m in book.recent(3)] == ["3", "2", "1"]


def test_知らない状態は受け付けない():
    from dq3.ui.models import LocationView

    with pytest.raises(ValueError):
        LocationView(location_id="x", knowledge="なにか")


def test_古い記録も読める():
    """⚠ 知らない欄があっても落ちない（★あとから欄が増える）。"""
    from dq3.ui.models import MemoBook

    book = MemoBook.from_dicts([
        {"order": 1, "text": "むかしの記録", "しらない欄": 1}])
    assert len(book) == 1


# --- ⚠⚠ ここが本丸: 知らないことを出さない（指示書 §10）--------------

def test_UIはROMの正解を読まない():
    """⚠⚠ **`world-model.json` を UI 側から読まないこと。**

    ★ROM 解析は、プレイヤーより多くを知っている。
    ⚠ それをそのまま出すと、まだ知らないことを教えてしまう。
    """
    # ⚠ 註釈と説明文には出てくる（★なぜ読まないかを書いてある）。
    #   → 字面ではなく **import と、実際に使う文字列**で見る。
    banned = ("world-model", "world_model", "dq3rom")
    for path in sorted(UI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {id(_docstring_node(n)) for n in ast.walk(tree)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(b in alias.name for b in banned), (
                        "⚠⚠ %s が %s を import している" % (path.name, alias.name))
            elif isinstance(node, ast.ImportFrom):
                assert not any(b in (node.module or "") for b in banned), (
                    "⚠⚠ %s が %s を import している" % (path.name, node.module))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docs:
                    continue          # ★説明文は見逃す
                assert not any(b in node.value for b in banned), (
                    "⚠⚠ %s が ROM の正解を指している: %r"
                    % (path.name, node.value[:60]))


def _docstring_node(node):
    """★その節の説明文（⚠ 無ければ None）。"""
    body = getattr(node, "body", None)
    # ⚠ `IfExp` などは `body` が**式 1 つ**（★並びではない）
    if not isinstance(body, list) or not body:
        return None
    first = body[0]
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return first.value
    return None


def test_訪れていない地点は中身を出さない():
    """⚠⚠ 名前すら出さない（★DQ3 の ROM に地名の平文は無い / RX3-0013）。"""
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel(state_path=ROOT / "work" / "state.json",
                      knowledge_path=ROOT / "存在しない.json")
    view = vm.location_view("aliahan")
    assert view.name is None, "⚠⚠ 訪れていないのに名前を出している"
    assert view.knowledge == "UNKNOWN"
    assert view.memo_count == 0 and view.heard_count == 0
    assert view.highlights == []
    assert view.display_name == "？"


def test_訪れた地点だけを地図に出す(tmp_path):
    """⚠ ROM にある全地点を出さない（指示書 §11）。"""
    from dq3.ui.view_model import Dq3ViewModel

    know = tmp_path / "k.json"
    know.write_text(json.dumps({
        "visited_locations": ["aliahan"],
        "location_names": {"aliahan": "アリアハン", "leb": "レーベ"},
        "memos": [{"order": 1, "text": "宿屋があった", "location_id": "aliahan"}],
        "heard_counts": {"aliahan": 2},
    }, ensure_ascii=False), encoding="utf-8")

    vm = Dq3ViewModel(state_path=ROOT / "work" / "state.json",
                      knowledge_path=know)
    assert vm.known_locations() == ["aliahan"], "⚠ 訪れていない地点が混ざっている"

    seen = vm.location_view("aliahan")
    assert seen.name == "アリアハン" and seen.knowledge == "VISITED"
    assert seen.memo_count == 1 and seen.heard_count == 2
    assert seen.highlights == ["宿屋があった"]

    # ⚠⚠ 名前を**知っていても**、訪れていなければ出さない
    unseen = vm.location_view("leb")
    assert unseen.name is None, "⚠⚠ 訪れていない地点の名前を出している"
    assert unseen.heard_count == 0


def test_関所はview_modelだけ():
    """★`LocationView` を作ってよいのは view_model だけ（⚠ 画面では作らない）。"""
    for path in (POPUP, MAIN, MAP, BATTLE):
        src = path.read_text(encoding="utf-8")
        body = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "LocationView(" not in body, (
            "⚠⚠ %s が LocationView を作っている（★関所を回り込んでいる）"
            % path.name)


# --- ⚠ 窓の大きさを変えない（指示書 §2）--------------------------------

def test_戦闘で窓の大きさを変えない():
    """⚠⚠ 戦闘中だけウィジェットを足すと、★窓が伸びる（DQ2 の知見）。

    ⚠ 2026-08-29（依頼者「下ウィンドウに戦闘モンスターとログを」）で、
    ★戦闘は**別ウィンドウ**へ出した。窓ごと開け閉めしても同じことが起きるので、
    ⚠ **中身を入れ替えるだけ**であることをここで見る。
    """
    src = BATTLE.read_text(encoding="utf-8")
    assert "set_cards([])" in src, "⚠⚠ 戦闘外で中身を空にしていない"
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    for bad in ("resize(", "setFixedHeight(", "hide()", "close()"):
        assert bad not in body.split("def refresh")[-1], (
            "⚠⚠ 戦闘の変わり目で窓を動かしている: %s" % bad)

    # ★本体側も、戦闘のたびにウィジェットを足していないこと
    main = MAIN.read_text(encoding="utf-8")
    assert "BattleMonsterStrip" not in main, (
        "⚠ 戦闘は下の窓が持つ（★本体に戻っている）")


def test_メモの行数で高さを変えない():
    """⚠ 件数が 0 でも場所を確保する（★増減で窓が動かない）。"""
    src = (UI / "memo_panel.py").read_text(encoding="utf-8")
    assert "setFixedHeight(ROW_PX)" in src, "⚠ 行の高さを固定していない"


# --- ★retroux を変更していないこと -------------------------------------

#: ★DQ3 の作業で触ることを**明示して認めた** `retroux/` のファイル（⚠ 理由つき）
#
#   ⚠⚠ ここを増やすときは、必ず「DQ2 の挙動が変わらない」ことを確かめてください。
#     ★`RX3-0011`（DQ3 は dev-only）の前提は `RX3-0431` で反転しましたが、
#     ⚠ 「DQ3 の都合で DQ2 を書き換えない」という歯止め自身は生かします。
ALLOWED_RETROUX_CHANGES = {
    "retroux/core/config/user_config.py": (
        "★`paths.dq3_rom` / `paths.fceux` を足した（RX3-0467 / RX3-0468）。"
        "⚠ `user_config.yaml` の読み手を 1 本に保つため（★別の reader を足すと、"
        "知らない項目として警告が出るか、同じファイルを 2 か所が別々に解釈する）。"
        "⚠ 既定は空文字で、DQ2 の挙動は変わりません"),
    "retroux/version.py": (
        "★`build-info.json` / `source_commit()` / `build_id()` / `stamp()` を足した"
        "（RX3-0464）。⚠ 配布 Runtime には `pyproject.toml` が入らないので、"
        "そこが無いと版が `0.0.0+unknown` になる。⚠⚠ 版の正本は pyproject のまま"
        "（★build-info は pyproject の**後**に読む）。DQ2 の表示は変わりません"),
}


def test_retrouxを変更していない():
    """⚠⚠ DQ3 の都合で DQ2 のコードを書き換えないための歯止め。

    ★`RX3-0011` の前提（DQ3 は dev-only）は `RX3-0431` で反転しましたが、
    ⚠ 「持ち出し」を止める役目は残します。★認めた変更は
    `ALLOWED_RETROUX_CHANGES` に**理由を書いて**並べます。
    """
    done = subprocess.run(
        ["git", "status", "--porcelain", "retroux/"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    changed = []
    for line in (done.stdout or "").splitlines():
        if not line.strip():
            continue
        # ★`git status --porcelain` は先頭 2 文字が状態、3 文字目から道
        path = line[3:].strip().strip('"')
        if path in ALLOWED_RETROUX_CHANGES:
            continue
        changed.append(line)
    assert not changed, (
        "⚠⚠ retroux/ を変更しています（★認めるなら "
        "`ALLOWED_RETROUX_CHANGES` に理由を書く）:\n" + "\n".join(changed))


def test_認めたretroux変更に理由が書いてある():
    """⚠ 許可リストが「とりあえず足す」置き場にならないように。"""
    assert ALLOWED_RETROUX_CHANGES, "★空なら項目を消してください"
    for path, why in ALLOWED_RETROUX_CHANGES.items():
        assert (ROOT / path).is_file(), f"⚠ 認めた道が実在しません: {path}"
        assert len(why) >= 40, f"⚠ 理由が短すぎます: {path}"
        assert "RX" in why, f"⚠ 理由に Work Item 番号がありません: {path}"


def test_使い回した部品をimportしている():
    """★DQ2 の部品を作り直していないこと（指示書 §2）。

    ⚠ ただし `PartyPanel` は**使えなかった**（2026-08-29）。
    ★中身に合わせて広がる表で、右パネルの最小幅を 556px まで押し上げ、
    ⚠ 依頼者の「4 人分の枠を固定 / MAX は 3 桁」にも合わない。
    → ★`dq3/ui/party_panel.py` を作った（⚠ `retroux/` は変更しない）。
    """
    assert "from retroux.ui.battle_monsters import BattleMonsterStrip" in (
        BATTLE.read_text(encoding="utf-8"))


def test_パーティは4人分の枠を固定する():
    """依頼者 2026-08-29「パーティーは 4 人分の枠を固定で撮っておく」。"""
    from dq3.ui.party_panel import SLOTS

    assert SLOTS == 4
    src = (UI / "party_panel.py").read_text(encoding="utf-8")
    assert "self.gold" in src, "⚠ 所持金の枠が無い"


def test_DQ2と同じ列がそろっている():
    """依頼者 2026-08-29:

        名前はいらない。職業を１文字（勇、戦、僧みたいな）
        攻撃、守備、素早さなどは DQ2 同様に表示させたい
        あと運の良さも出そう
    """
    from dq3.ui.party_panel import COLUMNS

    keys = [k for _t, _w, k in COLUMNS]
    for want in ("job", "level", "hp", "mp", "strength", "agility",
                 "attack", "defence", "luck", "to_next"):
        assert want in keys, "⚠ %s の列が無い" % want
    assert "name" not in keys, "⚠ 名前の列が残っている（★依頼者はいらないと）"


def test_列の合計が右パネルに収まる():
    """⚠⚠ 合計が幅を超えると、★列が潰れて**隣と重なって読めない**。

    （2026-08-29 に実際に重なった。合計 426px / パネル 360px）
    """
    from dq3.ui import layout
    from dq3.ui.party_panel import TOTAL_W

    for area in ((0, 0, 1920, 1032), (0, 0, 1280, 752)):
        panel = layout.compute(area).panel.w
        assert TOTAL_W <= panel, (
            "⚠⚠ 列の合計 %d が右パネル %d に入らない" % (TOTAL_W, panel))


def test_職業は画面から読む():
    """⚠⚠ 職業の**番地は分かっていない**（★推測で書かない）。

    ★ゲーム自身が「パーティの状態」の窓へ頭文字を出しているので、
    Lua がそれを拾って渡す。⚠ 「：」（`0x74`）の**手前**が頭文字。
    """
    from dq3.ui.party_panel import JOB_INITIAL

    # ★実測で確かめた 4 つ（2026-08-29 / セーブ 0）
    assert JOB_INITIAL[0x2F] == "勇"
    assert JOB_INITIAL[0x18] == "戦"
    assert JOB_INITIAL[0x19] == "僧"
    assert JOB_INITIAL[0x29] == "魔"

    dev = DEV.read_text(encoding="utf-8")
    assert "COLON_TILE" in dev and "remember_jobs" in dev, (
        "⚠ Lua が職業の頭文字を拾っていない")


def test_能力値は名前で読む():
    """⚠⚠ **画面と RAM で並びが違う**（★RAM は 力/速/賢/運/体）。

    ⚠ 位置で決め打ちすると、たいりょくとかしこさが入れ替わったまま気づけない。
    """
    dev = DEV.read_text(encoding="utf-8")
    for key in ("PARTY.strength", "PARTY.agility", "PARTY.wisdom",
                "PARTY.luck", "PARTY.stamina", "PARTY.attack",
                "PARTY.defence"):
        assert key in dev, "⚠ %s を読んでいない" % key


def test_ゴールドの番地は根拠つき():
    """★2026-08-29 に確定（⚠ 依頼者の画面 192 → 206 と一致）。"""
    import json

    prof = json.loads((ROOT / "dq3rom" / "profiles"
                       / "dq3_fc_jp_rev0a.json").read_text(encoding="utf-8"))
    gold = prof["runtime"]["gold"]
    assert gold["address"] == "0x07AC"
    assert gold["confidence"] == "confirmed"
    assert "192" in gold["evidence"] and "206" in gold["evidence"], (
        "⚠⚠ 根拠に実測の数字が書いていない")


def test_ゴールドは3バイト():
    """⚠⚠ 2 バイトだと 65535 を超えたところで**巻き戻ります**（RX3-0369）。

    ★依頼者の save6: 画面 66970 / ⚠ 誤表示 1434（= 66970 - 65536）。
    ★根拠は逆アセンブルの `_b0_s1B_player_gold_read`（`_players_gold` / `+1` / `+2`）。
    """
    import json

    prof = json.loads((ROOT / "dq3rom" / "profiles"
                       / "dq3_fc_jp_rev0a.json").read_text(encoding="utf-8"))
    gold = prof["runtime"]["gold"]
    assert gold["size"] == 3, "⚠⚠ ゴールドは 3 バイト（★2 だと 65535 で巻き戻る）"
    assert "_players_gold" in gold["evidence"], (
        "⚠ 根拠にコードの出どころが書いていない")
    assert "66970" in gold["evidence"], "⚠ 根拠に実測の数字が書いていない"


def test_ゴールドを読む所は桁数を決め打ちしない():
    """★`size` のぶんだけ回すこと（⚠ `>= 2 then` の並べ書きに戻さない）。"""
    for path in (DEV, ROOT / "dq3" / "phase0" / "restock_v0.lua"):
        src = path.read_text(encoding="utf-8")
        at = src.find("gold")
        assert at > 0, path
        assert "memory.readbyte(G.address + 1) * 256" not in src, (
            "⚠⚠ %s が 2 バイト決め打ちに戻っている" % path.name)
        assert "readbyte(GOLD.address + 1) * 256" not in src, (
            "⚠⚠ %s が 2 バイト決め打ちに戻っている" % path.name)


def test_セーブの所持金が3バイトで読める():
    """★手元のセーブ全部で、⚠ 3 バイトの値が DQ3 の上限に収まること。

    ⚠⚠ **セーブを番号で名指ししません**（★撮り直されたら壊れるため）。
    ★あるものを全部見て、⚠ 65535 を超える例があれば**そこだけ**強く確かめます。
    """
    ss = pytest.importorskip("retroux.core.bgmap.savestate",
                             reason="⚠ セーブステートを読む道具が無い")
    saves = sorted((ROOT / "tools" / "fceux" / "fcs").glob("DQ3_J.fc[0-9]"))
    if not saves:
        pytest.skip("⚠ セーブがまだ無い")
    big = []
    for path in saves:
        try:
            ram = ss.load(path).chunks["RAM"]
        except Exception:                                  # noqa: BLE001 ⚠ 壊れた控えは飛ばす
            continue
        two = ram[0x07AC] | (ram[0x07AD] << 8)
        high = ram[0x07AE]
        three = two | (high << 16)
        assert three < 1000000, (
            "⚠ %s の所持金が DQ3 の上限を超えた: %d" % (path.name, three))
        if high:
            big.append((path.name, two, three, high))
    if not big:
        pytest.skip("⚠ 65535 を超えるセーブが手元に無い（★この道は確かめられない）")
    for name, two, three, high in big:
        assert three > 65535, name
        assert three - two == high * 65536, name
        assert three != two, (
            "⚠⚠ %s: 2 バイトと 3 バイトが同じ ―― 上位バイトを読めていない" % name)


def test_HPとMPは桁をそろえる():
    """⚠⚠ 依頼者「桁を合わせたい（★数字は 3 桁スペースサプレス）」（RX3-0369）。

    ```text
    ⚠ 今まで   30/31    124/124   ← ★縦に並べるとスラッシュの位置がずれる
    ★これから   30/ 31   124/124
    ```
    """
    from dq3.ui.party_panel import PAIR_DIGITS, _pair

    assert PAIR_DIGITS == 3
    assert _pair(30, 31) == " 30/ 31"
    assert _pair(124, 124) == "124/124"
    assert _pair(7, 999) == "  7/999"
    # ⚠ 0 で埋めない（★`030` は別の数に見える）
    assert "0" not in _pair(3, 4).replace("/", "").strip()
    # ★どの組み合わせでも長さが同じ（⚠ これが「そろう」の中身）
    widths = {len(_pair(a, b)) for a, b in ((0, 0), (9, 9), (99, 99), (999, 999))}
    assert widths == {PAIR_DIGITS * 2 + 1}, widths


def test_HPの列は3桁2つが入る幅がある():
    """★桁をそろえても、⚠ 列が狭ければ切れます。"""
    from dq3.ui.party_panel import COLUMNS

    wide = {key: w for _t, w, key in COLUMNS}
    for key in ("hp", "mp"):
        assert wide[key] >= 56, "⚠ %s の列が「999/999」に足りない: %d" % (key, wide[key])


def test_FCEUXの重ね書きは既定で出さない():
    """依頼者 2026-08-29「FCEUX に表示している表示は右画面で代替するので不要」。

    ⚠ 消さずに**出すかどうかを 1 か所で決める**（★戻せるように）。

    ## ⚠⚠ 2026-08-31: いまの場所だけは**例外**にしました

      ★依頼者「座標はどこにも表示されない。ログに出すか FCEUX の画面に
      出すかが対応が必要」（`RX3-0013` の実機確認）。

      ⚠ 右の画面には**升の座標が出ていません**（★地図の絵はある）。
        入口の行き先を確かめるには、いま立っている升の数字が要ります。
      → ★`ui.position` で切れる形にして、既定は出す。

    ## ⚠⚠ 2026-09-12: 座標も既定で出さない（RX3-0195）

      ★依頼者「FCEUXの座標表示はいらない」。→ ★`ui.position = true` のときだけ出す（★切り替えは残す）。
    """
    allowed = {"dev.lua": 2}              # ⚠ overlay の 1 か所 ＋ 場所の 1 か所
    for path in (DEV, ROOT / "dq3" / "phase0" / "auto_v0.lua",
                 ROOT / "dq3" / "phase0" / "mantan_v0.lua"):
        src = path.read_text(encoding="utf-8")
        assert "OVERLAY" in src, "⚠ %s に切り替えが無い" % path.name
        body = chr(10).join(ln for ln in src.splitlines()
                            if not ln.lstrip().startswith("--"))
        calls = body.count("gui.text(")
        assert calls <= allowed.get(path.name, 1), (
            "⚠⚠ %s が %d か所で直に描いている（★1 か所にまとめること）"
            % (path.name, calls))
    # ★場所の表示も、切り替えを 1 つ持っていること
    src = DEV.read_text(encoding="utf-8")
    assert "SHOW_POS" in src and "ui or {}).position" in src, (
        "⚠ 場所の表示に切り替えが無い（★戻せるようにする）")
    # ★既定は出さない（2026-09-12 依頼者「FCEUXの座標表示はいらない」/ RX3-0195）
    assert "ui or {}).position == true" in src, (
        "⚠⚠ 座標の表示が既定で出る（★設定の ui.position = true のときだけ出す）")


def test_ボタンは1文字():
    """依頼者 2026-08-29「整、A、タ、満、終 の一文字のボタンにする（縦節約）」。

    ⚠ 2026-09-06（RX3-0084）訂正: ★以前は「**横 1 列**に並べる」を字面で固定していました。
      ⚠⚠ ボタンが 10 個になると 376px で、**右パネル 360 に入りません**（実測）。
      → ★守るのは「1 文字である」ことと「縦を無駄にしない」こと。
        ⚠ 並べ方は `BUTTONS_PER_ROW` で折り返します
        （★はみ出さないことは `test_ボタンが右パネルからはみ出さない` が幅で見ます）。
    """
    src = MAIN.read_text(encoding="utf-8")
    for role, label in (("align", "整"), ("auto", "オート"), ("turbo", "ターボ"),
                        ("mantan", "まんたん"), ("exit", "終")):
        assert ('("%s", "%s", ' % (role, label)) in src, "⚠ %s のボタンが無い" % label
    # ★★ 2026-09-20（RX3-0325）: 並べ方の決め打ち（`BUTTONS_PER_ROW`）は**外しました**。
    #   ⚠⚠ アイコン＋字にすると幅が字の長さで変わるので、★数ではなく**幅**で折り返します。
    #   ⚠ 註（`#` で始まる行）には残っているので、★**動く行だけ**を見ます。
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    back = [ln for ln in code if "BUTTONS_PER_ROW" in ln]
    assert not back, "⚠⚠ 段数の決め打ちが戻っている（★幅で折り返すこと）: %s" % back
    assert "wrap_rows" in src, "⚠ 折り返しが決まっていない"


def test_明るいテーマでも読める():
    """⚠⚠ 白っぽい色を決め打ちすると、★明るいテーマで**背景に溶ける**。

    （2026-08-29 に実際に踏んだ。パーティの名前が読めなくなった）
    """
    src = (UI / "party_panel.py").read_text(encoding="utf-8")
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    for bad in ("#e6e9ef", "#c8cdd8", "#8a93a5"):
        assert bad not in body, (
            "⚠⚠ 明暗どちらか片方でしか読めない色を決め打ちしている: %s" % bad)
    assert "palette(mid)" in body, "★環境の色を使っていない"


# --- ★Lua 側（state.json）---------------------------------------------

def test_state_writerは毎フレーム書かない():
    """⚠⚠ DQ2 で描き直しが 1 回 137.8 ms 掛かった（★録画で 1 フレーム落ちた）。"""
    src = WRITER.read_text(encoding="utf-8")
    assert "now - last_at < gap" in src, "⚠⚠ 間隔を見ていない"
    assert "opts.every or 30" in src, "⚠ 既定の間隔が無い"
    # ★戦闘中だけ詰める道（RX3-0065 / 2026-09-03）
    assert "opts.busy_every" in src, "⚠ 忙しいときの間隔が無い"
    assert "busy_every or every" in src, (
        "⚠⚠ 既定が `every` でない（★指定しなければ今までどおりであること）")


def test_state_writerは置き換えで書く():
    """⚠ 書いている途中を読ませない（★一時ファイルへ書いてから移す）。"""
    src = WRITER.read_text(encoding="utf-8")
    assert 'path .. ".tmp"' in src, "⚠⚠ 直接書いている"
    assert "os.rename" in src


def test_1本がstateを書いている():
    """★`dev.lua` から実際に呼ばれていること（⚠ 作っただけにしない）。"""
    src = DEV.read_text(encoding="utf-8")
    assert "state_writer.lua" in src, "⚠ 読み込んでいない"
    assert "pcall(state.tick)" in src, "⚠⚠ 毎フレーム呼んでいない"


def test_名前は生のタイルのまま渡す():
    """⚠ 文字にするのは Python 側（★文字コード表が直ったら読み直せる）。"""
    src = DEV.read_text(encoding="utf-8")
    assert "name_tiles" in WRITER.read_text(encoding="utf-8"), (
        "⚠⚠ 生のタイルを渡していない")
    assert "PARTY.name" in src


def test_戦闘かどうかはDQ3自身の式で見る():
    """★★ 戦闘中は DQ3 自身の式（RX3-0166 / `$32 == $FD かつ $60B7 & $20`）。

    ⚠⚠ 歴史（★どちらも実機で外れた / RX3-0165）::

        画面のマス数だけ        建物の中が「戦闘」（RX3-0157）
        画面 AND `$62 == 255`   2 手目以降ずっと「戦闘ではない」（318 枚）/ にげた後 FF が残る（632 枚）

    ★判定は `battle_state.lua` の 1 か所。dev.lua はそれを借りるだけで、旧い判定は診断にだけ残す。
    ★振る舞いは `dq3_dev_test.lua` §9 と `dq3_battle_speed_test.lua` が動かして見ています。
    """
    src = DEV.read_text(encoding="utf-8")
    body = chr(10).join(ln for ln in src.splitlines() if not ln.lstrip().startswith("--"))
    in_battle = body.split("function HOST.in_battle()")[1].split(chr(10) + "end")[0]
    assert "battle.is_in_battle()" in in_battle, "⚠⚠ HOST.in_battle が DQ3 自身の式を使っていない"
    assert "0x62" not in in_battle and "screen" not in in_battle, (
        "⚠⚠ HOST.in_battle に旧い判定（$62 / 画面）が混ざっている")
    state = (DEV.parent / "battle_state.lua").read_text(encoding="utf-8")
    assert "0x0032" in state and "0x60B7" in state and "0xFD" in state and "0x20" in state
    assert "0x62" not in state.replace("0x6A63", ""), "⚠⚠ battle_state.lua が $62 を読んでいる"


# --- ★画面から Lua へ頼む（RX3-0019 / 2026-08-29）----------------------

def test_同じ頼みを2回きかせない(tmp_path):
    """⚠⚠ 「押されたボタンの名前」だけだと、★同じボタンの 2 回目を取りこぼす。

    ⚠ DQ2 で踏んだ形。★通し番号で見分ける。
    """
    from dq3.ui.commands import CommandWriter

    path = tmp_path / "cmd.json"
    w = CommandWriter(path)
    first = w.send("auto")
    second = w.send("auto")
    assert second == first + 1, "⚠⚠ 通し番号が増えていない（★2 回目が消える）"

    # ★書き直しても続きから数える（⚠ 0 に戻すと Lua が古い頼みとして捨てる）
    again = CommandWriter(path)
    assert again.send("turbo") == second + 1, "⚠⚠ 番号が巻き戻っている"


def test_知らない頼みは受け付けない(tmp_path):
    from dq3.ui.commands import CommandWriter

    with pytest.raises(ValueError):
        CommandWriter(tmp_path / "c.json").send("なにか")


def test_頼みは1行で書く(tmp_path):
    """⚠⚠ Lua に JSON パーサは無い（★正規表現で拾う）。"""
    from dq3.ui.commands import CommandWriter

    path = tmp_path / "cmd.json"
    CommandWriter(path).send("mantan")
    text = path.read_text(encoding="utf-8")
    assert chr(10) not in text.strip(), "⚠⚠ 複数行で書いている"
    assert '"action":"mantan"' in text, text


def test_luaが同じ名前を知っている():
    """⚠ 片方だけ名前を変えると、★押しても何も起きない。"""
    from dq3.ui.commands import ACTIONS

    # ⚠ 受け口は 1 か所ではない（★turbo は dev、auto/mantan は各機能）
    lua = chr(10).join(
        p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "dq3" / "phase0").glob("*.lua")))
    for name in ACTIONS:
        assert ('wants("%s")' % name) in lua, (
            "⚠⚠ Lua 側が %r を知らない（★押しても効きません）" % name)


def test_luaが頼みを読んでいる():
    """★道具を作っただけで呼び忘れる、を防ぐ。"""
    assert "command_reader.lua" in DEV.read_text(encoding="utf-8")
    assert "commands.tick()" in DEV.read_text(encoding="utf-8")


def test_取り出した頼みは消える():
    """⚠⚠ 消さないと、★毎フレーム入り切りを繰り返す。"""
    src = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "pending[name] = nil" in src, "⚠⚠ 取り出しても消していない"


# --- ★下ウィンドウ（依頼者 2026-08-29）--------------------------------

def test_戦闘は下の別ウィンドウ():
    """依頼者「左右下のウィンドウ配置で、下ウィンドウに戦闘モンスターとログを」。"""
    src = BATTLE.read_text(encoding="utf-8")
    assert "Qt.WindowType.Window" in src, "⚠ 別ウィンドウになっていない"
    assert "BattleMonsterStrip" in src and "QTextBrowser" in src, (
        "⚠ モンスターとログの両方が要る")


def test_上段の高さは帯そのものが決める():
    """★★ ⚠⚠ 2026-09-01: **窓側が札を潰していました**。 ★★

    ★もとは DQ2 と同じ `60`〜`88` を `battle_window` に直書きしていました。
    ⚠ 帯を 104 にしたのに `setMaximumHeight(88)` で**頭打ち**になり、
      依頼者の画面で**性能と名前が切れていました**。

    ⚠⚠ DQ2 側は**同じ失敗を既に学んでいます**
      （`test_layout_heights.test_札を切らない` / 2026-08-14）。
      ★「下限を決め打ちすると、中身が伸びたときに切れる」。

    → ★数字を 2 か所に置かず、`Dq3MonsterStrip` から取ります。
    """
    from dq3.ui import battle_window as bw
    from dq3.ui.monster_panel import STRIP_HEIGHT
    from retroux.ui import log_window as dq2

    src = (UI / "battle_window.py").read_text(encoding="utf-8")
    assert "setMaximumHeight" not in src, (
        "⚠⚠ 窓側が帯の高さを決めています（★帯に任せること）")
    assert bw._strip_height() == STRIP_HEIGHT
    # ★DQ2 より低くはならない（⚠ 性能を出すぶん高い）
    assert STRIP_HEIGHT >= dq2.TOP_MAX, (STRIP_HEIGHT, dq2.TOP_MAX)
    assert bw.WINDOW_W >= 1264, "⚠ DQ2 より狭い"


def test_整列は左右下に並べる():
    """★DQ2 の「整列」と同じ並び。"""
    src = MAIN.read_text(encoding="utf-8")
    assert "def arrange_windows" in src
    for who in ("_place(self.map_window, plan.map)",
                "_place(self, plan.panel)",
                "_place(self.battle_window, plan.bottom)"):
        assert who in src, "⚠ %s を並べていない" % who


def test_窓は枠ごと置く():
    """⚠⚠ `setGeometry` が決めるのは**中身**で、題名の帯は外側に付く。

    ★そのまま並べると、下の窓が上の窓へ食い込む
    （依頼者 2026-08-29「上と下で被っている」）。
    """
    src = MAIN.read_text(encoding="utf-8")
    assert "def _place" in src, "⚠ 枠ごと置く道具が無い"
    assert "frameGeometry()" in src and "window.geometry()" in src, (
        "⚠⚠ 枠の厚みを測っていない")


def test_文字が窓の幅を決めない():
    """⚠⚠ 長い文が入った瞬間に、★右パネルが 360 → 556 へ広がった。

    （2026-08-29 / 依頼者「左真ん中右に間がある」の一因）
    """
    src = MAIN.read_text(encoding="utf-8")
    assert "QSizePolicy.Policy.Ignored" in src, (
        "⚠⚠ 状態欄の文字が窓の幅を押し上げる")
    party = (UI / "party_panel.py").read_text(encoding="utf-8")
    assert "QSizePolicy.Policy.Ignored" in party, (
        "⚠⚠ パーティの表が窓の最小幅を決めている")


def test_DQ2から引き継いだボタンがある():
    """依頼者「DQ2 で採用していたボタンは引き継げるものは引き継ぎたい」。

    ⚠ 2026-08-29 に**1 文字**へ縮めた（★縦を節約するため）。
    """
    src = MAIN.read_text(encoding="utf-8")
    for role, label in (("align", "整"), ("auto", "オート"), ("turbo", "ターボ"),
                        ("mantan", "まんたん"), ("exit", "終")):
        assert ('("%s", "%s", ' % (role, label)) in src, "⚠ %s のボタンが無い" % label


def test_Lua窓は最小化するだけで閉じない():
    """⚠⚠ **閉じると Lua が止まる**（★自動戦闘もまんたんも死ぬ）。

    依頼者 2026-08-29:「Lua 画面は最小化して非アクティブにしたい」
    ⚠ 隠す（`SW_HIDE`）と、★タスクバーからも消えて戻す手段を失う。
    """
    src = MAIN.read_text(encoding="utf-8")
    assert "window_align.minimize" in src, "⚠ 最小化していない"
    assert "LUA_WINDOW_TITLE" in src
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    for bad in ("window_align.hide", "SW_HIDE", 'close("Lua'):
        assert bad not in body, "⚠⚠ Lua の窓を閉じている/隠している: %s" % bad


def test_キーのちらつきを2回目としない():
    """⚠⚠ 実機で「まんたんが暴れた」（2026-08-29 / 依頼者）。

    ★ターボ中は 1 秒に数千フレーム進む。`input.get()` が押しっぱなしの
    途中で 1 度でも false を返すと、⚠ 離して押し直したように見える。
    → ★**実時間**で間を置く（⚠ フレーム数ではターボで一瞬に過ぎる）。
    """
    core = (ROOT / "dq3" / "phase0" / "core.lua").read_text(encoding="utf-8")
    assert "debounce" in core, "⚠⚠ 間合いを見ていない"
    assert "os.clock" in core, "⚠⚠ 実時間で計っていない（★フレームでは駄目）"

    # ⚠⚠ 2026-08-29（2 度目）: **時間の間合いだけでは足りなかった。**
    #   ★0.2 秒より長く押していると、途中のちらつきが
    #   「間合いを過ぎた押し直し」に見えて 2 回目が通った（実機で再現）。
    #   → ⚠ **本当に離した**（離れて見えた回数）まで見ること。
    assert "release_polls" in core, (
        "⚠⚠ 「本当に離した」を見ていない（★長押し中のちらつきで暴れます）")
    assert "waited and released" in core, (
        "⚠⚠ 2 つとも満たすことを求めていない（★片方だけでは通り抜けます）")
    assert "off_before" in core, (
        "⚠ 0 に戻す前の値で見ていない（★押し直しが永久に通らなくなります）")


# --- ★ログの中身（依頼者 2026-08-29）-----------------------------------

def test_ログはLuaが書いたものを読む():
    """依頼者「フレーム表示しかいま画面に出ていない。じゃなくて、全体的なログを」。

    ⚠⚠ 画面が組み立てると、★倍速で**取りこぼします**
    （DQ2 の `battle_review` にも同じ註釈がある）。
    ★Lua はその場でファイルへ書いているので、**そちらを読みます**。
    """
    from dq3.ui import battle_window as bw

    for _, path, _ in bw.SOURCES:
        assert path.name.endswith(".log"), "⚠ ログを読んでいない: %s" % path
    assert len(bw.SOURCES) >= 3, "⚠ 戦闘・満タン・本体の 3 つが要る"
    src = BATTLE.read_text(encoding="utf-8")
    assert "LogTail" in src, "⚠⚠ Lua のログを読んでいない"


def test_ログはタブを作らず色分けする():
    """依頼者 2026-08-29「ログ選択タブはいらない → 1 行節約 /
    全てのログを色分けさせる感じで表示する」。"""
    from dq3.ui import battle_window as bw

    src = BATTLE.read_text(encoding="utf-8")
    assert "QTabWidget" not in src, "⚠⚠ タブが残っている（★1 行の節約が効かない）"
    # ★印の強いほうから見る（⚠ `⚠⚠` は `⚠` を含む）
    #   ⚠ 2026-09-07（RX3-0111）: 白地にしたので**色そのものは変わりました**。
    #     ★色の値を書き写すと、⚠ 次に配色を変えたときここだけ古くなります。
    #     → ★見るのは「印ごとに**違う色**が付くこと」と「強いほうが勝つこと」。
    strong = bw.colour_of("⚠⚠ こわれた")
    weak = bw.colour_of("⚠ あぶない")
    good = bw.colour_of("★できた")
    plain = bw.colour_of("ふつうの行")
    assert len({strong, weak, good, plain}) == 4, (strong, weak, good, plain)
    assert plain == bw.PLAIN_COLOR
    assert strong == dict(bw.LEVEL_COLORS)["⚠⚠"], "⚠ 強いほうが勝っていない"


def test_ログの見出しを出さない():
    """依頼者「戦闘、モンスター のラベルはいらない。戦闘中のラベルもいらない」。"""
    src = BATTLE.read_text(encoding="utf-8")
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    for bad in ('_section("戦闘")', '_section("モンスター")', '_section("戦闘ログ")'):
        assert bad not in body, "⚠ 見出しが残っている: %s" % bad


def test_ログは増えたぶんだけ読む(tmp_path):
    """⚠ `auto_v0.log` は実測 75KB。★毎回全部読み直さない。"""
    from dq3.ui.log_tail import LogTail

    path = tmp_path / "a.log"
    path.write_text("むかしの行" + chr(10), encoding="utf-8")
    tail = LogTail(path)              # ★既定は「今から」
    assert tail.read_new() == [], "⚠⚠ 起動時に過去ぶんを全部出している"

    with path.open("a", encoding="utf-8") as handle:
        handle.write("あたらしい 1" + chr(10) + "あたらしい 2" + chr(10))
    assert tail.read_new() == ["あたらしい 1", "あたらしい 2"]
    assert tail.read_new() == [], "⚠ 同じ行を 2 回出している"


def test_途中の行を出さない(tmp_path):
    """⚠ Lua は書いている途中かもしれない（★半端な行を出さない）。"""
    from dq3.ui.log_tail import LogTail

    path = tmp_path / "a.log"
    path.write_text("", encoding="utf-8")
    tail = LogTail(path)
    tail.read_new()
    with path.open("a", encoding="utf-8") as handle:
        handle.write("とちゅ")            # ⚠ 改行が無い
    assert tail.read_new() == [], "⚠⚠ 改行前の半端な行を出した"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("うの行" + chr(10))
    assert tail.read_new() == ["とちゅうの行"], "★続きと繋がっていない"


def test_作り直されたら先頭から読む(tmp_path):
    """⚠ ログを消して起動し直したとき、★続きだと思って読み飛ばさない。"""
    from dq3.ui.log_tail import LogTail

    path = tmp_path / "a.log"
    path.write_text("いち" + chr(10) + "に" + chr(10), encoding="utf-8")
    tail = LogTail(path, from_end=False)
    assert tail.read_new() == ["いち", "に"]
    path.write_text("さん" + chr(10), encoding="utf-8")   # ★小さくなった
    assert tail.read_new() == ["さん"], "⚠⚠ 作り直しに気づいていない"


# --- ★窓の大きさ（依頼者 2026-08-29）-----------------------------------

def test_1920x1080にぴったり収まる():
    """依頼者「1920x1080 にピッタリハマるように。いまはメイン画面と被る」。"""
    from dq3.ui import layout

    for area in ((0, 0, 1920, 1032), (0, 0, 1920, 1080), (0, 0, 1280, 752)):
        plan = layout.compute(area)
        left, top, width, height = area
        assert plan.map.w + plan.center.w + plan.panel.w == width, (
            "⚠⚠ 横がぴったりでない: %s" % (area,))
        assert plan.map.h + plan.bottom.h == height, (
            "⚠⚠ 縦がぴったりでない: %s" % (area,))
        assert plan.map.x == left and plan.bottom.x == left
        assert plan.panel.x + plan.panel.w == left + width, "⚠ 右端に隙間"
        assert plan.bottom.y + plan.bottom.h == top + height, "⚠ 下端に隙間"


def test_上段はFCEUXの高さに合わせる():
    """依頼者 2026-08-29:「②にタイトルバー、メニューバーがついたやつで。」

    ★② ＝ NES 画面 240×2 = 480px。⚠ 帯の厚みは環境で違うので**決め打ちしない**
    （★動いている FCEUX の窓を測る）。
    """
    from dq3.ui import layout

    assert layout.TOP_H_FALLBACK == layout.NES_H * 2 + layout.TITLE_BAR_H         + layout.MENU_BAR_H
    plan = layout.compute((0, 0, 1920, 1032), top_h=layout.TOP_H_FALLBACK)
    assert plan.map.h == layout.TOP_H_FALLBACK
    assert plan.map.h + plan.bottom.h == 1032, "⚠ 下段が残り全部になっていない"

    src = MAIN.read_text(encoding="utf-8")
    assert "def _emulator_size" in src, "⚠ FCEUX の高さを測っていない"
    assert "top_h=tall or layout_mod.TOP_H_FALLBACK" in src


def test_終了はFCEUXを閉じるか聞く():
    """依頼者 2026-08-29「終了ボタンでは FCEUX が残ってしまう」。

    ⚠⚠ **黙って閉じない**（★セーブしていない進行が失われる）。
    """
    src = MAIN.read_text(encoding="utf-8")
    assert "def quit_all" in src, "⚠ 終了の道が無い"
    assert "QMessageBox.question" in src, "⚠⚠ 聞かずに閉じている"
    assert "window_align.close_window" in src, "⚠ FCEUX を閉じられない"


def test_中央にFCEUXの場所を空ける():
    """⚠⚠ 空けないと必ず重なる（★依頼者「メイン画面と被ってしまっている」）。"""
    from dq3.ui import layout

    plan = layout.compute((0, 0, 1920, 1032))
    assert plan.center.w >= 780, "⚠ FCEUX（実測 約 770x730）が入らない"
    # ★狭い画面では左右を守る（⚠ 全部見えなくなるのを防ぐ）
    narrow = layout.compute((0, 0, 1280, 752))
    assert narrow.map.w >= layout.SIDE_MIN and narrow.panel.w >= layout.SIDE_MIN
    assert plan.map.x + plan.map.w == plan.center.x, "⚠ 地図と中央が重なる"
    assert plan.center.x + plan.center.w == plan.panel.x, "⚠ 中央と右が重なる"


def test_論理と物理を混ぜない():
    """⚠⚠ 依頼者の画面は **125% / 150%** の拡大表示（2026-08-29）。

    ```text
    Qt（この画面）           論理  1280 x 752   ★availableGeometry()
    Win32（FCEUX を動かす）  物理  1920 x 1128  ⚠ window_align.work_area()
    ```

    ★物理を Qt へ渡したところ、窓が **1.5 倍**になって画面からはみ出した。
    """
    from dq3.ui import layout

    box = layout.Box(360, 0, 560, 492)
    assert layout.to_physical(box, 1.5).as_tuple() == (540, 0, 840, 738)
    assert layout.to_physical(box, 1.0).as_tuple() == box.as_tuple()
    assert layout.to_logical(1920, 1128, 1.5) == (1280, 752)
    assert layout.to_logical(1920, 1128, 1.0) == (1920, 1128)

    # ⚠ 註釈と説明文には「使ってはいけない」と書いてある。
    #   → ★字面ではなく **実際の呼び出し**で見る。
    for path in (MAIN, MAP, BATTLE):
        assert not _calls(path, "work_area"), (
            "⚠⚠ %s が**物理**の作業領域を呼んでいる"
            "（★150%% の画面で 1.5 倍になります）" % path.name)

    src = MAIN.read_text(encoding="utf-8")
    assert "layout_mod.qt_area" in src, "⚠ Qt の論理領域を使っていない"
    assert "layout_mod.to_physical" in src, (
        "⚠⚠ FCEUX へ渡す前に物理へ直していない")


def _calls(path, name: str) -> bool:
    """★その名前の**呼び出し**があるか（⚠ 説明文の中の語は数えない）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == name:
            return True
        if isinstance(func, ast.Name) and func.id == name:
            return True
    return False


def test_窓の初期位置も論理で置く():
    """⚠ 起動直後から画面に収まっていること（★整列を押す前）。"""
    for path in (MAP, BATTLE):
        assert not _calls(path, "work_area"), (
            "⚠⚠ %s が物理の作業領域を呼んでいる" % path.name)
        assert "layout_mod.qt_area()" in path.read_text(encoding="utf-8"), (
            "⚠ %s が Qt の論理領域を使っていない" % path.name)


def test_FCEUXの大きさは決め打ちしない():
    """⚠ 倍率設定や拡大率で必ずずれる（★いまの窓の大きさから決める）。"""
    src = MAIN.read_text(encoding="utf-8")
    assert "def _emulator_size" in src, "⚠ 中央の大きさを測っていない"
    assert "window_align.find_windows" in src, "⚠ FCEUX の実寸を見ていない"
    # ★大きさは変えない（⚠ 人が決めた倍率をこちらで壊さない）
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "None, None, match=" in body.replace(chr(10) + " " * 31, ""), (
        "⚠⚠ FCEUX の大きさまで変えている（★人が決めた倍率を壊します）")


def test_整列はFCEUXも動かす():
    """★依頼者の「被る」を直すには、こちらを寄せるだけでは足りない。"""
    src = MAIN.read_text(encoding="utf-8")
    assert "def move_emulator" in src, "⚠ FCEUX を動かしていない"
    assert "window_align.align" in src
    assert 'match="prefix"' in src, (
        "⚠⚠ 前方一致で探していない（★関係ない窓を動かします）")


# --- ★起動できること ---------------------------------------------------

def test_画面なしで確かめられる():
    """★Qt を出さずに、材料が読めるかだけ見られること。"""
    # ⚠⚠ 子に **PYTHONUTF8=1 を明示**する（2026-09-03 / RX-0128）。
    #   ★親が付けて走っているときだけ緑になる検査だった。
    #   ⚠ 相談 ZIP は `uv run pytest` を素で回すので、そこで cp932 になり
    #     「勇者メモ」が化けて落ちていた（★出力は正しく、照合だけが壊れた）。
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [sys.executable, "-m", "dq3.ui.app", "--check"],
        cwd=str(ROOT), capture_output=True, timeout=120,
        text=True, encoding="utf-8", errors="replace", env=env)
    both = (done.stdout or "") + (done.stderr or "")
    assert done.returncode == 0, both
    assert "勇者メモ" in both, both


def test_起動口がQtを先に読まない():
    """⚠ 検査に Qt を要求しない（★DQ2 と同じ作法）。

    ⚠⚠ 2026-09-21（RX3-0329）訂正: ★以前は「`def main` より前に PySide6 の字が無いか」で
      見ていました。⚠ 関数の**中**の import まで拾うので、★`def main` の前に
      小さな補助関数を置いただけで赤くなりました（2026-09-21 に踏んだ）。
    → ★守りたいのは「**モジュールを読み込むときに Qt を読まない**」ことなので、
      ⚠ 字面ではなく**トップレベルの import 文**で見ます
      （★`def main` の後ろに書いた module 直下の import も捕まえられます）。
    """
    import ast

    src = (UI / "app.py").read_text(encoding="utf-8")
    bad = []
    for node in ast.parse(src).body:               # ★トップレベルだけ
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.startswith("PySide6")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PySide6"):
            bad.append(node.module)
    assert not bad, "⚠⚠ モジュールの読み込みで Qt を import している: %s" % bad


def test_view_modelがQtを読まない():
    """★画面が無くても検査できること。"""
    src = VIEW_MODEL.read_text(encoding="utf-8")
    assert "PySide6" not in src, "⚠⚠ view_model が Qt に依存している"
    assert "PySide6" not in MODELS.read_text(encoding="utf-8")


def test_職業はファミコン版の8つだけ():
    """⚠⚠ **とうぞく（盗賊）はファミコン版に無い**。

    ★スーパーファミコン版で追加された職業で、⚠ 表に残しておくと
    「と」を拾ったときに**嘘の札**が出る。
    """
    from dq3.ui.party_panel import JOBS, JOB_INITIAL

    assert len(JOBS) == 8, "⚠ ファミコン版の職業は 8 つ"
    assert "盗" not in dict(JOBS).values()
    # ★頭文字が重ならないこと（⚠ 重なると片方が消える）
    assert len(JOB_INITIAL) == 8, "⚠⚠ 頭文字が重なっている"


def test_かなの並びから起こしている():
    """★実測の 4 つが、かなの並びから起こした番号と**一致する**こと。

    ⚠ ここが合っているから、残り 4 つ（武・商・遊・賢）も置ける。
    ⚠ 「ぶとうか」は**ふ＋濁点**で、★濁点は 1 行上の別タイル。
    """
    from dq3.ui.party_panel import KANA, KANA_BASE, VOICED, _tile

    assert KANA_BASE == 0x0B and KANA[0] == "あ"
    assert _tile("ゆ") == 0x2F and _tile("せ") == 0x18
    assert _tile("そ") == 0x19 and _tile("ま") == 0x29
    assert VOICED["ぶ"] == "ふ", "⚠ 濁点を落としていない"
    assert _tile("ぶ") == _tile("ふ")
    # ⚠ 名前「あかり」でも合う（★2026-08-29 の実測）
    assert [_tile(c) for c in "あかり"] == [0x0B, 0x10, 0x32]


def test_次のレベルまでは引き算で出さない():
    """★★ 次に要る**累計**はゲーム自身が持っている（`$6A3F`）。

    ⚠⚠ 経験値の表を**こちらで推測して作らない**（★職業ごとに違う）。
    ⚠ 引き算は Lua 側で済ませ、画面には**残り**だけを渡す。
    """
    import json

    prof = json.loads((ROOT / "dq3rom" / "profiles"
                       / "dq3_fc_jp_rev0a.json").read_text(encoding="utf-8"))
    party = prof["runtime"]["party"]
    assert party["next_exp"] == "0x6A3F"
    assert party["next_exp_stride"] == 3

    dev = DEV.read_text(encoding="utf-8")
    assert "PARTY.next_exp" in dev, "⚠ Lua が読んでいない"
    assert "m.to_next" in dev, "⚠ 残りにして渡していない"
    # ⚠ 上がりきったときに**負の数を出さない**
    assert "left > 0 and left or 0" in dev, "⚠⚠ 負の数の歯止めが無い"


def test_パーティの値が画面まで届く():
    """⚠⚠ 2026-08-29 に**ここが切れていた**。

    `dev.lua` は読んでいたのに、★`state_writer` の組み立てが
    **決まった一覧**だったので、⚠ 途中で黙って捨てられていた。
    画面には HP と MP しか出ず、⚠ 検査は全部緑のままだった。
    """
    writer = (ROOT / "dq3" / "phase0" / "state_writer.lua").read_text(
        encoding="utf-8")
    assert "for k, v in pairs(m) do" in writer, (
        "⚠⚠ 決まった一覧に戻っている（★増えた値が届かなくなる）")

    from dq3.ui.view_model import _Dq3Member

    for key in ("luck", "attack", "defence", "job_tile", "to_next"):
        assert key in _Dq3Member.EXTRA, "⚠ %s を画面へ通していない" % key


def test_止まったときは画面を残す():
    """⚠⚠ **止まった理由だけでは足りない。**

    ★2026-08-30: `auto` は理由しか残しておらず、
    `command_missing:p4=defend` が**半月ちかく追えなかった**。
    ⚠ まんたん側は最初から画面を残していて、実際に何度も助かっている
    （`target_window_missing` / `cursor_not_blinking` はどちらも画面で解けた）。

    ★止まる仕掛けを持つ Lua は、⚠ **全部**画面を残すこと。
    """
    for name in ("auto_v0.lua", "mantan_v0.lua"):
        src = (ROOT / "dq3" / "phase0" / name).read_text(encoding="utf-8")
        i = src.index("local function stop(reason)")
        j = src.index(chr(10) + "end", i)
        body = src[i:j]
        assert "★画面（32x30" in body, (
            "⚠⚠ %s が止まったときの画面を残していない" % name)


# --- ★★ RX3-0037 下の窓の配分 ----------------------------------------------


def test_下の窓の配分はモンスター寄り():
    """★★★ ⚠⚠ **伸びしろをログだけが持っていた** ★★★

    依頼者 2026-09-01:

        > モンスター画面とログ画面のバランスで、
        > ★モンスター画面はちゃんと**デフォルトでなるべく表示**させたい

    ⚠ もとは `addWidget(monsters)` ＋ `addWidget(log, 1)`。
      ★下の窓が高くなっても、増えたぶんは**全部ログ**でした。
    """
    from dq3.ui import layout
    from dq3.ui.battle_window import LOG_MIN
    from dq3.ui.monster_panel import STRIP_HEIGHT

    strip, log = layout.bottom_split(250, STRIP_HEIGHT, LOG_MIN)
    assert strip + log == 250, (strip, log)
    assert strip > log, "⚠⚠ ログのほうが広い（★モンスター寄りでない）"
    assert strip > STRIP_HEIGHT, "⚠ 帯が下限のまま（★伸びていない）"
    assert log >= LOG_MIN, "⚠ ログが下限を割った"


def test_配分はどちらの下限も割らない():
    """⚠ 割り切れないときの決まり ― ★**帯を優先**する。

    ★ログは 1 行減っても読めますが、⚠⚠ 切れた札は**嘘を出します**
      （2026-09-01 の実機で性能が 3 つ消えていました）。
    """
    from dq3.ui import layout

    # ★ちょうど下限ぶんしか無い
    assert layout.bottom_split(176, 104, 72) == (104, 72)
    # ⚠ 足りない → ★帯を先に満たす
    assert layout.bottom_split(150, 104, 72) == (104, 46)
    # ⚠⚠ 帯の下限にも足りない → ★あるだけ渡す（負にしない）
    assert layout.bottom_split(80, 104, 72) == (80, 0)
    assert layout.bottom_split(0, 104, 72) == (0, 0)
    # ★広いときも、ログの下限は必ず残る
    for total in range(176, 1200, 7):
        strip, log = layout.bottom_split(total, 104, 72)
        assert strip >= 104 and log >= 72, (total, strip, log)
        assert strip + log == total, (total, strip, log)


def test_配分は人がつまんで変えられる():
    """★`QSplitter` にする（⚠ 固定の割合を押しつけない）。

    `docs/design/dq3-ui-v0.md`:

        ⚠ してはいけない   中身が増えたら窓が広がる／高くなる
        ★してよい         人がつまんで変えたとき
    """
    src = BATTLE.read_text(encoding="utf-8")
    assert "QSplitter" in src, "⚠⚠ 仕切りが無い（★人が変えられない）"
    assert "setChildrenCollapsible(False)" in src, (
        "⚠⚠ 畳めてしまう（★ログ 0 行 / 帯が消える）")
    # ⚠ 帯を直に縦へ積んでいないこと（★積むと伸びしろがログだけになる）
    assert "root.addWidget(self.monsters)" not in src, (
        "⚠⚠ 帯が仕切りの外にある（★配分が効かない）")
    assert "root.addWidget(self.log, 1)" not in src, (
        "⚠⚠ ログだけが伸びしろを持っている（★これを直した WI です）")


def test_既定の配分は一度だけ当てる():
    """⚠⚠ **人が変えたぶんを、あとから戻さない**。

    ★`refresh()` は 0.5 秒ごとに回ります。⚠ そこで配分を当て直すと、
      つまんで広げたそばから**毎回戻ります**。
    """
    src = BATTLE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "refresh")
    body = ast.dump(fn)
    assert "apply_default_split" not in body and "setSizes" not in body, (
        "⚠⚠ 毎回の更新で配分を当て直しています（★人の調整が消えます）")
    assert "_split_applied" in src, "⚠ 一度きりの歯止めが無い"
# --- ⚠⚠ 白地で読めること（RX3-0040 / 2026-09-03）---------------------------
#
#   ★2026-09-03 の実機で、図鑑の**題（敵の名前）が読めませんでした**。
#     ⚠ 窓は OS の明るいパレット（白地）なのに、
#     文字色が暗い背景向け（`#e6e9ef`）のままだったためです。
#   ⚠ 「うすい」は**エラーにならない壊れ方**なので、ここで数で見ます。


def _contrast(hex_color: str, on: str = "#ffffff") -> float:
    """★WCAG の明暗比（⚠ 1.0〜21.0。大きいほど読める）。"""
    def lum(text):
        rgb = [int(text[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        out = []
        for c in rgb:
            out.append(c / 12.92 if c <= 0.03928
                       else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    a, b = lum(hex_color.lower()), lum(on.lower())
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def test_図鑑の字が白地で読める():
    """⚠⚠ ★暗い背景向けの色へ戻すと、ここが赤くなります。

    ⚠ 地の色を自分で敷いている行（`background:`）は対象外です
      （★絵の枠は黒地なので、うすい灰色で正しい）。
    """
    import re

    src = (UI / "monster_book_window.py").read_text(encoding="utf-8")
    bad = []
    for line in src.splitlines():
        if "color:#" not in line or "background:" in line:
            continue
        for hexval in re.findall(r"color:(#[0-9a-fA-F]{6})", line):
            ratio = _contrast(hexval)
            if ratio < 3.0:
                bad.append("%s（比 %.2f）: %s" % (hexval, ratio, line.strip()))
    assert not bad, (
        "⚠⚠ 白地で読めない色があります（★3.0 未満）:\n" + "\n".join(bad))


def test_明暗比の計算そのものが効いている():
    """⚠ 検査が空振りしていないこと（★白は落ち、黒は通る）。"""
    assert _contrast("#ffffff") < 1.1, "⚠ 白を落とせていない"
    assert _contrast("#e6e9ef") < 3.0, "⚠ 実際に読めなかった色を通している"
    assert _contrast("#1f2430") > 3.0, "⚠ 読める色まで落としている"
