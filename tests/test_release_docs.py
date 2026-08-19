"""公開に要る文書がそろっていること（RX-0059 / チェックリスト §6）。

## ⚠⚠ なぜ検査するか

2026-08-18 に実測したら、⚠ **1つも書いてありませんでした**:

    対応 ROM のハッシュ    0 件
    著作権上の注意        0 件
    ROM 非同梱の説明      0 件
    トラブルシューティング  0 件

★README は**配布物の顔**で、⚠ 著作権の注意が無いまま公開するのは危険です。

## ★ 「書いてある」で満足しない

⚠ 字面だけ見る検査は、この計画で何度もすり抜けました（F-089）。
★ここでは**中身が実装と合っているか**まで見ます:

  ・ハッシュは `memory_map.yaml` と**同じ値**か
  ・書いてある手順のコマンドが**実在**するか
"""

from __future__ import annotations

import pathlib
import sys

import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

README = PROJECT_ROOT / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


# --- ⚠ ROM の扱い -------------------------------------------------------

def test_ROM非同梱の説明がある():
    body = _readme()
    assert "ROM は同梱していません" in body or "同梱していません" in body, (
        "⚠ ROM を同梱していないことが書かれていない")
    # ⚠⚠ **`"work\rom"` と書かないこと**（★Python が `\r` を復帰文字と読む）。
    #   ヒアドキュメント越しに書いて実際に潰れた（2026-08-18 / 記憶にある罠）。
    assert r"work\rom" in body, "★置き場所が書かれていない"


def test_対応ROMのハッシュが書いてある():
    """★★ ⚠⚠ **実装と同じ値であること** ★★

    ⚠ 「ハッシュが書いてある」だけでは足りない。
      ★`memory_map.yaml` とずれていたら、読んだ人が確かめられない。
    """
    want = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "memory_map.yaml").read_text(encoding="utf-8"))["rom"]
    body = _readme()
    assert want["prg_sha256"] in body, (
        "⚠ README のハッシュが memory_map.yaml と違う（★確かめられない）")
    assert want["prg_crc32"] in body, "★CRC32 も書く"


def test_違うROMで止まることが書いてある():
    """⚠ 止まる理由が分からないと、利用者は「壊れた」と思う。"""
    body = _readme()
    assert "求めている ROM ではありません" in body, (
        "★止まったときに出る文言が書かれていない")
    assert "勝手に押す" in body or "見当違いのタイミング" in body, (
        "⚠ **なぜ止めるのか**が書かれていない")


def test_ハッシュの確かめ方が実際に動く():
    """★★★ ⚠⚠ **書いてあるコマンドが動くこと** ★★★

    ⚠ 手順は「書いてある」だけでは意味がない。
      ★README が案内している関数を、実際に呼んで確かめる。
    """
    from retroux.core.rom import identify

    rom = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
    if not rom.exists():
        import pytest

        pytest.skip("ROM がありません")
    want = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "memory_map.yaml").read_text(encoding="utf-8"))["rom"]
    assert identify(rom).prg_sha256 == want["prg_sha256"]


# --- ⚠ 著作権 -----------------------------------------------------------

def test_著作権の注意がある():
    body = _readme()
    assert "著作権" in body, "⚠⚠ 著作権の注意が無い"
    for word in ("再配布", "非公式"):
        assert word in body, f"★「{word}」に触れていない"


def test_改変しないことが書いてある():
    """★RetroUX の立ち位置（⚠ ROM を書き換えない）を明記する。"""
    body = _readme()
    assert "ゲームを改変しません" in body or "ROM も書き換えません" in body, (
        "★改造ツールではないことが書かれていない")


# --- ⚠ 制限とトラブルシューティング --------------------------------------

def test_できないことが書いてある():
    body = _readme()
    assert "できないこと" in body or "既知の制限" in body, (
        "⚠ 制限の一覧が無い（★「動くはず」と思われる）")
    # ★実装の実態と合っていること（⚠ 直したら書き換える）
    assert "RetroUX.vbs" in body and "止まりません" in body, (
        "⚠ `.vbs` を閉じても FCEUX が残ることが書かれていない")


def test_トラブルシューティングがある():
    body = _readme()
    assert "うまくいかないとき" in body, "⚠ 困ったときの節が無い"
    # ★まずログを見る、が書いてあること
    assert "retroux.log" in body, "★見るべきログが書かれていない"
    for symptom in ("起動しない", "数値がでたらめ", "地図が青いだけ"):
        assert symptom in body, f"★「{symptom}」の行が無い"


def test_ログの置き場が実装と合っている():
    """⚠ 案内したログが実際の出力先と違うと、見ても何も無い。"""
    from retroux.core.config import user_config as uc

    got, _ = uc.load()
    where = str(got.path("log")).replace("\\", "/")
    assert where.endswith("retroux.log"), where
    assert "retroux.log" in _readme()


# --- ⚠ 手順が通ること ---------------------------------------------------

def test_準備の手順に書いた生成物が実在する():
    """★`generate_lua` が作ると書いた3本が、実際にその名前であること。"""
    from retroux.core.config import generate_lua

    body = _readme()
    for name in ("memory_map.lua", "config.lua", "keybindings.lua"):
        assert name in body, f"★{name} を案内していない"
    # ⚠ 生成物の名前はソースに直書きされていない（`f"{name}.lua"` で作る）。
    #   ★元になる YAML が実在することで確かめる。
    plugin = PROJECT_ROOT / "retroux" / "plugins" / "dq2"
    for name in ("memory_map", "config"):
        assert (plugin / f"{name}.yaml").exists(), (
            f"⚠ {name}.yaml が無い（★{name}.lua は作られない）")
    # ★キーバインドは YAML ではなく `core/keybindings.py` が書き出す
    src = pathlib.Path(generate_lua.__file__).read_text(encoding="utf-8")
    assert "write_keybindings" in src, (
        "⚠ keybindings.lua は作られない（★案内が嘘）")
    assert "write_lua_module" in src


def test_ROMを先に置けと書いてある():
    """⚠ 順番を間違えると `generate_lua` の後で起動に失敗する。"""
    body = _readme()
    i = body.index("### 準備（初回のみ）")
    head = body[i:i + 400]
    assert "先に ROM を置いて" in head, (
        "★準備の冒頭に「先に ROM を置く」が無い")
