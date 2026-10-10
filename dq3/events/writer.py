"""Event Writer — ★書く側を 1 か所に寄せる（RX3-0154 / 2026-09-10）。

```text
各機能  ──►  EventWriter  ──┬──► Product Log      ★製品版の標準
                             ├──► Diagnostic Log   ⚠ 調査時だけ
                             ├──► Action Summary   ★右画面の行動履歴
                             └──► Adventure Log     ★冒険ログの素材
```

## ★2 つの mode（依頼者 §13）

```text
normal      Product ON / Diagnostic OFF   ★製品版の既定
diagnostic  Product ON / Diagnostic ON    ⚠ 開発・障害調査
```

⚠ 初版で mode を増やしません（★`quiet` などは要るようになってから）。

## ⚠⚠ ログのために本体を止めない（依頼者 §25）

```text
sink が落ちた  →  ★機能本体は続ける  →  ⚠ 落ちた件数だけ数える（dropped）
```

★`emit()` は**例外を外へ出しません**。⚠ ただし種別の間違いは検査で赤くしたいので、
`Event` の生成そのもの（`event.py`）は `ValueError` を上げます。

## ⚠ 大きな基盤にはしません

★依頼者 §30:「Event Sourcing 化」「DB 導入」「ログ解析基盤の大型化」は**やりません**。
⚠ ここにあるのは「1 行書く」「配る」だけです。
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from .. import paths
from . import event as EV
from . import formatter as FM

NORMAL = "normal"
DIAGNOSTIC = "diagnostic"
MODES = (NORMAL, DIAGNOSTIC)

#: ★環境変数で mode を上書きできる（⚠ 実機テスト・E2E 用）
MODE_ENV = "RETROUX_DQ3_LOG_MODE"

#: ★置き場（⚠ Technical Log の `dq3-probe/` とは**分けます**）
LOG_DIR = (paths.RUNTIME, "dq3-log")   # ★RX3-0493: work/runtime/dq3-log/
PRODUCT_NAME = "product.log"
DIAGNOSTIC_NAME = "diagnostic.jsonl"

#: ★1 本の Product Log に残す上限（⚠ 青天井にしない）
MAX_PRODUCT_LINES = 5000


def default_mode() -> str:
    """★mode の決め方（⚠ **新しい設定を増やしません**）。

    ```text
    1  環境変数 RETROUX_DQ3_LOG_MODE     ★実機テスト・E2E 用
    2  user_config.yaml の logging.mode  ★人が書く設定（既にある / retroux 側と共有）
    3  normal                            ★既定
    ```

    ⚠⚠ 2 を新設しませんでした。★`retroux/core/config/user_config.py` に
    `normal` / `diagnostic` が**もうあります**（2026-08-13 / 製品版ログ整理 §19）。
    ⚠ ここで別の設定項目を作ると、**同じことを 2 か所で決める**ことになります。
    """
    got = str(os.environ.get(MODE_ENV, "")).strip().lower()
    if got in MODES:
        return got
    return _config_mode()


#: ★設定は 1 回だけ読む（⚠ emit ごとに YAML を開かない）
_CONFIG_MODE: str | None = None


def _config_mode() -> str:
    global _CONFIG_MODE
    if _CONFIG_MODE is None:
        _CONFIG_MODE = NORMAL
        try:
            from retroux.core.config import user_config as UC
            cfg, _warn = UC.load()
            got = str(getattr(cfg.logging, "mode", "") or "").strip().lower()
            if got in MODES:
                _CONFIG_MODE = got
        except Exception:                                        # noqa: BLE001
            pass                                                  # ⚠ 設定が読めなくても動かす
    return _CONFIG_MODE


def forget_config_mode() -> None:
    """⚠ 検査用（★読み直させる）。"""
    global _CONFIG_MODE
    _CONFIG_MODE = None


def product_path() -> pathlib.Path:
    return paths.work(*LOG_DIR, PRODUCT_NAME)


def diagnostic_path() -> pathlib.Path:
    return paths.work(*LOG_DIR, DIAGNOSTIC_NAME)


# ----------------------------------------------------------------------
# ★sink
# ----------------------------------------------------------------------
class ProductLogSink:
    """★人が読む簡易ログ。⚠ 1 Event = 1 行（★出さない Event もある）。"""

    name = "product"

    def __init__(self, path=None, *, limit: int = MAX_PRODUCT_LINES) -> None:
        self._path = path
        self.limit = limit

    @property
    def path(self) -> pathlib.Path:
        # ⚠ 置き場は**呼ぶたび**に引く（★sandbox の書き先は import の後に立つ / RX3-0128）
        return pathlib.Path(self._path) if self._path else product_path()

    def write(self, ev: EV.Event) -> None:
        line = FM.stamped(ev, with_date=True)
        if line is None:
            return
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        # ⚠⚠ 改行は LF 固定（★`open(..., "a")` の既定は環境で変わる / RX-0121）
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write(line + "\n")
        self._trim(path)

    def _trim(self, path: pathlib.Path) -> None:
        """★上限を超えたら古いほうから捨てる（⚠ 数えるのは書いたときだけ）。"""
        try:
            rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        if len(rows) <= self.limit:
            return
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(rows[-self.limit:]) + "\n")

    def lines(self) -> list[str]:
        """★読み出し（⚠ 無ければ空。★落とさない）。"""
        try:
            return [ln for ln in self.path.read_text(
                encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        except OSError:
            return []


class DiagnosticSink:
    """⚠ 開発・調査用。★Event をそのまま 1 行 JSON で残す。

    ★従来の Technical Log 相当の細かさは、⚠ **既存の `.log` を消さない**ことで保ちます
    （依頼者 §18）。ここは「共通 Event の生ログ」です。
    """

    name = "diagnostic"

    def __init__(self, path=None) -> None:
        self._path = path

    @property
    def path(self) -> pathlib.Path:
        return pathlib.Path(self._path) if self._path else diagnostic_path()

    def write(self, ev: EV.Event) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(ev.as_dict(), ensure_ascii=False) + "\n")


class ActionSummarySink:
    """★右画面の行動履歴へ（⚠ `auto_watch` が自分で文章を作らなくなる）。

    ⚠⚠ ここが依頼者 §16 の中身です。★UI / Product Log / 冒険ログが
    **同じ Event**から作られるようになります。
    """

    name = "action_summary"

    def __init__(self, action_log=None) -> None:
        self._log = action_log

    @property
    def log(self):
        if self._log is None:
            from .. import action_log as AL
            self._log = AL.shared()
        return self._log

    def write(self, ev: EV.Event):
        got = FM.summary_of(ev)
        if got is None:
            return None
        action, status, message, detail = got
        return self.log.record(action, status, message, **detail)


# ----------------------------------------------------------------------
# ★Writer
# ----------------------------------------------------------------------
class EventWriter:
    """★出力経路を 1 本にする。⚠ ここが落ちても機能本体は止めません。"""

    def __init__(self, *, mode: str | None = None, session_id: str | None = None,
                 clock=time.time, sinks=None, action_log=None) -> None:
        self.clock = clock
        self.mode = mode if mode in MODES else default_mode()
        self.session_id = session_id or EV.new_session_id(clock)
        #: ★捨てた件数（⚠ 「黙って減っている」を見つけるため）
        self.dropped = 0
        self.rejected = 0
        self.rows: list[EV.Event] = []
        self._subscribers: list = []
        self.sinks = list(sinks) if sinks is not None else [
            ProductLogSink(), DiagnosticSink(), ActionSummarySink(action_log)]

    # ------------------------------------------------------------------
    def emit(self, type: str, source: str, data: dict | None = None, *,
             level: str = EV.INFO) -> EV.Event | None:
        """★1 件通知する。⚠ **例外を外へ出しません**（依頼者 §25）。"""
        try:
            ev = EV.Event(type=type, source=source, data=dict(data or {}),
                          level=level, ts=EV.now_iso(self.clock),
                          session_id=self.session_id)
        except Exception:                                        # noqa: BLE001
            # ⚠⚠ 種別の間違いは**検査で**赤くします（★`EV.Event(...)` を直に作る）。
            #   ここで広く受けるのは、依頼者 §25「ログで本体を止めない」のためです。
            self.rejected += 1
            return None
        self.rows.append(ev)
        del self.rows[:-500]
        for sink in list(self.sinks):
            if sink.name == "diagnostic" and self.mode != DIAGNOSTIC:
                continue
            try:
                sink.write(ev)
            except Exception:                                    # noqa: BLE001
                self.dropped += 1                                 # ⚠ 本体は止めない
        for fn in list(self._subscribers):
            try:
                fn(ev)
            except Exception:                                    # noqa: BLE001
                self.dropped += 1
        return ev

    # ------------------------------------------------------------------
    def subscribe(self, fn) -> None:
        """★sink 以外の見る側（⚠ 落ちても本体を止めない）。"""
        self._subscribers.append(fn)

    def set_mode(self, mode: str) -> str:
        if mode in MODES:
            self.mode = mode
        return self.mode

    def sink(self, name: str):
        return next((s for s in self.sinks if s.name == name), None)


#: ★アプリで 1 本だけ（⚠ 画面ごとに作らない / `action_log.shared()` と同じ考え）
_SHARED: EventWriter | None = None


def shared() -> EventWriter:
    global _SHARED
    if _SHARED is None:
        _SHARED = EventWriter()
    return _SHARED


def reset_shared() -> None:
    """⚠ 検査用（★本番では呼びません）。"""
    global _SHARED
    _SHARED = None


def emit(type: str, source: str, data: dict | None = None, *, level: str = EV.INFO):
    """★どこからでも 1 行で（⚠ producer はこれだけ呼べばよい）。"""
    return shared().emit(type, source, data, level=level)


__all__ = ["EventWriter", "ProductLogSink", "DiagnosticSink", "ActionSummarySink",
           "shared", "reset_shared", "emit", "product_path", "diagnostic_path",
           "default_mode", "forget_config_mode",
           "NORMAL", "DIAGNOSTIC", "MODES", "MODE_ENV", "LOG_DIR"]
