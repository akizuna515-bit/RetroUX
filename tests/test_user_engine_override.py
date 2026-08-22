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


def test_原本の既定エンジンはlayered():
    """★★ 同梱の既定は `layered`（2026-08-20 依頼者の指定 / RX-0089）。

    ★かつては「原本は legacy のまま」を守るテストだった。既定を layered に
      した判断ごとここで固定する（⚠ 黙って戻さない・黙って進めない）。
      フォールバック（未指定・不明名）が legacy のままであることは
      tests/test_battle_types.py::test_フォールバックはlegacy が見る。
    """
    cfg = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "config.yaml").read_bytes().decode("utf-8"))
    assert cfg["auto_input"]["engine"] == "layered", (
        "⚠⚠ 同梱の既定が layered ではありません（RX-0089 を参照）")


def test_生成に組み込まれている():
    """⚠ 関数を作っただけで**呼んでいない**、をやらないこと。

    ★2026-08-07 に8回踏んだ失敗の型です。
    """
    source = (PROJECT_ROOT / "retroux" / "core" / "config"
              / "generate_lua.py").read_bytes().decode("utf-8")
    assert "data = _apply_user_overrides(data)" in source, (
        "⚠⚠ 上書きを生成に組み込んでいません")


def test_生成に組み込まれているの挙動(tmp_path, monkeypatch):
    """★RX-0011: 字面の検査に挙動を併設。

    ★`generate_lua.main()` を**そのまま**（出力先だけ tmp に向けて）回し、
      `user_config.yaml` の `battle.engine` が出来上がった `config.lua` の
      `auto_input.engine` に入ることを見ます。
    ⚠ 同梱の既定が layered なので、上書きは **legacy** で試します
      （既定と同じ値では「効いた」のか「元からそう」なのか分かりません）。
    """
    out_dir = tmp_path / "generated"
    (tmp_path / "user_config.yaml").write_text(
        "battle:\n  engine: legacy\n", encoding="utf-8")
    monkeypatch.setattr(generate_lua, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(generate_lua, "OUT_DIR", out_dir)

    assert generate_lua.main() == 0

    body = (out_dir / "config.lua").read_bytes().decode("utf-8")
    block = body.split("auto_input = {")[1]
    assert 'engine = "legacy"' in block[:4000], block[:600]
    assert 'engine = "layered"' not in block[:4000], (
        "⚠⚠ user_config.yaml の上書きが生成物に届いていません")
