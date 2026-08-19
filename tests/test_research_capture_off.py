"""研究用の採取を通常運用から分ける（§22 / 完了条件 #13）。

## ⚠⚠ 何が足りていなかったか

Phase 3 で `monster_art` / `tile_shot` のログを DEBUG へ落としたが、
★**採取そのものは製品ランタイムの中で動いたまま**だった。

指示書 §20・§21 は NORMAL でも DIAGNOSTIC でも
**research capture を OFF** と定めており、§22 は専用ツールへ寄せることを求めている。

## ⚠ 「絵を撮るのをやめる」話ではない

★モンスターの絵は `python -m dq2rom monsters extract`（ROM から）で
**82 体そろっており**、実機の撮影10枚と画素まで一致している。
★画面からの採取は**その確かめのため**の研究作業。

## ⚠ ログの段階とは別にした

★研究は「ログを多く出す」ことではなく「別の仕事をする」こと。
第3のログレベル（`research`）にすると混ざるので、`research.capture` を別に置いた。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
PLUGIN_CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
GENERATED = PROJECT_ROOT / "work" / "generated" / "config.lua"


def test_既定は切():
    from retroux.core.config.user_config import ResearchConfig

    assert ResearchConfig().capture is False


def test_設定が未知項目扱いされない():
    """⚠ 2026-08-08 に `battle` で同じことが起きた。

        [WARNING] gui user_config.yaml: 知らない項目 battle は無視されます

    ★これは**嘘**の警告で、「効いていないのでは」と疑わせるだけだった。
    """
    from retroux.core.config import user_config as uc

    cfg, warnings = uc.load()
    bad = [w for w in warnings if "research" in w]
    assert bad == [], bad
    assert hasattr(cfg, "research")


def test_ゲーム側の設定にも既定がある():
    """★`user_config.yaml` が無くても動くこと。"""
    import yaml

    data = yaml.safe_load(PLUGIN_CONFIG.read_text(encoding="utf-8"))
    assert data.get("research", {}).get("capture") is False


def test_生成物へ渡っている():
    """⚠ ここを通さないと **Lua だけ常に採取する**。"""
    if not GENERATED.exists():
        pytest.skip("生成物が無い")
    body = GENERATED.read_text(encoding="utf-8")
    assert "research = {" in body, "research が生成物に無い"
    block = body.split("research = {")[1][:120]
    assert "capture =" in block, block


def test_上書き経路がある():
    from retroux.core.config.generate_lua import USER_OVERRIDES

    assert ("research", "capture") in USER_OVERRIDES


# --- ★★ Lua 側の門（要）--------------------------------------------------

def test_採取が門の内側にある():
    """★★ **これが本体**。設定だけ足して門を作り忘れる、を防ぐ。"""
    src = BRIDGE.read_text(encoding="utf-8")
    block = src.split("function Bridge:_arm_monster_art")[1][:2200]
    assert "(self.research or {}).capture == true" in block, block[:600]
    # ★門は「撮る対象を探す」より**前**にあること
    gate = block.index("(self.research or {}).capture == true")
    scan = block.index("local out_dir")
    assert gate < scan, "門が採取の準備より後ろにある（★無駄に走る）"


def test_切っていることを黙って隠さない():
    """⚠ 「撮れない」と「撮らない」を取り違えさせない。

    ★1回だけ理由を出す（毎戦闘は出さない）。
    """
    src = BRIDGE.read_text(encoding="utf-8")
    block = src.split("function Bridge:_arm_monster_art")[1][:2200]
    assert "art_off_told" in block, "1回だけ知らせる仕掛けが無い"
    assert "research.capture" in block, "戻し方が書かれていない"


def test_設定をLuaが読んでいる():
    src = BRIDGE.read_text(encoding="utf-8")
    assert "self.research = self.config.research or {}" in src


# --- ⚠ 利用者が要求する採取は別（tile_shot）------------------------------

def test_利用者が頼む採取は残っている():
    """★`tile_shot` は command.json 経由の**明示要求**。

    ⚠ 自動で走るものと、人が押して走るものを混ぜない。
      ★人が頼んだのに黙って何もしないほうが、よほど分かりにくい。
    """
    src = BRIDGE.read_text(encoding="utf-8")
    assert 'self:emit("tile_shot"' in src
    block = src.split('self:emit("tile_shot"')[0][-2500:]
    assert "(self.research or {}).capture" not in block, (
        "利用者が頼む採取まで切っている")
