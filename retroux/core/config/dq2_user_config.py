"""DQ2 専用の設定ファイル（RX-0147 / D-42 / 依頼者の判断 J4）。

★DQ2 は `dq2_user_config.yaml` を読みます。⚠ `user_config.yaml` は **DQ3 のもの**として残します。

## ⚠⚠ なぜ分けるか

`user_config.yaml` は DQ2 と DQ3 の**両方**が読んでいました。
⚠ たとえば DQ3 のために `paths.fceux` を書くと、DQ2 にも効いてしまう（★製品が独立しない）。
→ ★ROM・FCEUX・パッド・窓などの設定を DQ2 / DQ3 で互いに使わない（依頼者 2026-10-03）。

## ★読み方

```text
1 引数でファイルを渡された        → そのファイル（★`--config` / 検査）
2 dq2_user_config.yaml がある     → それ
3 無ければ旧 user_config.yaml     → ⚠ 読むだけ（★書き戻さない）。移行の案内を警告に 1 行
                                    ⚠ DQ3 のための項目（`paths.fceux` / `paths.dq3_rom`）は**取り込まない**
                                      （★それまで DQ2 には効いていなかった値。取り込むと挙動が変わる）
4 どちらも無い                     → 既定値
```

⚠ `retroux/core/config/user_config.py` は**変えていません**（★DQ3 が import する / J1）。
  ★読み方の本体（項目・既定値・未知の項目の警告）はそのまま借ります。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from . import user_config as _uc
from .user_config import UserConfig

PROJECT_ROOT = _uc.PROJECT_ROOT
#: ★DQ2 専用の設定ファイルの名前（★規約: `user_config.yaml` と同じ snake_case に `dq2_` を前置き）
CONFIG_NAME = "dq2_user_config.yaml"
EXAMPLE_NAME = "dq2_user_config.example.yaml"
#: ⚠ 旧ファイル（★DQ3 のものとして残る。DQ2 は読むだけ）
LEGACY_NAME = "user_config.yaml"
#: ⚠ 旧ファイルから取り込まない項目（★DQ3 のための値 / それまで DQ2 には効いていなかった）
LEGACY_IGNORED_PATHS = ("fceux", "dq3_rom")

#: ★DQ2 のログ（RX-0149 / 依頼者の判断 J3）。⚠ 旧 `work/retroux.log` は DQ3 の控えも書くので離れる。
#   ★旧ログは**動かさない**（新しい版からの出力先だけ変える）。
DQ2_LOG = "work/runtime/dq2-log/retroux.log"
#: ⚠ `paths.log` が既定（または雛形のまま）なら DQ2 のログへ読み替える（★人が別の場所を書いていたら尊重する）
SHARED_LOG = "work/retroux.log"


#: ★events.jsonl は設定で動かせない（RX-0162）。⚠ Lua はこの値を読まないので、変えると Python だけ別のファイルを見ていた
EVENTS_DEFAULT = "work/events.jsonl"


def events_note(cfg) -> list[str]:
    """⚠ `paths.events` を既定から変えていたら、効かないことを知らせる（★黙って捨てない）。"""
    if not _is_config(cfg):
        return []
    value = Path(str(cfg.paths.events or EVENTS_DEFAULT)).as_posix()
    if value == EVENTS_DEFAULT:
        return []
    return [f"paths.events（{cfg.paths.events}）は DQ2 では使いません。"
            f"記録は書き先の根の {EVENTS_DEFAULT} に固定です（★FCEUX 側がそこへ書くため / RX-0162）"]


def _is_config(cfg) -> bool:
    """★本物の設定か（⚠ 検査が `load` を差し替えて `path()` だけの代役を返すことがある / 代役には手を入れない）。"""
    return dataclasses.is_dataclass(cfg) and dataclasses.is_dataclass(getattr(cfg, "paths", None))


def _dq2_log(cfg: UserConfig) -> UserConfig:
    if not _is_config(cfg):
        return cfg
    if Path(cfg.paths.log).as_posix() != SHARED_LOG:
        return cfg
    return dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, log=DQ2_LOG))


def config_path(root: Path | None = None) -> Path:
    """★DQ2 専用の設定ファイルの場所（★プログラムの直下 = `user_config.yaml` の隣）。"""
    return (root if root is not None else PROJECT_ROOT) / CONFIG_NAME


def legacy_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_ROOT) / LEGACY_NAME


def migration_note(legacy: Path) -> str:
    return (f"{legacy.name} を読んでいます（⚠ DQ2 は読むだけで書き戻しません）。"
            f"DQ2 の設定は {CONFIG_NAME} に移してください"
            f"（{EXAMPLE_NAME} を {CONFIG_NAME} という名前でコピーし、必要な値を写す）。"
            f"⚠ {legacy.name} の paths.fceux / paths.dq3_rom は DQ3 用なので DQ2 では使いません")


def load(path: Path | str | None = None, *, root: Path | None = None) -> tuple[UserConfig, list[str]]:
    """DQ2 の設定を読む。戻り値: 設定, 警告の一覧（★例外を投げない / 元と同じ）。

    `root` は設定ファイルを探すフォルダ（★既定はプログラムの直下 / 検査が一時フォルダを渡す）。
    """
    if path is not None:
        cfg, warnings = _uc.load(path)
        return _dq2_log(cfg), [*warnings, *events_note(cfg)]
    own = config_path(root)
    if own.exists():
        cfg, warnings = _uc.load(own)
        return _dq2_log(cfg), [*warnings, *events_note(cfg)]
    legacy = legacy_path(root)
    if legacy.exists():
        cfg, warnings = _uc.load(legacy)
        if _is_config(cfg):
            blanked = {name: "" for name in LEGACY_IGNORED_PATHS}
            cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, **blanked))
        return _dq2_log(cfg), [migration_note(legacy), *warnings, *events_note(cfg)]
    cfg, warnings = _uc.load(own)     # ★無い → 既定値（元の load と同じ扱い）
    return _dq2_log(cfg), warnings


def source_path(root: Path | None = None) -> Path | None:
    """★いま DQ2 が読む設定ファイル（⚠ どちらも無ければ None）。Lua の生成など、自前で読む所のため。"""
    for candidate in (config_path(root), legacy_path(root)):
        if candidate.exists():
            return candidate
    return None
