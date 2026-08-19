"""アプリケーション層（2026-08-01 のリファクタ指示書 §2.3）。

★★ **依存の向きを固定する。** ★★

    UI / キーボード / ゲームパッド
                  ↓
            Action Dispatcher
                  ↓
          Application Services
                  ↓
    Repository / Emulator Adapter / File I/O

⚠ 逆向きの参照を作らない。ここから `retroux.ui` を import しない。
"""
