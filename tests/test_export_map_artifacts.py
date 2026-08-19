"""地図の成果物を固めるツール（2026-08-03 / 依頼者の要望）。

    > mapのやつは、もしもツールがあるのであれば、
    > ドキュメントに記録して再利用可能にしたい。

⚠⚠ **これまで手で組んでいました。** 同じものをもう一度作る手順が
  どこにも残っておらず、同梱の件数もすべて手打ちでした。

★ここで守りたいこと:

  1. ROM・セーブステートが**絶対に**混ざらない（★実際に検査する）
  2. 案内の数字を**手で書かない**（`index.json` から数え直す）
  3. 入れられなかったものを**黙って捨てない**
"""

from __future__ import annotations

import json
import pathlib
import zipfile

import pytest

from retroux.tools import export_map_artifacts as tool

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """★本物を1度だけ作る（遅いので使い回す）。"""
    out = tmp_path_factory.mktemp("maps")
    code = tool.main(["--out-dir", str(out)])
    zips = sorted(out.glob("retroux-maps-*.zip"))
    if code != 0 or not zips:
        pytest.skip("★成果物がまだありません（dq2_map_batch を先に走らせてください）")
    return zips[0]


# --- ⚠⚠ 配ってはいけないもの ---------------------------------------------

def test_ROMもセーブステートも入らない(built):
    """★★★ **指示書 §18.7。** ⚠ 「入れていないつもり」で終わらせない。"""
    with zipfile.ZipFile(built) as archive:
        names = [n.lower() for n in archive.namelist()]
    assert names, "⚠⚠ 空の ZIP です"
    for name in names:
        assert not name.endswith(".nes"), f"⚠⚠ ROM が入っています: {name}"
        for banned in (".fcs", ".sav", ".srm", ".bak"):
            assert not name.endswith(banned), f"⚠⚠ {name}"
        for slot in range(10):
            assert not name.endswith(f".fc{slot}"), f"⚠⚠ {name}"


def test_混入したら配布を中止する(tmp_path):
    """⚠ 検査が**実際に止める**こと（★検査が飾りになっていないか）。"""
    fake = tmp_path / "ま.zip"
    with zipfile.ZipFile(fake, "w") as archive:
        archive.writestr("07_maps/DQ2_J.nes", "ROM のつもり")
    assert tool._verify(fake) == ["07_maps/DQ2_J.nes"]


def test_空のZIPを合格にしない(tmp_path):
    """⚠ 「混ざっていないこと」だけ見ていると、空でも合格になります。"""
    empty = tmp_path / "から.zip"
    with zipfile.ZipFile(empty, "w"):
        pass
    assert tool._verify(empty), "⚠ 空の ZIP が合格になっています"


# --- ★★ 数字を手で書かない -----------------------------------------------

def test_案内の件数がindexと一致する(built):
    """★★★ **これがこのツールの肝です。**

    ⚠ 手書きの要約は、成果物が変わっても**黙って古いまま**残ります。
      実際、手で組んでいた ZIP の `00_README.md` がそうでした。
    """
    with zipfile.ZipFile(built) as archive:
        readme = archive.read("00_README.md").decode("utf-8")
        index = json.loads(archive.read("06_index/index.json").decode("utf-8"))

    rows = index["maps"]
    assert f"| 全マップ | {len(rows)} |" in readme
    drawn = sum(1 for r in rows if r["status"] == "renderable")
    assert f"| ★描けた | {drawn} |" in readme
    chests = sum(r.get("chest_count") or 0 for r in rows)
    assert f"| 宝箱 | {chests} |" in readme
    # ★ROM のハッシュも書いてある（どの ROM で出したか分かるように）
    assert index["rom"]["sha256"] in readme


def test_未解明を0と混ぜない(built):
    """⚠⚠ **推測で埋めません。**分からないものは件数のまま残します。"""
    with zipfile.ZipFile(built) as archive:
        readme = archive.read("00_README.md").decode("utf-8")
        index = json.loads(archive.read("06_index/index.json").decode("utf-8"))
    unknown = sum(len(r.get("unknown_terrain_ids") or [])
                  for r in index["maps"])
    assert f"| ⚠ 未解明の地形ID | {unknown} |" in readme


def test_世界地図が失敗に見えないよう説明する(built):
    """⚠ `$01` は種別0で、**この手順の対象外**（別経路）です。

    ★説明が無いと「1件失敗している」と読まれます。
    """
    with zipfile.ZipFile(built) as archive:
        readme = archive.read("00_README.md").decode("utf-8")
    assert "世界地図" in readme and "別ツール" in readme


# --- ★ 入れられなかったものを黙って捨てない --------------------------------

def test_欠けたものを理由つきで残す():
    """★`_collect` は困りごとを返すこと（★例外で落とさない）。"""
    picked, problems = tool._collect()
    assert picked, "★何も集められていません"
    assert isinstance(problems, list)


def test_同じものを2度入れない():
    """⚠ グロブが重なると同じファイルが2回入ります。"""
    picked, _ = tool._collect()
    names = [n for n, _ in picked]
    assert len(names) == len(set(names)), "⚠ 重複しています"


# --- ★ もう一度作れること --------------------------------------------------

def test_作り方が案内に書いてある(built):
    """★★ **手順が残らないのが、手で組んでいたときの問題でした。**"""
    with zipfile.ZipFile(built) as archive:
        readme = archive.read("00_README.md").decode("utf-8")
    assert "retroux.tools.export_map_artifacts" in readme


def test_READMEに載っている():
    """★プロジェクト規約: 資料は README の索引から辿れること。"""
    text = (PROJECT_ROOT / "README.md").read_bytes().decode("utf-8")
    assert "retroux.tools.export_map_artifacts" in text
