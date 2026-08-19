"""設定スキーマの版（Phase 10 / 2026-08-07）。

指示書 §18 Phase 10「設定スキーマのバージョニング」。

## ⚠⚠ なぜ要るか

★将来 DQ3 などを足すとき、**古い形の設定をそのまま読む**と
「設定したつもりの項目が黙って捨てられる」ことになります。
⚠ これは**いちばん気づきにくい壊れ方**です（★エラーで落ちるほうがまし）。

## ★ 決めごと

    版が無い    -> ⚠ 知らせて、いまの版として読む（★古い設定を動かす）
    版が違う    -> ⚠⚠ **止める**（★黙って読まない）
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = PROJECT_ROOT / "retroux" / "plugins" / "dq2"

from retroux.core.config import generate_lua  # noqa: E402


@pytest.mark.parametrize("name", ["config.yaml", "memory_map.yaml"])
def test_プラグイン設定に版がある(name):
    """★★ 版が無いと、形が変わったことに気づけません。"""
    data = yaml.safe_load((PLUGIN / name).read_bytes().decode("utf-8"))
    assert data.get("schema_version") == generate_lua.SUPPORTED_SCHEMA, (
        f"⚠ {name} の版が違います: {data.get('schema_version')!r}")


def test_知らない版なら止まる(tmp_path):
    """★★★ **これが本題**。⚠ 黙って読んだら意味がありません。"""
    path = tmp_path / "future.yaml"
    path.write_text("schema_version: 99\nspeed: {}\n", encoding="utf-8")
    with pytest.raises(ValueError) as got:
        generate_lua.load_yaml(path)
    assert "読めない設定スキーマ" in str(got.value)
    # ⚠ 何をすればよいかまで書く（★「読めません」だけでは動けない）
    assert "直すか" in str(got.value)


def test_版が無くても止まらない(tmp_path, capsys):
    """⚠ 古い設定でも**動く**こと。★止めるのは「違う版」だけ。

    ⚠⚠ ここで止めると、版を足す前の設定を持っている人が
      **いきなり起動できなくなります**。
    """
    path = tmp_path / "old.yaml"
    path.write_text("speed: {}\n", encoding="utf-8")
    got = generate_lua.load_yaml(path)
    assert got == {"speed": {}}
    # ★黙って読まない（知らせる）
    assert "schema_version がありません" in capsys.readouterr().out


def test_いまの版で読める(tmp_path):
    path = tmp_path / "now.yaml"
    path.write_text(
        f"schema_version: {generate_lua.SUPPORTED_SCHEMA}\nspeed: {{}}\n",
        encoding="utf-8")
    assert generate_lua.load_yaml(path)["speed"] == {}


def test_版を下げていない():
    """⚠ 版は上がるだけです。★下げると古い設定が通ってしまいます。"""
    assert generate_lua.SUPPORTED_SCHEMA >= 1
