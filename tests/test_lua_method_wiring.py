"""Lua の「呼んでいるのに定義が無い」を見つける（2026-08-01）。

★★ **この穴は構文チェックでは捕まらない。** ★★

  Lua は `self:no_such_method()` を**実行するまで**エラーにしない。
  `research/probes/reusable/luacheck.py`（`loadstring` による構文検査）は素通りする。

⚠⚠ 実際に踏んだ（リファクタ Phase 2 / 2026-08-01）:
  ファイルを分けるとき、**呼び出しだけを残して関数の挿入に失敗**した。
  構文チェックは 13/13 で通り、pytest も 1,187 件すべて緑。
  ⚠ **実機のスモークテストで初めて**「AUTO も高速化も効かない」と出た。

★だから機械で見張る。⚠ 内部の関数名を固定するテストではない
  （名前は何でもよい。**呼ぶ側と定義が対応していること**だけを見る）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
LUA_DIR = PROJECT_ROOT / "retroux" / "emulator" / "fceux"


def _code_only(source: str) -> str:
    """注釈を落として**コードだけ**にする。

    ⚠ 落とさないと、解説文に書いた `self:foo()` を「呼び出し」と数える。
    """
    out = []
    for line in source.splitlines():
        if line.strip().startswith("--"):
            continue
        out.append(line.split("--", 1)[0] if "--" in line else line)
    return "\n".join(out)


@pytest.mark.parametrize("name,klass", [
    ("bridge.lua", "Bridge"),
    ("battle_controller.lua", "BattleController"),
    ("speed_controller.lua", "SpeedController"),
    ("command_reader.lua", "CommandReader"),
])
def test_every_called_method_is_defined(name, klass):
    """★★ `self:xxx()` で呼ぶものは、そのファイルに定義があること。 ★★"""
    path = LUA_DIR / name
    if not path.exists():                              # pragma: no cover
        pytest.skip(f"{name} が無い")
    code = _code_only(path.read_text(encoding="utf-8"))

    defined = set(re.findall(rf"function {klass}[:.](\w+)", code))
    called = set(re.findall(r"self:(\w+)\(", code))
    missing = sorted(called - defined)
    assert missing == [], (
        f"{name}: 呼んでいるのに定義が無いメソッド {missing}\n"
        "★分割の途中で「呼び出しだけ残して関数を移し忘れた」形です。")
