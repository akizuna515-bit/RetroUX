"""改行コードと文字コードの検査（2026-08-12 / 監査 Step 5）。

## ⚠⚠ なぜ要るか

この計画は改行と文字コードを**意図的に使い分けています**（`.gitattributes`）。
`.vbs` を UTF-8 にすると**コンパイルエラーで起動すらしません**（実際に踏んだ）。

★ところが `.py` `.lua` `.md` には**改行の決まりがありません**。
実測（2026-08-12 / 792 件）:

```
.py   LF 296 / CRLF 148 / ⚠ 混在 4
.lua  LF 127 / CRLF  70 / ⚠ 混在 2
.md   LF  58 / CRLF  31 / ⚠ 混在 2
```

## ★ この検査が見るのは「混在」だけです

⚠⚠ **拡張子ごとの統一はまだ見ません。** 揃えるには一括変換が要り、
  ★Git の差分が改行で埋まって仕様の差分が読めなくなります（指示書 §19）。
  順番はこうします。

```
① 混在が無いことだけ検査する（★いまここ）
② EOL normalization only の専用コミットで既知の9件を揃える
③ そのあと拡張子ごとの規約を入れる
```

## ⚠ なぜ「人が気をつける」では止まらないか

混在の原因は**道具の既定動作**です（`docs/50-playbook.md`）。

- `cat >> file` / `Path.write_text` は **LF** を書く
  → ⚠ CRLF のファイルに足すと**その行だけ LF** になる
- `read_text` ＋ `write_text` の一括置換は **CRLF を全部潰す**

★どちらも注意では防げません。**検査で止めます。**
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 見る拡張子。⚠ バイナリと採取データは見ない。
TARGET_SUFFIX = (".py", ".lua", ".md", ".yaml", ".yml", ".json", ".toml",
                 ".ps1", ".cmd", ".bat", ".vbs")

#: ⚠ 混在を**許す**ファイル。★2026-08-12 に **空になりました**。
#:
#: 直す前は9件ありました（`.gitignore` を含む）。
#: `EOL normalization only` の専用コミットで、**各ファイルの多数派へ**
#: 揃えています（★少数派の行だけ直すので差分が小さい）。
#:
#: ⚠⚠ **ここへ足すのは最後の手段です。** 足す前に「なぜ混ざったか」を
#:   見てください。原因はほぼ**道具の既定動作**で、直し方があります
#:   （`docs/50-playbook.md` / `cat >>` と `Path.write_text` は LF を書く）。
KNOWN_MIXED: set[str] = set()

#: `.ps1` は **UTF-8 BOM 付き**（`.gitattributes` の表 / PS 5.1 は
#: BOM 無しを ANSI として読む）。
BOM = b"\xef\xbb\xbf"

#: ⚠ BOM を付けてはいけない拡張子。★`.ps1` は逆に**必須**なので入れない。
NO_BOM_SUFFIX = (".py", ".lua")


def _tracked() -> list[pathlib.Path]:
    raw = subprocess.run(["git", "ls-files", "-z"], cwd=str(PROJECT_ROOT),
                         capture_output=True).stdout
    out = []
    for chunk in raw.split(b"\0"):
        if not chunk:
            continue
        try:
            rel = chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue                     # ⚠ 名前が UTF-8 でないものは見ない
        p = PROJECT_ROOT / rel
        if p.is_file() and p.suffix.lower() in TARGET_SUFFIX:
            out.append(p)
    return out


def _rel(p: pathlib.Path) -> str:
    return p.relative_to(PROJECT_ROOT).as_posix()


@pytest.fixture(scope="module")
def files():
    got = _tracked()
    if not got:
        pytest.skip("git が使えないか、追跡ファイルがありません")
    return got


def _mixed(path: pathlib.Path) -> tuple[int, int]:
    b = path.read_bytes()
    crlf = b.count(b"\r\n")
    lf = b.count(b"\n") - crlf
    return crlf, lf


def test_単独のCRが無い(files):
    """⚠⚠ **改行ではない CR** を見つける（2026-08-13 に踏んだ）。

    ## ★ 何が起きたか

      README へ `work\\retroux.log` と書こうとして、
      heredoc の中で `\\r` が**本物の CR（0x0D）**になり、

          | `work` + CR + `etroux.log` |

      という壊れた行が入った。⚠ 画面には `worketroux.log` と出る。

    ## ⚠ なぜ既存の検査で見つからなかったか

      混在の検査は **CRLF と LF の数**しか見ていない。
      ★単独の CR は `crlf` にも `lf` にも数えられず、**両方 0 のまま**通る。

      ⚠ 「混在なし」という緑は、この壊れ方に対しては**無意味**だった。

    ★CR は Mac 形式（〜OS 9）の改行だが、この計画では使わない。
      1 件でもあれば、まず疑うのは**書き損じ**。
    """
    bad = []
    for p in files:
        b = p.read_bytes()
        lone = b.count(b"\r") - b.count(b"\r\n")
        if lone:
            # ★どこにあるかを出す（⚠ 「1件ある」だけでは直せない）
            idx = 0
            where = []
            while len(where) < 3:
                idx = b.find(b"\r", idx)
                if idx < 0:
                    break
                if b[idx:idx + 2] != b"\r\n":
                    around = b[max(0, idx - 30):idx + 30]
                    where.append(repr(around))
                idx += 1
            bad.append(f"{_rel(p)}（単独CR {lone} 件）\n      " + "\n      ".join(where))
    assert not bad, (
        "⚠⚠ 改行ではない CR（0x0D）があります。★`\\r` を書いたつもりが"
        "本物の CR になった可能性があります:\n  " + "\n  ".join(bad))


def test_新しく混在を増やしていない(files):
    """★★★ **これが目的**。⚠ 既知の9件以外に混在を作らないこと。"""
    bad = []
    for p in files:
        crlf, lf = _mixed(p)
        if crlf and lf and _rel(p) not in KNOWN_MIXED:
            bad.append(f"{_rel(p)}（CRLF {crlf} 行 / LF {lf} 行）")
    assert not bad, (
        "⚠⚠ 改行が混在しています。★CRLF のファイルへ LF で追記した"
        "（`cat >>` や `Path.write_text`）のが典型です:\n  "
        + "\n  ".join(bad))


def test_既知の混在が減ったら表からも消す(files):
    """⚠ 直したのに表に残っていると、**次の混在を見逃します**。

    ★「まだ直っていない」という嘘を、表の側にも残さないための検査です。
    """
    still = set()
    for p in files:
        crlf, lf = _mixed(p)
        if crlf and lf:
            still.add(_rel(p))
    fixed = KNOWN_MIXED - still
    assert not fixed, (
        "★直っています。KNOWN_MIXED から消してください: "
        + ", ".join(sorted(fixed)))


def test_混在は1件も無い(files):
    """★★★ **2026-08-12 に 9 件を揃えて、いま 0 件です。**

    ⚠ ここが赤くなったら、`KNOWN_MIXED` へ足す前に**原因を見てください**。
      ★`cat >>` や `Path.write_text` は LF を書きます。CRLF のファイルへ
        足すと、その行だけ LF になります。
    """
    got = {_rel(p) for p in files if all(_mixed(p))}
    assert got == KNOWN_MIXED, (
        f"⚠ 混在の一覧が変わりました。\n  増えた: {sorted(got - KNOWN_MIXED)}"
        f"\n  減った: {sorted(KNOWN_MIXED - got)}")


def test_pyとluaにBOMを付けない(files):
    """⚠ Python は BOM 付きでも動きますが、★他の道具が先頭行を読み違えます。

    ⚠⚠ **`.ps1` はここに入れません**（BOM が**必須**なので）。
    """
    bad = [_rel(p) for p in files
           if p.suffix.lower() in NO_BOM_SUFFIX
           and p.read_bytes().startswith(BOM)]
    # ⚠ 2026-08-12 時点で 1 件（`retroux/tools/__init__.py`）。
    #   ★意図が読み取れないので、消す前に確認が要ります（増やさないことだけ見る）。
    assert set(bad) <= {"retroux/tools/__init__.py"}, (
        f"⚠ BOM を付けてはいけないファイルに BOM があります: {bad}")


def test_gitignoreにBOMを付けない():
    """⚠ Git は先頭行を `﻿...` として読みます。

    ★2026-08-12 まで BOM が付いていました。**1行目が `# Secrets`
      （コメント）だったので実害はありません**でしたが、
      ⚠ 1行目にパターンを書いた瞬間に効かなくなります。→ 外しました。
    """
    b = (PROJECT_ROOT / ".gitignore").read_bytes()
    assert not b.startswith(BOM), (
        "⚠⚠ `.gitignore` に BOM があります（★1行目のパターンが効きません）")


def test_ps1はBOM付き(files):
    """★`.gitattributes` の表どおり（PS 5.1 は BOM 無しを ANSI として読む）。

    ★2026-08-12 に**例外は無くなりました**。

    ⚠ それまで唯一 BOM 無しだった `scripts/validate-flow.ps1` は、
      Power Automate 用の雛形の残りで、依頼者の判断で**削除**しました
      （`CLAUDE.md`「該当しない案件では削除して構いません」）。
    ★いまは `.ps1` すべてが BOM 付きです。**例外を作らないこと。**
    """
    bad = [_rel(p) for p in files
           if p.suffix.lower() == ".ps1" and not p.read_bytes().startswith(BOM)]
    assert bad == [], (
        f"⚠⚠ BOM 無しの .ps1 があります（PS 5.1 が ANSI として読みます）: {bad}")


def test_起動まわりはcp932のまま(files):
    """⚠⚠ **UTF-8 にすると `.vbs` はコンパイルエラーで起動しません**（実際に踏んだ）。

    ★`.gitattributes` の表を、実ファイルでも守れているか見ます。
    """
    for rel in ("RetroUX.vbs", "Start-RetroUX-Console.cmd"):
        p = PROJECT_ROOT / rel
        if not p.exists():
            continue
        b = p.read_bytes()
        assert not b.startswith(BOM), f"⚠⚠ {rel} に BOM があります"
        try:
            b.decode("utf-8")
        except UnicodeDecodeError:
            continue                     # ★cp932（＝期待どおり）
        # ⚠ ASCII だけなら UTF-8 としても読めるので、それは許す
        assert all(x < 128 for x in b), f"⚠⚠ {rel} が UTF-8 になっています"


def test_改行の規約が書いてある():
    """★規約の置き場は `.gitattributes` **1か所**（2026-08-12 に明文化）。

    ⚠⚠ **`* -text` は残っていること。** Git に改行を変換させると、
      clone し直したときに LF が CRLF になり、★**手元では通るのに
      clone 先で落ちる**という分かりにくい壊れ方をします
      （`.gitattributes` の解説を参照）。

    ⚠ 規約は「揃える」ではなく「**混在を作らない**」の段階です。
      拡張子ごとに揃えるのは専用コミットで（未実施）。
    """
    text = (PROJECT_ROOT / ".gitattributes").read_bytes().decode("utf-8")
    assert "* -text" in text, "⚠⚠ Git に改行を触らせない方針が消えています"
    assert "改行の規約" in text, (
        "⚠ 改行の規約が `.gitattributes` から消えました。"
        "★規約の置き場は1か所に保ってください")
    # ★⚠ `.vbs` の決まりは**壊すと起動しない**ので、文言ごと守る
    assert "cp932" in text and ".vbs" in text, (
        "⚠⚠ 起動まわりの文字コードの決まりが消えています")
