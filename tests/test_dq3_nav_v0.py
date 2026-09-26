"""nav_v0（街ナビの Lua）を実機なしで動かす（RX3-0058）。★足場は `dq3_nav_v0_test.lua`。"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_nav_v0_test.lua"
TARGET = ROOT / "dq3" / "phase0" / "nav_v0.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and TARGET.exists()),
    reason="Lua を動かせない環境")


@pytest.fixture(scope="module")
def result() -> str:
    done = subprocess.run([sys.executable, str(RUNNER), str(HARNESS)], cwd=str(ROOT), capture_output=True,
                          timeout=180, text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, result


def test_OKが減っていない(result):
    n = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert n >= 46, "⚠ OK が %d 件しかありません%s%s" % (n, chr(10), result)   # ★RX3-0263 → 37 / RX3-0277 → 41 / RX3-0273 → 44 / RX3-0311 → 46


def test_街移動と聞き込みの要を動かして確かめている(result):
    for line in ("OK 街移動は A を押さない", "OK 塞がれたら replan して迂回する",
                 "OK 向く → A → はなす → B × 6 で閉じる", "OK nav_stop で安全に止まる",
                 "OK 動く NPC の隣へ近づき直して会話", "OK 戦闘に入ったら止まる",
                 # ⚠⚠ 2026-09-08（RX3-0115）依頼者「メッセージが表示中で移動が吸われている」
                 "OK 窓が開いていたら、歩き出す前に閉じる",
                 "OK 閉じない窓でも歩き出す",
                 "OK 窓が読めなくても止まらない",
                 # ⚠⚠ 2026-09-12（RX3-0194）依頼者「イシス（save6）でやはり再発する」
                 "OK ★Q2（また たびだつか）: $BB9D が鳴ったら B をやめ、はい に A を 1 回だけ",
                 "OK ★Q2: ▶ が いいえ なら 上 で はい へ寄せてから A",
                 "OK ★Q2: bank が 13 でなければ見張りは鳴らない",
                 "OK ★ふつうの閉じ方では A を押さない",
                 "OK ★Q2 の窓が出なければ何も押さずに止める",
                 # ⚠⚠ 2026-09-13（RX3-0229）依頼者「長尺メッセージの時にうまくとれてない？」
                 "OK ★長い話は ▼ が出てから B で送り、3 ページとも打ち終えた形で拾う",
                 "OK ★送りで上の行が消えても、消える前の 1 枚を拾う",
                 "OK ★次の頼みでは会話のページは空に戻る",
                 # ⚠⚠ 2026-09-13（RX3-0241）依頼者の小WI「最初のメッセージが発生した瞬間に高速化を解除する」
                 "OK ★道具屋: 最初の台詞が出た瞬間に高速化を解き、そこで止める",
                 "OK ★$828B が鳴らない（相手がいない）ときは最初の台詞にしない",
                 "OK ★聞き込み（stop_at なし）は最初の台詞で止めず",
                 "OK ★宿屋: 最初の台詞で高速化を解き、▼ を B で送り、$A55C が鳴ったら はい に A",
                 "OK ★宿屋: ▶ が いいえ なら 上 で はい へ寄せてから A",
                 "OK ★宿屋: $A55C が鳴らない はい／いいえ には答えず",
                 # ★RX3-0277（2026-09-17）ダメージ床は、ほかに道があれば通らない / 無ければ通る
                 "OK ★RX3-0277 作り直しの経路は、回り道があればダメージ床（H）を踏まない",
                 "OK ★RX3-0277 ダメージ床しか道が無ければ通る",
                 # ★RX3-0273（2026-09-17 / ⚠ 09-18 に画面で数える形へ直した）
                 "OK ★RX3-0273 はい／いいえ が 3 回出たら B をやめて止め、窓を人に返す",
                 # ⚠⚠ 依頼者「save0 再聞き込みで途中で窓が開きっぱなし」の再発防止（★$8743 は会話でも鳴る）
                 "OK ★RX3-0273 ふつうの会話（はい／いいえ が出ない）では発火しない",
                 "OK ★RX3-0273 同じ問いが見えている間は数えない",
                 # ⚠⚠ 2026-09-20（RX3-0311）依頼者「ラダトームで聞き込みがきかない」
                 "OK ★RX3-0311 アレフガルドの町（kind 3）と洞窟（kind 5）でも歩く",
                 "OK ★RX3-0311 世界地図（kind 0 / 2）では今までどおり断る"):
        assert any(ln.startswith(line) for ln in result.splitlines()), "⚠ " + line + " が出ていません" + chr(10) + result
