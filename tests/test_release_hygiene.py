"""公開してはいけないものが Git に入っていないか（RX-0046 / RELEASE_CHECKLIST §3）。

## ⚠⚠ なぜ要るか

公開チェックリストには

    - [ ] ⚠ **ROM を同梱していない**
    - [ ] ⚠ **セーブステートをコミットしていない**

という項目が**最初からあった**。⚠ しかし **1 件もチェックされていなかった**ので、
★実際には**セーブステートが 1 件入っている**ことに 2026-08-14 まで気づけなかった。

    input/save_bak_260808/DQ2_J.fc1.fcs   10,457 バイト
    → 中身は `FCSX` マジックの FCEUX セーブステート（★実測）

原因は `.gitignore` の穴:

    *.fc[0-9]     ← `DQ2_J.fc1` は拾う
                  ⚠ `DQ2_J.fc1.fcs` は**拾わない**

★同じフォルダの他 24 件は除外されていて、⚠ **1 件だけ**すり抜けていた。

## ★ 人のチェックリストに頼らない

⚠ 「人が確認する項目」は、確認されないまま**何か月も残る**。
★機械で見られるものは機械で見る（§44）。
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ⚠ 公開物へ入れてはいけない拡張子
#:   ★`.fcs` は 2026-08-14 に追加（RX-0046 / これが漏れていた）
FORBIDDEN_SUFFIXES = (
    ".nes",           # ROM そのもの
    ".fcs",           # ⚠ FCEUX セーブステート（★これが漏れていた）
    ".sav", ".srm",   # セーブデータ
    ".fm2", ".fcm",   # 入力記録
)

#: ⚠ 拡張子だけでは拾えない形（`DQ2_J.fc0` など）
FORBIDDEN_PATTERNS = (".fc0", ".fc1", ".fc2", ".fc3", ".fc4",
                      ".fc5", ".fc6", ".fc7", ".fc8", ".fc9")

#: ★FCEUX セーブステートの先頭 4 バイト
FCEUX_MAGIC = b"FCSX"

#: ★iNES ROM の先頭 4 バイト
INES_MAGIC = b"NES\x1a"


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    done = subprocess.run(["git", "ls-files"], cwd=str(PROJECT_ROOT),
                          capture_output=True, timeout=60)
    if done.returncode != 0:
        pytest.skip("git が使えない")
    return [p for p in done.stdout.decode("utf-8", "replace").splitlines() if p]


# --- 1. 拡張子で見る -------------------------------------------------------

def test_ROMを同梱していない(tracked):
    bad = [p for p in tracked if p.lower().endswith(".nes")]
    assert bad == [], f"⚠ ROM が Git に入っている: {bad}"


def test_セーブステートをコミットしていない(tracked):
    """⚠⚠ ★これが 2026-08-14 まで 1 件すり抜けていた。"""
    bad = []
    for p in tracked:
        low = p.lower()
        if low.endswith(FORBIDDEN_SUFFIXES) or low.endswith(FORBIDDEN_PATTERNS):
            bad.append(p)
    assert bad == [], (
        f"⚠ 公開できないものが Git に入っている（{len(bad)} 件）: {bad[:5]}\n"
        "★`.gitignore` を直したうえで、既に入っているものは"
        "`git rm --cached` を検討してください（⚠ 履歴には残ります）")


# --- 2. ⚠ 中身で見る（★拡張子を変えられても効く）-------------------------

def test_中身がセーブステートのファイルが入っていない(tracked):
    """⚠ 拡張子だけでは、名前を変えられると素通りする。

    ★先頭 4 バイト（`FCSX`）で見る。
    """
    bad = []
    for rel in tracked:
        path = PROJECT_ROOT / rel
        if not path.is_file():
            continue
        try:
            if path.stat().st_size < 4:
                continue
            with path.open("rb") as fh:
                head = fh.read(4)
        except OSError:
            continue
        if head == FCEUX_MAGIC:
            bad.append(rel)
    assert bad == [], f"⚠ 中身がセーブステートのファイル: {bad}"


def test_中身がROMのファイルが入っていない(tracked):
    bad = []
    for rel in tracked:
        path = PROJECT_ROOT / rel
        if not path.is_file():
            continue
        try:
            if path.stat().st_size < 4:
                continue
            with path.open("rb") as fh:
                head = fh.read(4)
        except OSError:
            continue
        if head == INES_MAGIC:
            bad.append(rel)
    assert bad == [], f"⚠ 中身が ROM のファイル: {bad}"


# --- 3. ★ 穴が塞がっていること --------------------------------------------

def test_gitignoreがfcsを除外している():
    """★これが無かったので 1 件すり抜けた。"""
    body = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.fcs" in body, "⚠ `.fcs` の除外が無い（★これが漏れの原因だった）"
    assert "*.fc[0-9]" in body


def test_新しいセーブステートが除外される(tmp_path):
    """⚠ 「書いた」だけでは効いていない。★実際に効くか確かめる。"""
    probe = PROJECT_ROOT / "work" / "_ignore_probe.fcs"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_bytes(FCEUX_MAGIC + b"\x00" * 16)
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-v", str(probe.relative_to(PROJECT_ROOT))],
            cwd=str(PROJECT_ROOT), capture_output=True, timeout=30)
        assert done.returncode == 0, (
            "⚠ 新しい `.fcs` が除外されない\n" +
            done.stdout.decode("utf-8", "replace"))
    finally:
        probe.unlink(missing_ok=True)
