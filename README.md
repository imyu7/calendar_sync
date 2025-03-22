# Google カレンダー同期ツール

複数のGoogleカレンダーアカウント間で予定を同期するためのツールです。

## 機能

- 複数のGoogleカレンダーアカウント間で予定を同期
- カスタム同期ルールの設定（ソースカレンダー、宛先カレンダー、イベントタイトルの変更など）
- 削除された予定の同期
- 重複予定の自動検出

## セットアップ

1. Google Cloud Platformで新しいプロジェクトを作成し、Google Calendar APIを有効にします
2. OAuth 2.0クライアントIDを作成し、credentials.jsonとしてダウンロードします
3. `config.json`ファイルを編集して、アカウント情報と同期ルールを設定します
4. 必要なパッケージをインストール: `pip install -r requirements.txt`

## 設定

`config.json`ファイルで以下の設定を行います：

### アカウント設定

```json
"accounts": {
  "account_key": {
    "email": "your.email@example.com"
  },
  ...
}
```

- `account_key`: アカウントを識別するための任意のキー
- `email`: Googleアカウントのメールアドレス

認証トークンは自動的に `tokens/token_{account_key}.json` という名前で保存されます。

### 同期ルール設定

```json
"sync_rules": [
  {
    "source": "source_account_key",
    "destination": "destination_account_key",
    "new_summary": "変更後のイベントタイトル",
    "preserve_details": false
  },
  ...
]
```

- `source`: 同期元アカウントのキー
- `destination`: 同期先アカウントのキー
- `new_summary`: 同期先での予定タイトル（オプション）
- `preserve_details`: 詳細情報を保持するかどうか（true/false）

## 使い方

```
python main.py
```

初回実行時は各アカウントの認証が必要です。ブラウザが開き、各アカウントにログインするよう求められます。
認証トークンは`tokens`フォルダに保存され、再利用されます。

## ディレクトリ構造

```
.
├── config.json         # 設定ファイル
├── config.sample.json  # 設定ファイルのサンプル
├── credentials.json    # Google API認証情報（自分で取得する必要あり）
├── main.py             # メインスクリプト
├── requirements.txt    # 必要なパッケージリスト
└── tokens/             # 認証トークンが保存されるディレクトリ
    └── token_{account_key}.json # 各アカウントの認証トークン
```

## 注意事項

- 認証情報（credentials.jsonや`tokens`フォルダ内のファイル）はGitHubにアップロードしないでください
- アクセストークンは安全に保管してください
- 定期的に実行する場合はcronなどのスケジューラを使用してください 