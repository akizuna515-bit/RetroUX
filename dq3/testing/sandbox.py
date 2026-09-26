"""実機テストを本番プレイデータから**物理的に**切り離す（RX3-0128 / 2026-09-08）。

```text
本番（人が遊んでいる本物）                    ★テスト中は 1 バイトも変えない
  tools/fceux/fcs/DQ3_J.fc0..9   セーブステート
  tools/fceux/sav/DQ3_J.sav      カートリッジのセーブ（ぼうけんのしょ）
  tools/fceux/fceux.cfg          FCEUX の設定（⚠ 終了時に書き戻される）
  work/dq3-knowledge/            メモ・会話・場所・図鑑・進捗
  work/dq3-ui-settings.json      人が選んだ作戦・役割・補充の目標
        │ run のはじめに**物理コピー**
        ▼
work/test-sandbox/<run_id>/
  fceux/                         ★FCEUX 一式（exe + dll + cfg + fcs + sav）
  work/dq3-knowledge/ …          ★Python と Lua の書き先
  production-before.json / production-after.json / result.txt
```

## ★完了の条件は「戻せる」ではない

⚠⚠ **一度でも本番へ書いたこと自体を失敗**として捕まえます。
★run の前後で本番の sha256 を採り、1 件でも違えば `ProductionChanged`。

## ⚠⚠ なぜ FCEUX 一式を写すのか（★2026-09-08 実測）

★FCEUX は**自分の exe がある場所**を基準に `fcs/`（セーブステート）と `sav/` を決めます。

```text
⚠ 試したが効かなかった  fceux.cfg の "odstates" を隔離先に向けて `-cfg` で渡す
                        → ★保存は**本番の fcs** に落ちた（実測。fc6 を上書きした）
★効いた                 exe と dll を隔離先へ写し、そこから起動する（7.2 MB / run）
```

⚠ だから「コピーを作った」だけでは足りません。**どこから起動したか**が全てです。

## ★使い方

```python
from dq3.testing import sandbox as SB

with SB.open_sandbox("battle-ai") as sbx:   # ⚠ ここで環境変数が立つ
    proc = sbx.launch_fceux()               # ★隔離先の exe から起こす
    ...                                     # dq3.* の import は**この後**で
# ★抜けるときに本番を検算し、変わっていれば ProductionChanged
```
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess

from .. import paths

ROOT = paths.ROOT

#: ★隔離先の親
SANDBOX_ROOT = ROOT / "work" / "test-sandbox"
#: ★固定のテスト入力（★あれば本番ではなくこちらから写す / WI §6）
FIXTURES = ROOT / "work" / "test-fixtures" / "dq3"
#: ★証跡（⚠ 失敗した run は必ず残す）
EVIDENCE = ROOT / "work" / "evidence"

FCEUX_DIR = ROOT / "tools" / "fceux"
DEV_LUA = ROOT / "dq3" / "phase0" / "dev.lua"
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"

#: ★ROM の名前（★セーブステートと SRAM の名前はこれで決まる）
STEM = "DQ3_J"

#: ★隔離先へ写す FCEUX の中身（⚠ これだけで起動できる。★実測 7.2 MB）
FCEUX_FILES = ("fceux64.exe", "lua5.1.dll", "lua51.dll", "7z_64.dll", "auxlib.lua",
               "fceux.cfg")
#: ★FCEUX が使う置き場（⚠ 無ければ自分で作るが、先に作っておく）
FCEUX_DIRS = ("fcs", "sav", "snaps", "movies", "luaScripts", "cheats", "tools", "palettes")
#: ★成功した run から消してよいもの（⚠ プレイデータは消さない）
PRUNE = ("fceux64.exe", "lua5.1.dll", "lua51.dll", "7z_64.dll")


class ProductionChanged(RuntimeError):
    """⚠⚠ 本番のプレイデータが変わった（★戻したかどうかに関わらず失敗）。"""


# ----------------------------------------------------------------------
# ★本番の指紋
# ----------------------------------------------------------------------

def production_files(root: pathlib.Path = ROOT) -> list[pathlib.Path]:
    """★テスト中に 1 バイトも変わってはいけないもの。

    ⚠ 無いものは入れません。★run の途中で**増えた**ことも差分として出ます。
    """
    out: list[pathlib.Path] = []
    out += sorted((root / "tools" / "fceux" / "fcs").glob(STEM + ".fc*"))
    out += sorted((root / "tools" / "fceux" / "sav").glob(STEM + ".sav*"))
    cfg = root / "tools" / "fceux" / "fceux.cfg"
    if cfg.exists():
        out.append(cfg)
    for rel in ("work/dq3-knowledge", "work/test-fixtures/dq3", "work/playdata-archive"):
        d = root / rel
        if d.is_dir():
            out += sorted(p for p in d.rglob("*") if p.is_file())
    ui = root / "work" / "dq3-ui-settings.json"
    if ui.exists():
        out.append(ui)
    return out


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(files, root: pathlib.Path = ROOT) -> dict:
    """★`相対パス -> {size, sha256}`（⚠ mtime では見ない。★中身で見る）。"""
    out = {}
    for p in files:
        try:
            rel = str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = str(p).replace("\\", "/")
        out[rel] = {"size": p.stat().st_size, "sha256": digest(p)}
    return out


def compare(before: dict, after: dict) -> list[str]:
    """★変わったものを人の言葉で。⚠ 空なら「1 バイトも変わっていない」。"""
    lines = []
    for rel in sorted(set(before) | set(after)):
        was, now = before.get(rel), after.get(rel)
        if was is None:
            lines.append("増えた: %s（sha256=%s…）" % (rel, now["sha256"][:16]))
        elif now is None:
            lines.append("消えた: %s" % rel)
        elif was["sha256"] != now["sha256"]:
            lines.append("変わった: %s / before sha256=%s… / after sha256=%s…"
                         % (rel, was["sha256"][:16], now["sha256"][:16]))
    return lines


# ----------------------------------------------------------------------
# ★隔離先
# ----------------------------------------------------------------------

@dataclasses.dataclass
class Sandbox:
    run_id: str
    root: pathlib.Path
    before: dict = dataclasses.field(default_factory=dict)
    production_root: pathlib.Path = ROOT
    _saved_env: dict = dataclasses.field(default_factory=dict)

    # --- ★場所 --------------------------------------------------------

    @property
    def fceux(self) -> pathlib.Path:
        return self.root / "fceux"

    @property
    def saves(self) -> pathlib.Path:
        """★セーブステート（⚠ FCEUX は exe の隣の `fcs` を見る）。"""
        return self.fceux / "fcs"

    @property
    def sram(self) -> pathlib.Path:
        return self.fceux / "sav"

    @property
    def work(self) -> pathlib.Path:
        return self.root / "work"

    @property
    def knowledge(self) -> pathlib.Path:
        return self.work / "dq3-knowledge"

    # --- ★作る --------------------------------------------------------

    def build(self) -> "Sandbox":
        for d in (self.work, self.knowledge, self.work / "dq3-probe",
                  self.work / "generated", self.work / "evidence"):
            d.mkdir(parents=True, exist_ok=True)
        self.fceux.mkdir(parents=True, exist_ok=True)
        for name in FCEUX_DIRS:
            (self.fceux / name).mkdir(exist_ok=True)

        # ★FCEUX 一式（⚠ ここから起動しないと本番の fcs へ書く）
        for name in FCEUX_FILES:
            src = self.production_root / "tools" / "fceux" / name
            if src.exists():
                shutil.copyfile(src, self.fceux / name)

        # ★セーブステート 0〜9 をそのまま写す（⚠ 本番は読むだけ）
        #   ★意味のある固定入力は `dq3/testing/fixtures.py` が**名前で**入れます（RX3-0129）:
        #     fx = FX.get("battle_ai_injured_party"); slot = FX.install(fx, sbx)
        for p in sorted((self.production_root / "tools" / "fceux" / "fcs").glob(STEM + ".fc*")):
            shutil.copyfile(p, self.saves / p.name)
        # ★カートリッジのセーブ（ぼうけんのしょ）
        for p in sorted((self.production_root / "tools" / "fceux" / "sav").glob(STEM + ".sav*")):
            shutil.copyfile(p, self.sram / p.name)

        # ★プレイヤーの知識と画面の設定
        know = self.production_root / "work" / "dq3-knowledge"
        if know.is_dir():
            for p in sorted(know.rglob("*")):
                if p.is_file():
                    target = self.knowledge / p.relative_to(know)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, target)
        ui = self.production_root / "work" / "dq3-ui-settings.json"
        if ui.exists():
            shutil.copyfile(ui, self.work / "dq3-ui-settings.json")

        # ★生成物（⚠ 読むだけ。★隔離先からも require できるように写す）
        gen = self.production_root / "work" / "generated"
        if gen.is_dir():
            for p in sorted(gen.glob("*.lua")):
                shutil.copyfile(p, self.work / "generated" / p.name)

        self.before = manifest(production_files(self.production_root), self.production_root)
        self._write("production-before.json", self.before)
        return self

    def _write(self, name: str, data) -> None:
        (self.root / name).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                      encoding="utf-8")

    # --- ★環境変数 ----------------------------------------------------

    def env(self) -> dict:
        """★子プロセスにも渡す形（⚠ 読む場所は repo のまま）。"""
        return {paths.ENV: str(self.root).replace("\\", "/"),
                paths.SANDBOX_ENV: "1",
                "RETROUX_ROOT": str(ROOT).replace("\\", "/")}

    def apply_env(self) -> None:
        """⚠⚠ `dq3.*` を import する**前**に呼ぶこと（★定数はそのとき決まる）。"""
        for key, value in self.env().items():
            self._saved_env[key] = os.environ.get(key)
            os.environ[key] = value

    def restore_env(self) -> None:
        for key, was in self._saved_env.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was
        self._saved_env.clear()

    # --- ★起動 --------------------------------------------------------

    def launch_fceux(self, lua: pathlib.Path = DEV_LUA, rom: pathlib.Path = ROM,
                     extra=()) -> subprocess.Popen:
        """★隔離先の exe から起こす。⚠ セーブも SRAM も cfg も隔離先へ行く。"""
        exe = self.fceux / "fceux64.exe"
        if not exe.exists():
            raise FileNotFoundError("⚠ 隔離先に FCEUX がありません: %s" % exe)
        args = [str(exe), "-lua", str(lua).replace("\\", "/"), *extra,
                str(rom).replace("\\", "/")]
        return subprocess.Popen(args, cwd=str(self.fceux),
                                env=dict(os.environ, **self.env()))

    # --- ★検算 --------------------------------------------------------

    def verify(self) -> list[str]:
        """★本番が 1 バイトも変わっていないか。⚠ 差分の行を返す（空なら無事）。"""
        after = manifest(production_files(self.production_root), self.production_root)
        self._write("production-after.json", after)
        return compare(self.before, after)

    def prune(self) -> None:
        """★成功した run から重いものを外す（⚠ プレイデータと記録は残す）。"""
        for name in PRUNE:
            got = self.fceux / name
            if got.exists():
                got.unlink()

    def keep_as_evidence(self, name: str | None = None) -> pathlib.Path:
        """★証跡として `work/evidence/<run_id>/` へ写す。"""
        target = EVIDENCE / (name or self.run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copytree(self.root, target,
                            ignore=shutil.ignore_patterns(*PRUNE))
        return target


# ----------------------------------------------------------------------
# ★★ FCEUX を閉じるのは**隔離先のものだけ**（2026-09-11）
#
#   ⚠⚠ 実機スクリプトは `taskkill /IM fceux64.exe` で**名前ごと全部**閉じていた。
#     ★依頼者が遊んで確かめている最中の FCEUX まで閉じた（20:57 / 最後のセーブから後が消えうる）。
#   → ★exe の置き場で見分ける: 隔離先（work/test-sandbox/…）から起こしたものだけ閉じる。
#   ⚠ 依頼者の FCEUX（tools/fceux/）には触らない。
# ----------------------------------------------------------------------
FCEUX_IMAGE = "fceux64.exe"


def fceux_processes(runner=subprocess.run) -> list[tuple[int, str, int]]:
    """★動いている FCEUX の (pid, exe の置き場, 親の pid)。⚠ 置き場が読めなければ空文字。"""
    cmd = ["powershell", "-NoProfile", "-Command",
           "Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
           "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, $_.ExecutablePath }"
           % FCEUX_IMAGE]
    try:
        done = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                      timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in (done.stdout or "").splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3 and parts[0].isdigit():
            out.append((int(parts[0]), parts[2].strip(), int(parts[1]) if parts[1].isdigit() else 0))
    return out


def is_sandbox_exe(path: str) -> bool:
    """★隔離先から起こした FCEUX か（⚠ 置き場が分からなければ「違う」＝閉じない）。"""
    if not path:
        return False
    got = str(path).replace("\\", "/").lower()
    return "/work/test-sandbox/" in got


def _ours(path: str, ppid: int) -> bool:
    """★この run の FCEUX か（★隔離先の exe / ★このスクリプトが起こしたもの）。"""
    return is_sandbox_exe(path) or ppid == os.getpid()


def user_fceux(runner=subprocess.run) -> list[tuple[int, str]]:
    """★依頼者の（隔離先でも、このスクリプトが起こしたものでもない）FCEUX。"""
    return [(pid, path) for pid, path, ppid in fceux_processes(runner) if not _ours(path, ppid)]


def kill_sandbox_fceux(runner=subprocess.run) -> list[int]:
    """★この run の FCEUX だけを閉じる。戻り値: 閉じた pid。⚠ 依頼者の FCEUX には触らない。"""
    killed = []
    for pid, path, ppid in fceux_processes(runner):
        if _ours(path, ppid):
            runner(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            killed.append(pid)
    return killed


class UserFceuxRunning(RuntimeError):
    """⚠ 依頼者の FCEUX が動いている（★速度・音を触る run はそれを巻き込むので始めない）。"""


def refuse_if_user_fceux(why: str, runner=subprocess.run) -> None:
    """⚠ 速度（WM_COMMAND）や音は「最初に見つかった FCEUX」に効くので、★依頼者のものがあれば始めない。"""
    got = user_fceux(runner)
    if got:
        raise UserFceuxRunning("⚠⚠ 依頼者の FCEUX が動いています（pid %s）。%s のでこの run は始めません"
                               % (", ".join(str(p) for p, _ in got), why))


def new_run_id(tag: str = "run") -> str:
    return "%s-%s" % (dt.datetime.now().strftime("%Y%m%d-%H%M%S"), tag)


def create(tag: str = "run", *, production_root: pathlib.Path = ROOT,
           sandbox_root: pathlib.Path = SANDBOX_ROOT) -> Sandbox:
    run_id = new_run_id(tag)
    sbx = Sandbox(run_id=run_id, root=sandbox_root / run_id, production_root=production_root)
    sbx.root.mkdir(parents=True, exist_ok=True)
    return sbx.build()


@contextlib.contextmanager
def open_sandbox(tag: str = "run", *, production_root: pathlib.Path = ROOT,
                 sandbox_root: pathlib.Path = SANDBOX_ROOT, keep_on_success: bool = False):
    """★作って、環境変数を立てて、⚠ 抜けるときに**必ず**本番を検算する。

    ⚠⚠ 例外で抜けても検算します（★落ちたときこそ本番が心配）。
    ★失敗した run は `work/evidence/<run_id>/` に残ります。
    """
    sbx = create(tag, production_root=production_root, sandbox_root=sandbox_root)
    sbx.apply_env()
    failed = False
    try:
        yield sbx
    except BaseException:
        failed = True
        raise
    finally:
        sbx.restore_env()
        changed = sbx.verify()
        (sbx.root / "result.txt").write_text(
            ("⚠⚠ 本番が変わりました" + chr(10) + chr(10).join(changed)) if changed
            else "★本番は 1 バイトも変わっていません", encoding="utf-8")
        if failed or changed:
            sbx.keep_as_evidence()
        elif not keep_on_success:
            sbx.prune()
        if changed:
            raise ProductionChanged(
                "⚠⚠ 本番のプレイデータが変わりました（★戻したかどうかに関わらず失敗）"
                + chr(10) + chr(10).join(changed)
                + chr(10) + "★隔離先: " + str(sbx.root))


__all__ = ["Sandbox", "ProductionChanged", "open_sandbox", "create", "manifest", "compare",
           "production_files", "digest", "new_run_id",
           "SANDBOX_ROOT", "FIXTURES", "EVIDENCE", "STEM", "FCEUX_FILES", "PRUNE"]
