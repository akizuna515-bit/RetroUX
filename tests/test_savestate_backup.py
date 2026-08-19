"""セーブステートの世代バックアップの検証。

★守りたいのは「取り返しのつかない事故」なので、
  次の2点を重点的に固定化する。

  1. **同じ内容で世代を作らない**
     作ってしまうと、触っていないのに世代が流れて古い世代を押し出す。
     世代の目的は「戻れること」なので、押し出しは事故に直結する。
  2. **復元する前に、いまの内容も世代に残す**
     「復元したら復元前に戻せない」では同じ事故を繰り返す。
"""

from __future__ import annotations


from pathlib import Path

import pytest

from retroux.tools import savestate_backup as sb


@pytest.fixture()
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "fcs"
    dst = tmp_path / "backup"
    src.mkdir()
    return src, dst


def write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def test_世代を作る(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    f = src / "DQ2_J.fc0"
    write(f, b"one")

    assert sb.scan(src, dst, generations=10, quiet=True) == 1
    gens = sb.list_generations(dst, "DQ2_J.fc0")
    assert len(gens) == 1
    assert gens[0].read_bytes() == b"one"


def test_同じ内容なら世代を作らない(dirs: tuple[Path, Path]) -> None:
    """★古い世代を押し出さないための最重要の性質。"""
    src, dst = dirs
    f = src / "DQ2_J.fc0"
    write(f, b"one")
    sb.scan(src, dst, generations=10, quiet=True)

    # 中身が変わっていないのに何度見ても増えない
    for _ in range(5):
        assert sb.scan(src, dst, generations=10, quiet=True) == 0
    assert len(sb.list_generations(dst, "DQ2_J.fc0")) == 1


def test_内容が変わったら世代が増える(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    f = src / "DQ2_J.fc0"
    for i, data in enumerate((b"one", b"two", b"three")):
        write(f, data)
        sb.scan(src, dst, generations=10, quiet=True)
        assert len(sb.list_generations(dst, "DQ2_J.fc0")) == i + 1

    gens = sb.list_generations(dst, "DQ2_J.fc0")
    # 新しい順
    assert gens[0].read_bytes() == b"three"
    assert gens[-1].read_bytes() == b"one"


def test_世代数の上限を守る(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    f = src / "DQ2_J.fc0"
    for i in range(5):
        write(f, f"data{i}".encode())
        sb.rotate_in(f, dst, generations=3)

    gens = sb.list_generations(dst, "DQ2_J.fc0")
    assert len(gens) == 3
    # 残っているのは新しい3つ
    kept = {g.read_bytes() for g in gens}
    assert kept == {b"data2", b"data3", b"data4"}


def test_復元する前にいまの内容を世代に残す(dirs: tuple[Path, Path]) -> None:
    """★「復元したら復元前に戻せない」を防ぐ。"""
    src, dst = dirs
    f = src / "DQ2_J.fc0"

    write(f, b"good")
    sb.rotate_in(f, dst, generations=10)

    # 事故: ハマりポイントで上書きしてしまった
    write(f, b"stuck")

    rc = sb.cmd_restore(src, dst, "DQ2_J.fc0", gen=0, generations=10)
    assert rc == 0
    # 良い状態へ戻っている
    assert f.read_bytes() == b"good"
    # ★事故後の内容も世代に残っている（復元自体も取り消せる）
    contents = {g.read_bytes() for g in sb.list_generations(dst, "DQ2_J.fc0")}
    assert b"stuck" in contents
    assert b"good" in contents


def test_範囲外の世代を指定したら失敗する(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    f = src / "DQ2_J.fc0"
    write(f, b"one")
    sb.rotate_in(f, dst, generations=10)

    assert sb.cmd_restore(src, dst, "DQ2_J.fc0", gen=99, generations=10) == 1
    # 失敗しても元のファイルは壊さない
    assert f.read_bytes() == b"one"


def test_世代が無いファイルの復元は失敗する(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    assert sb.cmd_restore(src, dst, "NOPE.fc0", gen=0, generations=10) == 1


def test_複数のスロットを別々に管理する(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    write(src / "DQ2_J.fc0", b"slot0")
    write(src / "DQ2_J.fc8", b"slot8")

    sb.scan(src, dst, generations=10, quiet=True)
    assert sb.list_generations(dst, "DQ2_J.fc0")[0].read_bytes() == b"slot0"
    assert sb.list_generations(dst, "DQ2_J.fc8")[0].read_bytes() == b"slot8"


def test_セーブステート以外は拾わない(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    write(src / "memo.txt", b"not a savestate")
    write(src / "DQ2_J.fc0", b"real")

    sb.scan(src, dst, generations=10, quiet=True)
    assert not (dst / "memo.txt").exists()
    assert sb.list_generations(dst, "DQ2_J.fc0")


def test_変わっていないファイルは触らない(dirs: tuple[Path, Path]) -> None:
    """★1秒ごとに見ても負荷にならないこと。

    seen を渡すと、更新時刻とサイズが同じファイルは完全に飛ばす。
    これが無いと変化していなくても settled() の待機が毎回走り、
    実測でセーブステート24件のとき1回の巡回に約2秒かかっていた。
    """
    src, dst = dirs
    f = src / "DQ2_J.fc0"
    write(f, b"one")

    seen: dict[str, tuple[int, int]] = {}
    assert sb.scan(src, dst, generations=10, quiet=True, seen=seen) == 1

    # 2回目以降は読みにすら行かない
    calls = {"n": 0}
    real_settled = sb.settled

    def counting_settled(path, *a, **kw):
        calls["n"] += 1
        return real_settled(path, *a, **kw)

    sb.settled = counting_settled
    try:
        for _ in range(5):
            assert sb.scan(src, dst, generations=10, quiet=True, seen=seen) == 0
        assert calls["n"] == 0, "変わっていないのにファイルを触っている"
    finally:
        sb.settled = real_settled


def test_変わったファイルは拾う(dirs: tuple[Path, Path]) -> None:
    """飛ばす仕組みを入れても、実際の更新は取りこぼさないこと。"""
    src, dst = dirs
    f = src / "DQ2_J.fc0"
    write(f, b"one")

    seen: dict[str, tuple[int, int]] = {}
    sb.scan(src, dst, generations=10, quiet=True, seen=seen)

    # 中身が変われば（サイズも変わる）拾う
    write(f, b"two-different-length")
    assert sb.scan(src, dst, generations=10, quiet=True, seen=seen) == 1
    assert len(sb.list_generations(dst, "DQ2_J.fc0")) == 2


def test_同じ長さでも更新時刻が変われば中身を確認する(
    dirs: tuple[Path, Path],
) -> None:
    """★サイズが同じでも見逃さないこと。

    更新時刻かサイズのどちらかが変われば中身を読みに行き、
    そこで初めてハッシュで判定する。
    「同じ内容なのに世代を作る」ことは起きない。
    """
    import os

    src, dst = dirs
    f = src / "DQ2_J.fc0"
    write(f, b"aaa")
    seen: dict[str, tuple[int, int]] = {}
    sb.scan(src, dst, generations=10, quiet=True, seen=seen)

    # 同じ長さで別の内容にし、更新時刻を確実にずらす
    write(f, b"bbb")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert sb.scan(src, dst, generations=10, quiet=True, seen=seen) == 1

    # 同じ長さ・同じ内容で更新時刻だけずらしても、世代は増えない
    write(f, b"bbb")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    assert sb.scan(src, dst, generations=10, quiet=True, seen=seen) == 0
    assert len(sb.list_generations(dst, "DQ2_J.fc0")) == 2
