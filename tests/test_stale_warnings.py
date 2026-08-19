"""直したのに残る警告（2026-08-08 / 依頼者の報告）。

    > 警告は「遭遇済みキャッシュに・・」はまだ出てる

## ⚠⚠ 直したのに出続けていた理由

`work/encountered.txt` は直しました（★先頭の `0` を除いて書き直し済み）。
⚠ しかし画面に出る警告は `work/events.jsonl` を**読み直して**組み立てます。
★そこには**過去 612 件**の同じ警告が残っていました。

    2026-08-07 の警告 -> 今日の画面に出る

⚠⚠ 警告は「**いまどうなっているか**」の話です。
★終わった起動の苦情を出し続けるのは、**直したのに直っていないように
見せる**嘘になります。

→ ★`session_start` を読んだら、それまでの警告を捨てます。
  ⚠ Lua は `session_start` を**警告より先に**出すので、
    ★その起動の警告はちゃんと残ります。
"""

from __future__ import annotations

import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


@pytest.fixture
def recorder(tmp_path):
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder

    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    return Recorder(db, "HASH", events, tmp_path / "command.json")


def _event(payload: dict):
    """⚠ 実際に Lua が書く1行を通す（★手で組み立てて食い違わせない）。"""
    import json

    from retroux.core import events as ev

    got = ev.parse_line(json.dumps({"frame": 0, **payload}))
    assert got is not None, payload
    return got


def test_古い起動の警告は次の起動で消える(recorder):
    """★★★ **依頼者の報告そのもの**。"""
    recorder.handle(_event({"type": "warning", "code": "encountered_cache_broken",
                            "message": "遭遇済みキャッシュに読めない行が 1 件"}))
    assert recorder.stats.warnings, "⚠ 前提が崩れています（警告が入らない）"

    recorder.handle(_event({"type": "session_start", "rom": "DQ2"}))
    assert recorder.stats.warnings == [], (
        "⚠⚠ 起動し直しても前の起動の警告が残っています"
        "（★直したのに直っていないように見えます）")


def test_消したあと同じ警告をまた出せる(recorder):
    """⚠⚠ **重複よけの印まで残すと、今度は本物が出なくなります。**

    ★`warning_codes` を消し忘れると、⚠ 次の起動で同じ問題が起きていても
      「もう出した」と判断されて**黙ります**。
    """
    warning = _event({"type": "warning", "code": "encountered_cache_broken",
                      "message": "遭遇済みキャッシュに読めない行が 1 件"})
    recorder.handle(warning)
    recorder.handle(_event({"type": "session_start", "rom": "DQ2"}))
    recorder.handle(warning)
    assert len(recorder.stats.warnings) == 1, (
        "⚠⚠ 起動し直したのに、いま起きている問題が出ません")


def test_消すのは警告だけ(recorder):
    """⚠ 積み上げた戦闘の記録まで消さないこと。"""
    recorder.stats.battles_recorded = 7
    recorder.handle(_event({"type": "session_start", "rom": "DQ2"}))
    assert recorder.stats.battles_recorded == 7


def test_Luaは起動を警告より先に出す():
    """★★★ **順番が逆なら、その起動の警告まで消えます。**

    ⚠⚠ ここが崩れると、⚠ **本当に出したい警告が1件も出なくなります**。
      ★静かに壊れるので、字面ではなく**順番**を見張ります。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    at_session = source.index('self:emit("session_start"')
    at_warn = source.index('self:emit("warning"')
    assert at_session < at_warn, (
        "⚠⚠ 警告を session_start より先に出しています"
        "（★その起動の警告が消えます）")


# --- ⚠ 「知らない項目 battle は無視されます」は嘘だった -------------------


def test_battleの設定を知らない項目と言わない(tmp_path):
    """⚠⚠ 実機ログに毎回出ていた警告（2026-08-08）:

        [WARNING] gui user_config.yaml: 知らない項目 battle は無視されます

    ★`generate_lua.py` は `battle.engine` を**読んでいます**。
      ⚠ 無視されていないのに「無視されます」と出るのは嘘で、
        「効いていないのでは」と疑わせるだけでした。
    """
    from retroux.core.config.user_config import load

    path = tmp_path / "user_config.yaml"
    path.write_text("battle:\n  engine: layered\n", encoding="utf-8")
    cfg, warnings = load(path)
    assert cfg.battle.engine == "layered"
    assert warnings == [], warnings


def test_既定は従来どおり():
    """⚠ 書かなければ `legacy`（★挙動を勝手に変えない）。"""
    from retroux.core.config.user_config import UserConfig

    assert UserConfig().battle.engine == "legacy"


def test_読む側と生成側で同じ名前を使っている():
    """⚠⚠ **測り方を2か所に書かない。**

    ★`generate_lua.py` の対応表と、画面が読む項目名が揃っていること。
    """
    source = (PROJECT_ROOT / "retroux" / "core" / "config"
              / "generate_lua.py").read_bytes().decode("utf-8")
    assert '("battle", "engine")' in source, (
        "⚠ 生成側の項目名が変わりました（★読む側も直してください）")


# --- ⚠ 敵の絵が1戦ぶん遅れる（依頼者の報告）-----------------------------


def test_絵が切り出せたらその場で図鑑に出す():
    """⚠ 依頼者「１回モンスターグラフィックが出ない場面があった」。

    ★図鑑は**戦闘が変わったときだけ**並べ直します。⚠ 切り出しはその後に
      走るので、★初めて見た敵の絵は「1戦ぶん遅れて」出ていました。
    """
    source = ((PROJECT_ROOT / "retroux" / "ui" / "main_window.py")
              .read_bytes().decode("utf-8"))
    at = source.index("def _trim_and_show_art")
    body = source[at:at + 2000]
    assert "self._encounter.update_encounter" in body, (
        "⚠ 切り出したあと図鑑を並べ直していません")
    assert "if not made:" in body, (
        "⚠ 何も出来ていなくても描き直しています（★無駄な描き直し）")
