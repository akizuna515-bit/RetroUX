"""GUI の入口。**これが RetroUX の正式なメイン入口です**（MVP2 Phase 1）。

FCEUX 側（run.lua）と並行して起動します。表示専用で、ゲームへの入力は行いません。

    python -m retroux.gui
    python -m retroux.gui --read-only     # 取り込みはせず、記録を眺めるだけ

★`python -m retroux.record` は**同じ取り込みを CLI でやる補助**です。
  どちらか一方だけが events.jsonl を取り込めます（指示書 6.3）。
  両方動かすと**すべての戦闘が二重に記録**され、
  「削減できた待ち時間」という中心指標が壊れます。
  排他はロックファイル（既定 `work/event_ingestor.lock`）で行います。

★設定は2か所に分かれています。混ぜないでください:
    user_config.yaml                  … あなたの環境（パス・画面・ログ）
    retroux/plugins/dq2/config.yaml   … ゲームの知識（実機検証の積み重ね）
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from pathlib import Path

import yaml

from .core import rom as rom_mod
from .core import text as text_mod
from .core.config import user_config as user_config_mod
from .core.db.database import Database
from .core.console import say
from .core.logging_setup import get_logger, setup_logging
from .core.recorder import Recorder, rotate_events
from .core.single_instance import AlreadyRunningError, RecorderLock
from .ui.view_model import ViewModel
from .version import VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = PROJECT_ROOT / "retroux" / "plugins" / "dq2"

# 指示書 6.3 の文言。取り込みが二重にならないことが最優先。
BUSY_MESSAGE = (
    "イベント取込プロセスが既に稼働しています。\n"
    "GUIを閲覧専用で起動するか、既存Recorderを終了してください。\n"
    "  閲覧専用で起動: python -m retroux.gui --read-only"
)


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _ensure_art_dir(config: dict, key: str, default: str) -> Path:
    """モンスターの絵の置き場を用意する。

    ⚠⚠ **Lua 側では作れない。** `gui.savescreenshotas` はフォルダを作らず、
      無いと**黙って失敗する**（エラーも出ない）。そうなると毎回
      「書き出せませんでした」の警告が出続け、原因が分からない。
      Python 側は起動時に必ず通るので、ここで作る。

    ★設定と同じ場所を使う（`config.yaml` の `monster_art.dir`）。
      2か所に別々に書くと、片方だけ直して静かに食い違う。
    """
    art = config.get("monster_art") or {}
    rel = str(art.get(key) or default)
    path = PROJECT_ROOT / rel
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        # ★作れなくても本体は動かす（図鑑に「未撮影」と出るだけ）
        pass
    return path


def _ensure_tile_shot_dir(config: dict) -> Path:
    """遷移タイルの写真の置き場を用意する（マッパー仕様 フェーズ4）。

    ⚠⚠ **Lua 側では作れない**（`_ensure_art_dir` と同じ理由）。
      `gui.savescreenshotas` はフォルダを作らず、無いと黙って失敗する。
    """
    cfg = config.get("map") or {}
    rel = str(cfg.get("tile_shot_dir") or "work/map-observations/stair_tiles")
    path = PROJECT_ROOT / rel
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        # ★作れなくても本体は動かす（写真が撮れないとログに出るだけ）
        pass
    return path


def _load_map_meta(config: dict) -> dict:
    """マップの大きさ等を読む（`dq2rom maps export` の出力）。

    ★**無くても動く**。無ければ地図は「歩いた範囲に合わせた枠」で描く。
      推測の大きさを出さないので、無いこと自体は害にならない。
    """
    from .ui.map_window import load_map_meta

    cfg = config.get("map") or {}
    rel = str(cfg.get("meta_path") or "work/map-data/maps.json")
    return load_map_meta(PROJECT_ROOT / rel)



def _build_live_metatiles(config: dict, rom_path: Path):
    """見たマスの絵を **ROM から**用意する係を組み立てる（2026-08-02 / #65）。

    ⚠⚠ **無くても動く**ようにします。ここで落ちると地図どころか
      本体が起動しません。★用意できなければ None を返し、
      これまでどおり「色とタイルID」だけの地図になります。

    ★絵が ROM から出せるので、**採取したセーブステートの周り**という
      縛りが外れます。⚠ 描くのは見たマスだけ（指示書 §2.2）。
    """
    try:
        from dq2rom.monsters.palette import load_nes_palette

        from .core.bgmap.catalog import (
            DEFAULT_ASSETS_REL, AssetStore, resolve_assets_dir)
        from .core.bgmap.live import LiveMetatiles
        from .core.bgmap.rom_assets import RomTileSource

        # ⚠ 2026-08-12: ここは `map.assets_dir` を読んでいましたが、設定に
        #   あるのは `map.rendering.assets_path` でした（バックログ P0-01）。
        #   ★落ちない代わりに、**書いた値が黙って無視されて**いました。
        assets = resolve_assets_dir(config, PROJECT_ROOT)
        if assets != PROJECT_ROOT / DEFAULT_ASSETS_REL:
            # ⚠⚠ 採取（`bg_capture_probe.lua`）は `work/map-assets` へ書きます。
            #   ★既定から変えたことを黙っていると、「素材が無い」の原因が
            #     設定なのか採取漏れなのか分かりません。
            get_logger("gui").debug(
                "地図の素材の置き場所を設定から使います: %s"
                "（⚠ 採取は %s へ書きます）", assets, DEFAULT_ASSETS_REL)
        store = AssetStore(assets)
        store.prepare()
        palette = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"
        if not palette.exists() or not rom_path.exists():
            return None
        return LiveMetatiles(RomTileSource(rom_path), store,
                             load_nes_palette(palette))
    except Exception:                                   # noqa: BLE001
        # ⚠ 黙って消すのではなく「絵が出ないだけ」に留める。
        #   ★原因は地図ウィンドウの「素材」欄で分かるようにしてある。
        return None


def _build_map_render(config: dict):
    """地図の描き方を設定から読む（2026-08-12 / 監査 P0-A）。

    ⚠⚠ **これまで誰も呼んでいませんでした。** `core/bgmap/settings.py` は
      あったのに、呼んでいたのは `tests/test_map_settings.py` だけで、
      `config.yaml` の `map.rom_master` 6項目は**書いても無視**でした
      （`docs/audit/source-to-doc.md` の 2 / P0-01 と同じ形）。

    ★直した点や、まだ効かない項目は**必ずログに出します**。
      ⚠ 黙って無視するのが、いちばん原因を追いにくい壊れ方です。
    """
    from .core.bgmap.settings import load as load_map_render

    got = load_map_render(config)
    log = get_logger("gui")
    # ★起動時の要約。⚠ 利用者が読む必要は無い（§18K 通常→DEBUG）
    log.debug("地図の描き方: %s", got.summary())
    for note in got.notes:
        log.warning("地図の設定: %s", note)
    # ★★ まだ効かない項目を既定から変えていたら知らせる ★★
    for note in got.unsupported_changes():
        log.warning("地図の設定: %s", note)
    return got


def _build_navigation(config: dict, db, rom_hash: str):
    """移動知識ログの観測役を作る。無効なら None。

    ★★ **保存するのは「どのキーを押したか」ではなく「どこが通れたか」。**
      詳しくは `retroux/core/navigation/__init__.py`。

    ⚠ 作れなくても本体は動かす（地図知識が溜まらないだけ）。
    """
    cfg = config.get("navigation") or {}
    if not cfg.get("enabled", True):
        return None
    try:
        from .core.navigation import NavigationObserver, NavigationRepository
        from .core.navigation.repository import Thresholds

        repo = NavigationRepository(
            db, rom_hash,
            Thresholds(
                blocked_probable=int(cfg.get("blocked_probable_threshold", 3)),
                transition_confirmed=int(
                    cfg.get("transition_confirmed_threshold", 2))))
        # ★★ ROM 解析との食い違いだけを拾う（2026-08-13 / §17）★★
        #   ⚠ 表が無ければ `PassabilityTable` は空になり、**何も鳴りません**。
        #     ★作るには `python -m retroux.tools.map_passability`。
        from .core.navigation.mismatch import PassabilityTable

        table_path = PROJECT_ROOT / str(
            cfg.get("passability_path") or "work/generated/map_passability.json")
        table = PassabilityTable.load(table_path)
        if not table:
            # ⚠ 無いこと自体は異常ではない（★作っていないだけ）。
            #   ただし黙っていると「食い違いが 0 件」と取り違える。
            get_logger("navigation").debug(
                "通行可能性の表がありません: %s"
                "（★`python -m retroux.tools.map_passability` で作れます）",
                table_path.name)

        # ★★ 通常歩行の学習は既定で切（2026-08-13 / 製品版ログ整理 §12）★★
        #   ⚠ ここの既定が入のままだと、`NavigationObserver` 側だけ切っても
        #     **設定を経由する実運用では効きません**（★2か所そろえる）。
        #   ★遷移（§16）は入のまま。ROM 解析では作れないため。
        return NavigationObserver(
            repo,
            move_timeout_frames=int(cfg.get("move_timeout_frames", 30)),
            record_edges=bool(cfg.get("record_edges", False)),
            record_blocked=bool(cfg.get("record_blocked", False)),
            record_transitions=bool(cfg.get("record_transitions", True)),
            passability=table if table else None,
            logger=get_logger("navigation"))
    except Exception as exc:                           # noqa: BLE001
        get_logger("gui").warning("移動知識ログを用意できませんでした: %s", exc)
        return None


def _build_location_resolver(config: dict):
    """地名の辞書を読む（マッパー仕様 4章）。読めなければ None。

    ★★ **名前は表示だけに使う。** ★★
      自動移動が使うのは `map_id` と階層（どちらも ROM 由来）なので、
      辞書が無くても、名前が間違っていても、経路の判断は壊れない。
    """
    cfg = config.get("locations") or {}
    if not cfg.get("enabled", True):
        return None
    rel = str(cfg.get("data_dir") or "retroux/plugins/dq2/data")
    try:
        from .core.navigation.location_resolver import LocationResolver

        resolver = LocationResolver.load(PROJECT_ROOT / rel,
                                         logger=get_logger("locations"))
        if resolver.dictionary.is_empty:
            # ⚠ 空でも None にはしない。「未登録のマップ」と出るほうが、
            #   何も出ないより分かる。
            get_logger("gui").warning(
                "地名の辞書が空です（%s）。マップ名は ID だけになります。", rel)
        return resolver
    except Exception as exc:                           # noqa: BLE001
        get_logger("gui").warning("地名の辞書を読めませんでした: %s", exc)
        return None


def _build_floor_estimator(observer, resolver):
    """階層を決める役を作る（マッパー仕様 フェーズ5）。

    ★★ **階層は自動移動が使う情報。** ★★ 名前と違って、間違えると
      別の階へ行こうとする。だから出どころを分けて持ち、
      食い違ったら**黙って片方に丸めず画面に出す**。

    ⚠ どちらも無くても作る（そのぶん「階層不明」と出るだけ）。
    """
    try:
        from .core.navigation.floor_estimator import FloorEstimator

        return FloorEstimator(
            getattr(observer, "repo", None),
            getattr(resolver, "dictionary", None))
    except Exception as exc:                           # noqa: BLE001
        get_logger("gui").warning("階層の推定を用意できませんでした: %s", exc)
        return None


def _build_tactics(config: dict, user_cfg):
    """戦術プロフィールの置き場を用意する（仕様書 10.1）。

    ★★ **プロフィールが無くても、これまでとまったく同じ挙動。** ★★
      `work/generated/tactics.lua` が無ければ Lua は `config.yaml` の値で動く。
      「入れたら壊れた」を起こさないための線（仕様書 2.4）。

    ⚠ 置き場が作れなくても None にしない（同梱の見本だけで動く）。
    """
    cfg = config.get("tactics") or {}
    if not cfg.get("enabled", True):
        return None
    rel = str(cfg.get("dir") or "work/tactics/profiles")
    try:
        from .core.tactics import TacticsRepository

        repo = TacticsRepository(PROJECT_ROOT / rel,
                                 logger=get_logger("tactics"))
        # ★見本をファイルとしても置く（手で編集したい人向け）。
        #   ⚠ 既にあるファイルは上書きしない（手で直したものを壊さない）。
        if cfg.get("install_presets", True):
            placed = repo.install_presets()
            if placed:
                get_logger("gui").debug(
                    "戦術プロフィールの見本を %d 件置きました（%s）", placed, rel)
        return repo
    except Exception as exc:                           # noqa: BLE001
        get_logger("gui").warning("戦術プロフィールを用意できませんでした: %s", exc)
        return None


def build_view_model(rom_arg: str | None = None, *,
                     user_cfg: user_config_mod.UserConfig | None = None,
                     read_only: bool = False) -> tuple[ViewModel, Database]:
    user_cfg = user_cfg or user_config_mod.UserConfig()
    config = _load_yaml(PLUGIN_DIR / "config.yaml")
    memory_map = _load_yaml(PLUGIN_DIR / "memory_map.yaml")

    rom_path = Path(rom_arg) if rom_arg else user_cfg.path("rom")
    if not rom_path.is_absolute():
        rom_path = PROJECT_ROOT / rom_path
    info = rom_mod.identify(rom_path)

    rom_meta = memory_map.get("rom", {})
    # ★★ ⚠⚠ **求めている ROM かを確かめる**（2026-08-18 / RX-0057）★★
    #
    #   `memory_map.yaml` に期待するハッシュが書いてあるのに、
    #   ⚠ **どこも照合していなかった**。iNES ヘッダさえあれば起動していた。
    #
    #   ★別の ROM だと RAM の番地が全部違うので、
    #     「動いているように見えて、全部が嘘」になる。
    #     ⚠ AUTO と倍速が**見当違いのタイミングでキーを押す**のが一番危ない。
    rom_mod.check_expected(info, rom_meta)
    db = Database(user_cfg.path("db"))
    db.register_rom(
        rom_hash=info.prg_sha256,
        title=str(rom_meta.get("title", rom_path.stem)),
        region=str(rom_meta.get("region", "?")),
        mapper=info.mapper,
    )

    # ★★ イベントの世代交代（2026-08-13 / 製品版ログ整理 §25）★★
    #   ⚠ `Recorder` を作る**前**に一度だけ。取り込みが追いついていなければ
    #     何もしません（★未取り込みの行を置き去りにしないため）。
    #   ★世代交代と取り込み位置のリセットは `rotate_events` が対で行います。
    _rot_log = get_logger("record")
    try:
        rotation = rotate_events(db, user_cfg.path("events"))
        if rotation.rotated:
            _rot_log.info("%s", rotation.message())
        else:
            _rot_log.debug("%s", rotation.message())
    except Exception as exc:                           # noqa: BLE001
        # ⚠ 世代交代に失敗しても起動は止めない（★記録が伸びるだけ）
        _rot_log.warning("イベントの世代交代に失敗しました: %s", exc)

    recorder = Recorder(
        db=db,
        rom_hash=info.prg_sha256,
        events_path=user_cfg.path("events"),
        command_path=user_cfg.path("command"),
    )

    # boss_monster_ids が空なら、Lua からの警告を待たずに GUI へ出す。
    # 起動直後から見えていないと安全機構として意味がない（DEV-8）。
    # code を付けることで、後から届く Lua 側の同じ警告と重複しない。
    if not config.get("boss_monster_ids"):
        recorder.add_warning(
            "boss_monster_ids が未設定です。ボス戦を通常戦闘として扱うため、"
            "ボスに敗北後の再戦で倍速と自動入力が有効になります。",
            code="boss_ids_empty",
        )

    # ★遷移タイルの写真の置き場（Lua は作れない）
    _ensure_tile_shot_dir(config)

    navigation = _build_navigation(config, db, info.prg_sha256)
    location_resolver = _build_location_resolver(config)
    # ★見たマスの絵を ROM から用意する係（2026-08-02 / 課題 #65）
    live_metatiles = _build_live_metatiles(config, rom_path)

    view_model = ViewModel(
        recorder=recorder,
        db=db,
        rom_hash=info.prg_sha256,
        monsters={int(k): str(v) for k, v in (memory_map.get("monsters") or {}).items()},
        monster_stats={int(k): v
                       for k, v in (memory_map.get("monster_stats") or {}).items()},
        # --- 図鑑で使う ROM 由来データ（2026-07-27）------------------------
        # ★どれも「無くても動く」（memory_map が古い環境ではその欄が空になる）
        monster_behavior={int(k): v
                          for k, v in (memory_map.get("monster_behavior") or {}).items()},
        monster_actions={int(k): str(v)
                         for k, v in (memory_map.get("monster_actions") or {}).items()},
        action_rates={int(k): list(v)
                      for k, v in (memory_map.get("action_rates") or {}).items()},
        items={int(k): str(v) for k, v in (memory_map.get("items") or {}).items()},
        # モンスターの絵の置き場。**無ければ図鑑に「未撮影」と出る**
        art_dir=_ensure_art_dir(config, 'dir', 'work/monster-art'),
        art_raw_dir=_ensure_art_dir(config, 'raw_dir', 'work/monster-art/raw'),
        # ★ROM から展開した絵（`dq2rom monsters install`）。撮影より優先して出す
        art_rom_dir=_ensure_art_dir(config, 'rom_dir', 'work/monster-art-rom'),
        # ★マップの大きさ等（`dq2rom maps export` の maps.json）。
        #   ★地形は入っていない。⚠ 2026-08-12 訂正: 理由を「日本版では**未解読**」と
        #   書いていましたが、地形は 2026-08-02〜03 に解読済みです
        #   （非ワールド 108/108・世界地図 65536/65536）。`maps.json` に無いのは
        #   ★`dq2rom maps export` が大きさ等しか出していないからで、無くても動く。
        map_meta=_load_map_meta(config),
        # ★地図に記録する「画面に映る範囲」の半径（マス）
        view_radius=int((config.get('map') or {}).get('view_radius', 7)),
        # ★ワールドマップの大きさ（ROM から読めないので設定から。実測 256×256）
        overworld_size=(
            int((config.get('map') or {}).get('overworld_width', 256)),
            int((config.get('map') or {}).get('overworld_height', 256))),
        # ★地図の拡大倍率（整数倍だけ。0 で「収まる最大」）
        map_zoom=(int((config.get('map') or {}).get('zoom', 4)),
                  int((config.get('map') or {}).get('overworld_zoom', 1))),
        # ★ゲーム内で付けたキャラ名を出すための文字コード表（memory_map の text:）
        charset=text_mod.from_memory_map(memory_map),
        name_length=int(((memory_map.get('addresses') or {}).get('party') or {})
                        .get('names', {}).get('length', 4)),
        # ★`names` は dataclass。空文字の項目は「指定なし」として落とす
        name_overrides={k: v for k, v in
                        vars(getattr(user_cfg, 'names', None) or object()).items()
                        if isinstance(v, str) and v.strip()},
        read_only=read_only,
        # ★閲覧専用でも状態は読む（記録しないだけで、表示は止めない）
        state_path=user_cfg.path("state"),
        # ★移動知識ログ（`config.yaml` の `navigation:`）。
        #   ⚠ 閲覧専用のときは ViewModel 側で使わない（二重書きを避ける）
        navigation=navigation,
        # ★地名の辞書（`config.yaml` の `locations:`）。表示だけに使う
        location_resolver=location_resolver,
        # ★16×16 の絵を ROM から用意する係。⚠ None でも地図は動く
        live_metatiles=live_metatiles,
        # ★階層（人の指定 > ROM 由来 > 上下移動からの推定）。
        #   ⚠ こちらは表示だけでなく**自動移動が使う**情報
        floor_estimator=_build_floor_estimator(navigation, location_resolver),
        # ★キャラクター別戦術プロフィール（`config.yaml` の `tactics:`）
        tactics=_build_tactics(config, user_cfg),
        # ★地図の描き方（`config.yaml` の `map.rom_master:`）。
        #   ⚠⚠ 2026-08-12 まで**書いても効いていませんでした**（監査 P0-A）。
        map_render=_build_map_render(config),
    )
    # ★★ 起動時に、選んでいる戦術を Lua へ渡し直す。 ★★
    #   ⚠ これが無いと、前回選んだ戦術が「選ばれているのに効かない」状態になる
    #     （`tactics.lua` は Git 管理外なので、環境を移すと消える）。
    if not read_only and view_model.tactics is not None:
        if view_model.push_tactics():
            prof = view_model.active_tactics()
            get_logger("gui").debug("戦術プロフィールを渡しました: %s",
                                   prof.name if prof else "?")
    return view_model, db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RetroUX GUI（表示専用）")
    parser.add_argument("--rom", default=None,
                        help="対象ROM（既定は user_config.yaml の paths.rom）")
    parser.add_argument("--interval", type=int, default=None,
                        help="画面更新の間隔（ミリ秒）")
    parser.add_argument("--read-only", action="store_true",
                        help="イベントを取り込まず、記録を眺めるだけで起動する")
    parser.add_argument("--force", action="store_true",
                        help="他の記録プロセスが動いていても取り込む（非推奨）")
    parser.add_argument("--config", default=None, help="user_config.yaml のパス")
    # ★この起動のセッションID（起動スクリプトが渡す / 仕様書 6.3）。
    #   ⚠ **今回起動した子プロセスだけ**を見分けるための鍵。
    #     手で起動したバックアップを誤って終了しないために要る。
    parser.add_argument("--session", default=None,
                        help="起動スクリプトが付けるセッションID（内部用）")
    args = parser.parse_args(argv)

    user_cfg, cfg_warnings = user_config_mod.load(args.config)

    # ★ログ基盤はいちばん先に立てる。ここから先の失敗もログに残したい。
    # ★下限は `logging.mode` から決める（2026-08-13 / §19）。
    #   ⚠ `level` / `gui_level` が書いてあればそちらが勝つ。
    _levels = user_cfg.logging.resolved()
    log_handle = setup_logging(
        user_cfg.path("log"),
        level=_levels["level"],
        # ★画面に出す下限は別（2026-08-09）。細かい記録はファイルだけへ
        gui_level=_levels["gui_level"],
        max_bytes=user_cfg.logging.max_bytes,
        backup_count=user_cfg.logging.backup_count,
        buffer_capacity=user_cfg.logging.gui_lines,
    )
    log = get_logger("gui")
    for warning in cfg_warnings:
        log.warning(warning)

    try:
        read_only = args.read_only
        lock = RecorderLock(user_cfg.path("lock"))

        # 閲覧専用が指定されていなければ、取り込み役を取りにいく。
        if not read_only:
            try:
                lock.acquire(force=args.force)
            except AlreadyRunningError as exc:
                # ★ここで落とさない。閲覧専用へ落として**画面は出す**。
                #   記録は既に別プロセスが取っているので、失うものは無い。
                log.warning("%s", exc)
                # ⚠ `pythonw.exe` では `sys.stderr` が使えないことがある。
                #   `print` を直に呼ぶと AttributeError で落ち、
                #   利用者から見て「何も起きない」になる（仕様書 5.1）。
                say(BUSY_MESSAGE, logger=log, level="warning")
                say("閲覧専用で起動します。", logger=log, level="warning")
                read_only = True

        try:
            view_model, db = build_view_model(args.rom, user_cfg=user_cfg,
                                              read_only=read_only)
        except (FileNotFoundError, rom_mod.InvalidRomError) as exc:
            log.error("起動に失敗しました: %s", exc)
            say(f"起動に失敗しました: {exc}", logger=log, level="error")
            if not read_only:
                lock.release()
            return 1

        # ★★ バージョンと起動モードをログの1行目に残す（仕様書 14章）。★★
        #   問い合わせを受けたとき、まずここを見れば版と経路が分かる。
        log.info("RetroUX %s を起動しました（%s / %s / session=%s）",
                 VERSION, "閲覧専用" if read_only else "取り込みあり",
                 pathlib.Path(sys.executable).name, args.session or "-")

        # Qt の import は実際に画面を出すときだけ行う。
        # ViewModel の検証に Qt を要求しないため。
        from PySide6.QtWidgets import QApplication

        from .ui.main_window import MainWindow

        app = QApplication(sys.argv[:1])

        # ★★ ツールチップを早く出す（2026-08-11 / 依頼者の要望）★★
        #   ⚠ Qt はツールチップの待ち時間を**スタイルのヒント**で持ち、公開APIが
        #     無い。いまのスタイルを薄く包み、待ち時間だけ縮める（見た目は変えない）。
        from PySide6.QtWidgets import QProxyStyle, QStyle

        class _FastTooltipStyle(QProxyStyle):
            def styleHint(self, hint, option=None, widget=None,
                          returnData=None):
                if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
                    return 250          # 既定 ~700ms → 250ms
                return super().styleHint(hint, option, widget, returnData)

        app.setStyle(_FastTooltipStyle(app.style()))

        window = MainWindow(
            view_model,
            interval_ms=args.interval or user_cfg.gui.interval_ms,
            heartbeat=None if read_only else lock.touch,
            log_buffer=log_handle.buffer,
            gui_config=user_cfg.gui,
            # ⚠⚠ **`gui_config` と `user_config` の両方を渡す。**
            #   `gui_config`（= `user_cfg.gui`）に `path()` は無いので、
            #   これだけ渡すと診断情報とログ導線が動かない（2026-07-30 に踏んだ）。
            user_config=user_cfg,
            # ★地図は RetroUX の主要機能なので標準で出す（指示書 §8）。
            #   ⚠ フォーカスは奪わない（出しただけでゲームの操作を取らない）。
            show_map=True,
            # ★Lua も同じファイルへ書く。ファイルを追えば両方が時系列で並ぶ。
            log_path=user_cfg.path("log"),
            names_config=user_cfg.names,
        )
        window.show()
        # ★★ 前回開いていた窓を開き直す（2026-08-09 / 依頼者の指示）★★
        #   ⚠ **`show()` のあとで呼ぶこと。** 先に呼ぶと、開いた窓が本体より
        #     先に前面へ出て、ゲーム画面との重なりが変わります。
        #   ⚠ 起動の道だけが呼びます（`MainWindow` を作るだけでは開きません）。
        try:
            window.reopen_remembered_windows()
        except Exception:                               # noqa: BLE001
            log.warning("前回開いていた窓を戻せませんでした", exc_info=True)
        try:
            return app.exec()
        finally:
            if not read_only:
                lock.release()
            db.close()
    finally:
        log_handle.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
