"""戦闘ログの粗探し（2026-08-05 / モンキーテスト用）。

    > いろんな戦術を確認してログを取って自律的に改善して

★★ **検出器そのものを試す。** ★★
  ⚠⚠ 「0件だから合格」は、**検出器が弱いだけ**のことがあります。
    だから「わざと壊したログ」を食わせて、**ちゃんと鳴る**ことを見ます。

## ⚠ 2026-08-05 に実際に踏んだ2つ（記録）

### 1. 時刻だけで絞って、過去の日付まで拾った

`--since 07:37` を時刻だけで比べたため、**別の日の 07:37 以降**まで
拾い、★直したはずの二重回復が「まだある」ように見えました。

### 2. オーバーキルの数え方が誤っていた

「予約 > 残り × 1.6」で数えたら 34回中25回が引っかかりました。
★しかし中身は `残り 19 に 一撃 70` — **避けようのない単発**でした。
70 の攻撃しか持たない人が HP19 の敵を殴れば必ずそうなります。

→ 本当に見るべきは「**すでに十分な予約があるのに、さらに狙う**」場合。
"""

from __future__ import annotations

import pathlib

import pytest

from research.probes.reusable import battle_log_audit as audit


@pytest.fixture
def log(tmp_path):
    def write(lines: list[str]) -> pathlib.Path:
        path = tmp_path / "t.log"
        path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        return path
    return write


# --- ★★ 二重回復 ---------------------------------------------------------

def test_二重回復を見つける(log):
    """★同じ秒に同じ人が2回回復されている。"""
    path = log([
        "2026-08-05 07:00:00 回復を確認: samaltria の ホイミ"
        " -> lorasia のHP 40 -> 72（+32）/ MP 10 -> 7",
        "2026-08-05 07:00:00 回復を確認: moonbrooke の Healmore"
        " -> lorasia のHP 72 -> 122（+50）/ MP 20 -> 15",
    ])
    got = audit.audit(path, None)
    assert len(got["doubles"]) == 1, got["doubles"]


def test_道具での自己回復も回復として数える(log):
    """★★ **これが 2026-08-05 の実機で見つけた形**。

    ⚠ ちからのたて（道具）を回復に数えないと、
      呪文と重なっても**気づけません**。
    """
    path = log([
        "2026-08-05 07:00:00 戦闘で ちからのたて を使います"
        "（samaltria / 持ち物の行3 -> 0x08 の 列1,行1）",
        "2026-08-05 07:00:00 回復を確認: moonbrooke の Healmore"
        " -> samaltria のHP 22 -> 80（+58）/ MP 20 -> 15",
    ])
    got = audit.audit(path, None)
    assert len(got["doubles"]) == 1, "⚠ 道具と呪文の重なりを見逃しています"


def test_別々の人への回復は二重にしない(log):
    path = log([
        "2026-08-05 07:00:00 回復を確認: samaltria の ホイミ"
        " -> lorasia のHP 40 -> 72（+32）/ MP 10 -> 7",
        "2026-08-05 07:00:00 回復を確認: moonbrooke の Healmore"
        " -> samaltria のHP 30 -> 80（+50）/ MP 20 -> 15",
    ])
    assert audit.audit(path, None)["doubles"] == []


# --- ★★ オーバーキル -----------------------------------------------------

def test_避けようのない単発をオーバーキルにしない(log):
    """⚠⚠ **最初の数え方の誤り**（上の説明を参照）。

    70 の攻撃しか持たない人が HP19 の敵を殴れば必ずこうなります。
    ★直しようがないので、鳴らしてはいけません。
    """
    path = log([
        "2026-08-05 07:00:00 lorasia は やまねずみ を狙います"
        "（残り約19 / この攻撃で約70 / 予約 計70）",
    ])
    got = audit.audit(path, None)
    assert got["overkills"] == [], "⚠ 避けようのない単発で鳴っています"
    assert len(got["aims"]) == 1, "★狙いの行は読めていること"


def test_すでに足りているのに重ねたら鳴る(log):
    """★★ **これが本物のオーバーキル**（指示書 §3「最終調整」）。

    先に 100 の予約が入っているのに、HP 50 の敵をさらに狙っています。
    """
    path = log([
        "2026-08-05 07:00:00 samaltria は スライム を狙います"
        "（残り約50 / この攻撃で約30 / 予約 計130）",
    ])
    got = audit.audit(path, None)
    assert len(got["overkills"]) == 1, "⚠⚠ 重ねすぎを見逃しています"


def test_倒しきれない敵への追撃は鳴らさない(log):
    """★84 では HP88 を倒しきれないので、2撃目は正しい判断です。"""
    path = log([
        "2026-08-05 07:00:00 lorasia は バーサーカー を狙います"
        "（残り約88 / この攻撃で約84 / 予約 計168）",
    ])
    assert audit.audit(path, None)["overkills"] == []


# --- ⚠ 日付の絞り込み ----------------------------------------------------

def test_時刻だけで絞っても別の日を拾わない(log):
    """⚠⚠ **実際に踏んだ**（上の説明1）。

    ★日付を省いたら、ログの**最新の日付**を補います。
    """
    path = log([
        "2026-08-01 08:00:00 回復を確認: samaltria の ホイミ"
        " -> lorasia のHP 40 -> 72（+32）/ MP 10 -> 7",
        "2026-08-01 08:00:00 回復を確認: moonbrooke の Healmore"
        " -> lorasia のHP 72 -> 122（+50）/ MP 20 -> 15",
        "2026-08-05 09:00:00 [MONKEY] 1戦目に入りました",
    ])
    got = audit.audit(path, "08:00:00")
    assert got["doubles"] == [], "⚠ 別の日の二重回復を拾っています"
    assert got["battles"] == 1


# --- ⚠ 例外は最優先 -------------------------------------------------------

def test_例外を拾う(log):
    path = log([
        "2026-08-05 07:00:00 bridge.lua:100: attempt to call method 'x'",
    ])
    got = audit.audit(path, None)
    names = [k[0] for k in got["hits"]]
    assert "落ちた・例外" in names


def test_戦闘が0なら合格にしない(log, capsys):
    """★★ **「採れなかった」を合格に見せない**（playbook #43）。"""
    path = log(["2026-08-05 07:00:00 何も起きていない"])
    code = audit.main(["--log", str(path)])
    assert code == 1
    assert "何も検証できていません" in capsys.readouterr().out
