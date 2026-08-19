"""モンスターの絵まわり。

分担（指示書 §7 Phase M3 / §19-5）:

    decoder.py    圧縮を解いてタイルと置き方を出す
    palette.py    NES の色 → RGB、モンスターのパレット表
    renderer.py   タイルを並べて RGBA の絵にする
    png.py        PNG を書く（外部ライブラリなし）
    extractor.py  全部まとめて出す（PNG / JSON / 一覧シート）
    validator.py  実機で撮った絵と突き合わせる
"""
