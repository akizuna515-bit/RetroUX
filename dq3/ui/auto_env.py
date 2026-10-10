"""街内で RetroUX が代わりに動かす間の実行環境（RX3-0104 → RX3-0170 / 2026-09-11）。

## ★決まったこと（2026-09-11 依頼者「聞き込み・街移動 Auto Turbo化」）

```text
聞き込み / 街移動 / 補充   Turbo（FCEUX の Turbo / 約 35 倍〜）＋ 無音
設定                       管理画面の「聞き込みを高速実行」「街移動を高速実行」（★既定 ON）
                           ⚠ 補充は街移動に従う（★店まで歩いて買うだけ）
対象外                     通常の手動プレイ / 戦闘 AI（★右画面の「タ」は Auto 中の戦闘の速さ / 別物）
```

⚠⚠ 以前（RX3-0104）は **400% ＋ 無音**でした。★400% は「区間減速」の倍率として残します
（`town_turbo.slow_phases` に書いた局面だけ Lua が普通の速さにし、その間を 400% で進める）。

## ★Turbo は Lua が持つ

★Turbo の入り切りは `WM_COMMAND` では絶対指定できない（切り替えしか無い / `docs/research/260826_fceux-speed-control.md`）。
→ ★街の頼み（navigate / restock / use_item）に `turbo="1"` を添え、Lua の `town_speed.lua` が入れる。
  ★終わりの `town_end` で Lua が切る（⚠ 遭遇・セーブ・人の B では Lua が**先に**切る）。
★ここ（Python）が持つのは **無音**と、**開始前の倍率**（管理画面の 2 倍速など）だけ。

## ⚠⚠ 固定で 100% ・ Unmute へ戻してはいけません

★`begin()` の時点の倍率と消音を**覚えてから**変え、`end()` でそこへ戻します。
⚠ Lua の `emu.speedmode("normal")` は FCEUX を 100% に戻すので、★画面は `speed_normal_count` が
増えるたびに `EmulatorSpeedController.reassert()` で倍率を送り直します（`main_window._note_turbo`）。

## ⚠ 戻し損ねる道を作らない

```text
★正常完了 / 到達不能 / 経路逸脱 / NPC が動いて失敗 / ユーザー中断 / 例外 / 戦闘 / 別の安全停止
```

→ ★`TownNavController._finish()` が**唯一の出口**なので、そこから `end()` を呼びます。
⚠ さらに保険として `atexit`（`emu_speed` / `mute` がそれぞれ持つ）と、Lua 側の見張り（`lease_s`）が効きます。

## ★入れ子で二重に覚えない

⚠ `begin()` が 2 回続いても、★覚えるのは**最初の 1 回だけ**です。

## ★★ 途中で先に戻す（RX3-0241 / 2026-09-13）

★依頼者「施設の人の最初のメッセージが発生した瞬間に高速化を解除する」。★街移動が最初の台詞を見たら、
`release()` で速度・音を**開始前へ**戻します（⚠ 深さは変えない。★終わりの `end()` は二重に戻さない）。
★Lua は同じフレームで Turbo を切っています（`town_speed.first_message`）。
"""
from __future__ import annotations

#: ★区間減速の間の倍率（⚠ Turbo ではない区間 / 旧「街内の省力操作」の 400%）
DEFAULT_SPEED = 4.0
DEFAULT_MUTE = True

#: ★この環境を当てる操作（⚠ 戦闘 AI は入れない / 別ポリシー）
TOWN_ACTIONS = ("hearing", "move", "restock")

#: ⚠ 「聞き込みを高速実行」「街移動を高速実行」の設定は RX3-0259（2026-09-14 依頼者「いらないよね」）で外した。
#:   ★聞き込み・街移動・補充はいつも高速（★既定がもともと入り / 依頼者の保存も入り）。
#:   ⚠ `work/dq3-ui-settings.json` に残っている `automation.*` / `admin.speed_on_nav` はもう読まない。

#: ★ログと Lua に渡す名前
SOURCE_OF = {"hearing": "HEARING", "move": "MOVE", "restock": "RESTOCK"}


#: ★ログの置き場（⚠ Technical Log / Lua の `dev.log` と同じ `dq3-probe/`）
LOG_NAME = "town_speed.log"


def town_speed_log(line: str) -> None:
    """★状態が変わったときの 1 行を足す（依頼者 §27 / ⚠ 毎フレームは書かない）。⚠ 書けなくても続ける。"""
    import time

    from .. import paths

    try:
        path = paths.work("runtime", "dq3-probe", LOG_NAME)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as fh:
            fh.write("%s %s\n" % (time.strftime("%H:%M:%S"), line))
    except OSError:
        pass


class AutoOperationEnvironment:
    """★街内の省力操作の間だけ Turbo ＋ 無音にし、⚠ 終わりに**開始前へ**戻す。

    `speed`   … `EmulatorSpeedController`（★区間減速の倍率と、開始前の倍率 / ⚠ 無ければ触らない）
    `mute`    … `MuteController`（⚠ 無ければ音は触らない）
    `enabled` … ★その操作を高速実行するかを返す関数 `enabled(what)`（★渡さなければいつも高速 / ⚠ 管理画面のチェックは RX3-0259 で外した）
    `log`     … ★1 行を受け取る関数（★状態が変わったときだけ呼ぶ / 依頼者 §27）
    """

    def __init__(self, speed=None, mute=None, *, enabled=None, focus=None,
                 factor: float = DEFAULT_SPEED, mute_on: bool = DEFAULT_MUTE, log=None) -> None:
        self.speed = speed
        self.mute = mute
        #: ★終わったらゲームへ操作を返す（RX3-0116）。⚠ 無ければ何もしない
        self.focus = focus
        self._enabled = enabled if enabled is not None else (lambda _what: True)
        self._log = log
        self.factor = factor
        self.mute_on = mute_on
        #: ★入れ子の深さ（⚠ 0 のときだけ覚える / 戻す）
        self.depth = 0
        #: ★いまの操作と、Turbo を頼んでいるか（⚠ 高速実行を切ってあれば False）
        self.what: str | None = None
        self.turbo = False
        #: ★開始前の状態（⚠ **覚えられなかったら None**。★False と混ぜない）
        self.prior_speed: float | None = None
        self.prior_mute: bool | None = None
        #: ★こちらが実際に変えたか（⚠ 変えていないものは戻さない）
        self.changed_speed = False
        self.changed_mute = False
        #: ★途中で開始前へ戻したか（RX3-0241 / ⚠ 1 回の操作で 1 度だけ）
        self.released = False
        self.notes: list[str] = []

    # ------------------------------------------------------------------
    # ★入口 / 出口
    # ------------------------------------------------------------------
    def active(self) -> bool:
        return self.depth > 0

    def begin(self, what: str = "") -> None:
        """★Turbo を頼み、無音にする（⚠ **先に開始前を覚える**）。"""
        self.depth += 1
        if self.depth > 1:
            return                              # ⚠ 入れ子。★開始前は最初のものを保つ
        self.what = what
        self.released = False
        self.turbo = self._on(what)
        if not self.turbo:
            return
        self._remember()
        self._apply(self.source(what))

    def params(self, what: str | None = None) -> dict:
        """★街の頼みに添える項目（★Lua の `town_speed.lua` が読む）。"""
        what = what or self.what or ""
        return {"turbo": "1" if (self.active() and self.turbo) else "0",
                "source": self.source(what)}

    @staticmethod
    def source(what: str | None) -> str:
        return SOURCE_OF.get(what or "", "TOWN")

    def keep(self, what: str = "") -> None:
        """★区間減速の倍率を送り直す（⚠ Turbo の間は効かないが害も無い / 音は状態なので送らない）。"""
        if not self.active() or not self.changed_speed or self.speed is None:
            return
        try:
            self.speed.reassert()
        except Exception as err:                             # noqa: BLE001
            self._note("⚠ 速度を送り直せません: %s" % err)

    def release(self, what: str = "", why: str = "FIRST_MESSAGE") -> bool:
        """★★ 操作の途中で、速度・Mute を**開始前へ**戻す（RX3-0241 / 施設の人の最初の台詞）。

        ⚠ 深さは変えません（★終わりの `end()` はそのまま呼ばれ、二重には戻しません）。
        ★以後は区間減速の倍率も送り直さず（`keep`）、頼みにも Turbo を添えません（`params`）。
        戻り値: 戻したか（⚠ 入っていない・戻し済みなら False）。
        """
        if not self.active() or self.released:
            return False
        self.released = True
        source = "%s_%s" % (self.source(what or self.what), why)
        if self.turbo:
            self._line("[SPEED] TURBO -> NORMAL source=%s" % source)
        self._restore(source)
        self.turbo = False
        return True

    def end(self, what: str = "", why: str = "DONE") -> None:
        """⚠⚠ **開始前へ戻す**（★固定で 100% ・ Unmute にしない）。

        ⚠ どの終わり方でも呼ばれます。★深さが 0 になったときだけ戻します。
        ★Lua の Turbo は呼ぶ側（`TownNavController._finish`）が `town_end` で切ります。

        ⚠⚠ **フォーカスはここでは戻しません。**★`finish()` が、
        User Action Summary を出した**あと**に戻します（RX3-0116 の順番）。
        """
        if self.depth > 0:
            self.depth -= 1
        if self.depth > 0:
            return
        source = "%s_%s" % (self.source(what or self.what), why)
        if self.turbo:
            self._line("[SPEED] TURBO -> NORMAL source=%s" % source)
        self._restore(source)
        self.turbo = False
        self.released = False
        self.what = None

    def finish(self, what: str = "") -> bool:
        """★★ 省力操作の**いちばん最後**（RX3-0116）。

        ```text
        end()（速度・Mute を戻す） → User Action Summary → ★ここ（フォーカス）
        ```

        ⚠ 呼ぶ側が「サマリーを出したあと」に呼びます。
        ⚠ 戻せなくても `False` を返すだけ（★例外にしない）。
        """
        if self.focus is None:
            return False
        try:
            got = bool(self.focus.restore())
        except Exception as err:                             # noqa: BLE001
            self._note("⚠ ゲームへ戻せません: %s" % err)
            return False
        if not got:
            self._note("⚠ ゲームへ戻せません: %s"
                       % (getattr(self.focus, "last_error", None) or "?"))
        return got

    # ------------------------------------------------------------------
    # ★中身（⚠ どれも例外にしない。★音は「あると邪魔」なだけ）
    # ------------------------------------------------------------------
    def _on(self, what: str) -> bool:
        try:
            return bool(self._enabled(what))
        except Exception:                                    # noqa: BLE001
            return False

    def _note(self, text: str) -> None:
        self.notes.append(text)
        del self.notes[:-8]                     # ⚠ 溜めない（★直近だけ見れば足りる）

    def line(self, text: str) -> None:
        """★ログへ 1 行（★聞き込みの START / DONE も同じ置き場へ）。⚠ 落ちても続ける。"""
        self._line(text)

    def _line(self, text: str) -> None:
        if self._log is None:
            return
        try:
            self._log(text)
        except Exception:                                    # noqa: BLE001
            pass

    def _remember(self) -> None:
        self.prior_speed = None
        self.prior_mute = None
        if self.speed is not None:
            got = getattr(self.speed, "current", None)
            if isinstance(got, (int, float)):
                self.prior_speed = float(got)
        if self.mute is not None:
            try:
                self.prior_mute = self.mute.get()
            except Exception as err:                         # noqa: BLE001
                self._note("⚠ 音の状態を読めません: %s" % err)

    def _apply(self, source: str) -> None:
        self._line("[SPEED] NORMAL -> TURBO source=%s" % source)
        if self.speed is not None:
            try:
                # ★区間減速の倍率（⚠ Turbo の間は効かない。★Lua が normal にした区間だけ効く）
                self.changed_speed = bool(self.speed.set_speed(self.factor))
                # ★終わるまで戻すな（⚠ 管理画面を閉じても）
                self.speed.hold = self.changed_speed
                if not self.changed_speed:
                    self._note("⚠ 速度を変えられません: %s"
                               % getattr(self.speed, "last_error", "?"))
            except Exception as err:                         # noqa: BLE001
                self.changed_speed = False
                self._note("⚠ 速度を変えられません: %s" % err)
        if self.mute is not None and self.mute_on:
            # ⚠ 既に人が消していたら、★こちらは何もしない（戻すときに戻しすぎない / 依頼者 §10）
            if self.prior_mute is True:
                self.changed_mute = False
            else:
                try:
                    self.changed_mute = bool(self.mute.set(True))
                    if self.changed_mute:
                        self._line("[MUTE] OFF -> ON source=%s" % source)
                    else:
                        self._note("⚠ 音を消せません: %s"
                                   % getattr(self.mute, "last_error", "?"))
                except Exception as err:                     # noqa: BLE001
                    self.changed_mute = False
                    self._note("⚠ 音を消せません: %s" % err)

    def _restore(self, source: str) -> None:
        if self.speed is not None:
            try:
                self.speed.hold = False
                if self.changed_speed:
                    # ⚠⚠ 100% ではなく**開始前**へ（★覚えられていなければ 100%）
                    back = self.prior_speed if self.prior_speed is not None else 1.0
                    self.speed.set_speed(back)
            except Exception as err:                         # noqa: BLE001
                self._note("⚠ 速度を戻せません: %s" % err)
        if self.mute is not None and self.changed_mute:
            try:
                # ⚠ 開始前が分からないなら「消していない」へ（★こちらが消したので）
                self.mute.set(bool(self.prior_mute))
                self._line("[MUTE] ON -> OFF source=%s" % source)
            except Exception as err:                         # noqa: BLE001
                self._note("⚠ 音を戻せません: %s" % err)
        self.changed_speed = False
        self.changed_mute = False
        self.prior_speed = None
        self.prior_mute = None

    # ------------------------------------------------------------------
    # ★画面に出す用（⚠ 数字ではなく、人の言葉で / 依頼者 §22「35倍速」は出さない）
    # ------------------------------------------------------------------
    def describe(self) -> str:
        if not self.active():
            return ""
        bits = []
        if self.turbo:
            bits.append("高速実行")
        if self.changed_mute:
            bits.append("無音")
        return " / ".join(bits)


__all__ = ["AutoOperationEnvironment", "DEFAULT_SPEED", "DEFAULT_MUTE", "TOWN_ACTIONS", "town_speed_log",
           "SOURCE_OF"]
