"""DQ3 の画面を出す（RX3-0019 / 2026-08-29）。

★DQ2 の `retroux/gui.py` と同じ作法にします。
⚠ Qt の import は**実際に画面を出すときだけ**（検査に Qt を要求しないため）。

使い方:
    PYTHONUTF8=1 python -m dq3.ui.app
    PYTHONUTF8=1 python -m dq3.ui.app --no-map --interval 500

⚠⚠ **DQ3 は dev-only です。** 公開しません（`RX3-0011`）。
"""

from __future__ import annotations

import argparse
import sys

from .view_model import Dq3ViewModel


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="RetroUX DQ3 の画面（開発中）")
    ap.add_argument("--state", help="⚠ Lua が書く state.json（★既定は work/runtime/state.json）")
    ap.add_argument("--knowledge", help="★勇者が得たことの置き場")
    ap.add_argument("--interval", type=int, default=500,
                    help="見直す間隔 ms（★既定 500。DQ2 と同じ）")
    ap.add_argument("--memo-limit", type=int, default=3,
                    help="勇者メモの表示件数（★指示書 §7 の既定は 3）")
    ap.add_argument("--no-map", action="store_true",
                    help="⚠ 地図の窓を開かない")
    ap.add_argument("--check", action="store_true",
                    help="★画面を出さずに、読めるかだけ見る")
    ap.add_argument("--no-migrate-offer", action="store_true",
                    help="⚠ 初回起動の「旧版から引き継ぎますか」を出さない"
                         "（★撮影・検査から使います）")
    ap.add_argument("--migrate-offer-only", action="store_true",
                    help="★引き継ぎの誘いだけ出して終わる（⚠ launcher 用 / "
                         "結果は終了コードで返す = `dq3.migrate` の EXIT_*）")
    return ap


def _migrate_offer_only() -> int:
    """★★ 引き継ぎの誘い**だけ**を出して、結末を終了コードで返す（RX3-0481）★★

    ## ⚠⚠ なぜ別の入口が要るのか

      ★誘いは `dq3.ui.app` の中にありましたが、⚠ `start-dq3.ps1` は
      **ROM / FCEUX が見つからないと `exit 1`** するので、
      ⚠⚠ 設定の無い環境では**ここまで来ませんでした**（★2026-10-02 実機で判明）。
      → ★launcher が設定チェックの**前に**この入口を叩きます。

    ## ⚠⚠ 利用者データを 1 つも作らずに抜けます

      ★`Dq3ViewModel` を**作りません**（⚠ 作ると設定や記録の初期値が出来て、
      ★そのあと引き継いでも「既にある」で飛ばされます / 2026-10-02 実測）。
      ⚠ 残るのは記録（`work/dq3-log/`）と、決めたときの覚えだけです（★どちらも derived）。

    ## ★誘う必要が無ければ Qt を触りません

      ⚠ `should_offer()` が偽なら **`QApplication` も作らず** 0 を返します
      （★通常起動を 1 ミリ秒も遅くしないため）。
    """
    from dq3 import migrate as MG

    if not MG.should_offer():
        print("★引き継ぎの誘い: 出しません（⚠ もう決めている / 遊んだ証拠がある）",
              flush=True)
        return MG.EXIT_NOT_NEEDED

    # ⚠ ここで初めて Qt を触る（★`--check` と同じ作法）
    from PySide6.QtWidgets import QApplication

    from .migrate_dialog import exit_code_for, offer_if_first_run

    # ★★ ⚠⚠ **窓を出す前に 1 行出して、必ず flush する**（RX3-0481）★★
    #
    #   ⚠ `flush=True` が無いと、★Python は画面でないときに溜め込むので、
    #     **窓が開いているあいだ 1 文字も出ません**（⚠ 2026-10-02 実測）。
    #   ★launcher の記録に「ここまで来た」が残らないと、
    #     ⚠⚠ 「誘いに到達したのか / 設定チェックで落ちたのか」が分かりません
    #     （★まさにそれを 1 日かけて調べました）。
    print("★引き継ぎの誘い: 出します（⚠ 設定チェックより前 / RX3-0481）", flush=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    dlg = offer_if_first_run()
    code = exit_code_for(dlg)
    print("★引き継ぎの誘い: 終了コード %d" % code, flush=True)
    del app
    return code


def _use_fast_tooltips(app) -> None:
    """★説明が出るまでの待ちを短くする（RX3-0329 / 2026-09-21 依頼者「ツールチップはだしてほしい」）。

    ⚠⚠ 既定は **700ms** です。★アイコンだけのボタンでは、これが「出ない」と見えます。
    ★DQ2 側（`retroux/gui.py`）が同じことを 250ms でやっているので、⚠ 値も揃えます。
    """
    from PySide6.QtWidgets import QProxyStyle, QStyle

    class _FastTooltipStyle(QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, returnData=None):  # noqa: N802
            if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
                return 250                      # ★既定 ~700ms → 250ms
            return super().styleHint(hint, option, widget, returnData)

    app.setStyle(_FastTooltipStyle(app.style()))


def _show_tooltips_when_inactive(app) -> object:
    """★選んでいない窓でも、ボタンの説明を出す（RX3-0345 / 2026-09-21 依頼者）。

    ⚠⚠ Qt は既定で、**選ばれていない窓のツールチップを出しません**。
    → ★RetroUX は窓が何枚も並び、⚠ ふだん選ばれているのは **FCEUX** なので、
      説明が 1 つも出ませんでした（★依頼者「そこの窓がアクティブでないと効かない」）。

    ★直し方は `WA_AlwaysShowToolTips` ですが、⚠⚠ **立てる先はボタンではなく窓**です
    （★Qt の文書: "it must be set on the window"）。⚠ ボタンに立てても効きません。

    ⚠ 窓は何枚もあり、これからも増えるので、★**出てきた窓に自動で立てます**
      （⚠ 窓ごとに書き足す形にしない / 本 WI の Acceptance）。

    戻り値: ★入れた見張り（⚠ 捨てられないように呼ぶ側が持つ）。
    """
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QWidget

    attr = Qt.WidgetAttribute.WA_AlwaysShowToolTips

    def mark(obj) -> None:
        # ⚠ `isWindow()` が本物の窓（★子の部品に立てても意味が無い）
        if isinstance(obj, QWidget) and obj.isWindow():
            obj.setAttribute(attr, True)

    class _AlwaysShowToolTips(QObject):
        def eventFilter(self, obj, event):  # noqa: N802  ★Qt の名前
            # ⚠ ここは全部の出来事が通ります。★型を先に見て、すぐ抜けます
            if event.type() == QEvent.Type.Show:
                mark(obj)
            return False

    watcher = _AlwaysShowToolTips(app)
    app.installEventFilter(watcher)
    # ★もう出ている窓にも立てる（⚠ 見張りを入れる前に作られた窓）
    for w in app.topLevelWidgets():
        mark(w)
    return watcher


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # ★★ 版と断面を 1 行目に残す（RX3-0464 / 2026-09-29）★★
    #
    #   ⚠⚠ これが無いと、実機で見てもらった報告が**どの断面のものか**
    #     後から決められません（★2026-09-29 まで DQ3 には手段が 0 でした）。
    #   ⚠ `pythonw` 起動では標準出力が捨てられるので、★記録にも書きます。
    from dq3 import startup as ST

    line = ST.log_startup(extra=("check" if args.check else "gui"))
    print(line)

    # ★★ ⚠⚠ **知らせるだけ**のこと（RX3-0472 / 2026-10-01）★★
    #
    #   ① 前の引き継ぎが途中で終わっている（`work/.migration-incomplete`）
    #   ② カスタマイズ版を使っていて、見本（標準版）が更新されている
    #
    #   ⚠ どちらも自動で直しません（★自動 merge をしない方針 / `D-38`）。
    for notice in ST.log_notices():
        print(notice)

    # ★★ ⚠⚠ **利用者データを作る前に**引き継ぎの誘いだけを出す道（RX3-0481）★★
    #   ⚠ `Dq3ViewModel` より前でなければいけません（★下の註）。
    if args.migrate_offer_only:
        return _migrate_offer_only()

    # ★★ 製品間排他（RX3-0505 / 依頼者 2026-10-03「DQ2 / DQ3 の同時起動はサポートしない」）★★
    #   ★DQ2 が動いていたら、理由を出して**何も始めずに**終わる（⚠ 材料が読めるかだけの --check は対象外）。
    #   ★握った Mutex はプロセスの終わりまで持つ（⚠ 解放は OS 任せ = 異常終了でも残骸にならない）。
    product = None
    if not args.check:
        from dq3 import product_lock

        product = product_lock.guard("DQ3")
        if product is None:
            return 1

    vm = Dq3ViewModel(state_path=args.state, knowledge_path=args.knowledge)

    if args.check:
        # ★Qt を使わずに、材料が読めるかだけ確かめる
        state = vm.state()
        print("state.json   :", vm.state_path)
        print("  frame      :", state.frame)
        print("  戦闘中     :", state.in_battle)
        print("  パーティ   :", vm.party_names() or "⚠ 届いていません")
        print("勇者メモ     :", len(vm.memos), "件")
        print("訪れた地点   :", len(vm.known_locations()), "件")
        if not vm.memos:
            print("⚠ メモがまだありません（★RX3-0016 が貯め始めてから増えます）")
        return 0

    # ⚠ ここで初めて Qt を触る
    from PySide6.QtWidgets import QApplication

    from .main_window import Dq3MainWindow

    app = QApplication(sys.argv[:1])
    # ★説明を早く出す（RX3-0329 / ⚠ 既定は 700ms で「出ない」と見える）。
    #   ★DQ2 側（`retroux/gui.py`）と同じ 250ms に揃えます。
    _use_fast_tooltips(app)
    # ★選んでいない窓でも説明を出す（RX3-0345 / ⚠ ふだん選ばれているのは FCEUX）
    app._retroux_tooltip_watcher = _show_tooltips_when_inactive(app)

    # ★★ ⚠⚠ **窓を作る前に**引き継ぎを誘う（RX3-0471 / 2026-10-01）★★
    #
    #   ⚠ 順番がここでないといけません。★実測（2026-10-01）:
    #     窓を作ると `work/generated/*.lua`（derived）が出来るだけですが、
    #     ⚠⚠ **閉じると `work/dq3-window-state.json`（user）が出来ます**。
    #     → ★user data が出来たあとに引き継ぐと、⚠ そのぶんが「既にある」で
    #       飛ばされます（★消しはしませんが、引き継げません）。
    #   ⚠ 誘いが出るのは「まだ決めていない ＋ 遊んだ証拠が無い」ときだけです
    #     （`migrate.should_offer()`）。★断ったら次からは出ません。
    #   ★あとから呼ぶ道は管理画面の「旧版からデータを引き継ぐ」です（⚠ いつでも）。
    if not args.no_migrate_offer:
        from .migrate_dialog import offer_if_first_run

        offer_if_first_run()

    window = Dq3MainWindow(vm, interval_ms=args.interval,
                           memo_limit=args.memo_limit,
                           show_map=not args.no_map)
    window.show()
    # ★コントローラー（RX3-0486）。⚠ ここ（本物の起動）だけで始める
    #   （★検査で窓を作っても読み取りは始まらない = 実機のパッドでマウスが動かない）
    window.start_gamepad()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
