"""修飾キー付きの割り当てを、画面側の受け口にする（RX-0102 / 2026-08-23）。

★★ **キーを拾う道は2本ある。** ★★

    単独キー（`A` `T` `G` …）   -> Lua が拾う（FCEUX が前面のため）
    修飾キー付き（`Ctrl+K` …）  -> ここ（画面が前面のとき）

⚠⚠ **この2本目が長らく無かった。**
  `keybindings.write_lua` は修飾キー付きを Lua へ**渡しません**
  （FCEUX の `input.get()` が修飾キーを別項目で返すため、単独キーと同じには
  扱えない）。そこには「画面にフォーカスがあるときに使う」と書いてあるのに、
  ★その受け口が作られておらず、`Ctrl+Shift+R` / `Ctrl+K` / `Ctrl+Shift+L` は
  **どこにも届いていませんでした**（公開 README は効くと案内していた）。

  ⚠ 検査は「アクションが登録されているか」までしか見ていなかったので、
    **押しても何も起きない状態が緑のまま**でした。

★`ApplicationShortcut` にします。地図や図鑑の窓を触っているときに
  効かないと、「たまに効く」といういちばん困る形になります。
"""

from __future__ import annotations


def gui_pairs(bindings, registered) -> list:
    """画面側で受けるべき `(アクション名, キー)` の一覧。

    ★入れるもの: **修飾キー付き**で、かつ**実装が登録されている**もの。
    ⚠ 単独キーは入れない（Lua の担当。両方で拾うと二重に実行される）。

    @param bindings `keybindings.Keybindings`
    @param registered 実装が登録されているアクション名（`in` が使えるもの）
    """
    pairs = []
    for name in sorted(bindings.keys):
        if name not in registered:
            # ⚠ 実装が無いものに受け口だけ作らない。★押して無反応が一番困る
            continue
        for key in bindings.keys_for(name):
            if "+" in key:
                pairs.append((name, key))
    return pairs


def install(widget, bindings, registered, run, logger=None) -> list:
    """`widget` に受け口を作る。戻り値は作った `QShortcut` の一覧。

    ★呼ぶたびに作り直す前提（割り当てを変えたら呼び直す）。
      ⚠ 古いものは呼び出し側で捨てること（`clear` を使う）。

    @param run `run(アクション名)` を実行するもの
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut

    made = []
    for name, key in gui_pairs(bindings, registered):
        sequence = QKeySequence(key)
        # ⚠⚠ `isEmpty()` では判断できない（2026-08-23 に実測）。
        #   `QKeySequence("Ctrl+ほげ")` も `isEmpty() == False` / `count() == 1`
        #   を返し、★**押しても絶対に鳴らない受け口**ができてしまう。
        #   → **文字列に戻せるか**で見る（戻せないものは Qt も読めていない）。
        if not sequence.toString():
            # ⚠ 読めない表記は飛ばすが**黙らない**
            if logger is not None:
                logger.warning(
                    "ショートカットを作れません（%s の %s）", name, key)
            continue
        shortcut = QShortcut(sequence, widget)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(lambda n=name: run(n))
        made.append(shortcut)
    return made


def clear(shortcuts) -> None:
    """作った受け口を捨てる。★作り直す前に必ず呼ぶ。

    ⚠ 捨てないと同じキーが二重に登録され、Qt が
      「ambiguous shortcut」として**どちらも呼ばなくなる**。
    """
    for shortcut in shortcuts or ():
        try:
            shortcut.setParent(None)
        except Exception:                              # noqa: BLE001
            pass
