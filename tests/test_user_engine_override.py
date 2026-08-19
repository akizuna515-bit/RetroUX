"""`user_config.yaml` から判断エンジンを上書きする（Phase 10A / 2026-08-07）。

## ⚠⚠ なぜ要るか（★実際に困りました）

`engine: layered` を実機で試そうとして、`work/generated/config.lua` を
手で書き換えました。⚠ ところが `start-retroux.ps1` は**起動のたびに
`generate_lua` を実行**するため、★書き換えは必ず消えます。

結果、ログにこう出て**veto を1件も確認できませんでした**:

    [戦術] 省資源（適合度 4.5）※まだ効かせていません

## ★ 役割の分け方

    retroux/plugins/dq2/config.yaml … ★ゲームの知識（⚠ 触らない）
    user_config.yaml                … ★利用者・環境ごとの選択

⚠ `engine` はどちらかといえば後者なので、こちらで上書きします。
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from retroux.core.config import generate_lua

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _base() -> dict:
    return {"auto_input": {"engine": "legacy", "heal": {}}}


def test_上書きが無ければ触らない(tmp_path, monkeypatch):
    """⚠ 設定が無いのは**普通のこと**。★既定のまま動きます。"""
    monkeypatch.setattr(generate_lua, "PROJECT_ROOT", tmp_path)
    got = generate_lua._apply_user_overrides(_base())
    assert got["auto_input"]["engine"] == "legacy"


def test_上書きが効く(tmp_path, monkeypatch, capsys):
    """★★★ **これが本題**。"""
    (tmp_path / "user_config.yaml").write_text(
        "battle:\n  engine: layered\n", encoding="utf-8")
    monkeypatch.setattr(generate_lua, "PROJECT_ROOT", tmp_path)
    got = generate_lua._apply_user_overrides(_base())
    assert got["auto_input"]["engine"] == "layered"
    # ★★ **黙って変えない**（⚠ 何が効いているか分からなくなります）
    out = capsys.readouterr().out
    assert "user_config.yaml で上書き" in out
    assert "元は 'legacy'" in out, out


def test_他の項目を壊さない(tmp_path, monkeypatch):
    """⚠ 上書きのついでに別の設定を消さないこと。"""
    (tmp_path / "user_config.yaml").write_text(
        "battle:\n  engine: layered\n", encoding="utf-8")
    monkeypatch.setattr(generate_lua, "PROJECT_ROOT", tmp_path)
    got = generate_lua._apply_user_overrides(_base())
    assert "heal" in got["auto_input"]


def test_壊れていても止まらない(tmp_path, monkeypatch, capsys):
    """⚠⚠ **設定が壊れていても起動できること。**

    ★ここで止めると、利用者が**編集を間違えただけで遊べなくなります**。
    """
    (tmp_path / "user_config.yaml").write_text(
        "battle: [これは\n  壊れた yaml", encoding="utf-8")
    monkeypatch.setattr(generate_lua, "PROJECT_ROOT", tmp_path)
    got = generate_lua._apply_user_overrides(_base())
    assert got["auto_input"]["engine"] == "legacy"
    # ★黙って無視しない
    assert "読めません" in capsys.readouterr().out


def test_原本を書き換えていない():
    """★★ `config.yaml`（ゲームの知識）は `legacy` のままであること。

    ⚠ ここが `layered` になっていたら、★**全員の挙動が変わります**。
    """
    cfg = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "config.yaml").read_bytes().decode("utf-8"))
    assert cfg["auto_input"]["engine"] == "legacy", (
        "⚠⚠ 原本が legacy ではありません。★試すなら user_config.yaml で")


def test_生成に組み込まれている():
    """⚠ 関数を作っただけで**呼んでいない**、をやらないこと。

    ★2026-08-07 に8回踏んだ失敗の型です。
    """
    source = (PROJECT_ROOT / "retroux" / "core" / "config"
              / "generate_lua.py").read_bytes().decode("utf-8")
    assert "data = _apply_user_overrides(data)" in source, (
        "⚠⚠ 上書きを生成に組み込んでいません")
