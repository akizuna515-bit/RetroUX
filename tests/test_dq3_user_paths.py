"""ROM と FCEUX の場所を利用者が決められること（RX3-0467 / RX3-0468 / 2026-09-29）。

## ⚠⚠ なぜ要るか

★配布 Runtime は任意のフォルダに置かれます。⚠ ROM も FCEUX も RetroUX の外に
あるのが普通なので、**固定配置を必須にできません**。

```text
⚠ 直す前  ROM の既定値が 8 か所に独立して書かれていた
          （★1 か所直しても、残り 7 か所は古い場所を見続ける）
⚠⚠ FCEUX  exe / fceux.cfg / fcs/ の 3 つを各機能が別々に組み立てていた
          → ★fcs を見失うと **世代バックアップが静かに空振りする**
```

⚠ 「静かに空振り」は画面に出ません。★だから warning が**出ること**を検査します。
"""
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

from dq3 import paths as P3

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★以前 ROM の既定値を独立に持っていたところ（⚠ 1 本に集約したことを見張る）
ROM_CONSUMERS = (
    "dq3/knowledge/rom_names.py",
    "dq3/knowledge/item_info.py",
    "dq3/knowledge/terrain.py",
    "dq3/knowledge/monster_art.py",
    "dq3/knowledge/enemies_seen.py",
    "dq3/knowledge/monster_book.py",
    "dq3/knowledge/locations.py",
    "dq3/phase0/generate_walkmap.py",
)

#: ⚠ 「`work/rom/DQ3_J.nes` を自分で組み立てている」形
OWN_ROM_EXPR = re.compile(
    r'(parents\[\d+\]|ROOT|_ROOT)\s*/?\s*[\r\n ]*/?\s*"work"\s*/\s*"rom"')


def write_config(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """★書き先に `user_config.yaml` を置く（⚠ 改行は LF で書く / RX-0121）。"""
    target = tmp_path / P3.USER_CONFIG_NAME
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    return target


# ----------------------------------------------------------------------
# RX3-0467 — ROM
# ----------------------------------------------------------------------

def test_ROMの解決は設定が最優先(tmp_path, monkeypatch) -> None:
    """★1 番目: `user_config.yaml` の `paths.dq3_rom`。"""
    elsewhere = tmp_path / "somewhere" / "MY_DQ3.nes"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_bytes(b"NES\x1a")
    write_config(tmp_path, 'paths:\n  dq3_rom: "%s"\n'
                 % elsewhere.as_posix())
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    assert P3.rom() == elsewhere
    assert P3.rom_or_legacy() == elsewhere


def test_ROMは後方互換の場所も見る(tmp_path, monkeypatch) -> None:
    """★2 番目: `<書き先>/work/rom/DQ3_J.nes`（⚠ 今までの置き場）。"""
    legacy = tmp_path / "work" / "rom" / P3.LEGACY_ROM_NAME
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"NES\x1a")
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    assert P3.rom() == legacy


def test_ROMが無ければNoneで落ちない(tmp_path, monkeypatch) -> None:
    """★3 番目: 無ければ `None`（⚠ 例外にしない / 案内は呼ぶ側）。

    ⚠ program 側の控えも見るので、**そこにも無い**ことを作ってから見ます。
    """
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    monkeypatch.setattr(P3, "program_root", lambda: tmp_path / "program")
    P3._CONFIG_CACHE.clear()

    assert P3.rom() is None
    # ⚠ 古い呼び出し向けの入口は「従来の場所」を返す（★None を扱えないため）
    assert P3.rom_or_legacy() == tmp_path / "program" / "work" / "rom" / P3.LEGACY_ROM_NAME


def test_相対パスの設定はprogram_root基準(tmp_path, monkeypatch) -> None:
    """⚠ 相対で書かれたら、★置いた場所からの相対にする（開発機基準にしない）。"""
    write_config(tmp_path, 'paths:\n  dq3_rom: "roms/DQ3_J.nes"\n')
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    monkeypatch.setattr(P3, "program_root", lambda: tmp_path / "program")
    P3._CONFIG_CACHE.clear()

    assert P3.rom() == tmp_path / "program" / "roms" / "DQ3_J.nes"


@pytest.mark.parametrize("rel", ROM_CONSUMERS)
def test_ROMの既定値を自分で組み立てていない(rel: str) -> None:
    """⚠⚠ 同じ式が散ると、★1 か所直しても残りが古い場所を見続ける。"""
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    body = [ln for ln in text.splitlines()
            if not ln.lstrip().startswith(("#", "--", '"""', "*"))]
    hits = [ln.strip() for ln in body if OWN_ROM_EXPR.search(ln)]
    assert hits == [], (
        f"⚠⚠ {rel} が ROM の場所を自分で組み立てています "
        "（★dq3/paths.py::rom() を使ってください）:\n" + "\n".join(hits))


def test_設定を書き換えたら次に引くとき追いつく(tmp_path, monkeypatch) -> None:
    """⚠ import のときに固まっていないこと（★`lazy_rom` の意味）。"""
    from dq3.knowledge import rom_names

    first = tmp_path / "a.nes"
    first.write_bytes(b"NES\x1a")
    write_config(tmp_path, 'paths:\n  dq3_rom: "%s"\n' % first.as_posix())
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()
    assert pathlib.Path(rom_names.DEFAULT_ROM) == first

    second = tmp_path / "b.nes"
    second.write_bytes(b"NES\x1a")
    write_config(tmp_path, 'paths:\n  dq3_rom: "%s"\n' % second.as_posix())
    P3._CONFIG_CACHE.clear()
    assert pathlib.Path(rom_names.DEFAULT_ROM) == second


def test_hash照合は既存の実装を使う() -> None:
    """⚠ 新しい ROM hash の実装を作っていないこと（依頼者 §5-4）。"""
    text = (ROOT / "dq3" / "paths.py").read_text(encoding="utf-8")
    for banned in ("sha256", "md5", "crc32", "hashlib"):
        assert banned not in text, (
            f"⚠⚠ dq3/paths.py が {banned} を持っています "
            "（★照合は dq3rom/profile.py の仕事）")


def test_削除の走査は外部ROMに届かない() -> None:
    """★依頼者 §5-5 の判断材料（⚠ 不要な保護 path を足さないため）。

    ⚠⚠ `PlayDataService` が消すのは `ITEMS` に並べた**決まった名前**だけで、
      ★`work/dq3-knowledge/` の中しか見ません（glob も walk もしない）。
      → ⚠ 外部の ROM を触り得ないので、`NEVER_TOUCH` に足す必要はありません。
    """
    from dq3.knowledge import playdata as PD

    service = PD.PlayDataService()
    targets = service.all_files()
    assert targets, "★消す対象が 0 件（検査が空振りしている）"
    knowledge = pathlib.Path(str(PD.KNOWLEDGE)).resolve()
    for path in targets:
        assert pathlib.Path(path).resolve().parent == knowledge, (
            f"⚠⚠ 消す対象が work/dq3-knowledge の外にあります: {path}")
    source = (ROOT / "dq3" / "knowledge" / "playdata.py").read_text(encoding="utf-8")
    for banned in (".glob(", ".rglob(", "os.walk"):
        assert banned not in source, (
            f"⚠ playdata.py が {banned} を使っています "
            "（★走査の範囲が広がったら NEVER_TOUCH を見直すこと）")


# ----------------------------------------------------------------------
# RX3-0468 — FCEUX
# ----------------------------------------------------------------------

def test_FCEUXの派生は1つの場所から(tmp_path, monkeypatch) -> None:
    """★exe を指したら cfg / fcs / palettes が**全部ついてくる**。"""
    home = tmp_path / "Emulators" / "FCEUX"
    home.mkdir(parents=True)
    exe = home / "fceux.exe"
    exe.write_bytes(b"MZ")
    write_config(tmp_path, 'paths:\n  fceux: "%s"\n' % exe.as_posix())
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    assert P3.fceux() == exe
    assert P3.fceux_dir() == home
    assert P3.fceux_cfg() == home / "fceux.cfg"
    assert P3.fceux_fcs() == home / "fcs"
    assert P3.fceux_palettes() == home / "palettes"


def test_FCEUXを動かしても設定を変えるだけで戻る(tmp_path, monkeypatch) -> None:
    """⚠ 再インストールが要らないこと（依頼者 §8）。"""
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    for name in ("old", "new"):
        home = tmp_path / name
        home.mkdir()
        (home / "fceux.exe").write_bytes(b"MZ")
        (home / "fcs").mkdir()
        write_config(tmp_path, 'paths:\n  fceux: "%s"\n'
                     % (home / "fceux.exe").as_posix())
        P3._CONFIG_CACHE.clear()
        assert P3.fceux_fcs() == home / "fcs"


def test_FCEUXが無ければNone(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    monkeypatch.setattr(P3, "program_root", lambda: tmp_path / "program")
    P3._CONFIG_CACHE.clear()

    assert P3.fceux() is None
    assert P3.fceux_cfg() is None
    assert P3.fceux_fcs() is None


# ----------------------------------------------------------------------
# ⚠⚠ 控えが静かに空振りしないこと（依頼者 §7）— ★鳴ることを見る
# ----------------------------------------------------------------------

def test_FCEUXが分からなければ控えの警告が出る(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    monkeypatch.setattr(P3, "program_root", lambda: tmp_path / "program")
    P3._CONFIG_CACHE.clear()

    got = P3.fcs_warning()
    assert got is not None and "FCEUX" in got


def test_fcsが無ければ控えの警告が出る(tmp_path, monkeypatch) -> None:
    home = tmp_path / "FCEUX"
    home.mkdir()
    (home / "fceux.exe").write_bytes(b"MZ")
    write_config(tmp_path, 'paths:\n  fceux: "%s"\n'
                 % (home / "fceux.exe").as_posix())
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    got = P3.fcs_warning()
    assert got is not None and "セーブステート" in got


def test_fcsが空でも控えの警告が出る(tmp_path, monkeypatch) -> None:
    """⚠ フォルダが在るだけでは「守れている」根拠にならない。"""
    home = tmp_path / "FCEUX"
    (home / "fcs").mkdir(parents=True)
    (home / "fceux.exe").write_bytes(b"MZ")
    write_config(tmp_path, 'paths:\n  fceux: "%s"\n'
                 % (home / "fceux.exe").as_posix())
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    got = P3.fcs_warning()
    assert got is not None and "1 つもありません" in got


def test_そろっていれば警告は出ない(tmp_path, monkeypatch) -> None:
    """⚠ 鳴りすぎも壊れ方（★検出器自身を検査する）。"""
    home = tmp_path / "FCEUX"
    (home / "fcs").mkdir(parents=True)
    (home / "fceux.exe").write_bytes(b"MZ")
    (home / "fcs" / "DQ3_J.fc0").write_bytes(b"x")
    write_config(tmp_path, 'paths:\n  fceux: "%s"\n'
                 % (home / "fceux.exe").as_posix())
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    assert P3.fcs_warning() is None


def test_控えは警告を記録にも残す(tmp_path, monkeypatch) -> None:
    """⚠⚠ 画面の無い起動（pythonw）でも後から分かること。"""
    from dq3 import savestate_backup as SB

    monkeypatch.setenv(P3.ENV, str(tmp_path))
    monkeypatch.setattr(P3, "program_root", lambda: tmp_path / "program")
    P3._CONFIG_CACHE.clear()

    log = tmp_path / "warn.log"
    got = SB.warn_if_no_savestates(write=log)
    assert got is not None
    assert log.is_file()
    assert "FCEUX" in log.read_text(encoding="utf-8")
    # ⚠ 改行を混ぜない（★LF で足す / RX-0121）
    assert b"\r\n" not in log.read_bytes()


def test_控えはfcsをsrcとして渡す(tmp_path, monkeypatch) -> None:
    """⚠⚠ これが無いと、★あちらの既定（同梱 fcs）を見続けて空振りする。"""
    from dq3 import savestate_backup as SB

    home = tmp_path / "FCEUX"
    (home / "fcs").mkdir(parents=True)
    (home / "fceux.exe").write_bytes(b"MZ")
    write_config(tmp_path, 'paths:\n  fceux: "%s"\n'
                 % (home / "fceux.exe").as_posix())
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    got = SB.with_src(["--once"])
    assert got[0] == "--src"
    assert pathlib.Path(got[1]) == home / "fcs"
    assert got[2] == "--once"


def test_控えは人の指定を上書きしない(tmp_path, monkeypatch) -> None:
    from dq3 import savestate_backup as SB

    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()
    assert SB.with_src(["--src", "D:/mine"]) == ["--src", "D:/mine"]


# ----------------------------------------------------------------------
# ★起動スクリプトと設定の雛形
# ----------------------------------------------------------------------

def test_起動スクリプトが場所を自分で組み立てない() -> None:
    """⚠ `.ps1` が `work\\rom\\DQ3_J.nes` / `tools\\fceux` を直に書いていないこと。"""
    text = (ROOT / "scripts" / "start-dq3.ps1").read_text(
        encoding="utf-8-sig", errors="replace")
    body = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    joined = "\n".join(body)
    assert "dq3.paths --rom" in joined, "⚠ ROM の場所を paths に聞いていません"
    assert "dq3.paths --fceux" in joined, "⚠ FCEUX の場所を paths に聞いていません"
    for banned in ('Join-Path $Root "work\\rom\\DQ3_J.nes"',
                   'Join-Path $Root "tools\\fceux\\fceux64.exe"'):
        assert banned not in joined, f"⚠⚠ 場所を直に書いています: {banned}"


# ----------------------------------------------------------------------
# RX3-0476 — ⚠⚠ 設定を**読めなかった**ときに黙って既定へ落ちない
#
#   ★2026-09-30 の実機確認で起きたこと（依頼者）:
#
#     user_config.yaml に paths.fceux を書いた
#           ↓
#     python -m dq3.paths --fceux      ⚠ bare `python` = system Python
#           ↓
#     C:\Projects\...\tools\fceux\fceux64.exe   ⚠⚠ 設定ではなく控えを答えた
#           ↓
#     ★警告 0 行 / 終了コード 0（⚠ 「効いていない」と分からない）
#
#   ⚠ 原因は key 名でも reader でもなく、**PyYAML が無い Python だった**。
#     `_paths_config()` の `import` が落ち、`_setting()` が
#     `except Exception` で飲み込んで空文字を返していた。
# ----------------------------------------------------------------------

def _設定を読めなくする(monkeypatch) -> None:
    """⚠ PyYAML が無い Python と同じ形にする（★`import` が落ちる）。

    ⚠⚠ `sys.modules` の差し替えだけでは**素通りします**。
      ★`from pkg import mod` は先に**パッケージの属性**を見るので、
      いちど import 済みなら `sys.modules` を None にしても届きません
      （⚠ `docs/90-retrospective.md` の既知の教訓 / 2026-09-30 に再度踏んだ）。
    """
    import sys

    import retroux.core.config as CFG

    monkeypatch.delattr(CFG, "user_config", raising=False)
    monkeypatch.setitem(sys.modules, "retroux.core.config.user_config", None)
    monkeypatch.setattr(P3, "_config_error", None)
    P3._CONFIG_CACHE.clear()


def test_設定を読めなかったら理由が残る(tmp_path, monkeypatch) -> None:
    """⚠⚠ 黙って既定へ落ちないこと（★`CLAUDE.md` の実装の基本ルール）。"""
    write_config(tmp_path, 'paths:\n  fceux: "C:/Tools/RetroUX/tools/fceux/fceux64.exe"\n')
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    _設定を読めなくする(monkeypatch)

    assert P3._setting("fceux") == "", "★読めないので空（⚠ ここは従来どおり）"
    problem = P3.config_error()
    assert problem, "⚠⚠ 読めなかったのに理由が残っていない（★黙って落ちた）"
    assert P3.USER_CONFIG_NAME in problem, problem


def test_設定ファイルが無いときは理由を残さない(tmp_path, monkeypatch) -> None:
    """⚠ 鳴りすぎも壊れ方（★設定を置いていないのは普通のこと）。"""
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    monkeypatch.setattr(P3, "_config_error", None)
    P3._CONFIG_CACHE.clear()

    # ⚠ program_root にある本物を拾わないよう、★両方を空のフォルダへ向ける
    monkeypatch.setattr(P3, "program_root", lambda: tmp_path / "program")
    assert P3.user_config_path() is None
    assert P3._setting("fceux") == ""
    assert P3.config_error() is None, P3.config_error()


def test_CLIは設定を読めなければ黙って答えない(tmp_path) -> None:
    """⚠⚠ 依頼者が踏んだ道そのもの（★`python -m dq3.paths --fceux`）。

    ★別プロセスで、`retroux.core.config.user_config` を**読めない**状態にして
      呼びます（⚠ PyYAML が無い Python と同じ形）。
    """
    import os
    import sys

    write_config(tmp_path, 'paths:\n  fceux: "C:/Tools/RetroUX/tools/fceux/fceux64.exe"\n')
    blocker = tmp_path / "sitecustomize.py"
    with open(blocker, "w", encoding="utf-8", newline="") as fh:
        fh.write("import sys\n"
                 "sys.modules['retroux.core.config.user_config'] = None\n")

    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "dq3.paths", "--fceux"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(tmp_path),
             P3.ENV: str(tmp_path)}, timeout=120)

    assert done.returncode != 0, \
        "⚠⚠ 設定を読めていないのに終了コード 0（★黙って控えを答えた）\n%s" % done.stdout
    assert P3.USER_CONFIG_NAME in done.stderr, done.stderr
    assert "tools" not in done.stdout, \
        "⚠⚠ 設定を無視した道を答えている: %r" % done.stdout


def test_CLIは設定が読めれば従来どおり答える(tmp_path, monkeypatch) -> None:
    """★誤検知しないこと（⚠ 読めているときに赤くしない）。"""
    import os
    import sys

    home = tmp_path / "FCEUX"
    home.mkdir()
    exe = home / "fceux.exe"
    exe.write_bytes(b"MZ")
    write_config(tmp_path, 'paths:\n  fceux: "%s"\n' % exe.as_posix())

    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "dq3.paths", "--fceux"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1", P3.ENV: str(tmp_path)}, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(exe), done.stdout


# ----------------------------------------------------------------------
# RX3-0476 — ★区切り文字（依頼者が最初に試した形）
# ----------------------------------------------------------------------

@pytest.mark.parametrize("sep", ["/", "\\"])
def test_設定の区切りはslashでもbackslashでも同じ場所(tmp_path, monkeypatch, sep) -> None:
    """⚠ 依頼者は backslash → slash と直しても症状が変わらなかった（★当然）。"""
    home = tmp_path / "Tools" / "FCEUX"
    home.mkdir(parents=True)
    exe = home / "fceux64.exe"
    exe.write_bytes(b"MZ")
    written = str(exe).replace("\\", "/") if sep == "/" else str(exe)
    # ⚠ YAML の二重引用符の中では `\` が escape になるので、★単一引用符で書く
    write_config(tmp_path, "paths:\n  fceux: '%s'\n" % written)
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    P3._CONFIG_CACHE.clear()

    assert P3.fceux() == exe, "⚠ 区切りで結果が変わった（%s）" % sep


def test_設定を書かなければ控えのtools_fceuxが効く(tmp_path, monkeypatch) -> None:
    """★従来どおり（⚠ 設定を入れた人だけが外を向く）。"""
    monkeypatch.setenv(P3.ENV, str(tmp_path))
    monkeypatch.setattr(P3, "_config_error", None)
    # ⚠⚠ repo 直下の**本物の** user_config.yaml を拾わないようにする
    #   （★`user_config_path()` は write_root → program_root の順に見る）
    monkeypatch.setattr(P3, "program_root", lambda: tmp_path / "program")
    P3._CONFIG_CACHE.clear()
    home = tmp_path / "tools" / "fceux"
    home.mkdir(parents=True)
    exe = home / "fceux64.exe"
    exe.write_bytes(b"MZ")

    assert P3.fceux() == exe


def test_設定の雛形に新しい欄がある() -> None:
    text = (ROOT / "user_config.example.yaml").read_text(encoding="utf-8")
    assert "dq3_rom" in text
    assert "fceux" in text


def test_paths_CLIが1行で答える() -> None:
    """★`.ps1` から呼ぶ口（⚠ 見つからないときは空 ＋ 終了コード 1）。"""
    import os
    import sys

    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "dq3.paths", "--program-root"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"}, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(P3.program_root())
