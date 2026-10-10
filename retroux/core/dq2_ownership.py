"""DQ2 のデータの持ち主と分類（RX-0156 / D-44 / 依頼 §8〜§10）。

★DQ2 が書く・読むファイルを、**1 件ずつ**分類した表です（⚠ フォルダの名前では決めない）。
⚠ DQ3 の `dq3/ownership.py` は参考にしただけで import しません（★独立した製品 / D-42）。

```text
USER_DATA         人が決めた・人が作ったもの（設定・セーブ・作戦）。⚠ 作り直せない
OBSERVED_DATA     遊んで貯まった記録（DB・events・遭遇の控え・地形の観測）。⚠ 作り直せない
DERIVED_DATA      ROM や他のデータから作り直せるもの
RUNTIME           実行中のやり取り・ロック・ログ。⚠ 古い値を持ち込むと誤動作する
DEVELOPMENT_ONLY  開発・調査の作業物（★利用者の環境には無い）
```

★`carry` は移行（`0001_legacy_to_portable` / RX-0158）での扱いです:

```text
migrate      写す
convert      形を変えて写す（★元の名前では写さない）
optional     利用者が選ぶ（★default が既定）
regenerate   写さずに作り直す
skip         写さない
```

## ⚠⚠ 名前を信じない

`work/generated/` は「生成物」の名前ですが、`tile_art.txt` は Lua が**遊びながら追記する観測**です
（★作り直せない）。⚠ 逆に DQ3 の `ownership.py` は DQ2 の DB を derived と数えています（RX3-0506）。
★表は**上から順に**照合し、最初に当たった行で決めます（⚠ 細かい行を先に置く）。

## root

```text
write    <write_root>    （`dq2_paths.write_root()` / 依頼 J7: Portable では ZIP の直下）
program  <program_root>  （`dq2_paths.program_root()`）
fceux    FCEUX の exe の隣（`dq2_paths.fceux_dir()` / ⚠ FCEUX はそこにしか書かない）
```

⚠ いまの DQ2 は `program` と `write` が同じ場所です（★起動スクリプトは RETROUX_WRITE_ROOT を立てない）。
★分けたのは「どちらの根から辿るか」がコードで決まっているから（★Lua は `self.root`、events とログは write_root）。
"""

from __future__ import annotations

import dataclasses
import fnmatch

USER_DATA = "USER_DATA"
OBSERVED_DATA = "OBSERVED_DATA"
DERIVED_DATA = "DERIVED_DATA"
RUNTIME = "RUNTIME"
DEVELOPMENT_ONLY = "DEVELOPMENT_ONLY"
KINDS = (USER_DATA, OBSERVED_DATA, DERIVED_DATA, RUNTIME, DEVELOPMENT_ONLY)

CARRIES = ("migrate", "convert", "optional", "regenerate", "skip")

#: ★移行の方針（依頼 §8 の語彙 / RX-0157）。★carry から決まる（⚠ 別に一覧を持たない）
MIGRATE = "MIGRATE"            # そのまま写す（★DB など変換が要るものは step の専用処理）
CONVERT = "CONVERT"            # 形を変えて写す（★step の専用処理が必須）
OPTIONAL = "OPTIONAL"          # 利用者が選ぶ（★default_on が既定）
REGENERATE = "REGENERATE"      # 写さずに新しい版で作り直す
DO_NOT_MIGRATE = "DO_NOT_MIGRATE"
POLICY_OF_CARRY = {"migrate": MIGRATE, "convert": CONVERT, "optional": OPTIONAL,
                   "regenerate": REGENERATE, "skip": DO_NOT_MIGRATE}
ROOTS = ("write", "program", "fceux")

#: ⚠ DQ3 のもの（★DQ2 の表には載せない / 移行もしない / playdata の FOREIGN_PREFIXES と同じ考え）
DQ3_NAME_PREFIXES = ("dq3_", "dq3-")


@dataclasses.dataclass(frozen=True)
class Entry:
    pattern: str          # ★root からの相対（posix・fnmatch）
    kind: str
    carry: str
    root: str
    note: str
    default_on: bool = False   # ★carry=optional のときの既定


E = Entry
#: ★上から順に照合する（⚠ 細かい行を先に）
TABLE: tuple[Entry, ...] = (
    # --- 設定 -----------------------------------------------------------
    E("dq2_user_config.yaml", USER_DATA, "migrate", "program",
      "DQ2 の設定（RX-0147）。⚠ 絶対パスが旧フォルダの中なら警告（書き換えない）"),
    E("user_config.yaml", USER_DATA, "convert", "program",
      "⚠ 旧の共用設定。DQ2 は読むだけ。dq2_user_config.yaml が無いときだけ変換して作る"),
    E("work/dq2-settings/*", USER_DATA, "migrate", "write",
      "画面から保存する利用者設定（keybindings / mantan / mission / RX-0156）"),
    E("config/keybindings.yaml", USER_DATA, "convert", "program",
      "⚠ 旧の置き場。読むだけ → 新では work/dq2-settings/ へ"),
    E("config/mantan.yaml", USER_DATA, "convert", "program",
      "⚠ 旧の置き場。読むだけ → 新では work/dq2-settings/ へ"),
    E("config/mission.yaml", USER_DATA, "convert", "program",
      "⚠ 旧の置き場。読むだけ → 新では work/dq2-settings/ へ"),
    E("work/dq2-data.json", RUNTIME, "skip", "write",
      "データの版の印（RX-0157）。★移行は写さずに新しく書く"),
    E("work/dq2-migration/*", RUNTIME, "skip", "write",
      "移行の journal と staging（RX-0157）"),
    E("work/window-state.json", USER_DATA, "migrate", "write",
      "窓の位置と大きさ（⚠ 「遊んだ証拠」には数えない）"),
    E("work/tactics/*", USER_DATA, "migrate", "program",
      "戦術プロフィール（profiles/*.yaml）と選んでいるもの（active.txt）。★同梱の見本と同名は飛ばしてよい"),
    # --- セーブ -----------------------------------------------------------
    E("fcs/*", USER_DATA, "migrate", "fceux",
      "セーブステートの本物。★DQ2 の ROM の stem だけ・上書きしない"),
    E("sav/*", USER_DATA, "migrate", "fceux",
      "電池セーブ。★DQ2 の ROM の stem だけ"),
    E("work/runtime/dq2-backup/savestate-backup/*", USER_DATA, "migrate", "write",
      "セーブの控え（新 / RX-0144）"),
    E("work/runtime/dq2-backup/*", RUNTIME, "skip", "write",
      "控えのロック・停止の合図・状態（savestate_backup.lock / .stop / .status.json）"),
    E("work/savestate-backup/*", USER_DATA, "migrate", "program",
      "セーブの控え（旧）。⚠ DQ3 と混在 → DQ2 の stem の下位フォルダだけ"),
    E("work/rom/*", USER_DATA, "optional", "program",
      "ROM（★既定 OFF / 依頼 §13）。写すなら paths.rom の 1 本を同じ名前で"),
    # --- 遊んで貯まった記録 ----------------------------------------------
    E("work/retroux.sqlite3*", OBSERVED_DATA, "migrate", "program",
      "DB（WAL）。★backup API で写し IngestState を論理 ID（dq2:events:main）へ。⚠ 作り直せない"),
    E("work/events.jsonl", OBSERVED_DATA, "migrate", "write",
      "取り込み前の記録（★Lua が write_root に追記）。IngestState の鍵と組"),
    E("work/events-*.jsonl", OBSERVED_DATA, "optional", "write",
      "回した events（分析ツールだけが読む）"),
    E("work/encountered.txt", OBSERVED_DATA, "migrate", "program",
      "会った敵の控え。★DB の EncounteredMonster と組（ずれると初遭遇の安全機構が働かない）"),
    E("work/caution.txt", OBSERVED_DATA, "migrate", "program",
      "警戒の控え。★DB と組"),
    E("work/generated/tile_art.txt", OBSERVED_DATA, "migrate", "program",
      "⚠⚠ generated の中だが Lua が遊びながら追記する観測（作り直せない）"),
    E("work/monster-art-rom/*", DERIVED_DATA, "regenerate", "program",
      "ROM から展開する絵（monster_art_setup）"),
    E("work/monster-art/*", OBSERVED_DATA, "optional", "program",
      "撮影した絵（★ROM の絵が優先されるので通常は使われない）"),
    E("work/playdata-archive/*", OBSERVED_DATA, "optional", "program",
      "playdata の退避。⚠ dq3-*・seen-*.json は除く / 中の DB も IngestState が絶対パス"),
    E("work/backups/*", OBSERVED_DATA, "optional", "program",
      "tile_reset の退避"),
    # --- 作り直せるもの ---------------------------------------------------
    E("work/map-assets/*", DERIVED_DATA, "optional", "program",
      "見たマスの絵（再訪すれば作り直されるが、それまで欠ける / ★既定 ON）", default_on=True),
    E("work/map-data/*", DERIVED_DATA, "regenerate", "program",
      "マップの大きさ表（map_meta_setup が ROM から）"),
    E("work/generated/*", DERIVED_DATA, "regenerate", "program",
      "config.lua / memory_map.lua / keybindings.lua / tactics.lua / enemy_tables.json / "
      "map_passability.json（★起動のたびに作り直す）"),
    # --- 実行時 -----------------------------------------------------------
    E("work/state.json", RUNTIME, "skip", "program", "Lua → GUI の現在の状態"),
    E("work/command.json", RUNTIME, "skip", "program", "GUI → Lua の頼み"),
    E("work/gamepad_input.txt", RUNTIME, "skip", "program", "パッドの入力の受け渡し"),
    E("work/enemyhp.txt", RUNTIME, "skip", "program", "⚠ 旧版の残り（いまのコードは書かない）"),
    E("work/event_ingestor.lock", RUNTIME, "skip", "program", "取り込みのロック"),
    E("work/savestate_backup.lock", RUNTIME, "skip", "program", "⚠ 旧の控えのロック（設定 paths.backup_lock）"),
    E("work/savestate_backup.status.json", RUNTIME, "skip", "program", "⚠ 旧の控えの状態"),
    E("work/runtime/dq2-log/*", RUNTIME, "skip", "write", "DQ2 のログ（RX-0149）"),
    E("work/retroux.log*", RUNTIME, "skip", "program", "⚠ 旧の共用ログ（DQ3 の行も混じる）"),
    E("fceux.cfg", RUNTIME, "skip", "fceux", "⚠ 環境依存。倍率は起動のたびに書く（J6）"),
    E("*", USER_DATA, "optional", "fceux",
      "利用者が置いた FCEUX 本体（exe・dll・palettes・luaScripts など / ★fcs・sav・fceux.cfg は上の行）。"
      "★既定で写す（依頼者 2026-10-05 / RX-0167 / ⚠ 旧フォルダの中に置いていたときだけ）", default_on=True),
    # --- 開発・調査 -------------------------------------------------------
    E("work/map-capture/*", DEVELOPMENT_ONLY, "skip", "program", "地図の撮影（dq2_map_capture）"),
    E("work/map-observations/*", DEVELOPMENT_ONLY, "skip", "program", "階段のタイルの撮影"),
    E("work/map-code-analysis/*", DEVELOPMENT_ONLY, "skip", "program", "地図のコード解析"),
    E("work/mantan/*", DEVELOPMENT_ONLY, "skip", "program", "まんたんの実機確認の撮影"),
    E("work/battle-cases/*", DEVELOPMENT_ONLY, "skip", "program", "戦闘の検査の素材"),
    E("work/world-map.png", DEVELOPMENT_ONLY, "skip", "program", "世界地図の書き出し"),
    E("work/ramwatch.txt", DEVELOPMENT_ONLY, "skip", "program", "RAM の観察（ramwatch.lua）"),
    E("work/research/*", DEVELOPMENT_ONLY, "skip", "program", "調査"),
    E("work/tests/*", DEVELOPMENT_ONLY, "skip", "program", "検査の作業物"),
    E("work/release/*", DEVELOPMENT_ONLY, "skip", "program", "公開の作業物"),
    E("work/archive/*", DEVELOPMENT_ONLY, "skip", "program", "片付けた物"),
    E("work/cache/*", DEVELOPMENT_ONLY, "skip", "program", "作業の控え"),
    # ★2026-10-03 に開発機の work/ 直下を照合して足した（⚠ いまのコードは書かない・旧版や調査の残り）
    E("work/recorder.lock", RUNTIME, "skip", "program", "⚠ 旧版の残り"),
    E("work/state_test.json", DEVELOPMENT_ONLY, "skip", "program", "Lua の検査の出力"),
    E("work/map_state_probe.*", DEVELOPMENT_ONLY, "skip", "program", "probe の出力"),
    E("work/_*", DEVELOPMENT_ONLY, "skip", "program", "撮影・窓の一覧の残り（_desktop.png / _windows.txt）"),
    E("work/prompt_*.md", DEVELOPMENT_ONLY, "skip", "program", "別セッションへの作業指示書（CLAUDE.md）"),
    E("work/.gitkeep", DEVELOPMENT_ONLY, "skip", "program", "Git の置き場の印"),
)
del E


def is_dq3(path: str) -> bool:
    """⚠ DQ3 のもの（★DQ2 の表の外 / DQ3 の移行で扱う）。"""
    parts = path.replace("\\", "/").split("/")
    return any(p.casefold().startswith(DQ3_NAME_PREFIXES) for p in parts)


def classify(path: str, root: str | None = None) -> Entry | None:
    """★相対パス（posix）の分類。⚠ 表に無ければ None（= 持ち主が決まっていない）。

    ★フォルダそのもの（`work/map-assets`）も、その中身の行で答える。
    """
    rel = path.replace("\\", "/").strip("/")
    for entry in TABLE:
        if root is not None and entry.root != root:
            continue
        if entry.pattern == "*" and root is None:
            continue            # ⚠ 根を名指ししたときだけの受け皿（★FCEUX 本体 / work/ の何でもを飲み込まない）
        if fnmatch.fnmatchcase(rel, entry.pattern):
            return entry
        if entry.pattern.endswith("/*") and rel == entry.pattern[:-2]:
            return entry
    return None


def policy(entry: Entry) -> str:
    """★移行の方針（MIGRATE / CONVERT / OPTIONAL / REGENERATE / DO_NOT_MIGRATE）。"""
    return POLICY_OF_CARRY[entry.carry]


def policy_of(path: str, root: str | None = None) -> str | None:
    """★相対パスの移行の方針。⚠ DQ3 のものは DO_NOT_MIGRATE、表に無ければ None。"""
    if is_dq3(path):
        return DO_NOT_MIGRATE
    got = classify(path, root)
    return policy(got) if got else None


def entries(kind: str | None = None, carry: str | None = None) -> tuple[Entry, ...]:
    return tuple(e for e in TABLE
                 if (kind is None or e.kind == kind) and (carry is None or e.carry == carry))
