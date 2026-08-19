"""起動スクリプトの形と文字コード（仕様書 4章）。

★2026-08-01 に `test_release_prep.py`（848 実質行）から切り出しました（指示書 §11.1）。
  ⚠ **内容は1件も減らしていません。**機械で切り、件数で確かめています。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _code_lines(text: str) -> list:
    """コメントと空行を落とした行を返す。

    ★★ **「その語がソースにある」だけの検査は穴になる。** ★★
      説明のコメントに同じ語が書いてあると、**実装を消しても緑**のままになる。
      実際に `MessageBox` と `MsgBox` の検査がこれで通り抜けた（2026-07-30）。

    ⚠ PowerShell は `#`、VBS と `.cmd` は `'` / `rem` がコメント。
    """
    made = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "'", "rem ", "REM ")):
            continue
        made.append(stripped)
    return made

# --- 起動スクリプト（仕様書 4章）---------------------------------------

LAUNCHERS = ("scripts/start-retroux.ps1", "scripts/launcher-common.ps1",
             "scripts/start.ps1", "research/probes/active/check-launchers.ps1")


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_powershell_files_have_a_bom(rel):
    """★★ **BOM が無いと日本語が壊れる**（実際に踏んだ）。 ★★

    Windows PowerShell 5.1 は BOM の無い `.ps1` を ANSI（cp932）として読む。
    UTF-8 の日本語がそのまま化け、文字列の閉じ引用符まで壊れて
    「スクリプトが壊れている」ようにしか見えなくなる。
    """
    raw = (PROJECT_ROOT / rel).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), f"{rel} に BOM が無い"


#: **cp932 で保存する**ファイル。★`.ps1` と**逆**の規則
#   ⚠ `.vbs` もここに入る（Windows Script Host は .vbs を ANSI として読む）
ANSI_FILES = ("Start-RetroUX-Console.cmd", "scripts/backup.cmd", "RetroUX.vbs")


def _read_script(rel: str) -> str:
    """拡張子に応じた文字コードで読む。★**決め打ちしない**。"""
    raw = (PROJECT_ROOT / rel).read_bytes()
    if rel in ANSI_FILES:
        return raw.decode("cp932")
    return raw.decode("utf-8-sig")


@pytest.mark.parametrize("rel", ANSI_FILES)
def test_windows_native_scripts_are_cp932_without_a_bom(rel):
    """★★ **拡張子ごとに必要な文字コードが違う。しかも逆。** ★★

    | 拡張子 | 文字コード | なぜ |
    | --- | --- | --- |
    | `.ps1` | UTF-8 **BOM あり** | BOM が無いと PS 5.1 は ANSI として読む |
    | `.cmd` | **cp932 / BOM なし** | cmd.exe は BOM を読み飛ばさない |
    | `.vbs` | **cp932 / BOM なし** | WSH は .vbs を既定で ANSI として読む |

    ⚠ `.cmd` の規則は `scripts/backup.cmd` の冒頭に既に書いてあったのに、
      見落として UTF-8 で作ってしまった（2026-07-30 に踏んだ）。
      UTF-8 のままだと、cp932 のコンソールで**エラーメッセージが化ける**
      ＝いちばん読んでほしいときに読めない。

    ⚠⚠ **`.vbs` はもっと重い。** UTF-8 だと日本語の文字列が途中で切れて
      「閉じていない文字列型の定数です」という**コンパイルエラー**になり、
      **ダブルクリックしても何も起きない**。公開用の入口そのものが
      起動しない状態だった（cscript で実測して発覚 / 2026-07-30）。

    ★実測（4通り試した結果）:
      | 形 | 結果 |
      | --- | --- |
      | UTF-8 / BOM なし | NG（閉じていない文字列型の定数です） |
      | UTF-8 / BOM あり | NG（無効な文字です。**WSH は UTF-8 BOM 非対応**） |
      | cp932 / BOM なし | **OK** ★採用 |
      | UTF-16LE / BOM あり | OK（ただし他の道具で扱いにくい） |

    ★`chcp 65001` を頭に置く手も試されて**却下**されている
      （`scripts/backup.cmd` に理由あり）。cmd はバッチをバイト位置で
      読み進めるため、途中でコードページを変えると多バイト文字の後半が
      別コマンドと解釈される。
    """
    raw = (PROJECT_ROOT / rel).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{rel} に BOM がある"
    # ★cp932 として読めること（UTF-8 の日本語が入っていると必ず失敗する）
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError as exc:                  # pragma: no cover
        raise AssertionError(f"{rel} が cp932 で読めない: {exc}") from exc
    # ⚠ 「読めた」だけでは弱い。**往復して一致する**ことを見る
    assert text.encode("cp932") == raw, f"{rel} の文字コードが混ざっている"
    # ★中身が本当にそのスクリプトであること（空ファイルを通さない）
    if rel.endswith(".cmd"):
        assert "@echo off" in text
    else:
        assert "Option Explicit" in text

    # ⚠⚠ **往復チェックでも足りない。**
    #   UTF-8 の日本語のバイト列は、cp932 の2バイト文字としても「読めて」
    #   しまい、**往復も一致する**（＝化けた文字がそのまま戻るだけ）。
    #   実際、UTF-8 で保存し直しても上の2つは通った（2026-07-30 に判明）。
    #
    # ★★ 決め手: **cp932 の日本語は UTF-8 として読めない。** ★★
    #   UTF-8 は先頭バイトが後続バイト数を決める厳しい形なので、
    #   cp932 の日本語をそのまま UTF-8 として読むとほぼ必ず失敗する。
    #   逆に「UTF-8 として読めてしまう」なら、UTF-8 で保存されている。
    #   ⚠ 一部だけ UTF-8 に変わった混在状態も、これで捕まる。
    assert not raw.isascii(), f"{rel} に日本語が無い（この検査の前提が崩れた）"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        pass                       # ★これが正しい状態
    else:
        raise AssertionError(
            f"{rel} が UTF-8 として読めてしまう（cp932 で保存すること）")

    # ⚠⚠ **ファイルの一部だけが UTF-8 になった混在状態**は、上の2つを
    #   すり抜ける（残りが cp932 なら UTF-8 として読めないままなので）。
    #
    # ★★ 決め手: **UTF-8 を cp932 として読むと半角カナが混ざる。** ★★
    #   実測（`RetroUX 開発・調査用` を UTF-8 で書いて cp932 で読む）:
    #     U+FF7B / U+FF7F / U+FF68 ... が現れる
    #   これらのファイルの日本語は**全角だけ**なので、半角カナが出たら化けている。
    halfwidth = sorted({ch for ch in text if "｡" <= ch <= "ﾟ"})
    assert not halfwidth, (
        f"{rel} に半角カナが混ざっています（UTF-8 で保存された部分がある）: "
        + " ".join(f"U+{ord(ch):04X}" for ch in halfwidth))


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_no_powershell_line_starts_with_a_plus(rel):
    """⚠ PowerShell 5.1 は**行頭の `+`** で式を続けられない。

    `+` は行末に置く。三項演算子が無いのと同じ種類の落とし穴で、
    症状が「スクリプトが壊れている」にしか見えない。
    """
    text = (PROJECT_ROOT / rel).read_text(encoding="utf-8-sig")
    bad = [n for n, line in enumerate(text.splitlines(), 1)
           if line.strip().startswith("+ ")]
    assert bad == [], f"{rel} の {bad} 行目が行頭 `+`"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell が要る")
def test_the_launchers_parse():
    """★★ **実行せずに構文だけ確かめる。** ★★

    起動スクリプトは実行すると FCEUX と GUI が立ち上がるので、
    構文の確認のために気軽に実行できない。
    """
    script = PROJECT_ROOT / "research" / "probes" / "active" / "check-launchers.ps1"
    if not script.exists():
        pytest.skip("check-launchers.ps1 が無い")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT, timeout=120)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def test_the_quiet_switch_exists():
    """★公開用の入口が要る `-Quiet`（仕様書 4.3）。"""
    text = (PROJECT_ROOT / "scripts" / "start-retroux.ps1").read_text(
        encoding="utf-8-sig")
    assert "[switch]$Quiet" in text
    # ★Quiet のときは pythonw.exe を使う（コンソールを作らない）
    assert "Get-PythonForGui" in text


@pytest.mark.parametrize("rel", LAUNCHERS + ANSI_FILES)
def test_no_string_literal_is_broken_across_lines(rel):
    """★★ **文字列リテラルが行の途中で切れていないか。** ★★

    ⚠⚠ これは実際に踏んだ事故で、**3つの検査をすべてすり抜けた**:

      1. `work\\retroux.log` と書いたつもりが `work` + CR + `etroux.log` に
         なった（Python の文字列リテラルで `\\r` が改行として解釈された）
      2. そのあとファイルを読み書きしたので、孤立 CR は**普通の CRLF に化けた**
         → 「孤立 CR を探す」では見つからない
      3. PowerShell は**複数行の文字列を許す**ので `research/probes/active/check-launchers.ps1`
         の構文検査も通った
      4. `pytest` も全部緑だった（ログのパスを検査していなかった）

    結果、ログの行き先が `work\\<改行>etroux.log` という無効なパスになり、
    **失敗したときにログが残らない**状態になっていた
    （＝この作業でいちばん避けたかったこと）。

    ★だから「引用符の数が奇数の行」を数える。
      意図した複数行文字列は、この3ファイルには無い。
    """
    text = _read_script(rel)
    bad = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # ⚠ コメントは数えない（説明文に引用符が1つだけ出ることがある）
        if stripped.startswith(("#", "rem ", "'")) or "@" in line:
            continue
        if line.count('"') % 2 == 1:
            bad.append((number, stripped))
    assert bad == [], f"{rel} で引用符が閉じていない行: {bad}"


def test_the_log_path_is_the_one_file_everything_writes_to():
    """★失敗を拾うための唯一の場所。**綴りが崩れていたら気づけない。**

    ⚠ ここが壊れると、コンソールを消したうえに**ログも残らない**という
      いちばん悪い状態になる（実際に一度そうなった / 上のテスト参照）。
    """
    text = (PROJECT_ROOT / "scripts" / "start-retroux.ps1").read_text(
        encoding="utf-8-sig")
    assert 'Join-Path $Root "work\\retroux.log"' in text, \
        "ログのパスが work\\retroux.log になっていない"


def test_quiet_uses_pythonw_and_normal_uses_python():
    """★仕様書 4.1 の使い分け。"""
    text = (PROJECT_ROOT / "scripts" / "launcher-common.ps1").read_text(
        encoding="utf-8-sig")
    assert "pythonw.exe" in text
    assert "python.exe" in text


def test_failures_go_through_a_message_box():
    """★★ **コンソールが無いとき、失敗を黙殺しない**（仕様書 5.1）。 ★★

    ⚠⚠ **「MessageBox という語がある」では弱すぎた。**
      説明のコメントにも同じ語が出るので、`::Show(` の呼び出しを
      丸ごと消しても**テストは緑だった**（2026-07-30 に判明）。
      ★呼び出しの形そのものを見る。
    """
    common = (PROJECT_ROOT / "scripts" / "launcher-common.ps1").read_text(
        encoding="utf-8-sig")
    code = _code_lines(common)
    assert any("[System.Windows.Forms.MessageBox]::Show(" in line
               for line in code), "MessageBox を実際に呼んでいない"
    assert any(line.startswith("function Stop-Launcher") for line in code), \
        "Stop-Launcher が定義されていない"

    main = (PROJECT_ROOT / "scripts" / "start-retroux.ps1").read_text(
        encoding="utf-8-sig")
    # ⚠ 起動の失敗を Write-Error で終わらせない（誰にも届かない）
    assert "Write-Error" not in main, "Write-Error は Stop-Launcher へ置き換える"
    assert main.count("Stop-Launcher") >= 4


def test_start_process_never_uses_the_console_python():
    """★★ **`Start-Process` は新しいプロセスに自前のコンソールを作る。** ★★

    ⚠⚠ だから `python.exe` で `Start-Process` すると、VBS から隠して呼んでも
      **黒い窓が出る**。コンソール抑止が丸ごと無意味になる。
      実際に GUI がこの形で起動されていた（2026-07-30 に見つけた）。

    ★同期呼び出しの `& $python ...` は**親のコンソールを継ぐ**ので問題ない。
      窓が増えるのは `Start-Process` のときだけ。だからここだけを見る。
    """
    text = (PROJECT_ROOT / "scripts" / "start-retroux.ps1").read_text(
        encoding="utf-8-sig")
    bad = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or "Start-Process" not in stripped:
            continue
        # ★`$guiPython` は許す。`$python` を単体で使っていたら駄目
        if re.search(r"-FilePath\s+\$python\b", stripped):
            bad.append((number, stripped))
    assert bad == [], f"Start-Process が $python を使っている: {bad}"

    # ★★ ここから 2026-07-30 の実機確認で分かったこと ★★
    #
    # ⚠⚠ **`pythonw.exe` を選ぶだけでは足りなかった。**
    #   uv が作る venv の `Scripts\pythonw.exe` は**トランポリン**で、
    #   起動するのは base の **`python.exe`（コンソール版）**。
    #   だから conhost が付いて窓が出る。実測:
    #       窓の題名  = `F:\...\.venv\Scripts\pythonw.exe`
    #       窓のクラス = `ConsoleWindowClass`
    #   ★`python.exe` と `pythonw.exe` が同じ 47104 バイト＝中身が同じ。
    #
    # ⚠⚠ **`-WindowStyle Hidden` で直してはいけない。**
    #   STARTUPINFO の `wShowWindow` に SW_HIDE が入るので **Qt の窓まで隠れる**
    #   （実測: `IsWindowVisible` が False。プロセスは生きているのに
    #   画面に何も出ない＝黒い窓より悪い）。
    #
    # ★正解は `CREATE_NO_WINDOW`（`Start-NoConsole`）。
    code = _code_lines(text)
    spawns = [ln for ln in code if "Start-Process" in ln]
    assert spawns == [], \
        f"Start-Process が残っている（Start-NoConsole を使う）: {spawns}"
    used = [ln for ln in code if "Start-NoConsole" in ln]
    assert len(used) >= 2, f"Start-NoConsole が {len(used)} か所しかない"
    assert any("retroux.gui" in ln for ln in code)
    assert any("savestate_backup" in ln for ln in code)


def test_the_startup_align_does_not_force_the_gui_position():
    """★★ **起動時の自動整列は、覚えている窓の位置を壊さない**（R-8）★★

    ⚠⚠ 実機で「保存して終了しても窓の位置がリセットされる」と判明した。
      原因は起動の手順そのもの:
        1. GUI が復元する
        2. **手順7の自動整列が `SetWindowPos` で上書きする**

    ★自動整列に `--force` を付けないこと。付けると元の不具合に戻る。
      「整列」ボタン側は `force=True` で明示的に動かす。
    """
    text = (PROJECT_ROOT / "scripts" / "start-retroux.ps1").read_text(
        encoding="utf-8-sig")
    align = [ln for ln in _code_lines(text) if "align_windows" in ln]
    assert align, "自動整列の呼び出しが見つからない"
    assert not any("--force" in ln for ln in align), \
        f"自動整列に --force が付いている（覚えた位置を壊す）: {align}"

    # ★ボタン側は force=True であること（戻す手段が無くなるため）
    # ★★ 2026-08-01 のリファクタで、並べるのは `WindowManager` の仕事。
    #   ⚠ 探す先を直さないと「直っているのに赤い」ままになる。
    gui = (PROJECT_ROOT / "retroux" / "ui" / "window_manager.py").read_text(
        encoding="utf-8")
    assert "self.arrange(force=True)" in gui, \
        "標準レイアウトに戻す処理が force=True で呼んでいない"


def test_start_no_console_uses_create_no_window_not_hidden():
    """★`CreateNoWindow` と `UseShellExecute=$false` は**2つ揃って**初めて効く。

    ⚠ どちらか片方だけだと CREATE_NO_WINDOW にならない。
    ⚠ 窓を隠す方式（`WindowStyle` / SW_HIDE）へ戻すと Qt の窓が隠れる。
    """
    text = (PROJECT_ROOT / "scripts" / "launcher-common.ps1").read_text(
        encoding="utf-8-sig")
    code = _code_lines(text)

    assert any(line.startswith("function Start-NoConsole") for line in code), \
        "Start-NoConsole が定義されていない"
    assert any("$psi.CreateNoWindow = $true" in ln for ln in code), \
        "CreateNoWindow を立てていない"
    assert any("$psi.UseShellExecute = $false" in ln for ln in code), \
        "UseShellExecute を false にしていない（CREATE_NO_WINDOW にならない）"
    assert not any("WindowStyle" in ln for ln in code), \
        "WindowStyle は使わない（Qt の窓まで隠れる）"
    # ★空白を含む引数を囲むこと（`F:\My Projects\...` のような置き方がある）
    assert any("-match" in ln and "\\s" in ln for ln in code), \
        "空白を含む引数を囲んでいない"


def test_the_session_tag_is_defined_before_it_is_used():
    """★★ **PowerShell は未定義の変数を `$null` として黙って通す。** ★★

    ⚠⚠ `$script:RetroUXSession` を定義せずに `--session` へ渡していた。
      子プロセスは**空の札**を受け取るので、あとで「今回起動したものだけを
      止める」ができない。しかも**エラーは何も出ない**ので気づけない
      （2026-07-30 に見つけた）。

    ★だから「使う前に代入がある」ことを行番号で見る。
    """
    text = (PROJECT_ROOT / "scripts" / "start-retroux.ps1").read_text(
        encoding="utf-8-sig")
    lines = text.splitlines()
    assigned = None
    used = []
    for number, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            continue
        if re.match(r"\s*\$script:RetroUXSession\s*=", line):
            assigned = assigned or number
        elif "$script:RetroUXSession" in line:
            used.append(number)
    assert assigned is not None, "$script:RetroUXSession に代入が無い"
    assert used, "$script:RetroUXSession を誰も使っていない"
    assert assigned < min(used), \
        f"代入が {assigned} 行目、最初の使用が {min(used)} 行目（順が逆）"


def test_the_gui_gets_the_session_tag_too():
    """★バックアップだけでなく **GUI にも札を渡す**（仕様書 6.3）。

    ⚠ 片方だけだと、終了処理を作るときに GUI を見分けられない。
    """
    text = (PROJECT_ROOT / "scripts" / "start-retroux.ps1").read_text(
        encoding="utf-8-sig")
    assert '"-m", "retroux.gui", "--session", $script:RetroUXSession' in text


def test_the_public_and_dev_launchers_both_exist():
    """★公開用を作るために開発用を消さない（仕様書 2.1）。"""
    assert (PROJECT_ROOT / "RetroUX.vbs").exists()
    assert (PROJECT_ROOT / "Start-RetroUX-Console.cmd").exists()
    assert (PROJECT_ROOT / "scripts" / "start-retroux.ps1").exists()


def test_the_vbs_launcher_quotes_its_arguments():
    """⚠ フォルダ名に空白があると、囲まないと引数が切れる。

    ⚠⚠ **前の書き方は3つとも穴だった**（2026-07-30 に判明）:

      | 前の検査 | なぜ穴だったか |
      | --- | --- |
      | `-Quiet` を含むか | `-NoQuiet` に変えても部分文字列として通る |
      | 引用符4つの並びを含むか | 別の行にも同じ並びが出るので、`-File` の囲みを外しても通る |
      | `MsgBox` を含むか | 3か所あるうち1つ消しても通る（説明文にも出る） |

    ★行ごとに、**その引数を渡している行そのもの**を見る。
    """
    code = _code_lines(_read_script("RetroUX.vbs"))

    # ★`-Quiet` は**単独の語**として渡すこと（`-NoQuiet` を弾く）
    quiet = [line for line in code if re.search(r'"\s*-Quiet"', line)]
    assert quiet, "-Quiet を単独の語として渡していない"

    # ★`-File` に渡すパスが引用符で囲まれていること
    assert any('-File """ & script & """"' in line for line in code), \
        "-File のパスを引用符で囲んでいない"
    # ★powershell 自体のパスも囲むこと（%SystemRoot% に空白は無いが、
    #   Windows のフォルダ名は変えられる）
    assert any('"""" & powershell & """"' in line for line in code), \
        "powershell のパスを引用符で囲んでいない"

    # ★失敗を黙って捨てない。**3つの失敗の道すべて**に MsgBox がある
    #   （起動スクリプトが無い / powershell が無い / Run が失敗した）
    boxes = [line for line in code if "MsgBox" in line]
    assert len(boxes) >= 3, f"MsgBox が {len(boxes)} か所しかない（3つの失敗の道）"
    # ⚠ WScript.Echo は Quiet では誰にも見えない（cscript なら標準出力）
    assert not any("WScript.Echo" in line for line in code), \
        "WScript.Echo は MsgBox へ置き換える（コンソールが無いので見えない）"


@pytest.mark.skipif(sys.platform != "win32", reason="WSH は Windows だけ")
def test_the_vbs_launcher_actually_compiles_and_quotes_a_spaced_path(tmp_path):
    """★★ **文字を読むだけでは足りない。実際に WSH に食わせる。** ★★

    ⚠⚠ `RetroUX.vbs` が UTF-8 で保存されていて**コンパイルエラー**になり、
      ダブルクリックしても何も起きない状態だった。
      静的な検査（引用符・`-Quiet`・`MsgBox`）は**全部通っていた**。
      文字コードの問題は、実際に実行系へ渡すまで分からない（2026-07-30）。

    ★`shell.Run` の行だけ差し替えて、**組み立てた文字列を見る**。
      PowerShell も FCEUX も起動しないので安全。
    ★置き場は**空白を含むフォルダ**にする（仕様書 4.2 の落とし穴）。
    """
    run_line = "code = shell.Run(command, 0, True)"
    text = _read_script("RetroUX.vbs")
    assert run_line in text, "Run の行が見つからない（書き方が変わった？）"

    # ★★ 空白を含むフォルダ名（これが試したいこと）★★
    work = tmp_path / "My Projects" / "Retro UX"
    (work / "scripts").mkdir(parents=True)
    (work / "scripts" / "start-retroux.ps1").write_text("# fake\n",
                                                        encoding="utf-8")
    target = work / "RetroUX.vbs"
    target.write_bytes(
        text.replace(run_line, "WScript.Echo command\ncode = 0", 1)
        .encode("cp932"))

    proc = subprocess.run(["cscript", "//NoLogo", str(target)],
                          cwd=work, capture_output=True, timeout=60)
    out = (proc.stdout or b"").decode("cp932", errors="replace").strip()
    err = (proc.stderr or b"").decode("cp932", errors="replace").strip()

    assert not err, f"VBS がコンパイル・実行できない: {err}"
    assert proc.returncode == 0, f"終了コード {proc.returncode}: {out}"

    # ★空白を含むパスが、引数として**切れずに**渡っていること
    assert " -Quiet" in out, out
    assert f'-File "{work}\\scripts\\start-retroux.ps1"' in out, out
    assert f'-Root "{work}"' in out, out
    assert out.count('"') % 2 == 0, f"引用符が閉じていない: {out}"


def test_the_console_launcher_does_not_pass_quiet():
    """★開発用はコンソールに出すのが目的なので `-Quiet` を付けない。

    ⚠ **コメント行を数えない。**「`-Quiet` は付けない」という説明が
      あるので、単純な文字列検索では引っかかる。
    """
    code = _code_lines(_read_script("Start-RetroUX-Console.cmd"))
    assert not any("-Quiet" in line for line in code), \
        [line for line in code if "-Quiet" in line]
    # ★起動スクリプトを呼んでいること自体は確かめる
    assert any("start-retroux.ps1" in line for line in code)
