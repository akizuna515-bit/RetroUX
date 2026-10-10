"""DQ2 専用のセーブステート世代バックアップ（RX-0144 / D-42 / 依頼者の判断 J1・J5）。

★`retroux/tools/savestate_backup.py` の**複製**です（⚠ 共有ではありません）。

  元のエンジンは DQ3 が import しています（`dq3/savestate_backup.py`）。
  ⚠ DQ2 のために元を変えると DQ3 の挙動が変わるので、DQ2 は自分の写しを持ちます
  （2026-10-03 依頼者「DQ2 / DQ3 は当面独立した製品。必要な重複は許す」）。
  ★以後、元の `savestate_backup.py` は事実上 DQ3 の持ち物です。

## ★元との違い（DQ2 専用にしたところ）

```text
見張るファイル  <DQ2 ROM の stem>*.fc[0-9] / *.fcs だけ（★例 DQ2_J.fc0・DQ2_J-bak.fc0）
                ⚠ 元は fcs/ の *.fc* を全部見ていて、DQ3_J のスロットまで 10 世代で回していた
                  （DQ3 の控えフォルダの 100 世代が 10 まで削られた / 調査 D1）
ロック・停止・状態  <write_root>/work/runtime/dq2-backup/savestate_backup.{lock,stop,status.json}
                ⚠ 元は work/savestate_backup.*（DQ3 の控えと同じ場所 = 先に立った方が両方を担当していた）
保存先          <write_root>/work/runtime/dq2-backup/savestate-backup/<ファイル名>/
                ★旧 work/savestate-backup/ は**動かさない**。`--legacy` で一覧・復元だけできる（J5）
状態の確認      --status で BUSY / FREE（★起動スクリプトが DQ2 専用のロックだけを見る）
```

★write_root は環境変数 `RETROUX_WRITE_ROOT`、無ければ repo 直下（★検査は conftest がこれを一時フォルダへ向ける）。

## 依頼者の要望（元のまま）

    セーブステートが出来たら、10世代ぐらいバックアップする。
    更新されるたびに世代バックアップが理想だが、ダメなら1分ごとにとかでもOK。
    いまのセーブステート管理だと、間違えてハマりポイントでセーブしたり、
    セーブロード間違えると最初の場面でセーブしたりと危険

★守りたいもの: **取り返しのつかない事故**（ハマりポイントで上書き / ロードのつもりでセーブ）。
★上書きされる前の内容を世代として残す。同じ内容なら世代を作らない（古い世代を押し出さない）。
★書き込み途中のファイルを掴まない（サイズが安定するまで待つ）。

使い方:

    uv run python -m retroux.tools.dq2_savestate_backup            # 監視し続ける
    uv run python -m retroux.tools.dq2_savestate_backup --once     # 1回だけ
    uv run python -m retroux.tools.dq2_savestate_backup --list     # 世代を一覧
    uv run python -m retroux.tools.dq2_savestate_backup --restore DQ2_J.fc0 --gen 3
    uv run python -m retroux.tools.dq2_savestate_backup --list --legacy   # 旧保存先（〜2026-10-03）
    uv run python -m retroux.tools.dq2_savestate_backup --status   # BUSY / FREE

⚠ 復元は**いまのファイルも世代として残してから**行う。
"""

from __future__ import annotations

import argparse
import atexit
import glob
import hashlib
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from ..core import backup_status, console
from ..core.console import say

PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: FCEUX がセーブステートを書く場所（★DQ2 の FCEUX は tools/fceux 固定 / RX-0146 で resolver へ）
DEFAULT_SRC = PROJECT_ROOT / "tools" / "fceux" / "fcs"
DEFAULT_GENERATIONS = 10
DEFAULT_INTERVAL = 1.0
#: ★ROM の名前が取れないときの stem（`work/rom/DQ2_J.nes`）
DEFAULT_ROM_STEM = "DQ2_J"

#: ★DQ2 の控えの置き場（`<write_root>/work/` からの相対）。⚠ work/ 直下に新しく作らない（区分 runtime/ の中）
HOME_PARTS = ("runtime", "dq2-backup")
LOCK_NAME = "savestate_backup.lock"
DST_NAME = "savestate-backup"

#: FCEUX のセーブステートの拡張子。fc0〜fc9 と fcs。
SUFFIX_PATTERNS = (".fc[0-9]", ".fcs")

#: ★世代ファイル名に入れる**プロセス内で単調増加する連番**（元の 2026-08-11 の対策）。
_gen_seq = 0


# --- ★場所（DQ2 専用）-----------------------------------------------------

def write_root() -> Path:
    """書き先の根。★`RETROUX_WRITE_ROOT` が立っていればそこ、無ければ repo 直下。"""
    env = os.environ.get("RETROUX_WRITE_ROOT")
    return Path(env) if env else PROJECT_ROOT


def home() -> Path:
    """DQ2 の控えの置き場（ロック・停止・状態・世代）。"""
    return write_root().joinpath("work", *HOME_PARTS)


def lock_path() -> Path:
    return home() / LOCK_NAME


def stop_path() -> Path:
    """停止の合図。★ロックの隣（`savestate_backup.stop`）。"""
    return lock_path().with_suffix(".stop")


def default_dst() -> Path:
    return home() / DST_NAME


def legacy_dst() -> Path:
    """旧保存先（〜2026-10-03 / DQ3 の控えと共有だった）。★読む・戻すだけ。"""
    return write_root() / "work" / "savestate-backup"


def patterns_for(rom_stem: str) -> tuple[str, ...]:
    """★DQ2 ROM のファイルだけを拾う glob。

    ★`*` を付けるのは `DQ2_J-bak.fc0`（playdata の退避）も拾うため。
    ⚠ stem に glob の特殊文字があっても字義どおりに扱う（`glob.escape`）。
    """
    stem = glob.escape(rom_stem)
    return tuple(f"{stem}*{suffix}" for suffix in SUFFIX_PATTERNS)


def rom_stem_from(user_cfg) -> str:
    """設定の ROM のファイル名から stem を取る。★取れなければ `DQ2_J`。"""
    try:
        stem = Path(user_cfg.path("rom")).stem
    except Exception:                                  # noqa: BLE001
        return DEFAULT_ROM_STEM
    return stem or DEFAULT_ROM_STEM


# --- 世代（★元と同じ）------------------------------------------------------

def digest(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def settled(path: Path, tries: int = 5, wait: float = 0.08) -> bool:
    """書き込み途中でないことを確かめる。サイズが2回続けて同じなら安定とみなす。"""
    last = -1
    for _ in range(tries):
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last and size > 0:
            return True
        last = size
        time.sleep(wait)
    return False


def gen_dir(dst: Path, name: str) -> Path:
    return dst / name


def list_generations(dst: Path, name: str) -> list[Path]:
    """新しい順に世代を返す。"""
    d = gen_dir(dst, name)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.bak"), key=lambda p: p.name, reverse=True)


def rotate_in(src: Path, dst: Path, generations: int) -> Path | None:
    """src を新しい世代として保存する。同じ内容なら何もしない。

    ★名前は「マイクロ秒までの刻印 ＋ プロセス内で単調増加する連番」
      （⚠ Windows の時計は粗く、同着で最新の世代を消した事故の対策 / 元の 2026-08-11）。
    """
    name = src.name
    d = gen_dir(dst, name)
    d.mkdir(parents=True, exist_ok=True)

    src_hash = digest(src)
    if src_hash is None:
        return None

    gens = list_generations(dst, name)
    # ★同じ内容なら世代を作らない。作ると古い世代を押し出してしまう。
    if gens and digest(gens[0]) == src_hash:
        return None

    global _gen_seq
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    _gen_seq += 1
    target = d / f"{stamp}-{_gen_seq:06d}.bak"
    while target.exists():
        _gen_seq += 1
        target = d / f"{stamp}-{_gen_seq:06d}.bak"
    shutil.copy2(src, target)

    # 古い世代を削る（新しい順に generations 個だけ残す）。★このファイル名のフォルダの中だけ
    for old in list_generations(dst, name)[generations:]:
        old.unlink(missing_ok=True)
    return target


def watched_files(src_dir: Path, rom_stem: str) -> list[Path]:
    """★見張るファイル（DQ2 ROM の stem に合うものだけ）。"""
    files: set[Path] = set()
    for pat in patterns_for(rom_stem):
        files.update(src_dir.glob(pat))
    return sorted(f for f in files if f.is_file())


def scan(src_dir: Path, dst: Path, generations: int, rom_stem: str = DEFAULT_ROM_STEM,
         quiet: bool = False, seen: dict[str, tuple[int, int]] | None = None) -> int:
    """1回ぶん見る。★DQ2 ROM のファイルだけ。

    ★`seen` を渡すと「前回と同じ（更新時刻とサイズが不変）」のファイルを**完全に飛ばす**
      （⚠ 無いと 1 巡に約 2 秒かかっていた / 元の実測）。
    """
    made = 0
    for f in watched_files(src_dir, rom_stem):
        if seen is not None:
            try:
                st = f.stat()
            except OSError:
                continue
            key = str(f)
            sig = (st.st_mtime_ns, st.st_size)
            if seen.get(key) == sig:
                continue                    # 変わっていない。触らない
            seen[key] = sig
        if not settled(f):
            continue
        made_path = rotate_in(f, dst, generations)
        if made_path is not None:
            made += 1
            message = f"世代を保存: {f.name} -> {made_path.relative_to(dst)}"
            _log().info("%s", message, extra={"event_type": "savestate_backup"})
            if not quiet:
                print(message)
    return made


def write_status(lock: Path, args, *, running: bool, session=None,
                 last_backup=None, last_error=None) -> None:
    """稼働状態を GUI へ伝える（仕様書 6.1）。★**失敗しても止まらない**。"""
    try:
        backup_status.write(
            lock, running=running,
            generations=args.generations, watching=args.src,
            destination=args.dst, interval=args.interval,
            last_backup=last_backup, session=session, last_error=last_error)
    except Exception:                                  # noqa: BLE001
        pass


def _log():
    """共有ロガー。★ここで setup_logging は呼ばない（設定するのは入口 main の仕事）。"""
    from ..core.logging_setup import get_logger

    return get_logger("savestate")


def is_busy(lock: Path | None = None) -> bool:
    """★DQ2 の控えが動いているか（心拍と PID で見る）。"""
    from ..core.single_instance import RecorderLock

    return RecorderLock(lock or lock_path()).is_active()


#: ★`stop_own` の答え
STOPPED, OTHER, NONE = "STOPPED", "OTHER", "NONE"


def stop_own(session: str, lock: Path | None = None, wait: float = 0.0,
             poll: float = 0.1) -> str:
    """★起動スクリプトが立てた控えに、**その起動の札が合うときだけ**止まってもらう（RX-0170）。

    ⚠⚠ 起動に失敗した（GUI がすぐ終わった）とき、同じ起動で立てた控えが残り続けていた
      （2026-10-05 実機: 10/04 の失敗した起動の pythonw が翌日も動き、展開先を消せなかった）。
      ★GUI が無ければ GUI の後始末（`MainWindow._stop_own_backup`）は走らない。

    ★`wait` 秒まで、状態ファイルが「動いている・札が同じ」になるのを待つ:
      ⚠ 立てた直後の控えは、合図の置き場を**消してから**状態を書く（`main`）。
        状態より先に合図を置くと消されるので、状態に札が出てから置く。

    戻り値: `STOPPED`（合図を置いた）/ `OTHER`（別の起動の控え）/ `NONE`（状態が無い・止まっている）
    """
    import json

    status = backup_status.status_path(lock or lock_path())
    deadline = time.monotonic() + max(0.0, float(wait))
    got: dict = {}
    while True:
        try:
            got = json.loads(status.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = {}
        if got.get("running") and session and got.get("session") == session:
            (lock or lock_path()).with_suffix(".stop").write_text("stop", encoding="utf-8")
            return STOPPED
        if time.monotonic() >= deadline:
            break
        time.sleep(poll)
    return OTHER if (got.get("running") and got.get("session")) else NONE


def cmd_list(dst: Path) -> int:
    if not dst.is_dir():
        print(f"世代がありません: {dst}")
        return 0
    names = sorted(p.name for p in dst.iterdir() if p.is_dir())
    if not names:
        print("世代がありません")
        return 0
    for name in names:
        gens = list_generations(dst, name)
        print(f"{name}  （{len(gens)}世代）")
        for i, g in enumerate(gens):
            size = g.stat().st_size
            print(f"  {i}: {g.stem}  {size:,} バイト"
                  + ("   <- 最新" if i == 0 else ""))
    return 0


def cmd_restore(src_dir: Path, dst: Path, name: str, gen: int,
                generations: int, keep_dst: Path | None = None) -> int:
    """世代を戻す。★いまのファイルも世代として残してから。

    ★`keep_dst` は「いまのファイル」を残す先（★旧保存先から戻すときも、残すのは新しい保存先へ）。
    """
    gens = list_generations(dst, name)
    if not gens:
        print(f"世代がありません: {name}", file=sys.stderr)
        return 1
    if gen < 0 or gen >= len(gens):
        print(f"世代 {gen} は範囲外です（0〜{len(gens) - 1}）", file=sys.stderr)
        return 1

    target = src_dir / name
    if target.exists():
        kept = rotate_in(target, keep_dst or dst, generations)
        if kept is not None:
            print(f"復元前の状態を世代に残しました: {kept.name}")
        else:
            print("復元前の状態は既に最新世代と同じでした")

    shutil.copy2(gens[gen], target)
    print(f"復元しました: {gens[gen].name} -> {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DQ2 のセーブステートの世代バックアップ")
    ap.add_argument("--src", type=Path, default=None,
                    help="監視するフォルダ（既定: DQ2 の FCEUX の隣の fcs / dq2_user_config.yaml の paths.fceux に従う）")
    ap.add_argument("--dst", type=Path, default=None,
                    help="世代の保存先（既定: work/runtime/dq2-backup/savestate-backup）")
    ap.add_argument("--generations", type=int, default=DEFAULT_GENERATIONS,
                    help="残す世代数（既定 10）")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                    help="監視間隔（秒。既定 1）")
    ap.add_argument("--once", action="store_true", help="1回だけ見て終わる")
    ap.add_argument("--list", action="store_true", help="世代を一覧する")
    ap.add_argument("--restore", metavar="ファイル名",
                    help="復元する（例: DQ2_J.fc0）")
    ap.add_argument("--gen", type=int, default=0,
                    help="復元する世代（0=最新。--list で確認）")
    ap.add_argument("--legacy", action="store_true",
                    help="旧保存先 work/savestate-backup を一覧・復元する（〜2026-10-03 の世代）")
    ap.add_argument("--status", action="store_true",
                    help="DQ2 の控えが動いているかを BUSY / FREE で出す（起動スクリプト用）")
    # ★この起動のセッションID（起動スクリプトが渡す）。GUI が「自分が立てた控えだけ」を止めるための鍵。
    ap.add_argument("--session", default=None,
                    help="起動スクリプトが付けるセッションID（内部用）")
    ap.add_argument("--force", action="store_true",
                    help="別のバックアップが動いていても起動する（★非推奨）")
    # ★RX-0170: 起動に失敗したとき、その起動で立てた控えだけを止める（起動スクリプト用）
    ap.add_argument("--stop-session", metavar="ID", default=None,
                    help="この札の控えだけに停止の合図を置く（STOPPED / OTHER / NONE を出す）")
    ap.add_argument("--wait", type=float, default=5.0,
                    help="--stop-session: 控えが立ち上がるのを待つ秒数（既定 5）")
    args = ap.parse_args(argv)

    if args.status:
        print("BUSY" if is_busy() else "FREE")
        return 0
    if args.stop_session:
        print(stop_own(args.stop_session, wait=args.wait))
        return 0
    if args.dst is None:
        args.dst = legacy_dst() if args.legacy else default_dst()
    if args.list:
        return cmd_list(args.dst)
    if args.src is None:
        # ★DQ2 の FCEUX の隣の fcs/（RX-0146）。⚠ FCEUX を外に置くとセーブも一緒に動く（exe の隣に書く）
        from ..core import dq2_paths

        args.src = dq2_paths.fcs_dir()
    if args.restore:
        keep = default_dst() if args.legacy else None
        return cmd_restore(args.src, args.dst, args.restore, args.gen,
                           args.generations, keep_dst=keep)
    if args.legacy:
        print("--legacy は --list / --restore と一緒に使います", file=sys.stderr)
        return 2

    # ★監視し続けるとき（＝GUI と並走するとき）だけログ基盤を立てる。
    from ..core.config import dq2_user_config as user_config_mod  # ★DQ2 専用の設定（RX-0147）
    from ..core.logging_setup import setup_logging

    user_cfg, _ = user_config_mod.load()
    log_handle = setup_logging(
        user_cfg.path("log"),
        level=user_cfg.logging.resolved()["level"],
        max_bytes=user_cfg.logging.max_bytes,
        backup_count=user_cfg.logging.backup_count,
    )
    atexit.register(log_handle.shutdown)
    rom_stem = rom_stem_from(user_cfg)

    if not args.src.is_dir():
        # ⚠⚠ 置き場の親（★FCEUX のフォルダ）が無ければ作らない（RX-0176）。
        #   ⚠ 以前は `parents=True` で、FCEUX の場所の設定が間違っていると**存在しない FCEUX のフォルダごと**作り、
        #     誰も書かない場所を見張り続けた（★RX-0169 の fceux.cfg と同じ型）。
        if not args.src.parent.is_dir():
            say(f"セーブステートの置き場を作りません: {args.src}"
                f"（★FCEUX のフォルダが見つかりません: {args.src.parent}）",
                logger=_log(), level="error")
            return 1
        # ★無ければ作る（新規の FCEUX 展開直後は fcs/ が未作成 / 2026-08-20 UAT）
        try:
            args.src.mkdir(exist_ok=True)
            say(f"セーブステートの置き場を作成しました: {args.src}", logger=_log())
        except OSError as exc:
            say(f"セーブステートの置き場を作れません: {args.src}（{exc}）",
                logger=_log(), level="error")
            return 1

    if args.once:
        made = scan(args.src, args.dst, args.generations, rom_stem=rom_stem)
        print(f"{made} 件を世代に保存しました")
        return 0

    # ★★ 二重起動を止める（★DQ2 専用のロック / 心拍で見るので異常終了しても10秒後に解放）★★
    from ..core.single_instance import AlreadyRunningError, RecorderLock

    lock_file = lock_path()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock = RecorderLock(
        lock_file,
        description="DQ2 のセーブステートのバックアップ",
        consequence=("2つ動くと世代が倍の速さで流れ、"
                     "戻りたい世代が押し出されます。"),
    )
    try:
        lock.acquire(force=args.force)
    except AlreadyRunningError as exc:
        say(f"起動を中止しました: {exc}", logger=_log(), level="warning")
        return 1

    say(f"監視します: {console.short_path(args.src)}（{rom_stem}* だけ）", stream_name="stdout")
    say(f"  保存先: {console.short_path(args.dst)}"
        f" / {args.generations}世代 / {args.interval}秒ごと",
        stream_name="stdout")
    say("  ★世代を作るのは中身が変わったときだけです"
        "（古い世代を押し出さないため）。", stream_name="stdout")
    if console.has_console():
        say("  Ctrl+C で終了", stream_name="stdout")
    _log().info("DQ2 のセーブステートのバックアップを開始しました（%s* / %s世代 / %s秒ごと）",
                rom_stem, args.generations, args.interval,
                extra={"event_type": "savestate_backup"})
    seen: dict[str, tuple[int, int]] = {}
    # ★★ 止め方: ファイルで伝える（コピーの途中で殺さない）。★DQ2 専用の場所 ★★
    stop = stop_path()
    stop.unlink(missing_ok=True)      # 前回の残骸を消してから始める

    last_backup = None
    write_status(lock_file, args, running=True, session=args.session)

    try:
        while True:
            made = scan(args.src, args.dst, args.generations, rom_stem=rom_stem, seen=seen)
            if made:
                last_backup = datetime.now().strftime("%H:%M:%S")
            lock.touch()          # 心拍。止まったら他が起動できるように
            write_status(lock_file, args, running=True, session=args.session,
                         last_backup=last_backup)
            if stop.exists():
                stop.unlink(missing_ok=True)
                say("停止の合図を受け取りました。終了します。",
                    stream_name="stdout")
                _log().info("DQ2 のセーブステートのバックアップを終了しました",
                            extra={"event_type": "savestate_backup"})
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        say("終了しました", stream_name="stdout")
    finally:
        lock.release()
        # ★停止したことを状態ファイルにも書く（⚠ 消すと「一度も動いていない」と区別できない）
        write_status(lock_file, args, running=False, session=args.session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
