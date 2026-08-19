"""地図の素材の置き場所が、設定から**実際に**引かれること（2026-08-12）。

バックログ P0-01（`docs/project/RETROUX_BACKLOG.md`）:

    retroux/gui.py:126               → map.assets_dir を読む
    retroux/plugins/dq2/config.yaml  → map.rendering.assets_path にある
    実測                             → map.assets_dir は None（既定へ落ちる）

★落ちはしませんが、**設定しても効きません**でした。
⚠ 黙って無視される種類の不具合は、あとで原因を追いにくいです
（「素材が無いのは採取漏れか、設定か」が分かりません）。

⚠⚠ **鍵の名前を写経しないこと。** ここでは実際の `config.yaml` を読んで、
  そこに書いてある値が返ってくるかを見ます。★片方だけ直しても赤くなります。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.catalog import (
    DEFAULT_ASSETS_REL, resolve_assets_dir)
from retroux.core.config.generate_lua import load_yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_CONFIG = (PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml")


def test_本物の設定に書いてある場所が返る():
    """★実際の `config.yaml` を読む（鍵の名前をテストへ写さない）。

    ⚠⚠ **これ1つでは不具合を捕まえられません。**
      いま `assets_path` に書いてある値は既定と同じ `work/map-assets` なので、
      ★鍵を読み違えて既定へ落ちても**同じ答え**になります
      （わざと戻して確認済み: この検査は緑のままでした）。
      だから下の「設定を変えたら結果も変わる」が要ります。
    """
    config = load_yaml(PLUGIN_CONFIG)
    written = ((config.get("map") or {}).get("rendering") or {}).get(
        "assets_path")
    assert written, "⚠ config.yaml に assets_path がありません"
    assert resolve_assets_dir(config, PROJECT_ROOT) == PROJECT_ROOT / written


def test_設定を変えたら結果も変わる():
    """★★★ **これが P0-01 そのもの**。

    ⚠ 直す前は、何を書いても既定（`work/map-assets`）が返っていました。
    """
    changed = resolve_assets_dir(
        {"map": {"rendering": {"assets_path": "work/別の場所"}}},
        PROJECT_ROOT)
    assert changed == PROJECT_ROOT / "work/別の場所"
    assert changed != PROJECT_ROOT / DEFAULT_ASSETS_REL


def test_古い名前も読む():
    """⚠ `map.assets_dir` と書いてある設定を、こちらの都合で無効にしない。"""
    assert resolve_assets_dir(
        {"map": {"assets_dir": "work/古い名前"}},
        PROJECT_ROOT) == PROJECT_ROOT / "work/古い名前"


def test_新しい名前が優先される():
    """⚠ 両方あるときに古いほうを採ると、直したつもりが効きません。"""
    assert resolve_assets_dir(
        {"map": {"assets_dir": "work/古い", "rendering": {
            "assets_path": "work/新しい"}}},
        PROJECT_ROOT) == PROJECT_ROOT / "work/新しい"


@pytest.mark.parametrize("config", [
    {}, {"map": None}, {"map": {}}, {"map": {"rendering": None}},
    {"map": {"rendering": {}}}, {"map": {"rendering": {"assets_path": None}}},
])
def test_書いていなければ既定へ落ちる(config):
    """⚠ 無くても動くこと（★ここで落ちると本体が起動しません）。"""
    assert resolve_assets_dir(config, PROJECT_ROOT) == (
        PROJECT_ROOT / DEFAULT_ASSETS_REL)


def test_道具も同じ場所を見る():
    """⚠⚠ **片方だけが設定に従うと、作った素材を GUI が見つけられません。**

    ★`dq2_map` の既定と `resolve_assets_dir` が一致すること。
    """
    from retroux.tools.dq2_map import default_assets

    config = load_yaml(PLUGIN_CONFIG)
    assert default_assets() == resolve_assets_dir(config, PROJECT_ROOT)


def test_GUIが古い鍵を直接読んでいない():
    """⚠ `gui.py` が `assets_dir` を直に読む形へ戻っていたら赤くする。

    ★鍵の解決は `resolve_assets_dir` の1か所に閉じ込めます。
    """
    source = (PROJECT_ROOT / "retroux" / "gui.py").read_bytes().decode("utf-8")
    assert 'get("assets_dir"' not in source, (
        "⚠⚠ 設定にない鍵を直接読んでいます（黙って既定へ落ちます）")
    assert "resolve_assets_dir(config, PROJECT_ROOT)" in source
