"""記録プロセスの入口（CLI）。

FCEUX 側（run.lua）と並行して動かし、events.jsonl を SQLite に取り込む。
このプロセスが落ちてもゲームは正常に動く（D-1）。ログだけが欠落する。

★正式なメイン入口は **GUI**（`python -m retroux.gui`）です（MVP2 Phase 1）。
  こちらは画面を出さずに記録だけしたいとき・集計を見たいときの補助。
  **同時に動かせません**（どちらも events.jsonl を取り込むため / 指示書 6.3）。
  排他はロックファイル（既定 `work/event_ingestor.lock`）で行います。

使い方:
    python -m retroux.record
    python -m retroux.record --summary       # 記録の集計だけ表示して終了
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

from .core import enemy_tables
from .core import rom as rom_mod
from .core.config import user_config as user_config_mod
from .core.db.database import Database
from .core.logging_setup import get_logger, setup_logging
from .core.recorder import Recorder, rotate_events
from .core.single_instance import AlreadyRunningError, RecorderLock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = PROJECT_ROOT / "retroux" / "plugins" / "dq2"


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _build(args: argparse.Namespace,
           user_cfg: user_config_mod.UserConfig) -> tuple[Database, Recorder, dict]:
    config = _load_yaml(PLUGIN_DIR / "config.yaml")
    memory_map = _load_yaml(PLUGIN_DIR / "memory_map.yaml")

    rom_path = Path(args.rom) if args.rom else user_cfg.path("rom")
    if not rom_path.is_absolute():
        rom_path = PROJECT_ROOT / rom_path
    info = rom_mod.identify(rom_path)

    rom_meta = memory_map.get("rom", {})
    expected = str(rom_meta.get("prg_crc32", "")).upper()
    if expected and expected != info.prg_crc32:
        print(f"警告: ROM が memory_map.yaml と一致しません "
              f"(期待 {expected} / 実際 {info.prg_crc32})", file=sys.stderr)
    enemy_tables.attach(memory_map, rom_path,
                        PROJECT_ROOT / "work" / "generated" / enemy_tables.CACHE_NAME)
    if info.has_dirty_header:
        print("警告: iNES ヘッダのパディングにゴミがあります。"
              "FCEUX がマッパーを誤認して起動しない可能性があります。", file=sys.stderr)

    db = Database(user_cfg.path("db"))
    db.register_rom(
        rom_hash=info.prg_sha256,
        title=str(rom_meta.get("title", rom_path.stem)),
        region=str(rom_meta.get("region", "?")),
        mapper=info.mapper,
    )

    # ★イベントの世代交代（§25）。⚠ `Recorder` を作る**前**に一度だけ。
    #   ★世代交代と取り込み位置のリセットは `rotate_events` が対で行う。
    try:
        rotation = rotate_events(db, user_cfg.path("events"))
        if rotation.rotated:
            get_logger("record").info("%s", rotation.message())
    except Exception as exc:                           # noqa: BLE001
        get_logger("record").warning(
            "イベントの世代交代に失敗しました: %s", exc)

    recorder = Recorder(
        db=db,
        rom_hash=info.prg_sha256,
        events_path=user_cfg.path("events"),
        command_path=user_cfg.path("command"),
    )
    return db, recorder, {"rom": info, "config": config}


def _print_summary(db: Database, rom_hash: str) -> None:
    s = db.speedup_summary(rom_hash)
    print(f"記録した戦闘数: {s['battles']}")
    if not s["battles"]:
        print("（まだ戦闘の記録がありません）")
        return
    # ★秒のままだと桁が大きくなって実感できない（依頼者の指摘）
    from .core.humanize import duration

    print(f"ゲーム内フレーム合計: {s['total_frames']:,} "
          f"(等速なら {duration(s['baseline_ms'] / 1000)})")
    print(f"実際にかかった時間  : {duration(s['actual_ms'] / 1000)}")
    print(f"削減できた待ち時間  : {duration(s['saved_ms'] / 1000)}")
    print(f"平均の実測倍率      : {s['avg_speed']:.2f} 倍")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RetroUX 記録プロセス")
    parser.add_argument("--rom", default=None,
                        help="対象ROM（既定は user_config.yaml の paths.rom）")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="events.jsonl を読む間隔（秒）")
    parser.add_argument("--summary", action="store_true",
                        help="集計を表示して終了する")
    parser.add_argument("--force", action="store_true",
                        help="他の記録プロセスが動いていても起動する（非推奨）")
    parser.add_argument("--config", default=None, help="user_config.yaml のパス")
    args = parser.parse_args(argv)

    user_cfg, cfg_warnings = user_config_mod.load(args.config)
    log_handle = setup_logging(
        user_cfg.path("log"),
        # ★下限は `logging.mode` から（2026-08-13 / §19）
        level=user_cfg.logging.resolved()["level"],
        max_bytes=user_cfg.logging.max_bytes,
        backup_count=user_cfg.logging.backup_count,
    )
    log = get_logger("record")
    for warning in cfg_warnings:
        log.warning(warning)

    try:
        db, recorder, meta = _build(args, user_cfg)
    except (FileNotFoundError, rom_mod.InvalidRomError) as exc:
        print(f"起動に失敗しました: {exc}", file=sys.stderr)
        return 1

    info = meta["rom"]
    lock: RecorderLock | None = None
    try:
        if args.summary:
            _print_summary(db, info.prg_sha256)
            return 0

        # record と gui は同時に動かせない（同じ events.jsonl を二重に取り込む）
        lock = RecorderLock(user_cfg.path("lock"))
        try:
            lock.acquire(force=args.force)
        except AlreadyRunningError as exc:
            lock = None
            print(f"起動を中止しました: {exc}", file=sys.stderr)
            return 1

        log.info("記録を開始しました / rom_hash=%s", info.prg_sha256[:16])
        print(f"RetroUX 記録開始 / rom_hash={info.prg_sha256[:16]}...")
        print("FCEUX 側で run.lua を実行してください。Ctrl+C で終了します。")
        recorder.push_encountered()
        while True:
            n = recorder.poll()
            lock.touch()
            if n:
                st = recorder.stats
                state = "戦闘中" if st.in_battle else "フィールド"
                print(f"  [{state}] 記録済み {st.battles_recorded} 戦闘"
                      f" / 倍率 {st.current_speed}"
                      + ("  ⚠危険状態" if st.danger else ""))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n終了します。")
        _print_summary(db, info.prg_sha256)
        return 0
    finally:
        if lock is not None:
            lock.release()
        db.close()
        log_handle.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
