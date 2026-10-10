"""戦闘中の敵（RX3-0021 / 2026-08-29）。

★★ 名前は「画面で見て覚える」 ★★

⚠⚠ **原作テキストを成果物へ焼かない**（`RX3-0011` 決定 ③）。
  ⚠ ここが崩れると、★出荷物に原作の敵名が入ります。
"""

from __future__ import annotations

import json
import pathlib

import pytest

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "dq3" / "knowledge" / "enemies_seen.py"
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()

from dq3_states import BATTLE, one, pick


def _most_groups():
    """★群がいちばん多い戦闘のセーブ（⚠ 番号は当てにしない）。

    ⚠ 2 群以上のセーブがあると、**行の切り分け**まで確かめられます。
      ★いまは 1 群のものしかありません（`RX3-0028` に書いてあります）。
    """
    from retroux.core.bgmap.savestate import load

    def count(path):
        ram = load(path).ram
        return sum(1 for i in range(4) if ram[0x56D + i] != 0xFF)

    return max(pick(BATTLE), key=count)


def _battle_screen(slot=None):
    """★実機の戦闘画面。

    ⚠⚠ **番号で名指ししない**（RX3-0028 / 2026-08-31）。

      ★ここは `fc6` を名指しし、⚠ 戦闘でなければ `skip` していました。
      2026-08-31 に `fc6` が町のセーブへ上書きされた結果、
      ⚠⚠ **14 件が静かに skip になり、誰も気づきませんでした**
      （★赤くならないので、走っていないことが見えない）。

      → ★戦闘中のセーブを**中身で選ぶ**。⚠ 1 本も無ければ**赤**。
    """
    #   ★群が**いちばん多い**戦闘を選ぶ（⚠ 行の切り分けを見たいので）。
    path = FCS / ("DQ3_J.%s" % slot) if slot else _most_groups()

    if not path.exists():
        pytest.skip("⚠ セーブステートが無い環境")
    from dq3rom import ppu
    from retroux.core.bgmap.savestate import load

    st = load(path)
    ram = st.ram
    assert ram[0x62] == 0xFF, (
        "⚠⚠ 戦闘中のセーブを選んだのに戦闘中でない: %s" % path.name)
    groups = [{"id": ram[0x56D + i], "n": ram[0x571 + i]}
              for i in range(4) if ram[0x56D + i] != 0xFF]
    return list(ppu.screen_of(st.chunks)), groups


# --- ⚠⚠ 原作テキストを焼いていない ------------------------------------------

def test_敵の名前をソースに書いていない():
    """⚠⚠ **これが今回いちばん大事な検査**。

    ★名前は実行時に**利用者の ROM／画面**から読む。
    ⚠ ここに書いてしまうと、出荷物に原作テキストが入る。
    """
    src = SRC.read_text(encoding="utf-8")
    body = "\n".join(L for L in src.splitlines()
                     if not L.lstrip().startswith("#"))
    # ★註釈の例に出てくるものは、コードの外（docstring）だけに許す
    code = body.split('"""')[0] + '"""'.join(body.split('"""')[2::2])
    for name in ("スライム", "おおがらす", "ドラキー", "まほうつかい"):
        assert name not in code, "⚠⚠ 敵の名前がコードに書いてある: %s" % name


def test_文字表はプロファイルから読む():
    """⚠ ここに文字表を書くと、★原作の字を持つことになる。"""
    src = SRC.read_text(encoding="utf-8")
    assert "PROFILE" in src and "Charset(spec)" in src
    assert "あいうえお" not in src, "⚠⚠ 文字表を書いている"


# --- ★画面から読む ----------------------------------------------------------

def test_実機の画面から名前を読む():
    """★画面から読んだ数が、RAM の群の数と合うこと。

    ⚠⚠ 2026-08-31: ここは「fc6 は スライム 1 + おおがらす 2」と
      **1 つの場面を覚え込んで**いました。★そのセーブは上書きで失われ、
      ⚠ いま 2 群の戦闘は 1 本もありません（`RX3-0028`）。
      → ★どの戦闘でも成り立つ**性質**で見ます。
    """
    from dq3.knowledge.enemies_seen import names_on_screen

    tiles, groups = _battle_screen()
    got = names_on_screen(tiles)

    assert len(got) == len(groups) >= 1
    assert all(got), "⚠ 読めていない群がある: %r" % (got,)
    assert len(set(got)) == len(got), "⚠ 同じ名前を 2 度読んでいる"
    # ⚠ 濁点は 1 行上の別タイル（★合成できていること）
    assert "゛" not in "".join(got), "⚠ 濁点が合成されていない"


def test_左の窓の字が混ざらない():
    """⚠⚠ 1 行は画面いっぱい（32 桁）。

    ★素で切ると、**左のコマンド窓の字が混ざる**
    （2026-08-29 に実際に「▶たたかう スライム」と読めてしまった）。
    """
    from dq3.knowledge.enemies_seen import names_on_screen

    tiles, _groups = _battle_screen()
    got = names_on_screen(tiles)

    for name in got:
        assert "たたかう" not in name and "にげる" not in name, (
            "⚠⚠ 隣の窓が混ざっている: %r" % name)
        assert "▶" not in name


def test_枠と空白を落とす():
    from dq3.knowledge.enemies_seen import names_on_screen

    tiles, _groups = _battle_screen()
    for name in names_on_screen(tiles):
        assert name == name.strip()
        assert "·" not in name and "␣" not in name


def test_戦闘でない画面からは読まない():
    """⚠ フィールドの窓に「ー」があっても、★敵として拾わない。"""
    from dq3.knowledge.enemies_seen import names_on_screen

    assert names_on_screen([]) == []
    assert names_on_screen([0] * (32 * 30)) == []


# --- ★覚える ---------------------------------------------------------------

def test_見たら覚える(tmp_path):
    from dq3.knowledge.enemies_seen import EnemyNames

    tiles, groups = _battle_screen()
    seen = EnemyNames(tmp_path / "enemy-names.json")

    assert seen.learn(groups, tiles) == len(groups)
    assert seen.names[groups[0]["id"]]
    assert seen.save(force=True) is True

    again = EnemyNames.load(tmp_path / "enemy-names.json")
    assert again.names == seen.names, "⚠ 覚えたものが残っていない"


def test_数が合わなければ覚えない(tmp_path):
    """⚠⚠ ずれたまま覚えると、★別の敵に名前が付く。"""
    from dq3.knowledge.enemies_seen import EnemyNames

    tiles, groups = _battle_screen()
    seen = EnemyNames(tmp_path / "enemy-names.json")

    # ⚠ RAM の群と画面の行がずれている状態を作る。
    #   ★2026-08-31: 以前は「群を 1 つに削る」でずらしていたが、
    #   ⚠ 1 群だけの戦闘では削っても同じ数になり、**空回り**する。
    #   → ★**足して**ずらす（どの戦闘でも必ずずれる）。
    more = groups + [{"id": 0x77, "n": 1}]
    assert seen.learn(more, tiles) == 0
    assert seen.names == {}


def test_知らない敵を知っている風に出さない(tmp_path):
    """⚠ 名前を知らないのに、★それらしい名前を作らない。"""
    from dq3.knowledge.enemies_seen import EnemyNames

    from dq3.knowledge import rom_names

    seen = EnemyNames(tmp_path / "enemy-names.json")
    label = seen.label({"id": 77, "n": 3})

    assert "3" in label
    if rom_names.available():
        # ★2026-09-03（RX3-0069 §8）: ROM が primary。⚠ 画面で読めていなくても ROM の名前で出す
        assert rom_names.monster(77) in label, label
    else:
        assert "77" in label and "？" in label, "⚠⚠ 知らないことが分からない出し方"


def test_覚えた名前で出す(tmp_path):
    from dq3.knowledge.enemies_seen import EnemyNames

    tiles, groups = _battle_screen()
    seen = EnemyNames(tmp_path / "enemy-names.json")
    seen.learn(groups, tiles)

    last = groups[-1]
    label = seen.label(last)
    assert seen.names[last["id"]] in label
    assert str(last["n"]) in label, "⚠ 数が出ていない: %r" % label


def test_記録が無くても始められる(tmp_path):
    from dq3.knowledge.enemies_seen import EnemyNames

    seen = EnemyNames.load(tmp_path / "まだ無い.json")
    assert seen.names == {}


def test_壊れた記録でも残りは読める(tmp_path):
    from dq3.knowledge.enemies_seen import EnemyNames

    path = tmp_path / "enemy-names.json"
    path.write_text(json.dumps({"names": {"0": "あ", "×": "い"}}),
                    encoding="utf-8")

    seen = EnemyNames.load(path)
    assert seen.names == {0: "あ"}
    assert seen.failed == 1


def test_書けなければ理由を残す(tmp_path):
    from dq3.knowledge.enemies_seen import EnemyNames

    blocked = tmp_path / "ふさがれている"
    blocked.write_text("★これはフォルダではない", encoding="utf-8")
    seen = EnemyNames(blocked / "enemy-names.json")
    seen.names[0] = "あ"

    assert seen.save(force=True) is False
    assert seen.failed == 1 and seen.last_error


# --- ★Lua とつながっていること ---------------------------------------------

def test_Luaが敵と画面を送っている():
    """⚠ 送っていなければ、★画面には何も出ない。"""
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "read_enemies" in dev and "out.enemies" in dev
    assert "battle_screen" in dev and "out.screen" in dev


def test_戦闘中だけ画面を送る():
    """⚠ フィールドでも送ると、★state.json が 4 倍に膨らむ。"""
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    i = dev.index("if fighting then")
    j = dev.index("return out", i)
    assert "out.screen" in dev[i:j], "⚠⚠ 戦闘の外でも送っている"


def test_Luaは文字にしない():
    """⚠⚠ Lua が文字にすると、★文字表が 2 か所になる。"""
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    for bad in ("スライム", "あいうえお", "charset"):
        assert bad not in dev, "⚠ Lua が文字を持っている: %s" % bad


# --- ★画面に出るところ -----------------------------------------------------

def _vm(tmp_path, body):
    from dq3.knowledge.enemies_seen import EnemyBook
    from dq3.ui.view_model import Dq3ViewModel

    path = tmp_path / "state.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    # ⚠ 本物の作り方で作る（★`__new__` だと state の読み手が無くて落ちる）
    vm = Dq3ViewModel(state_path=path,
                      knowledge_path=tmp_path / "knowledge.json")
    # ⚠ 画面が使うのは EnemyBook（★会った / 倒した も覚える）
    vm._enemy_names = EnemyBook(tmp_path / "enemy-names.json")
    return vm


def _write_state(vm, body) -> None:
    """★`state.json` を書き直す。⚠⚠ **更新時刻を必ず進める。**

    ## ⚠⚠ ここで 1 日ぶんの時間を溶かしました（2026-08-30 / RX-0114）

      `StateReader.read` は、⚠ **更新時刻が同じなら読み直しません**
      （★0.5 秒ごとに JSON を読むより軽い、という正しい作りです）。

      ⚠ ところが検査は同じ `state.json` を**数マイクロ秒で 2 回**書きます。
        Windows の更新時刻はそこまで細かくないので、★2 回目が
        「変わっていない」と見なされ、**古い値が返ります**。

      ```text
      5 回まわしたときの失敗   1 / 1 / 1 / 3 / 2 件
      ⚠ 落ちる検査も毎回ちがう（★時刻の刻みに当たるかどうか）
      ```

      ⚠⚠ **「たまに落ちる」を放っておくと、本物の壊れが埋もれます。**

    ★だから、書いたあとに更新時刻を 1 秒進めます。
    """
    import os
    import time

    vm.state_path.write_text(json.dumps(body, ensure_ascii=False),
                             encoding="utf-8")
    later = time.time() + 1
    os.utime(vm.state_path, (later, later))


def _hex(tiles) -> str:
    return "".join("%02X" % (t & 0xFF) for t in tiles)


def test_画面から敵の一覧を組み立てる(tmp_path):
    tiles, groups = _battle_screen()
    vm = _vm(tmp_path, {"enemies": groups, "screen": _hex(tiles)})

    got = vm.enemy_groups()
    assert len(got) == len(groups)
    assert all(g["name"] for g in got), "⚠ 名前が出ていない群がある"
    assert [g["n"] for g in got] == [g["n"] for g in groups], (
        "⚠ 数が RAM と合っていない")


def test_画面が来ていなくても数は出る(tmp_path):
    """⚠ 窓は場面によって消える。★そのときも「何匹」は出せる。"""
    _tiles, groups = _battle_screen()
    vm = _vm(tmp_path, {"enemies": groups})

    got = vm.enemy_groups()
    assert len(got) == len(groups)
    # ★2026-09-03（RX3-0069）: 画面で読めていなくても、⚠ ROM から起こした名前は出す。
    #   ⚠⚠ 「知らないのに名前を作る」のではなく、★ユーザーの ROM に書いてある名前。
    from dq3.knowledge import rom_names
    want = rom_names.monster(groups[0]["id"]) if rom_names.available() else None
    assert got[0]["name"] == want, "⚠⚠ 画面が無いときの名前が ROM と違う: %r" % got[0]["name"]


def test_一度覚えたら画面が無くても名前が出る(tmp_path):
    tiles, groups = _battle_screen()
    vm = _vm(tmp_path, {"enemies": groups, "screen": _hex(tiles)})
    vm.enemy_groups()                       # ★ここで覚える

    _write_state(vm, {"enemies": groups})
    got = vm.enemy_groups()
    assert got[0]["name"], "⚠ 覚えたはずの名前が出ない"


def test_戦闘中でなければ空(tmp_path):
    vm = _vm(tmp_path, {"party": []})
    assert vm.enemy_groups() == []


def test_壊れた画面でも落ちない(tmp_path):
    _tiles, groups = _battle_screen()
    vm = _vm(tmp_path, {"enemies": groups, "screen": "ZZZ"})

    got = vm.enemy_groups()
    from dq3.knowledge import rom_names
    want = rom_names.monster(groups[0]["id"]) if rom_names.available() else None
    assert len(got) == len(groups) and got[0]["name"] == want


def test_下段の窓が敵を出している():
    """⚠ 実装があっても**呼ばれていなければ**意味が無い。"""
    src = (ROOT / "dq3" / "ui" / "battle_window.py").read_text(encoding="utf-8")
    i = src.index("def refresh(self)")
    assert "self.vm.battle_view()" in src[i:], "⚠⚠ 敵を出していない"
    assert "MonsterCard" in src[i:]


def test_一瞬空になっても表示を消さない():
    """⚠⚠ 戦闘の入りかけで群が取れない一瞬がある。

    ★そこで消すと、**画面がちらつく**。
    ⚠ 戦闘中は消さず、★終わってから消す。
    """
    src = (ROOT / "dq3" / "ui" / "battle_window.py").read_text(encoding="utf-8")
    i = src.index("groups, fighting = self.vm.battle_view()")
    j = src.index("self._show_enemies", i)
    body = src[i:j]
    assert "if not groups:" in body and "if not fighting:" in body, (
        "⚠⚠ 戦闘中でも表示を消している")


def test_知らない敵は中身を出さないと言う():
    """⚠⚠ **知らないことを、知らないと出す**。

    ★依頼者の選択（2026-08-30）は「1 度でも**倒したら**中身を出す」。
    ⚠ 会っただけの敵は、中身を出しません。
    """
    src = (ROOT / "dq3" / "ui" / "battle_window.py").read_text(encoding="utf-8")
    assert "まだ倒していないので、中身は出しません" in src, (
        "⚠⚠ 知らないことが分からない出し方")
    assert 'group.get("known")' in src, "⚠ 倒したかを見ていない"


def test_直近だと分かるように出す():
    """⚠⚠ **終わったものを「いま戦っている」と見せない**（依頼者 2026-08-30）。"""
    src = (ROOT / "dq3" / "ui" / "battle_window.py").read_text(encoding="utf-8")
    assert "（直近）" in src, "⚠⚠ 直近だと分からない"
    assert "if not fighting:" in src


# --- ★★ 会った / 倒した（RX3-0025 / 2026-08-30）---------------------------
#
#   依頼者の選択:「1 度でも**倒したら**中身を出す」（⚠ DQ2 の図鑑と同じ）

def test_倒すまで中身を出さない(tmp_path):
    """⚠⚠ **これが今回いちばん大事な検査**（★No-Spoiler）。"""
    from dq3.knowledge.enemies_seen import EnemyBook

    book = EnemyBook(tmp_path / "enemy.json")
    assert book.knows_details(0) is False

    # ⚠ 逃げた（★経験値が増えていない）
    book.record_battle([{"id": 0, "n": 1}], won=False)
    assert 0 in book.met, "⚠ 会ったことは覚える"
    assert book.knows_details(0) is False, "⚠⚠ 逃げたのに中身を出している"

    # ★倒した
    book.record_battle([{"id": 0, "n": 1}], won=True)
    assert book.knows_details(0) is True


def test_中身はROMから引く(tmp_path):
    """★敵の表（`RX3-0003`）から引く。⚠ ここに数字を書かない。"""
    from dq3.knowledge.enemies_seen import details_of

    got = details_of(0)
    if got is None:
        pytest.skip("⚠ ROM が無い環境")
    labels = [label for label, _v in got]
    assert "レベル" in labels and "最大HP" in labels and "経験値" in labels
    values = dict(got)
    assert values["レベル"] == 1 and values["最大HP"] == 8


def test_中身に数字を書いていない():
    """⚠⚠ **原作のデータを成果物へ焼かない**（`RX3-0011` ③）。"""
    src = SRC.read_text(encoding="utf-8")
    i = src.index("DETAIL_FIELDS")
    j = src.index("def details_of")
    # ⚠ 2026-09-01: `hp_raw`（下位 8 bit）→ `hp`（10 bit）に替えた
    #   ★`RX3-0033` で上位 2 bit が確定したため（⚠ HP 500 の敵が居る）
    assert '"hp"' in src[i:j], "⚠ 項目名は要る"
    # ★項目の**名前**だけで、値は書いていない
    for bad in ("= 8", "hp = ", "level = 1"):
        assert bad not in src[i:j], "⚠⚠ 値を書いている: %s" % bad


def test_知らない敵の番号を出しても落ちない():
    from dq3.knowledge.enemies_seen import details_of

    assert details_of(9999) is None
    assert details_of(-1) is None


def test_覚えたことが残る(tmp_path):
    from dq3.knowledge.enemies_seen import EnemyBook

    path = tmp_path / "enemy.json"
    book = EnemyBook(path)
    book.names[0] = "スライム"
    book.record_battle([{"id": 0, "n": 1}, {"id": 1, "n": 2}], won=True)
    assert book.save(force=True) is True

    again = EnemyBook.load(path)
    assert again.names[0] == "スライム"
    assert again.defeated == {0, 1}
    assert again.met == {0, 1}


def test_壊れた記録でも残りは読める(tmp_path):
    """⚠ 1 つ壊れていても、★残りは読めること。"""
    from dq3.knowledge.enemies_seen import EnemyBook

    path = tmp_path / "enemy.json"
    path.write_text(json.dumps({
        "names": {"0": "あ"}, "met": [0, "×"], "defeated": [0],
    }), encoding="utf-8")

    book = EnemyBook.load(path)
    assert book.defeated == {0} and 0 in book.met
    assert book.failed == 1


# --- ★★ 戦闘が終わっても残す ------------------------------------------------

def test_戦闘が終わっても直近が残る(tmp_path):
    """依頼者 2026-08-30:「戦闘が終わると消えちゃうので、
    戦闘が終わっても直近のモンスター情報を表示させたい」。"""
    tiles, groups = _battle_screen()
    vm = _vm(tmp_path, {"in_battle": True, "enemies": groups,
                        "screen": _hex(tiles), "party": []})

    got, fighting = vm.battle_view()
    assert fighting is True and len(got) == len(groups)

    # ★戦闘が終わった
    _write_state(vm, {"in_battle": False, "party": []})
    got, fighting = vm.battle_view()
    assert fighting is False, "⚠ まだ戦っていることになっている"
    assert len(got) == len(groups), "⚠⚠ 直近の敵が消えた"


def test_終わったものを今と見せない(tmp_path):
    """⚠⚠ 終わった戦闘を「いま戦っている」と見せない。"""
    tiles, groups = _battle_screen()
    vm = _vm(tmp_path, {"in_battle": True, "enemies": groups,
                        "screen": _hex(tiles), "party": []})
    vm.battle_view()
    _write_state(vm, {"in_battle": False, "party": []})

    _got, fighting = vm.battle_view()
    assert fighting is False


def test_勝ったかは経験値で見分ける(tmp_path):
    """⚠⚠ 「倒した」を**経験値が増えたか**で見る。

    ★逃げた・全滅したときは増えないので、これで見分けられる。
    """
    tiles, groups = _battle_screen()
    party = [{"name": "p1", "exp": 100}]
    vm = _vm(tmp_path, {"in_battle": True, "enemies": groups,
                        "screen": _hex(tiles), "party": party})
    vm.battle_view()

    # ★経験値が増えて終わった → 倒した
    _write_state(vm, {"in_battle": False, "party": [{"name": "p1", "exp": 140}]})
    vm.battle_view()

    for group in groups:
        assert vm.enemy_names.knows_details(group["id"]), (
            "⚠ 倒したのに覚えていない")


def test_逃げたら中身を出さない(tmp_path):
    """⚠⚠ 経験値が増えていなければ、★倒していない。"""
    tiles, groups = _battle_screen()
    party = [{"name": "p1", "exp": 100}]
    vm = _vm(tmp_path, {"in_battle": True, "enemies": groups,
                        "screen": _hex(tiles), "party": party})
    vm.battle_view()

    # ⚠ 経験値が変わらないまま終わった → 逃げた
    _write_state(vm, {"in_battle": False, "party": party})
    vm.battle_view()

    for group in groups:
        assert not vm.enemy_names.knows_details(group["id"]), (
            "⚠⚠ 逃げたのに中身を出している")
        assert int(group["id"]) in vm.enemy_names.met, "⚠ 会ったことは覚える"


def test_戦闘に入る前は空(tmp_path):
    vm = _vm(tmp_path, {"in_battle": False, "party": []})

    got, fighting = vm.battle_view()
    assert got == [] and fighting is False
# --- ⚠⚠ 戦闘メッセージを敵の行と間違えない（RX3-0063 / 2026-09-03）---------
#
#   ★2026-09-03 の実機で、⚠ 敵の名前が `あかりはダメ` になっていました。
#     「あかりは 2 の ダメージを うけた!」の **ダ「メー」ジ** の ー が、
#     敵の行の区切り（`0x7F`）と同じタイルだったためです。
#   ⚠ 敵 1 匹・該当行 1 本だと、**件数の歯止めも通ります**。


class _Box:
    def __init__(self, x, width):
        self.x, self.width = x, width


def _row(text, x=12, width=16):
    """★窓の左端 `x` から始まる 1 行を作る（⚠ ー の位置に区切りを置く）。"""
    from dq3.knowledge.enemies_seen import DASH_TILE, _split_row

    inside = bytearray(0x00 for _ in range(width + 2))
    for i, ch in enumerate(text[:width + 2]):
        if ch == "ー":
            inside[i] = DASH_TILE
    return _split_row("·" * x + text, _Box(x, width), bytes(inside))


def test_ダメージの文を敵の行にしない():
    """⚠⚠ ★これが RX3-0063 の本体。"""
    assert _row("␣あかりは␣2␣の␣ダメージを␣うけた!") is None
    assert _row("␣あかりは␣ダメージを␣うけた!␣␣") is None


def test_名前にーが入っていても読める():
    """⚠ 右から探す理由（★名前そのものに ー が入るものがある）。"""
    assert _row("␣キラーマシン␣␣ー␣2ひき·") == ("キラーマシン", 2)
    assert _row("␣スライム␣␣␣␣ー␣3ひき·␣␣") == ("スライム", 3)


def test_匹数のずれは数えるだけ(tmp_path):
    """⚠⚠ ★ここは一度「合わない回は覚えない」にして**失敗しました**。

    2026-09-03 の実機 run（`20260903_085554_fix-verify`）で
    ⚠ **会った 4 体 / 覚えた 0 件**になりました。
    ★戦闘中、窓の「N ひき」は**描き直されません**。
    ⚠ 1 匹倒した時点で RAM の匹数とずれ、そこから先は永久に覚えません。

    → ★メッセージ窓を弾くのは `_split_row` の**形**のほう。
      ⚠ 匹数のずれは**数えるだけ**にします（★覚えるのは止めない）。
    """
    from dq3.knowledge.enemies_seen import EnemyNames

    tiles, groups = _battle_screen()
    got = EnemyNames(path=tmp_path / "names.json")
    shifted = [{"id": g["id"], "n": g["n"] + 1} for g in groups]
    assert got.learn(shifted, tiles) == len(groups), (
        "⚠⚠ 匹数がずれただけで覚えなくなっている（★歯止めが強すぎる）")
    assert got.mismatched == len(groups), "⚠ ずれを数えていない"


def test_合っている回は今までどおり覚える(tmp_path):
    """⚠⚠ **歯止めを強くしすぎていないこと**。

    ★「覚えなくなった」は赤くならないので、⚠ ここで必ず見ます。
    """
    from dq3.knowledge.enemies_seen import EnemyNames

    tiles, groups = _battle_screen()
    got = EnemyNames(path=tmp_path / "names.json")
    assert got.learn(groups, tiles) == len(groups)
    assert all(got.names.values()), "⚠ 空の名前を覚えた"
def test_カーソルを名前に入れない():
    """⚠ 相手を選んでいるあいだ、敵の行の先頭に ▶ が出る。

    ★2026-09-03 の実機で `▶スライム` と読めていた
      （`work/runtime/dq3-probe/battle-screens.jsonl` #8 / #10 / #13）。
    """
    assert _row("▶スライム␣␣␣␣ー␣1ひき·␣␣") == ("スライム", 1)
    assert _row("␣いっかくうさぎ␣ー␣1ひき·") == ("いっかくうさぎ", 1)
def test_覚えられなかった理由が数で残る(tmp_path):
    """⚠⚠ ★「0 件」が続いていることに気づけるように（RX3-0065）。

    2026-09-03 の実機で **会った 4 体 / 覚えた 0 件**になったとき、
    ⚠ 記録には**何も出ていませんでした**。★数だけでも残します。
    """
    from dq3.knowledge.enemies_seen import EnemyNames

    tiles, groups = _battle_screen()
    got = EnemyNames(path=tmp_path / "names.json")

    # ★行が 1 本も読めない（⚠ 敵の一覧が画面に出ていない）
    assert got.learn(groups, [0] * (32 * 30)) == 0
    assert got.no_rows == 1, "⚠ 行なしを数えていない"

    # ⚠ 群のほうが多い（★一部しか出ていない）
    more = list(groups) + [{"id": 99, "n": 1}]
    assert got.learn(more, tiles) == 0
    assert got.partial == 1, "⚠ 一部だけを数えていない"

    # ★ちゃんと読めた回は覚える
    assert got.learn(groups, tiles) == len(groups)


def test_1群なら現れた行から覚える(tmp_path):
    """★DQ3 は群が 1 つのとき、敵の一覧を**出しません**（RX3-0065 実測）。

    ⚠ 出るのは「◯◯が␣あらわれた！」の 1 行だけ。
    """
    from dq3.knowledge.enemies_seen import APPEARED, _tidy

    got = APPEARED.match(_tidy("␣␣␣␣·アルミラージが␣あらわれた！␣␣␣␣·"))
    assert got and got.group(1) == "アルミラージ"
    # ⚠ 長すぎるものは名前ではない（★取り違え防止）
    assert APPEARED.match("あいうえおかきくけこさしすが␣あらわれた") is None
@pytest.mark.xfail(reason="⚠ 基準にしていたセーブが失われた（RX-0135）。★観点は docs/audit/tests-waiting-savestates.md", strict=False)
def test_開始直後の未初期化から覚えない(tmp_path):
    """⚠⚠ ★戦闘の開始直後、RAM が未初期化の値を返す枚がある（RX3-0065）。

    ```text
    実測（work/runtime/dq3-probe/battle-screens.jsonl）
      ids/n=[(0, 255)]                  ⚠ 匹数が 255
      ids/n=[(0,0),(0,0),(0,0),(0,0)]   ⚠ 全部 0
    ```

    ★そこで名前を覚えると、⚠ 間違った番号に名前が付き、**保存されます**。
    """
    from dq3.knowledge.enemies_seen import EnemyNames, _sane

    assert _sane({"id": 0, "n": 255}) is False
    assert _sane({"id": 0, "n": 0}) is False
    assert _sane({"id": 11, "n": 4}) is True

    tiles, _groups = _battle_screen()
    got = EnemyNames(path=tmp_path / "names.json")
    assert got.learn([{"id": 0, "n": 255}], tiles) == 0
    assert got.names == {}, "⚠⚠ 未初期化の群から覚えている"
# --- ★ROM の名前辞書との突き合わせ（RX3-0069 / 2026-09-03）--------------------
#
#   ★2 系統（画面読み / ROM）で互いを確かめる。⚠⚠ 不一致でも**上書きしない**。


def test_画面で読んだ名前はROMの名前と一致する(tmp_path):
    """★実機の画面（セーブ）から読んだ名前が、ROM から起こした名前と同じ。"""
    from dq3.knowledge import rom_names
    from dq3.knowledge.enemies_seen import EnemyNames

    if not rom_names.available():
        pytest.skip("⚠ ROM が無い環境: %s" % rom_names.last_error)
    tiles, groups = _battle_screen()
    got = EnemyNames(path=tmp_path / "names.json")
    assert got.learn(groups, tiles) == len(groups)
    assert got.rom_agree == len(groups) and got.rom_disagree == 0, (
        "⚠⚠ 画面と ROM で食い違い: %s" % got.mismatches)


def test_不一致は上書きせず残す(tmp_path):
    """⚠⚠ ROM と違っても、画面で読んだ名前を**勝手に直さない**（指示書 §9）。"""
    from dq3.knowledge import rom_names
    from dq3.knowledge.enemies_seen import EnemyNames

    if not rom_names.available():
        pytest.skip("⚠ ROM が無い環境")
    got = EnemyNames(path=tmp_path / "names.json")
    got._cross_check(0, "??")
    assert got.rom_disagree == 1 and got.mismatches[0]["id"] == 0
    assert got.mismatches[0]["screen"] == "??" and got.mismatches[0]["rom"]
    assert got.names == {}, "⚠⚠ 突き合わせが名前を書き換えている"
