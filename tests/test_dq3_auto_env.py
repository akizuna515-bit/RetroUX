"""街内の省力操作の実行環境 ― Turbo ＋ 無音、⚠ 終わりに**開始前へ**（RX3-0104 → RX3-0170）。

## ★ここで守るもの（依頼者の Acceptance）

```text
1 聞き込み・街移動・補充を始めたら Turbo を頼む（★Lua の town_speed.lua へ turbo="1"）
2 その間は無音
3 終わったら**始めたときの速度・音**へ（⚠ 固定で 100%・Unmute にしない）
4 区間減速の間は 400%（★旧「街内の省力操作」の倍率。Lua が normal にした区間だけ効く）
5 設定は「聞き込みを高速実行」「街移動を高速実行」（★補充は街移動に従う / 旧設定の false は引き継ぐ）
6 到達不能で止まっても・ユーザー中断でも戻る
7 ログは変わったときだけ（[SPEED] / [MUTE]）
```

⚠⚠ **偽の FCEUX で見ます。**★本物の音は触りません（COM は環境に依存するため）。
"""
from __future__ import annotations

from dq3.ui import auto_env as AE
from dq3.ui import emu_speed as ES


class FakeMuteBackend:
    """★プロセスごとの消音を覚えているだけの偽物。"""

    available = True

    def __init__(self, muted=False, works=True) -> None:
        self.muted = muted
        self.works = works
        self.last_error = None
        self.calls: list[bool] = []

    def get_mute(self, pid):
        return self.muted if self.works else None

    def set_mute(self, pid, on):
        if not self.works:
            self.last_error = "⚠ 偽物なので失敗する"
            return False
        self.calls.append(bool(on))
        self.muted = bool(on)
        return True


def _env(*, speed_ok=True, mute_works=True, muted=False, enabled=True, prior=1.0):
    from dq3.ui.mute import MuteController

    sent: list[int] = []

    def sender(cmd):
        sent.append(cmd)
        return speed_ok

    speed = ES.EmulatorSpeedController(sender=sender, finder=lambda: 1 if speed_ok else 0)
    if prior != 1.0:
        speed.set_speed(prior)
        sent.clear()
    backend = FakeMuteBackend(muted=muted, works=mute_works)
    mute = MuteController(backend=backend, pid_finder=lambda: 4242)
    env = AE.AutoOperationEnvironment(speed, mute, enabled=lambda _what: enabled)
    return env, speed, backend, sent


# ----------------------------------------------------------------------
# ★1・2 … 始めたら Turbo を頼み、無音（★区間減速の 400% も用意する）
# ----------------------------------------------------------------------
def test_始めるとTurboを頼み無音で区間減速の倍率も用意する():
    env, speed, backend, sent = _env()
    env.begin("move")
    assert env.params() == {"turbo": "1", "source": "MOVE"}
    assert speed.current == 4.0, "★Lua が普通の速さにした区間は 400% で進む"
    assert sent == [ES.CMD_NORMAL] + [ES.CMD_UP] * 4
    assert backend.muted is True
    assert env.describe() == "高速実行 / 無音", "⚠ 倍率（35倍速・400%）は画面に出さない（依頼者 §22）"


def test_既定は区間減速400パーセントと無音():
    assert AE.DEFAULT_SPEED == 4.0 and AE.DEFAULT_MUTE is True
    assert 4.0 in ES.STEPS, "⚠ 400% は EmulatorSpeedController が出せる倍率でなければならない"


def test_終わるとTurboを頼まない():
    env, speed, backend, sent = _env()
    env.begin("hearing")
    assert env.params()["turbo"] == "1"
    env.end("hearing")
    assert env.params("hearing") == {"turbo": "0", "source": "HEARING"}


def test_高速実行を切った操作はTurboを頼まない():
    """★設定は操作ごと（依頼者 §20）。⚠ 切ってあれば速度も音も触らない。"""
    from dq3.ui.mute import MuteController

    speed = ES.EmulatorSpeedController(sender=lambda c: True, finder=lambda: 1)
    backend = FakeMuteBackend()
    env = AE.AutoOperationEnvironment(speed, MuteController(backend=backend, pid_finder=lambda: 1),
                                      enabled=lambda what: what == "hearing")
    env.begin("move")
    assert env.params() == {"turbo": "0", "source": "MOVE"}
    assert speed.current == 1.0 and backend.calls == []
    env.end("move")
    env.begin("hearing")
    assert env.params()["turbo"] == "1" and backend.muted is True
    env.end("hearing")


def test_ログは変わったときだけ出す():
    """★依頼者 §27 の形（`[SPEED] NORMAL -> TURBO source=HEARING` …）。"""
    lines = []
    env, speed, backend, sent = _env()
    env._log = lines.append
    env.begin("hearing")
    env.keep("hearing")                          # ⚠ 送り直しはログにしない（★毎回は出さない）
    env.end("hearing", "DONE")
    assert lines == ["[SPEED] NORMAL -> TURBO source=HEARING",
                     "[MUTE] OFF -> ON source=HEARING",
                     "[SPEED] TURBO -> NORMAL source=HEARING_DONE",
                     "[MUTE] ON -> OFF source=HEARING_DONE"], lines


def test_切ってあればログも出さない():
    lines = []
    env, speed, backend, sent = _env(enabled=False)
    env._log = lines.append
    env.begin("move")
    env.end("move", "CANCEL")
    assert lines == []


def test_人が先に消していたら音のログは出さない():
    lines = []
    env, speed, backend, sent = _env(muted=True)
    env._log = lines.append
    env.begin("move")
    env.end("move", "BATTLE")
    assert lines == ["[SPEED] NORMAL -> TURBO source=MOVE", "[SPEED] TURBO -> NORMAL source=MOVE_BATTLE"]


# ----------------------------------------------------------------------
# ★5 … 設定（⚠ 「聞き込みを高速実行」「街移動を高速実行」は RX3-0259 で外した）
# ----------------------------------------------------------------------
def test_高速実行の設定は無く_いつも高速():
    """★RX3-0259（2026-09-14 依頼者「いらないよね」）: 設定を読む口は無い / ★`enabled` を渡さなければいつも高速。"""
    assert not hasattr(AE, "fast_run_enabled") and not hasattr(AE, "SETTING_OF"), "⚠ 外した設定の口が残っている"
    env = AE.AutoOperationEnvironment()
    assert all(env._enabled(what) for what in AE.TOWN_ACTIONS)


# ----------------------------------------------------------------------
# ★3 … ⚠⚠ 戻すのは **100% ではなく開始前**
# ----------------------------------------------------------------------
def test_終わると開始前の速度へ戻る():
    """⚠⚠ ここが今回の肝。★150% で遊んでいた人を 100% に落とさない。"""
    env, speed, backend, sent = _env(prior=1.5)
    env.begin("move")
    assert speed.current == 4.0
    sent.clear()
    env.end("move")
    assert speed.current == 1.5, "⚠⚠ 開始前（150%）へ戻っていない"
    assert sent == [ES.CMD_NORMAL, ES.CMD_UP]


def test_終わると開始前の音へ戻る():
    env, speed, backend, sent = _env(muted=False)
    env.begin("hearing")
    assert backend.muted is True
    env.end("hearing")
    assert backend.muted is False
    assert backend.calls == [True, False]


def test_人が先に消していたら触らない():
    """⚠ 開始前から無音なら、★こちらは消しも戻しもしない（戻しすぎない）。"""
    env, speed, backend, sent = _env(muted=True)
    env.begin("hearing")
    assert backend.calls == [], "⚠ 既に無音なのに触った"
    env.end("hearing")
    assert backend.muted is True, "⚠⚠ 人が消していた音を勝手に戻した"


# ----------------------------------------------------------------------
# ★6・7 … ⚠ どの終わり方でも戻る
# ----------------------------------------------------------------------
def test_どの終わり方でも戻る():
    """⚠ 「正常完了」だけでは足りない（★到達不能・中断・例外）。"""
    for why in ("arrived", "unreachable", "user_stop", "exception"):
        env, speed, backend, _ = _env(prior=2.0)
        env.begin("move")
        env.end(why)                       # ★呼ばれ方は同じ 1 本
        assert speed.current == 2.0, why
        assert backend.muted is False, why


def test_入れ子でも開始前を見失わない():
    """⚠ `begin` が 2 回続いても、★覚えるのは最初の 1 回だけ。"""
    env, speed, backend, _ = _env(prior=1.5)
    env.begin("hearing")
    env.begin("move")                      # ⚠ ここで 400% を「開始前」にしてはいけない
    assert env.depth == 2
    env.end("move")
    assert speed.current == 4.0, "⚠ 内側で戻してしまった"
    env.end("hearing")
    assert speed.current == 1.5
    assert backend.muted is False


def test_二重に終わっても壊れない():
    env, speed, backend, _ = _env()
    env.begin("move")
    env.end("move")
    env.end("move")                        # ⚠ もう 1 度呼ばれても
    assert env.depth == 0 and speed.current == 1.0


# ----------------------------------------------------------------------
# ⚠ 失敗しても処理を止めない
# ----------------------------------------------------------------------
def test_音を消せなくても速度は変わる():
    env, speed, backend, _ = _env(mute_works=False)
    env.begin("hearing")
    assert speed.current == 4.0
    assert env.changed_mute is False
    assert any("音" in n for n in env.notes), env.notes
    env.end("hearing")
    assert speed.current == 1.0


def test_FCEUXが居なくても落ちない():
    env, speed, backend, _ = _env(speed_ok=False)
    env.begin("move")
    assert env.changed_speed is False
    env.end("move")                        # ⚠ 例外にならないこと


def test_切ってあれば何もしない():
    env, speed, backend, _ = _env(enabled=False)
    env.begin("move")
    assert speed.current == 1.0 and backend.calls == []
    env.end("move")


# ----------------------------------------------------------------------
# ★送り直し（⚠ Lua が速度を戻すことがある / RX3-0059）
# ----------------------------------------------------------------------
def test_送り直しは区間減速の400パーセントを送り直す():
    env, speed, backend, sent = _env()
    env.begin("move")
    sent.clear()
    env.keep("move")
    assert sent == [ES.CMD_NORMAL] + [ES.CMD_UP] * 4


def test_終わったあとは送り直さない():
    env, speed, backend, sent = _env()
    env.begin("move")
    env.end("move")
    sent.clear()
    env.keep("move")
    assert sent == [], "⚠⚠ 終わったのに 400% を送り直した"


# ----------------------------------------------------------------------
# ★★ 途中で開始前へ戻す（RX3-0241 / 施設の人の最初の台詞）
# ----------------------------------------------------------------------
def test_最初の台詞で開始前の速度と音へ戻し_終わりでは二重に戻さない():
    lines = []
    env, speed, backend, sent = _env(prior=1.5)
    env._log = lines.append
    env.begin("move")
    assert env.release("move") is True
    assert speed.current == 1.5 and backend.muted is False, "⚠⚠ 開始前（150%・音あり）へ戻っていない"
    assert env.active() and env.params() == {"turbo": "0", "source": "MOVE"}
    assert env.release("move") is False, "⚠ 2 回目も戻した"
    sent.clear()
    env.keep("move")
    assert sent == [], "⚠⚠ 戻したあとに区間減速の 400% を送り直した"
    env.end("move", "DONE")
    assert env.depth == 0 and speed.current == 1.5 and sent == []
    assert lines == ["[SPEED] NORMAL -> TURBO source=MOVE", "[MUTE] OFF -> ON source=MOVE",
                     "[SPEED] TURBO -> NORMAL source=MOVE_FIRST_MESSAGE",
                     "[MUTE] ON -> OFF source=MOVE_FIRST_MESSAGE"], lines


def test_入っていなければ途中で戻さない():
    env, speed, backend, sent = _env()
    assert env.release("move") is False
    env.begin("move")
    env.end("move")
    assert env.release("move") is False


def test_次の操作ではまた途中で戻せる():
    env, speed, backend, sent = _env(prior=1.5)
    env.begin("move")
    env.release("move")
    env.end("move")
    env.begin("move")
    assert speed.current == 4.0 and env.params()["turbo"] == "1", "⚠ 前の操作の「戻した」を持ち越した"
    assert env.release("move") is True and speed.current == 1.5
    env.end("move")


# ======================================================================
# ★省力操作の終わりに、ゲームへ操作を返す（RX3-0116 / 2026-09-08）
# ======================================================================
class _Focus:
    """★偽のフォーカス（⚠ 本物の Win32 は呼ばない）。"""

    def __init__(self, ok=True, blockers=(), boom=False):
        from dq3.ui.game_focus import GameFocus

        self.seen = []
        self.boom = boom

        def focus(title):
            if self.boom:
                raise RuntimeError("⚠ Windows が断った")
            self.seen.append(title)
            return ok

        self.inner = GameFocus(focus=focus, blockers=lambda: blockers)

    def restore(self):
        return self.inner.restore()

    @property
    def last_error(self):
        return self.inner.last_error


def _env_with_focus(**kw):
    from dq3.ui.mute import MuteController

    sent = []
    speed = ES.EmulatorSpeedController(sender=lambda c: (sent.append(c), True)[1],
                                       finder=lambda: 1)
    mute = MuteController(backend=FakeMuteBackend(), pid_finder=lambda: 42)
    focus = _Focus(**kw)
    env = AE.AutoOperationEnvironment(speed, mute, focus=focus)
    return env, focus, speed, sent


def test_終わりにゲームへ戻す():
    env, focus, _speed, _sent = _env_with_focus()
    env.begin("move")
    env.end("move")
    assert env.finish("move") is True
    assert focus.seen == ["FCEUX"]


def test_モーダルが出ていたら戻さない():
    """⚠ 人が読むべき窓が残っているときは、★そのまま。"""
    env, focus, _speed, _sent = _env_with_focus(blockers=("確認",))
    env.begin("move")
    env.end("move")
    assert env.finish("move") is False
    assert focus.seen == [], "⚠⚠ モーダルが出ているのに前面を奪った"
    assert "確認" in (focus.last_error or "")


def test_FCEUXが居なくても落ちない():
    env, focus, _speed, _sent = _env_with_focus(ok=False)
    env.begin("hearing")
    env.end("hearing")
    assert env.finish("hearing") is False        # ⚠ 例外にならないこと
    assert any("ゲームへ戻せません" in n for n in env.notes), env.notes


def test_例外でも落ちない():
    env, focus, _speed, _sent = _env_with_focus(boom=True)
    env.begin("move")
    env.end("move")
    assert env.finish("move") is False


def test_速度とMuteを戻したあとに戻す():
    """⚠⚠ **順番**（★速度・Mute の復元 → サマリー → フォーカス）。"""
    order = []
    from dq3.ui.mute import MuteController

    class _Speed(ES.EmulatorSpeedController):
        def set_speed(self, factor):
            order.append("speed:%s" % factor)
            return super().set_speed(factor)

    speed = _Speed(sender=lambda c: True, finder=lambda: 1)
    mute = MuteController(backend=FakeMuteBackend(), pid_finder=lambda: 42)

    class _F:
        last_error = None

        def restore(self):
            order.append("focus")
            return True

    env = AE.AutoOperationEnvironment(speed, mute, focus=_F())
    env.begin("move")
    order.clear()
    env.end("move")
    order.append("summary")
    env.finish("move")
    assert order[-1] == "focus", order
    assert order.index("speed:1.0") < order.index("summary") < order.index("focus"), order


def test_focusが無ければ何もしない():
    env, _speed, _backend, _sent = _env()
    env.begin("move")
    env.end("move")
    assert env.finish("move") is False           # ⚠ 例外にならないこと


def test_戻してはいけない窓は断る():
    """⚠⚠ 題名の**部分一致**で探すので、★RetroUX 自身を前面にしない。"""
    from dq3.ui.game_focus import FORBIDDEN, GameFocus

    for bad in FORBIDDEN:
        g = GameFocus(focus=lambda t: True, title=bad)
        assert g.restore() is False, bad
        assert "戻してはいけない" in (g.last_error or "")


def test_窓を数えられなくても止めない():
    """⚠ 数えられない＝「モーダルがある」ではない（★止めない）。"""
    from dq3.ui.game_focus import GameFocus

    def boom():
        raise RuntimeError("⚠ 数えられない")

    g = GameFocus(focus=lambda t: True, blockers=boom)
    assert g.restore() is True
