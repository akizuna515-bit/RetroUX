"""セーブステートの世代バックアップ。

依頼者の要望:

    セーブステートが出来たら、10世代ぐらいバックアップする。
    更新されるたびに世代バックアップが理想だが、ダメなら1分ごとにとかでもOK。
    いまのセーブステート管理だと、間違えてハマりポイントでセーブしたり、
    セーブロード間違えると最初の場面でセーブしたりと危険

★守りたいもの: **取り返しのつかない事故**。

  ・ハマりポイントで上書き保存した
  ・ロードのつもりでセーブして、序盤の状態で潰した

どちらも「上書きされた瞬間に元が消える」ため、後から復旧できない。
そこで**上書きされる前の内容を世代として残す**。

方式: ファイルの更新を監視して、変化を検知したら世代を1つ繰り上げる。
「更新されるたび」を実現するため、既定は1秒ごとに見る（1分でもよいと
言われているが、1秒でも負荷はほぼ無い。取りこぼしを減らす方を選ぶ）。

★同じ内容なら世代を作らない（ハッシュで判定）。
  そうしないと、触っていないのに世代が流れて**古い世代を押し出してしまう**。
  世代の目的は「戻れること」なので、押し出しは事故に直結する。

★書き込み途中のファイルを掴まないようにする。
  サイズが安定するまで待ってからコピーする。

使い方:

    uv run python -m retroux.tools.savestate_backup            # 監視し続ける
    uv run python -m retroux.tools.savestate_backup --once     # 1回だけ
    uv run python -m retroux.tools.savestate_backup --list     # 世代を一覧
    uv run python -m retroux.tools.savestate_backup --restore DQ2_J.fc0 --gen 3

⚠ 復元は**いまのファイルも世代として残してから**行う。
  「復元したら復元前に戻せない」では同じ事故を繰り返す。
"""

from __future__ import annotations

# ★世代を作った事実は**共有ログ**に残す（MVP2 Phase 1）。
#   このツールは自分のコンソールにしか出しておらず、
#   「いつ世代が回ったか」が後から追えなかった。
#   守っているのが**取り返しのつかない事故**なので、
#   「動いていた証拠」が残らないのは具合が悪い。

import argparse
import atexit
import hashlib
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from ..core import backup_status, console
from ..core.console import say

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = PROJECT_ROOT / "tools" / "fceux" / "fcs"
DEFAULT_DST = PROJECT_ROOT / "work" / "savestate-backup"
DEFAULT_GENERATIONS = 10
DEFAULT_INTERVAL = 1.0

# FCEUX のセーブステート。fc0〜fc9 と fcs。
PATTERNS = ("*.fc[0-9]", "*.fcs")

#: ★世代ファイル名に入れる**プロセス内で単調増加する連番**（2026-08-11）。
#   時計の分解能が粗いと同じ刻印で複数できるので、これで並びの同着を必ず解く。
#   ⚠ 捨てた番号は**再利用しない**（常に増やす）。再利用すると並びが逆転する。
_gen_seq = 0


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def settled(path: Path, tries: int = 5, wait: float = 0.08) -> bool:
    """書き込み途中でないことを確かめる。サイズが2回続けて同じなら安定とみなす。

    ★掴むのが早すぎると、壊れた（途中までの）内容を世代に残してしまう。
      それでは「戻れる」という目的を果たさない。
    """
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
    """src を新しい世代として保存する。同じ内容なら何もしない。"""
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

    # ★マイクロ秒まで入れる。名前の長さを常に同じにして、
    #   **文字列の並び順＝時刻の並び順**にする。
    #
    #   ⚠⚠ **時計の分解能では足りない**（2026-08-11 に再発）。★★
    #     秒までにして衝突時に "-1" を足す作りだと、"…-1.bak" が "….bak" より
    #     前に並び（"-" < "."）、同じ時刻に2つできると最新判定が逆転していた。
    #     マイクロ秒にしても、Windows の時計は粗く（数ms〜十数ms）、素早い連続
    #     保存で**同じ刻印**になる。そのとき衝突連番 "-001" がやはり "….bak" より
    #     前に並び、★**最新の世代を消してしまう**（テストで検出 / 3回に2回失敗）。
    #
    #   → ★**プロセス内で単調増加する連番**を必ず名前へ入れる。刻印が同着でも
    #     連番で必ず「新しいほど後ろ」に並ぶ。連番は捨てた番号を再利用しない
    #     （間引きで消えた低い番号を後から使うと、また逆転するため）。
    #     ⚠ 再起動で連番は 0 に戻るが、そのときは実時計が秒単位で進むので、
    #       刻印（時刻）が新しい方を勝たせる。
    global _gen_seq
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    _gen_seq += 1
    target = d / f"{stamp}-{_gen_seq:06d}.bak"
    while target.exists():
        _gen_seq += 1
        target = d / f"{stamp}-{_gen_seq:06d}.bak"
    shutil.copy2(src, target)

    # 古い世代を削る（新しい順に generations 個だけ残す）
    for old in list_generations(dst, name)[generations:]:
        old.unlink(missing_ok=True)
    return target


def scan(src_dir: Path, dst: Path, generations: int, quiet: bool = False,
         seen: dict[str, tuple[int, int]] | None = None) -> int:
    """1回ぶん見る。

    ★`seen` を渡すと「前回と同じ（更新時刻とサイズが不変）」のファイルを
      **完全に飛ばす**。読まない・ハッシュも取らない・待機もしない。

      これが無いと、変化していなくても毎回すべてのファイルに対して
      settled() の待機（1ファイルあたり最低0.08秒）が走り、
      実測でセーブステート24件のとき**1回の巡回に約2秒**かかっていた。
      1秒間隔で見る意味が無くなるうえ、無駄にCPUとディスクを使う。

      更新時刻とサイズが同じなら中身も同じとみなす。
      厳密にはハッシュを取らないと分からないが、
      **変化したファイルは必ずハッシュで確認する**ので、
      「同じ内容なのに世代を作る」ことは起きない。
    """
    made = 0
    files: list[Path] = []
    for pat in PATTERNS:
        files.extend(src_dir.glob(pat))
    for f in sorted(files):
        if not f.is_file():
            continue
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


def write_status(user_cfg, args, *, running: bool, session=None,
                 last_backup=None, last_error=None) -> None:
    """稼働状態を GUI へ伝える（仕様書 6.1）。★**失敗しても止まらない**。

    ⚠ ここで例外を外へ出さない。表示のための処理でバックアップを止めたら、
      守るはずのもの（セーブステート）を守れなくなる。
    """
    try:
        backup_status.write(
            user_cfg.path("backup_lock"), running=running,
            generations=args.generations, watching=args.src,
            destination=args.dst, interval=args.interval,
            last_backup=last_backup, session=session, last_error=last_error)
    except Exception:                                  # noqa: BLE001
        pass


def _log():
    """共有ロガー。`setup_logging` を呼んでいなくても安全に使える。

    ★ここで setup_logging は呼ばない。呼ぶと、**どの入口から動かしても**
      ログの設定が上書きされる。設定するのは入口（main）の仕事。
    """
    from ..core.logging_setup import get_logger

    return get_logger("savestate")


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
                generations: int) -> int:
    gens = list_generations(dst, name)
    if not gens:
        print(f"世代がありません: {name}", file=sys.stderr)
        return 1
    if gen < 0 or gen >= len(gens):
        print(f"世代 {gen} は範囲外です（0〜{len(gens) - 1}）", file=sys.stderr)
        return 1

    target = src_dir / name
    # ★復元する前に、いまのファイルも世代として残す。
    #   「復元したら復元前に戻せない」では同じ事故を繰り返す。
    if target.exists():
        kept = rotate_in(target, dst, generations)
        if kept is not None:
            print(f"復元前の状態を世代に残しました: {kept.name}")
        else:
            print("復元前の状態は既に最新世代と同じでした")

    shutil.copy2(gens[gen], target)
    print(f"復元しました: {gens[gen].name} -> {target}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="セーブステートの世代バックアップ")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC,
                    help="監視するフォルダ（既定: FCEUX の fcs）")
    ap.add_argument("--dst", type=Path, default=DEFAULT_DST,
                    help="世代の保存先")
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
    # ★この起動のセッションID（起動スクリプトが渡す / 仕様書 6.3）。
    #   ⚠ **今回起動したものだけ**を見分けるための鍵。GUI が終了処理で使う。
    #     手で起動したものを誤って終了しないために要る。
    ap.add_argument("--session", default=None,
                    help="起動スクリプトが付けるセッションID（内部用）")
    ap.add_argument("--force", action="store_true",
                    help="別のバックアップが動いていても起動する（★非推奨）")
    args = ap.parse_args()

    if args.list:
        return cmd_list(args.dst)
    if args.restore:
        return cmd_restore(args.src, args.dst, args.restore, args.gen,
                           args.generations)

    # ★監視し続けるとき（＝GUI と並走するとき）だけログ基盤を立てる。
    #   --list / --restore は人が見るコマンドなので、画面に出れば足りる。
    from ..core.config import user_config as user_config_mod
    from ..core.logging_setup import setup_logging

    user_cfg, _ = user_config_mod.load()
    log_handle = setup_logging(
        user_cfg.path("log"),
        # ★下限は `logging.mode` から（2026-08-13 / §19）
        level=user_cfg.logging.resolved()["level"],
        max_bytes=user_cfg.logging.max_bytes,
        backup_count=user_cfg.logging.backup_count,
    )
    atexit.register(log_handle.shutdown)

    if not args.src.is_dir():
        # ★無ければ作る（新規の FCEUX 展開直後は fcs/ が未作成）。★2026-08-20 UAT。
        #   FCEUX が最初のセーブステートを書くまで空だが、監視は始められる。
        #   ⚠ `pythonw.exe` では画面に出ないので、作成・失敗ともログへ必ず書く。
        try:
            args.src.mkdir(parents=True, exist_ok=True)
            say(f"セーブステートの置き場を作成しました: {args.src}", logger=_log())
        except OSError as exc:
            say(f"セーブステートの置き場を作れません: {args.src}（{exc}）",
                logger=_log(), level="error")
            return 1

    if args.once:
        made = scan(args.src, args.dst, args.generations)
        print(f"{made} 件を世代に保存しました")
        return 0

    # ★★ 二重起動を止める ★★
    #
    #   2つ動くと、同じ変更を**両方が世代に回す**。世代数は決まっているので
    #   倍の速さで流れ、**戻りたい世代が押し出される**。
    #   このツールが守っているのは「取り返しのつかない事故」なので、
    #   守るはずの仕組み自身が事故を起こしてはいけない。
    #
    #   心拍で見るので、異常終了しても10秒後には自動的に解放される。
    from ..core.single_instance import AlreadyRunningError, RecorderLock

    lock = RecorderLock(
        user_cfg.path("backup_lock"),
        description="セーブステートのバックアップ",
        consequence=("2つ動くと世代が倍の速さで流れ、"
                     "戻りたい世代が押し出されます。"),
    )
    try:
        lock.acquire(force=args.force)
    except AlreadyRunningError as exc:
        say(f"起動を中止しました: {exc}", logger=_log(), level="warning")
        return 1

    # ⚠ コンソールが無いとき（公開用 / pythonw.exe）は画面に出ない。
    #   `say` はログへ必ず書くので、経過は残る（仕様書 4.1）。
    # ★パスは相対で出す（⚠ 利用者名が混ざらないように / RX-0043・§26）
    say(f"監視します: {console.short_path(args.src)}", stream_name="stdout")
    say(f"  保存先: {console.short_path(args.dst)}"
        f" / {args.generations}世代 / {args.interval}秒ごと",
        stream_name="stdout")
    say("  ★世代を作るのは中身が変わったときだけです"
        "（古い世代を押し出さないため）。", stream_name="stdout")
    if console.has_console():
        # ★Ctrl+C の案内は、コンソールがあるときだけ意味がある
        say("  Ctrl+C で終了", stream_name="stdout")
    _log().info("セーブステートのバックアップを開始しました（%s世代 / %s秒ごと）",
                args.generations, args.interval,
                extra={"event_type": "savestate_backup"})
    # 前回見たときの (更新時刻, サイズ)。変わっていないファイルは触らない。
    seen: dict[str, tuple[int, int]] = {}
    # ★★ 止め方 ★★
    #   このプロセスは別ウィンドウで動くので、GUI から Ctrl+C を送れない。
    #   **強制終了はしたくない**（コピーの途中で殺すと、途中まで書けた
    #   世代ファイルが残る＝壊れた世代が「戻れる状態」の顔をして並ぶ）。
    #   そこで「止まってほしい」を**ファイルで伝える**。
    #   ループの切れ目で見るので、コピーの最中に止まることがない。
    stop_path = user_cfg.path("backup_lock").with_suffix(".stop")
    stop_path.unlink(missing_ok=True)      # 前回の残骸を消してから始める

    # ★★ 状態ファイル（GUI が「稼働中／停止」を出すために読む / 仕様書 6.1）★★
    #   ⚠ 「動いているか」の判定は心拍（ロックの更新時刻）で行う。
    #     ここに書く `running` は当てにされない（異常終了すると残るため）。
    last_backup = None
    write_status(user_cfg, args, running=True, session=args.session)

    try:
        while True:
            made = scan(args.src, args.dst, args.generations, seen=seen)
            if made:
                # ★世代を作った時刻を覚える（画面の「最新バックアップ」）
                last_backup = datetime.now().strftime("%H:%M:%S")
            lock.touch()          # 心拍。止まったら他が起動できるように
            write_status(user_cfg, args, running=True, session=args.session,
                         last_backup=last_backup)
            if stop_path.exists():
                stop_path.unlink(missing_ok=True)
                say("停止の合図を受け取りました。終了します。",
                    stream_name="stdout")
                _log().info("セーブステートのバックアップを終了しました",
                            extra={"event_type": "savestate_backup"})
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        say("終了しました", stream_name="stdout")
    finally:
        # ★必ず離す。残しても心拍で10秒後に無効化されるが、
        #   すぐ再起動したいときに待たされる。
        lock.release()
        # ★★ 停止したことを状態ファイルにも書く（GUI が「停止」と出せる）。
        #   ⚠ 消すのではなく「停止」と書く。消すと GUI 側が
        #     「一度も動いていない」と「止まった」を区別できない。
        write_status(user_cfg, args, running=False, session=args.session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
