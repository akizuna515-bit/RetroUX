"""ROM 地図の設定を読む（2026-08-03 / Phase 5）。

★★ **既定は「現行のまま」です。** ★★

⚠ 設定が無くても、壊れていても、**必ず動く既定へ落ちます**。
  ここで例外を投げると GUI が起動できなくなります。

⚠ Qt にも GUI にも依存しません。Core 層です。

## ⚠⚠ 2026-08-12 の訂正（監査 P0-A）

★**この設定は、書いても効いていませんでした。**
`load()` を呼んでいたのは `tests/test_map_settings.py` **だけ**で、
`retroux/ui/map/presenter.py` は設定を通らずに ROM の地図を描いていました
（`docs/audit/source-to-doc.md` の 2）。

⚠ そのとき既定は `observed`（現行表示）でしたが、**実際の挙動は ROM 描画**
でした（README 2026-08-09 / 08-11）。★配線するにあたり、
**既定を実際の挙動（`rom_master`）に合わせました。**
そうしないと「設定を繋いだら地図の絵が消えた」ことになります。

⚠ 「既定＝現行のまま」という方針は変えていません。**現行が変わった**ので、
  既定の値を追従させただけです。

## ⚠ まだ効かない3項目（★黙って無視しません）

`show_dynamic_objects` / `show_unknown_objects` / `show_regions` は、
**いまの値と同じ挙動に固定**されています（描き手側に切り替える口が無い）。
★既定から変えたら `unsupported_changes()` が理由を返すので、
呼び出し側はログに出してください。
"""

from __future__ import annotations

import dataclasses

#: ★描き方
RENDERER_OBSERVED = "observed"
RENDERER_ROM_MASTER = "rom_master"
RENDERERS = (RENDERER_OBSERVED, RENDERER_ROM_MASTER)

#: ★どこまで見せるか
REVEAL_EXPLORED = "explored"
REVEAL_ALL = "all"
REVEAL_MODES = (REVEAL_EXPLORED, REVEAL_ALL)


@dataclasses.dataclass(frozen=True)
class MapRenderSettings:
    """★地図の描き方。⚠ 既定は**すべて安全側**です。"""

    renderer: str = RENDERER_ROM_MASTER
    """★既定は ROM の地図（＝**いまの実際の挙動**）。

    ⚠ 2026-08-12 に `observed` から変えました。理由はモジュールの説明を参照。
    ★`observed` にすると、これまでの「色とタイルID」の地図に戻ります。
    """
    fallback_renderer: str = RENDERER_OBSERVED
    reveal_mode: str = REVEAL_EXPLORED
    """★既定は「歩いたマスだけ」（指示書 §2.2）。"""
    show_dynamic_objects: bool = True
    show_unknown_objects: bool = False
    """⚠ 表にだけある座標は既定で出しません。"""
    show_regions: bool = False
    #: ⚠ 設定を読むときに直した点（★黙って直さない）
    notes: tuple = ()

    @property
    def uses_rom_master(self) -> bool:
        return self.renderer == RENDERER_ROM_MASTER

    @property
    def reveals_everything(self) -> bool:
        """⚠ 全部見せる（**検証用**）。★探索を潰します。"""
        return self.reveal_mode == REVEAL_ALL

    def unsupported_changes(self) -> tuple:
        """★**まだ効かない項目**のうち、既定から変えられたものを返す。

        ⚠⚠ 黙って無視するのがいちばん困る壊れ方です（設定したのに効かない、
          が分からない）。★呼ぶ側はこれをログに出してください。
        """
        fixed = (
            ("show_dynamic_objects", self.show_dynamic_objects, True,
             "宝箱・扉は常に出します（描き手に切り替える口がありません）"),
            ("show_unknown_objects", self.show_unknown_objects, False,
             "表にだけある座標は常に出しません"),
            ("show_regions", self.show_regions, False,
             "区画の色分けは未実装です（第一弾に入れない判断 / BACKLOG 2.2）"),
        )
        return tuple(
            f"⚠ {key}={value!r} は効きません（★{why}）"
            for key, value, default, why in fixed if value != default)

    def summary(self) -> str:
        head = ("★ROM の地図" if self.uses_rom_master else "★現行表示")
        reveal = ("⚠ 全部見せる（検証用）" if self.reveals_everything
                  else "★歩いたマスだけ")
        tail = f"   ⚠ 直した点: {'; '.join(self.notes)}" if self.notes else ""
        return f"{head} / {reveal}{tail}"


def load(config) -> MapRenderSettings:
    """設定から読む。⚠ **何があっても既定へ落ちます**（例外を出しません）。

    `config` は `config.yaml` を読んだ辞書（`map.rom_master` を見ます）。
    """
    notes = []
    try:
        section = ((config or {}).get("map") or {}).get("rom_master") or {}
    except AttributeError:
        section = {}
        notes.append("⚠ 設定の形が違ったので既定にしました")
    if not isinstance(section, dict):
        section = {}
        notes.append("⚠ map.rom_master が辞書ではないので既定にしました")

    def pick(key: str, allowed, default: str) -> str:
        value = section.get(key, default)
        if value in allowed:
            return value
        notes.append(f"⚠ {key}={value!r} は使えないので {default!r} にしました")
        return default

    def flag(key: str, default: bool) -> bool:
        value = section.get(key, default)
        if isinstance(value, bool):
            return value
        notes.append(f"⚠ {key}={value!r} は真偽値ではないので {default} にしました")
        return default

    return MapRenderSettings(
        renderer=pick("renderer", RENDERERS, RENDERER_ROM_MASTER),
        fallback_renderer=pick("fallback_renderer", RENDERERS,
                               RENDERER_OBSERVED),
        reveal_mode=pick("reveal_mode", REVEAL_MODES, REVEAL_EXPLORED),
        show_dynamic_objects=flag("show_dynamic_objects", True),
        show_unknown_objects=flag("show_unknown_objects", False),
        show_regions=flag("show_regions", False),
        notes=tuple(notes))
