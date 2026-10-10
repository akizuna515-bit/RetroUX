"""照合をやり直さないための覚え（RX-0114 / 2026-08-30）。

## ⚠⚠ 何を避けたいか

  `validator.validate_dir` は **721 秒**かかります（★テスト全体の 65%）。
  ⚠ ROM も撮影もコードも変わっていないのに、毎回やり直しています。

## ★材料が同じなら、答えも同じ

  `validate_dir` は副作用がなく、⚠ **同じ材料なら必ず同じ答え**です。
  → ★材料の指紋を鍵にして、答えを取っておきます。

## ⚠⚠ ここが危ないところ

  ★鍵が当たり続けると、**照合は二度と走りません**。
  ⚠ 壊れていても気づけません（★「0 件は通っていないだけ」と同じ形）。

  → ⚠ 歯止め:

    1  ★いつ計算したかを残し、画面に必ず出す
    2  ★`RETROUX_NO_TEST_CACHE=1` で必ず計算し直す
    3  ⚠ 鍵が変わることを検査で確かめる（ROM / 撮影 / コード）

  詳しくは `docs/design/platform/dq2-test-validation-cache.md`。
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / "work" / "_cache" / "monster-validation"

#: ⚠ 答えの形が変わったら上げる（★古い覚えは捨てる）
FORMAT = 1

#: ★これを立てると、必ず計算し直す
OFF_ENV = "RETROUX_NO_TEST_CACHE"

#: ⚠⚠ 鍵に入れるコード。★`validator` だけに絞らない。
#:   「比べ方だけ見ればいい」と絞ると、`locator.py` を直したときに
#:   ⚠ **古い答えが返ります**。★安いので丸ごと入れる。
CODE_DIR = ROOT / "dq2rom"


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_dir(folder: pathlib.Path) -> str:
    """★folder の中の `.py` を、名前ごと 1 つの指紋にする。"""
    got = hashlib.sha256()
    for path in sorted(folder.rglob("*.py")):
        got.update(str(path.relative_to(folder)).replace("\\", "/").encode())
        got.update(path.read_bytes())
    return got.hexdigest()


def _digest_captures(folder: pathlib.Path) -> str:
    """⚠ 撮影は**遊ぶたびに増えます**。★1 枚増えたら鍵が変わること。"""
    got = hashlib.sha256()
    if folder.is_dir():
        for path in sorted(folder.glob("*.png")):
            got.update(path.name.encode())
            got.update(str(path.stat().st_size).encode())
            got.update(path.read_bytes())
    return got.hexdigest()


def key_for(prg: bytes, captures: pathlib.Path, extra=()) -> str:
    """★材料の指紋。⚠ 1 つでも変わったら別の鍵になる。"""
    got = hashlib.sha256()
    got.update(b"format=%d;" % FORMAT)
    got.update(("rom=%s;" % _digest_bytes(prg)).encode())
    got.update(("shots=%s;" % _digest_captures(captures)).encode())
    got.update(("code=%s;" % _digest_dir(CODE_DIR)).encode())
    for one in extra:
        got.update(("extra=%s;" % one).encode())
    return got.hexdigest()


def path_for(key: str) -> pathlib.Path:
    return CACHE / ("%s.json" % key[:16])


def load(key: str):
    """★取っておいた答え。⚠ 無い / 形が違う / 鍵が違うなら None。"""
    if os.environ.get(OFF_ENV):
        return None
    path = path_for(key)
    if not path.is_file():
        return None
    try:
        with io.open(path, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return None
    if got.get("format") != FORMAT or got.get("key") != key:
        return None
    return got


def save(key: str, rows, made_by: str = "") -> pathlib.Path:
    """★答えを取っておく。⚠ `work/` の下なので Git には入らない。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = path_for(key)
    body = {
        "format": FORMAT,
        "key": key,
        "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "made_by": made_by,
        "rows": [dataclasses.asdict(one) if dataclasses.is_dataclass(one)
                 else dict(one) for one in rows],
    }
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        json.dump(body, fh, ensure_ascii=False)
    return path


def note(got) -> str:
    """⚠⚠ **画面に必ず出す**。★黙って当てない。"""
    if got is None:
        return "★照合をやり直しました（⚠ 覚えは使っていません）"
    return ("★覚えから読みました（%s に計算 / %d 枚）"
            " ⚠ やり直すには %s=1"
            % (got.get("computed_at", "?"), len(got.get("rows") or ()),
               OFF_ENV))


#: ⚠ JSON にすると tuple が list になる。★戻すところ。
TUPLES = ("offset", "expected_size", "shot_size")


def rehydrate(rows, cls):
    """★取っておいた答えを `Comparison` に戻す。

    ⚠⚠ JSON は tuple を持てません。`(8, 44)` は `[8, 44]` になります。
      ★そのまま使うと、`==` の比べ方が変わって**静かに違う答え**になります。
    """
    out = []
    for row in rows:
        got = dict(row)
        for key in TUPLES:
            if isinstance(got.get(key), list):
                got[key] = tuple(got[key])
        out.append(cls(**got))
    return out
