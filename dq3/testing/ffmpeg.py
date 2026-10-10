"""ffmpeg / ffprobe の置き場を見つける（RX3-0048 / 2026-09-02）。

## ⚠⚠ なぜ PATH に入れないのか

★CLAUDE.md は「システム全体へのインストール・PATH/レジストリ変更」を禁じています。
⚠ 指示書 A-1 は「導入できるか確認」なので、★**プロジェクトの中**に置きます。

```text
work/research/tools/ffmpeg/bin/ffmpeg.exe    ★ここ（⚠ Git の外 / 依頼者の PATH を触らない）
```

★出どころ: gyan.dev の `ffmpeg-release-essentials.zip`（⚠ ffmpeg.org が案内する Windows 版）。
★取得時に `.sha256` と突き合わせています（`work/research/tools/get_ffmpeg.ps1`）。

## ★探す順

```text
1  環境変数 RETROUX_FFMPEG（★folder か exe）
2  work/research/tools/ffmpeg/**/ffmpeg.exe
3  PATH（⚠ 依頼者が別に入れていれば使う）
```

⚠⚠ **見つからなくても落ちません。** ★`None` を返し、動画の検証は
「ffprobe が無い」と記録して先へ進みます（指示書 §3「録画が無くても run は成立する」）。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★置き場（⚠ Git の外）
LOCAL_DIR = ROOT / "work" / "research" / "tools" / "ffmpeg"

#: ★環境変数（★folder でも exe でもよい）
ENV = "RETROUX_FFMPEG"

#: ⚠ `-version` の待ち時間
VERSION_TIMEOUT = 10.0


def _exe(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def find(name: str = "ffmpeg", *, env: dict | None = None) -> pathlib.Path | None:
    """★`ffmpeg` か `ffprobe` の道。⚠ 無ければ `None`（**例外を投げません**）。

    @param env ⚠ 検査で差し替える（★既定は `os.environ`）
    """
    env = os.environ if env is None else env
    want = _exe(name)

    told = env.get(ENV)
    if told:
        p = pathlib.Path(told)
        for cand in (p, p / want, p / "bin" / want):
            if cand.is_file() and cand.name.lower() == want.lower():
                return cand

    if LOCAL_DIR.exists():
        for cand in sorted(LOCAL_DIR.rglob(want)):
            if cand.is_file():
                return cand

    got = shutil.which(name)
    return pathlib.Path(got) if got else None


def version(name: str = "ffmpeg") -> tuple[bool, str]:
    """★`-version` の 1 行目。⚠ `(通ったか, 1 行目 or 理由)`。"""
    exe = find(name)
    if exe is None:
        return False, "⚠ %s が見つかりません（★work/research/tools/ffmpeg か %s）" % (name, ENV)
    try:
        done = subprocess.run([str(exe), "-version"], capture_output=True,
                              timeout=VERSION_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as err:
        return False, "⚠ %s を起動できません: %s" % (name, err)
    if done.returncode != 0:
        return False, "⚠ %s -version が %d で終わりました" % (name, done.returncode)
    first = (done.stdout or b"").decode("utf-8", "replace").splitlines()
    return True, first[0] if first else "(空)"
