"""アクションの入口を1つにする（指示書 §6）。

★★ **「何を押したか」と「何をするか」を切り離す。** ★★

    GUIボタン ─┐
    キーボード ─┼→ ActionDispatcher → 実際の処理
    ゲームパッド ┘      （将来）

⚠ 指示書 §6.2 が禁じている形:

    GUIボタン    → 独自処理
    キーボード   → 別処理
    Luaホットキー → 別処理

  すべて**同じアクション名**へ変換する。

## フォーカスの後始末（指示書 §6.3）

  ⚠⚠ **各ボタンに Windows API 呼び出しを書かない。**
    アクションの**属性**として持つ。書き忘れが起きない形にする。

  | 属性 | 意味 |
  | --- | --- |
  | `restore_emulator_focus=True` | 実行後にゲームへ操作を返す（通常プレイ中の操作） |
  | `restore_emulator_focus=False` | RetroUX 側に留まる（設定・編集・入力） |

  ★見分け方: **そのあとキーボードを使うのはどちらか**。
"""

from __future__ import annotations

from .models import ACTION_BY_NAME, ACTIONS, ActionResult


class ActionDispatcher:
    """アクションの実装を集め、名前で呼び出す。

    ⚠ 実装が登録されていないアクションを呼んでも**落とさない**。
      理由を返して呼び出し側が画面に出せるようにする
      （キーバインド設定に古い名前が残っていても遊べるようにするため）。
    """

    def __init__(self, focus_emulator=None, logger=None) -> None:
        #: {name: 呼び出せるもの}
        self._handlers: dict = {}
        #: ゲームへフォーカスを返す処理（無ければ何もしない）
        self._focus_emulator = focus_emulator
        self._log = logger
        #: 実行した記録（診断・テスト用）。★最後の1件だけ
        self.last_action: str | None = None
        self.last_result: ActionResult | None = None

    def register(self, name: str, handler) -> None:
        """アクションに実装を結び付ける。

        ⚠ 知らない名前は**受け付けない**。受け付けると、
          呼ばれないアクションが静かに増えて誰も気づかない。
        """
        if name not in ACTION_BY_NAME:
            raise KeyError(f"知らないアクションです: {name}")
        self._handlers[name] = handler

    def has(self, name: str) -> bool:
        return name in self._handlers

    @property
    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def missing(self) -> tuple[str, ...]:
        """実装が登録されていないアクション。★**実装済みのものだけ**数える。"""
        return tuple(sorted(
            a.name for a in ACTIONS
            if a.implemented and a.name not in self._handlers))

    def dispatch(self, name: str) -> ActionResult:
        """アクションを実行する。

        ★★ 手順は必ずこの順（指示書 §6.3）★★

            アクション実行 → 状態反映 → ゲームへフォーカス

          ⚠ フォーカスを先に返すと、**処理中のキー入力がゲームへ届く**。
        """
        spec = ACTION_BY_NAME.get(name)
        if spec is None:
            return self._done(name, ActionResult.fail(
                f"知らないアクションです: {name}"), None)
        handler = self._handlers.get(name)
        if handler is None:
            return self._done(name, ActionResult.fail(
                f"『{spec.label}』はこの版では使えません"), spec)

        try:
            outcome = handler()
        except Exception as exc:                       # noqa: BLE001
            # ⚠ 1つのアクションが落ちても画面ごと止めない。
            #   ★ただし黙らない（何もしなかったように見えるのが最悪）。
            if self._log is not None:
                self._log.warning(
                    "component=action_dispatcher action=%s result=error"
                    " reason=%s", name, exc)
            return self._done(name, ActionResult.fail(
                f"『{spec.label}』を実行できませんでした: {exc}"), spec)

        # ★実装が `ActionResult` を返さない場合は「成功」とみなす。
        #   既存の処理をそのまま繋げられるようにするため。
        result = outcome if isinstance(outcome, ActionResult) \
            else ActionResult.ok()
        return self._done(name, result, spec)

    def _done(self, name, result: ActionResult, spec) -> ActionResult:
        self.last_action = name
        self.last_result = result

        # ★属性に従ってフォーカスを返す。**ここだけ**が前面化を呼ぶ。
        #   ⚠ 失敗したときは戻さない（エラーを読ませる / 指示書 §6.3）。
        wants = result.restore_focus
        if wants is None:
            wants = bool(spec is not None and spec.restore_emulator_focus
                         and result.success)
        if wants and self._focus_emulator is not None:
            try:
                self._focus_emulator()
            except Exception as exc:                   # noqa: BLE001
                # ⚠ 前面化は Windows に拒否されることがある。
                #   アクション自体は成功しているので**失敗にしない**。
                if self._log is not None:
                    self._log.debug("ゲーム画面へ戻せませんでした: %s", exc)

        if self._log is not None and spec is not None:
            self._log.debug(
                "component=action_dispatcher action=%s result=%s",
                name, "success" if result.success else "failure")
        return result
