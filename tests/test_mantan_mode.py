"""まんたんの回復目標モードのテスト（Python 側の配線）。

守りたい契約:
  1. 既定は 9割モード（ratio90）。依頼者の指定
  2. GUI からは**モード名だけ**を渡す（割合そのものは渡さない）
     -> 画面に出す名前と実際の挙動をずれさせないため
  3. モードを指定しないときは command.json に書かない
     （書くと config の設定を毎回上書きしてしまう）

★目標割合の計算そのものは Lua 側（mantan.lua）にあり、
  実機で検証している（work/hoimi/ratio_test.txt）:
    満タン -> しきい値 58/42 で両方が対象
    9割    -> しきい値 52/37 で両方が対象
    6割    -> しきい値 34/25 でサマルトリアだけ（41>=34 で除外）
    5割    -> 誰も対象でない（ボタンを1つも押さない）
  ここでは YAML の既定値と、Python -> Lua の受け渡しを固定する。
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from retroux.core.bridge.writer import write_command

CONFIG = (
    pathlib.Path(__file__).resolve().parents[1]
    / "retroux" / "plugins" / "dq2" / "config.yaml"
)


@pytest.fixture(scope="module")
def mantan_cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["mantan"]


def test_default_mode_is_ratio90(mantan_cfg):
    """既定は9割モード（依頼者の指定）。"""
    assert mantan_cfg["mode"] == "ratio90"


def test_modes_define_full_and_ratio90(mantan_cfg):
    modes = mantan_cfg["modes"]
    assert set(modes) >= {"full", "ratio90"}
    assert modes["full"]["target_ratio"] == 1.0
    assert modes["ratio90"]["target_ratio"] == 0.9
    # 画面に出す名前を持つこと（GUI がモード名だけで表示できるように）
    for name, mode in modes.items():
        assert mode.get("label"), f"{name} に label が無い"


def test_target_ratio_is_between_zero_and_one(mantan_cfg):
    """割合の範囲。1を超えると最大HPを超える目標になり、0以下だと常に達成扱いになる。"""
    for name, mode in mantan_cfg["modes"].items():
        r = mode["target_ratio"]
        assert 0 < r <= 1.0, f"{name}: {r}"


def test_mode_is_sent_as_name_not_ratio(tmp_path):
    """GUI からはモード名だけを渡す。

    割合そのものを渡さないのは、画面に出す名前と実際の挙動を
    ずれさせないため（名前と割合の対応は config が唯一の正）。
    """
    path = tmp_path / "command.json"
    write_command(path, encountered=[], mantan_mode="ratio90")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mantan_mode"] == "ratio90"
    assert "target_ratio" not in payload


def test_mode_is_absent_when_not_specified(tmp_path):
    """指定しないときは書かない。

    毎回書くと config の設定を上書きしてしまい、
    「設定を変えたのに反映されない」という混乱になる。
    """
    path = tmp_path / "command.json"
    write_command(path, encountered=[1])
    assert "mantan_mode" not in json.loads(path.read_text(encoding="utf-8"))


def test_mode_is_parseable_by_lua_style_regex(tmp_path):
    """Lua 側は正規表現で拾うため、その形で読めること。"""
    import re

    path = tmp_path / "command.json"
    write_command(path, encountered=[], mantan_mode="full")
    body = path.read_text(encoding="utf-8")
    m = re.search(r'"mantan_mode"\s*:\s*"([\w_]+)"', body)
    assert m and m.group(1) == "full"


def test_cli_accepts_mode(tmp_path, monkeypatch):
    """CLI からモードを指定できること（GUI 実装前の切り替え手段）。"""
    from retroux import mantan as mantan_cli

    path = tmp_path / "command.json"
    monkeypatch.setattr(mantan_cli, "_command_path", lambda: path)
    assert mantan_cli.main(["--mode", "full"]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["mantan_mode"] == "full"
