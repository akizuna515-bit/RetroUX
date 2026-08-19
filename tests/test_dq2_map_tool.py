"""地図をこしらえる道具（2026-08-02 / マップ指示書 §17）。

★★ 守りたい契約 ★★

  1. ⚠ 既定は**数えるだけ**。`--apply` で初めて書く
  2. ⚠⚠ FIELD_IDLE 以外の採取は飛ばす（指示書 §6.2）
  3. ⚠⚠ 黒観測は結びつけない（指示書 §11.2）
  4. ⚠ CHR の半分を決めきれないときは飛ばす（推測で描かない）
  5. 素材が無くても落ちない
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.tools import dq2_map


def _write_capture(path: pathlib.Path, *, state="FIELD_IDLE", map_id=0x3F):
    """★本物と同じ形の採取ファイルを作る。"""
    nametable = "5F" * 960
    attr = "00" * 64
    palette = "0F30160600001016001016060000100A"
    # ★タイル $5F を「地の色だけ」にしておく（黒観測になる）
    chr_data = ["00"] * 8192
    path.write_text(
        f"slot=9\nmap_id={map_id}\nmap_x=10\nmap_y=10\n"
        f"scroll_x=0\nscroll_y=0\nstate={state}\n"
        f"nametable_left={nametable}\nnametable_right={nametable}\n"
        f"attr_left={attr}\nattr_right={attr}\n"
        f"palette={palette}\nchr={''.join(chr_data)}\n",
        encoding="utf-8")


def test_素材が無ければ止まる(tmp_path, capsys):
    assert dq2_map.build_assets(tmp_path, apply=False) == 1
    assert "採取データがありません" in capsys.readouterr().out


def test_既定は数えるだけ(tmp_path, capsys):
    _write_capture(tmp_path / "capture-9.txt")
    assert dq2_map.build_assets(tmp_path, apply=False) == 0
    out = capsys.readouterr().out
    assert "数えただけ" in out
    # ★何も作っていない
    assert not (tmp_path / "metatiles").exists()


def test_FIELD_IDLE以外は飛ばす(tmp_path, capsys):
    """⚠⚠ 移動中・メニュー中の背景を地形にしない（指示書 §6.2）。"""
    _write_capture(tmp_path / "capture-9.txt", state="FIELD_MOVING")
    dq2_map.build_assets(tmp_path, apply=False)
    out = capsys.readouterr().out
    assert "FIELD_MOVING" in out
    assert "飛ばします" in out


def test_黒だけの採取からは何も作らない(tmp_path, capsys):
    """⚠⚠ 全部が地の色なら地形にしない（指示書 §11.2）。"""
    _write_capture(tmp_path / "capture-9.txt")
    dq2_map.build_assets(tmp_path, apply=True)
    out = capsys.readouterr().out
    assert "メタタイル 0" in out
    # ★見送った数は残る（黙って捨てない）
    assert "黒で見送り 160" in out


def test_ステータス窓の行を採らない():
    """★窓は 16px マス行 10 から（2026-08-02 実測）。上 10 行だけ採る。"""
    assert dq2_map.MAP_CELL_ROWS == 10
    assert dq2_map.MAP_CELL_COLS == 16


def test_コマンドは2つ(tmp_path):
    """⚠ 知らないコマンドは argparse が弾く。"""
    with pytest.raises(SystemExit):
        dq2_map.main(["でたらめ"])


def test_applyを付けないと書かない(tmp_path, capsys, monkeypatch):
    """★`link-cells` も既定は数えるだけ。"""
    _write_capture(tmp_path / "capture-9.txt")

    class _Cfg:
        def path(self, _k):
            return tmp_path / "ない.sqlite3"

    import retroux.core.config.user_config as uc
    monkeypatch.setattr(uc, "load", lambda _p=None: (_Cfg(), []))
    assert dq2_map.link_cells(tmp_path, apply=False) == 1
    assert "DB がありません" in capsys.readouterr().out


# --- 実データ（★あるときだけ）------------------------------------------

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = PROJECT_ROOT / "work" / "map-assets"

needs_capture = pytest.mark.skipif(
    not (ASSETS / "capture-3.txt").exists(),
    reason="採取データが無い（bg_capture_probe.lua を先に走らせる）")


@needs_capture
def test_実データで素材を数えられる(capsys):
    assert dq2_map.build_assets(ASSETS, apply=False) == 0
    out = capsys.readouterr().out
    # ★再構成の一致率も出す（何を根拠に採ったか分かるように）
    assert "再構成" in out
    assert "黒で見送り" in out


@needs_capture
def test_辞書から画像を引けるところまで通っている():
    """★★ **DB -> 画像 -> 描画** が本当につながっているか。

    ⚠ 「配線したつもり」で届かないのが一番困る。
    """
    from retroux.core.bgmap.catalog import AssetStore

    store = AssetStore(ASSETS)
    metatiles = list(store.metatiles.glob("*/1x.png")) if \
        store.metatiles.exists() else []
    if not metatiles:
        pytest.skip("まだ素材を作っていない（build-assets --apply）")
    # ★鍵から画像を引ける
    key = metatiles[0].parent.name
    assert store.image_path(key, "1x") is not None
    assert store.image_path(key, "4x") is not None


# --- 起動スクリプト -----------------------------------------------------

def test_起動スクリプトがある():
    """⚠ 2026-08-02、README に**相対パス**で書いたら依頼者が踏んだ:

        cannot open research/probes/active/bg_capture_probe.lua

    ★FCEUX は相対パスを**自分の場所**から探す。
      スクリプトが絶対パスに直してから渡す。
    """
    script = PROJECT_ROOT / "scripts" / "build-map-assets.ps1"
    assert script.exists()
    text = script.read_text(encoding="utf-8-sig")
    # ★絶対パスを組み立てている
    assert "Join-Path $Root" in text
    # ⚠ 相対パスで渡していない
    assert "-lua research" not in text


def test_起動スクリプトはBOM付きUTF8():
    """⚠ PowerShell 5.1 は BOM 無しを cp932 として読み、日本語が壊れる。"""
    script = PROJECT_ROOT / "scripts" / "build-map-assets.ps1"
    assert script.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_起動スクリプトは配列で引数を渡さない():
    """⚠⚠ 2026-08-02 に踏んだ。

    PowerShell 5.1 で `$apply = @()` を `@apply` で渡すと
    「- - a p p l y」と**1文字ずつ**に分解され、
    `unrecognized arguments` になった。★呼び分ける。
    """
    import re

    script = PROJECT_ROOT / "scripts" / "build-map-assets.ps1"
    text = script.read_text(encoding="utf-8-sig")
    # ⚠ 注釈にも `@apply` と書いてある（何を避けたかの記録）。★コードだけ見る
    code = re.sub(r"^\s*#.*$", "", text, flags=re.M)
    assert "@apply" not in code
    assert "build-assets --apply" in code
    assert "link-cells --apply" in code


def test_起動スクリプトは遊んでいる最中に走らない():
    """⚠ FCEUX をもう1つ起こすので、遊んでいる画面を掴んでしまう。"""
    script = PROJECT_ROOT / "scripts" / "build-map-assets.ps1"
    text = script.read_text(encoding="utf-8-sig")
    assert "Get-Process fceux64" in text
    assert "exit 1" in text


def test_READMEが相対パスで案内していない():
    """★依頼者が同じところで詰まらないように。"""
    import re

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    # ⚠ **コードブロックの中**に、そのままでは動かない形が無いこと。
    #   ★本文で「こう書くと動かない」と説明するのは構わない。
    blocks = re.findall(r"```[a-z]*(.*?)```", readme, re.S)
    for block in blocks:
        assert "-lua research" not in block, (
            "★README のコード例が相対パスになっている（FCEUX は開けない）")
    # ★1コマンドの案内がある
    assert "build-map-assets.ps1" in readme
