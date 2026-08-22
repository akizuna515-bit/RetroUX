"""地図の描き方の設定が**実際に効く**こと（2026-08-12 / 監査 P0-A）。

## ⚠⚠ 何が起きていたか

`retroux/core/bgmap/settings.py` は 2026-08-03 に書かれましたが、
`load()` を呼んでいたのは **`tests/test_map_settings.py` だけ**でした。
`retroux/ui/map/presenter.py` は設定を通らずに ROM の地図を描いており、
★`config.yaml` の `map.rom_master` **6項目は書いても無視**でした。

```
map:
  rom_master:
    renderer: rom_master        # ⚠ 効かなかった
    fallback_renderer: observed # ⚠ 効かなかった
    reveal_mode: explored       # ⚠ 効かなかった（all にしても全部見せない）
    ...
```

★2026-08-12 に直した **P0-01（`map.assets_dir`）とまったく同じ形**です
（`docs/audit/source-to-doc.md` の 2）。

## ★ ここで守ること

⚠ 「設定を読める」だけでは足りません（それは `test_map_settings.py` の仕事）。
★**設定を変えたら presenter の答えが変わる**ことを見ます。
"""

from __future__ import annotations

import os
import pathlib

import pytest

from retroux.core.bgmap import settings as S
from retroux.ui.map.presenter import MapPresenter

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PRESENTER = PROJECT_ROOT / "retroux" / "ui" / "map" / "presenter.py"
GUI = PROJECT_ROOT / "retroux" / "gui.py"


class _Vm:
    """presenter が触るものだけ持つ入れ物。

    ⚠ `live_metatiles` は None にしてあります。★ROM を読む所まで行かずに
      「設定で止まったか」を見分けたいためです。
    """

    def __init__(self, map_render=None) -> None:
        self.map_render = map_render
        self.live_metatiles = None


def test_設定でこれまでの地図に戻せる():
    """★★★ **これが P0-A そのもの**。

    ⚠ 直す前は、何を書いても ROM の地図で描いていました。
    """
    vm = _Vm(S.load({"map": {"rom_master": {"renderer": "observed"}}}))
    got = MapPresenter(vm).rom_layer(0x40, 0, [])
    assert got is not None, "⚠ 設定で止めたのに理由が返っていません"
    assert "設定" in got.get("note", ""), got
    assert "observed" in got.get("note", ""), got


def test_ROMの地図を選べば設定では止まらない():
    """⚠ 逆向きも見ます（★片側だけだと「常に止まる」でも通ります）。"""
    vm = _Vm(S.load({"map": {"rom_master": {"renderer": "rom_master"}}}))
    got = MapPresenter(vm).rom_layer(0x40, 0, [])
    # ★`live_metatiles` が無いので None（＝設定より先へ進んだ）
    assert got is None, f"⚠ 設定で止まってしまいました: {got}"


def test_設定が渡っていなければ今の挙動のまま():
    """⚠⚠ **安全側の向きを間違えないこと。**

    ★ここで「設定が無いなら observed」に落とすと、設定を用意していない
      環境で**地図の絵が消えます**（直したつもりで劣化）。
    ⚠ 既定は `rom_master`（＝いまの実際の挙動）です。
    """
    assert MapPresenter(_Vm(None)).rom_layer(0x40, 0, []) is None


def test_全部見せるは検証用として区別されている():
    """★`reveal_mode: all` は地図デコーダの答え合わせに要ります。

    ⚠ 探索を潰すので、既定では絶対に選ばれないこと。
    """
    assert not S.load({}).reveals_everything
    assert S.load({"map": {"rom_master": {"reveal_mode": "all"}}}
                  ).reveals_everything


def test_歩いた記録が無くても全部見せるなら描きにいく_字面():
    """⚠ この形が消えたら気づくための固定（★挙動は下の実 ROM の検査）。"""
    source = PRESENTER.read_bytes().decode("utf-8")
    assert "if not explored and not render.reveals_everything:" in source, (
        "⚠⚠ 歩いた記録が無いだけで止めています（all が使えません）")
    assert "apply_exploration_mask" in source


# --- ★★ ⚠⚠ **ここから実際に動かす**（2026-08-15 / RX-0011）★★ ---------
#
#   ⚠ 上の2件は長く**字面だけ**でした。★「その行が書いてある」ことしか
#     見ていないので、書いてあるのに効かない形（F-089）を捕まえられません。
#   → ★ROM があるときは**本当に描かせて**、開示の量が変わることを見ます。

ROM_PATH = pathlib.Path(
    os.environ.get("DQ2_ROM_PATH") or "work/rom/DQ2_J.nes")
needs_rom = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"ROM がありません（{ROM_PATH}）")


@pytest.fixture(scope="module")
def live():
    """★ROM から絵を作る係（⚠ 利用者の DB は使わない）。"""
    import yaml

    from retroux.gui import _build_live_metatiles

    config = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "config.yaml").read_bytes().decode("utf-8"))
    got = _build_live_metatiles(config, ROM_PATH)
    if got is None:
        pytest.skip("★絵の材料を用意できない環境")
    return got


class _RomVm(_Vm):
    def __init__(self, map_render, live) -> None:
        super().__init__(map_render)
        self.live_metatiles = live


def _layer(live, reveal: str, observed):
    render = S.load({"map": {"rom_master": {"reveal_mode": reveal}}})
    return MapPresenter(_RomVm(render, live)).rom_layer(0x40, 0, observed)


@needs_rom
def test_歩いた記録が無いときはexploredなら止まる(live):
    """★既定（`explored`）は、歩いていない所を開けない（指示書 §2.2）。"""
    got = _layer(live, "explored", [])
    assert got is not None
    assert "歩いた記録がまだありません" in got.get("note", ""), got
    assert not got.get("metatiles"), got


@needs_rom
def test_歩いた記録が無くても全部見せるなら描きにいく(live):
    """★★★ ⚠⚠ **字面ではなく、開示の量で見る** ★★★

    ⚠ `reveal_mode: all` で止めてしまうと、
      **地図デコーダの答え合わせができません**（検証用の設定が死ぬ）。
    """
    got = _layer(live, "all", [])
    assert got is not None
    assert "歩いた記録がまだありません" not in got.get("note", ""), got
    assert got.get("metatiles"), "⚠ 全部見せるはずが1マスも出ていません"


@needs_rom
def test_探索マスクが設定で切り替わる(live):
    """★★★ ⚠⚠ **設定を変えたら開示の量が変わること** ★★★

    ★これが「`apply_exploration_mask` と書いてある」より強い。
      ⚠ 書いてあっても、呼ばれていなければ意味がありません。
    """
    walked = [(0, 0, 1, None), (2, 0, 1, None)]
    few = _layer(live, "explored", walked)
    many = _layer(live, "all", walked)
    assert few and many
    assert len(few["metatiles"]) < len(many["metatiles"]), (
        f"★explored {len(few['metatiles'])} / all {len(many['metatiles'])}"
        "（⚠ 設定が効いていません）")
    # ⚠ 歩いたぶんは explored でも出ること（★0 になっていないか）
    assert few["metatiles"], "⚠ 歩いたのに1マスも出ていません"


def test_効かない項目は黙って無視しない():
    """⚠⚠ **設定したのに効かない**が分からないのが、いちばん困ります。

    ★`show_dynamic_objects` / `show_unknown_objects` / `show_regions` は
      いまの値に固定されています。既定から変えたら理由を返すこと。
    """
    got = S.load({"map": {"rom_master": {"show_regions": True}}})
    notes = got.unsupported_changes()
    assert notes, "⚠ 効かない設定を黙って受け取っています"
    assert any("show_regions" in n for n in notes)
    # ★既定のままなら何も言わない（⚠ 鳴りすぎも壊れ方）
    assert S.load({}).unsupported_changes() == ()


def test_同梱の設定では警告が出ない():
    """★出荷している `config.yaml` は、そのままで静かであること。"""
    import yaml

    path = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
    config = yaml.safe_load(path.read_bytes().decode("utf-8"))
    got = S.load(config)
    assert got.notes == (), got.notes
    assert got.unsupported_changes() == (), got.unsupported_changes()


def test_起動時に設定を読んでViewModelへ渡している():
    """⚠ 作っただけで呼んでいなければ、設定は永遠に効きません。"""
    source = GUI.read_bytes().decode("utf-8")
    assert "def _build_map_render(config" in source
    assert "map_render=_build_map_render(config)" in source
    # ★読んだ内容と、効かない項目をログに出すこと
    assert "got.summary()" in source
    assert "unsupported_changes()" in source


def test_起動時に設定を読んでViewModelへ渡しているの挙動(caplog, tmp_path):
    """★RX-0011: 字面の検査に挙動を併設。

    `_build_map_render` を実際に呼び、設定が `MapRenderSettings` に
    載ること・効かない項目が WARNING で出ることを見ます。
    """
    import logging

    from retroux.gui import _build_map_render

    config = {"map": {"rom_master": {
        "reveal_mode": "all",      # ★効く項目
        "show_regions": True,      # ⚠ まだ効かない項目
        "renderer": "typo",        # ⚠ 使えない値 → 既定へ直す
    }}}
    with caplog.at_level(logging.DEBUG, logger="retroux.gui"):
        got = _build_map_render(config)

    assert isinstance(got, S.MapRenderSettings)
    assert got.reveals_everything, "★読んだ設定が載っていない"
    assert got.uses_rom_master, "★使えない値は既定へ落ちること"
    warnings = [r.getMessage() for r in caplog.records
                if r.levelno == logging.WARNING]
    assert any("show_regions" in w for w in warnings), (
        "⚠ 効かない設定を黙って受け取っています")
    assert any("renderer" in w for w in warnings), (
        "⚠ 直した点を黙っています")
    # ★要約は DEBUG で1回
    assert any(r.levelno == logging.DEBUG and "地図の描き方" in r.getMessage()
               for r in caplog.records)
    # ★ViewModel は渡された値をそのまま持つ（gui.py と同じキーワードで渡す）
    from retroux.ui.view_model import ViewModel

    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder

    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_bytes(b"")
    vm = ViewModel(Recorder(db, "HASH", events, tmp_path / "command.json"),
                   db, "HASH", map_render=got)
    assert vm.map_render is got
