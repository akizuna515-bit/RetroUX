"""DQ3 の控えは 100 世代（RX3-0307）。

依頼者 2026-09-20「セーブステート保持 100 のしたい。そうすれば実質どこでもセーブになる」。

★仕組みは DQ2 のものをそのまま使い（`retroux/tools/savestate_backup.py` / 公開済み・変更しない）、
DQ3 の入口（`dq3/savestate_backup.py`）が**既定を 100 にする**だけ。

## ⚠⚠ この検査がいちばん見たいもの

★世代数は「引数で渡すもの」で、`rotate_in()` が**その場で**古い世代を削ります。
→ ⚠ 控えるときだけ 100 にしても、**戻すときに 10 で叩けば 90 世代が消えます**。
   ★だから「入口を通ったか」を見ます（`test_DQ2の既定で戻すと90世代が消える`）。

⚠ 本物のセーブ（`tools/fceux/fcs/`）には触りません。すべて `tmp_path` の中です。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from retroux.tools import savestate_backup as sb

from dq3 import savestate_backup as dq3sb


@pytest.fixture()
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "fcs"
    dst = tmp_path / "backup"
    src.mkdir()
    return src, dst


def fill(src: Path, dst: Path, name: str, times: int, generations: int) -> None:
    """中身を変えながら `times` 回控える（★同じ内容だと世代が増えないため）。"""
    f = src / name
    for i in range(times):
        f.write_bytes(f"state-{i:04d}".encode())
        sb.rotate_in(f, dst, generations)


# --- 既定値 ---------------------------------------------------------------


def test_DQ3の入口は100世代を既定にする() -> None:
    assert dq3sb.DQ3_GENERATIONS == 100
    assert dq3sb.with_generations([]) == ["--generations", "100"]


def test_ほかの引数はそのまま後ろへ残る() -> None:
    got = dq3sb.with_generations(["--session", "abc"])
    assert got == ["--generations", "100", "--session", "abc"]


@pytest.mark.parametrize("given", [
    ["--generations", "5"],
    ["--generations=5"],
    # ★argparse は前置きの省略を受ける（`--generation` は `--generations` のこと）
    ["--generation", "5"],
])
def test_人が世代数を書いていたら触らない(given: list[str]) -> None:
    """⚠ 人の指定を黙って上書きしない。"""
    assert dq3sb.with_generations(given) == given


def test_戻す世代の指定を世代数と読み違えない() -> None:
    """⚠ `--gen`（戻す世代の番号）は `--generations`（保つ数）とは別の引数。"""
    given = ["--restore", "DQ3_J.fc0", "--gen", "3"]
    assert dq3sb.with_generations(given) == ["--generations", "100", *given]


# --- 入口の配線（★純粋関数だけでなく、実際に渡ることを見る）----------------


def test_入口はDQ2の道具に100世代を渡して呼ぶ(monkeypatch: pytest.MonkeyPatch) -> None:
    """★`with_generations` が正しくても、呼ばれていなければ意味がない。"""
    seen: list[list[str]] = []

    def fake_main() -> int:
        seen.append(list(sys.argv[1:]))
        return 0

    monkeypatch.setattr(dq3sb._dq2, "main", fake_main)
    rc = dq3sb.main(["--once"])

    assert rc == 0
    assert seen == [["--generations", "100", "--once"]]


def test_入口は呼び出しのあとsys_argvを戻す(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ 差し替えたまま戻さないと、★同じ process の後続が巻き添えになる。"""
    monkeypatch.setattr(dq3sb._dq2, "main", lambda: 0)
    before = list(sys.argv)

    dq3sb.main(["--list"])

    assert sys.argv == before


def test_入口は道具の終了コードをそのまま返す(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dq3sb._dq2, "main", lambda: 1)
    assert dq3sb.main([]) == 1


# --- 100 世代たまること ----------------------------------------------------


def test_100世代まで積んで古いものから捨てる(dirs: tuple[Path, Path]) -> None:
    src, dst = dirs
    fill(src, dst, "DQ3_J.fc0", times=120, generations=dq3sb.DQ3_GENERATIONS)

    gens = sb.list_generations(dst, "DQ3_J.fc0")
    assert len(gens) == 100
    # ★新しい順に並ぶ。最新は最後に書いた内容
    assert gens[0].read_bytes() == b"state-0119"
    # ⚠ 捨てられるのは**古いほう**（★20 件が押し出されている）
    assert gens[-1].read_bytes() == b"state-0020"


def test_スロットごとに100世代を持つ(dirs: tuple[Path, Path]) -> None:
    """⚠「全部で 100」ではない。

    ★よく使うスロットが、ほかのスロットの世代を押し出してはいけない
      （それでは「あのときへ戻る」が果たせない）。
    """
    src, dst = dirs
    fill(src, dst, "DQ3_J.fc0", times=120, generations=dq3sb.DQ3_GENERATIONS)
    fill(src, dst, "DQ3_J.fc1", times=5, generations=dq3sb.DQ3_GENERATIONS)

    assert len(sb.list_generations(dst, "DQ3_J.fc0")) == 100
    # ★fc0 を 120 回回しても fc1 の 5 世代は無事
    assert len(sb.list_generations(dst, "DQ3_J.fc1")) == 5


# --- ⚠⚠ 入口を分けた理由そのもの -----------------------------------------


def test_DQ2の既定で戻すと90世代が消える(dirs: tuple[Path, Path]) -> None:
    """⚠⚠ これは**直すべき挙動ではなく、入口を分けた理由**。

    ★`retroux` 側は公開済みで既定 10 のまま（変えない）。
    ⚠ だから DQ3 で `python -m retroux.tools.savestate_backup --restore` を叩くと、
      `cmd_restore` → `rotate_in(..., generations=10)` が 90 世代を削る。
    → ★`scripts/start-dq3.ps1` と文書は `dq3.savestate_backup` だけを案内する。
      ⚠ この検査が赤くなったら、それは**道具側の既定が変わった**ということ。

    ## ⚠⚠ 削られる条件（★2026-09-21 に最初この検査を書き損じた）

    ★`rotate_in()` は「いまの内容が最新世代と同じ」なら**早期 return** し、
    削る行まで進みません。⚠ だから世代を積んだ直後に戻しても**何も起きません**。
    → ★削られるのは「本物のファイルが最新世代と違うとき」＝**上書き事故のとき**。
      ⚠ つまり**いちばん戻りたい場面でだけ**、90 世代が消えます。
    """
    src, dst = dirs
    fill(src, dst, "DQ3_J.fc0", times=100, generations=dq3sb.DQ3_GENERATIONS)
    assert len(sb.list_generations(dst, "DQ3_J.fc0")) == 100

    # ★上書き事故（⚠ 控えが止まっている間にセーブしてしまった）
    (src / "DQ3_J.fc0").write_bytes(b"accident")

    # ⚠ DQ2 の既定（10）で 1 回戻す
    rc = sb.cmd_restore(src, dst, "DQ3_J.fc0", gen=0,
                        generations=sb.DEFAULT_GENERATIONS)

    assert rc == 0
    assert sb.DEFAULT_GENERATIONS == 10
    assert len(sb.list_generations(dst, "DQ3_J.fc0")) == 10

    # ★DQ3 の入口の値で戻せば、同じ場面でも 100 世代のまま
    fill(src, dst, "DQ3_J.fc1", times=100, generations=dq3sb.DQ3_GENERATIONS)
    (src / "DQ3_J.fc1").write_bytes(b"accident")
    rc = sb.cmd_restore(src, dst, "DQ3_J.fc1", gen=0,
                        generations=dq3sb.DQ3_GENERATIONS)

    assert rc == 0
    # ⚠ 事故の内容も世代に残るので 100 のまま（★押し出されたのは最古の 1 件）
    assert len(sb.list_generations(dst, "DQ3_J.fc1")) == 100


def test_戻す前と中身が同じなら世代は削られない(dirs: tuple[Path, Path]) -> None:
    """★上の検査の裏側。⚠ 片側だけ見ると「10 に削られる」を誤って一般化する。

    ⚠ `rotate_in()` が早期 return するので、世代数の指定が 10 でも何も起きない。
    """
    src, dst = dirs
    fill(src, dst, "DQ3_J.fc0", times=100, generations=dq3sb.DQ3_GENERATIONS)

    # ★本物のファイルは最新世代と同じ内容のまま（⚠ 何も上書きしていない）
    rc = sb.cmd_restore(src, dst, "DQ3_J.fc0", gen=0,
                        generations=sb.DEFAULT_GENERATIONS)

    assert rc == 0
    assert len(sb.list_generations(dst, "DQ3_J.fc0")) == 100


def test_起動スクリプトはDQ3の入口を呼ぶ() -> None:
    """⚠ 起動スクリプトが道具を直に呼ぶと、★既定の 10 世代に戻る（黙って）。"""
    ps1 = Path(__file__).resolve().parents[1] / "scripts" / "start-dq3.ps1"
    text = ps1.read_text(encoding="utf-8-sig")

    assert '"-m", "dq3.savestate_backup"' in text
    # ⚠ 起動の引数として道具を直に呼んでいないこと（★註の中の言及は行頭が # なので除く）
    launching = [ln for ln in text.splitlines()
                 if "retroux.tools.savestate_backup" in ln
                 and not ln.lstrip().startswith("#")]
    assert launching == [], launching
