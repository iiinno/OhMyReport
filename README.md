# OhMyReport

AI が作る日本語の技術レポートを、固定 CSS と HTML 部品で整えるスキルです。
デスクトップ、モバイル、A4 印刷をブラウザで描画し、文字・色・配置・表・SVG を検査します。

スキル名は `report-design` です。調査報告、検証結果、比較資料、設計資料を HTML と PDF にまとめます。

## Codex に入れる

このリポジトリを取得し、`report-design` フォルダ全体を `~/.codex/skills/report-design` にコピーします。
Windows では通常、ユーザーフォルダ内の `.codex/skills` が配置先です。
既存の同名スキルがある場合は退避してから更新してください。

新しいチャットで次のように依頼します。

```text
$report-design この検証結果をHTMLの報告書にして。linterと目視確認まで行って。
```

## コマンドで試す

Python 3.10 以上と、Chrome・Edge・Chromium のいずれかが必要です。
Python の追加パッケージは使いません。ブラウザはインストール済みのものを検出します。
検出できない場合は環境変数 `CHROME` にブラウザ実行ファイルを指定します。

リポジトリのルートで実行します。

```sh
python report-design/scripts/new_report.py report.html
python report-design/scripts/lint_report.py report.html --shots outputs
```

`report.html` の本文を編集してから、もう一度検査します。
誤りがあると終了コードは `1` になります。`--json` で結果を JSON 出力できます。
出力された画面と PDF も確認してください。linter は文章の事実関係や視覚的な完成度を保証しません。

`assets/catalog.html` は部品見本です。数値・ログ・出典欄をそのまま実際の報告として使わず、資料に合わせて置き換えてください。
日本語推敲には `yomiyasu` があれば使います。未導入時の手順もスキルに含まれています。

## 保存用コピーを集める

保存先は利用者が指定します。アップロードや作者への送信はありません。

```sh
python report-design/scripts/archive_report.py report.html --shots outputs --dest archives
```

`OHMYREPORT_ARCHIVE_DIR` を設定しておくと `--dest` を省けます。
指定先に `v8`、`v9` のようなフォルダがあれば番号が最大のものを使い、なければ指定先へ保存します。
HTML と同名の PDF、デスクトップ・モバイルの PNG を一組にします。
同じ内容は追加せず、変更版にはハッシュを付けます。`archive-info.json` にスキル版と各ファイルの SHA-256 を記録します。

## 検証する

```sh
python -m unittest discover -s tests -v
```

セキュリティ上の前提と公開前の確認内容は [SECURITY.md](SECURITY.md) にあります。

## ライセンス

[MIT License](LICENSE)
