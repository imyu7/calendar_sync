import datetime
import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

# 必要なスコープ（権限）
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# トークンフォルダへのパス
TOKENS_DIR = "tokens"

# トークンフォルダが存在しない場合は作成
if not os.path.exists(TOKENS_DIR):
    os.makedirs(TOKENS_DIR)


# Cloud Functionsで実行する場合、ローカルファイルシステムではなくGCS（Cloud Storage）からファイルを読み込む
def is_cloud_function():
    """コードがCloud Functions環境で実行されているかどうかを判断します。"""
    return os.environ.get("FUNCTION_TARGET") is not None


# 設定ファイルを読み込む
def load_config():
    """設定ファイルを読み込みます。"""
    try:
        if is_cloud_function():
            # 環境変数から設定を読み込む
            config_json = os.environ.get("CONFIG_JSON")
            if config_json:
                return json.loads(config_json)
            else:
                print("エラー: 環境変数CONFIG_JSONが設定されていません。")
                return {}
        else:
            # ローカル実行の場合、ファイルから読み込む
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except FileNotFoundError:
        print("エラー: config.jsonファイルが見つかりません。")
        print("config.sample.jsonをconfig.jsonにコピーして編集してください。")
        exit(1)
    except json.JSONDecodeError:
        print("エラー: config.jsonの形式が無効です。")
        exit(1)


# 設定を読み込む
CONFIG = load_config()
ACCOUNTS = CONFIG.get("accounts", {})
SYNC_RULES = CONFIG.get("sync_rules", [])


def get_credentials(account_key):
    """
    指定されたアカウントの認証資格情報を取得します。
    Cloud Functions環境では、環境変数から資格情報を取得します。
    """
    if account_key not in ACCOUNTS:
        print(f"エラー: アカウント'{account_key}'が設定ファイルに存在しません。")
        return None

    if is_cloud_function():
        # Cloud Functions環境では、環境変数からトークンを取得
        token_env_var = f"TOKEN_{account_key.upper()}"
        token_json = os.environ.get(token_env_var)
        if token_json:
            creds_data = json.loads(token_json)
            creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                        # Cloud Functionsでは環境変数は読み取り専用なので、更新をログに記録
                        print(f"{account_key}のトークンが更新されました")
                    except Exception as e:
                        print(
                            f"{account_key}のトークン更新中にエラーが発生しました: {e}"
                        )
                        return None
                else:
                    print(f"エラー: {account_key}の有効なトークンがありません")
                    return None
            return creds
        else:
            # サービスアカウント認証の確認
            service_account_key = os.environ.get("SERVICE_ACCOUNT_KEY")
            auth_type = ACCOUNTS[account_key].get("auth_type")

            if auth_type == "service_account" and service_account_key:
                # サービスアカウント認証
                try:
                    from deploy.service_account_auth import get_service_credentials

                    return get_service_credentials(json.loads(service_account_key))
                except Exception as e:
                    print(f"サービスアカウント認証に失敗しました: {e}")
                    return None
            else:
                print(f"エラー: 環境変数{token_env_var}が設定されていません")
                return None
    else:
        # ローカル実行用の元のコード
        creds = None
        # アカウントキーからトークンファイル名を生成
        token_filename = f"token_{account_key}.json"
        token_file = os.path.join(TOKENS_DIR, token_filename)

        # アカウントにサービスアカウント設定があるか確認
        auth_type = ACCOUNTS[account_key].get("auth_type")
        service_account_file = ACCOUNTS[account_key].get("service_account_file")

        if auth_type == "service_account" and service_account_file:
            # サービスアカウント認証を使用
            try:
                # ローカル実行用にモジュールをインポート
                if os.path.exists("deploy/service_account_auth.py"):
                    import sys

                    sys.path.append("deploy")
                    from service_account_auth import get_service_credentials

                    if os.path.exists(service_account_file):
                        return get_service_credentials(service_account_file)
                    else:
                        print(
                            f"エラー: サービスアカウントキーファイル{service_account_file}が見つかりません"
                        )
                        return None
                else:
                    print("エラー: service_account_auth.pyが見つかりません")
                    return None
            except Exception as e:
                print(f"サービスアカウント認証に失敗しました: {e}")
                return None
        else:
            # 標準のOAuth認証を使用
            if os.path.exists(token_file):
                with open(token_file, "r") as f:
                    creds_data = json.load(f)
                creds = Credentials.from_authorized_user_info(creds_data)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except RefreshError as e:
                        print(
                            f"{ACCOUNTS[account_key]['email']}のトークンの更新に失敗しました: {e}"
                        )
                        print(
                            "トークンの有効期限が切れているか、取り消されています。トークンファイルを削除して新しい認証フローを開始します。"
                        )
                        # トークンファイルを削除
                        if os.path.exists(token_file):
                            os.remove(token_file)
                        # 新しい認証フローを開始
                        flow = InstalledAppFlow.from_client_secrets_file(
                            "credentials.json", SCOPES
                        )
                        creds = flow.run_local_server(port=0)
                    except Exception as e:
                        print(
                            f"{ACCOUNTS[account_key]['email']}のトークン更新中に予期しないエラーが発生しました: {e}"
                        )
                        print(
                            "トークンファイルを削除して新しい認証フローを開始します。"
                        )
                        # トークンファイルを削除
                        if os.path.exists(token_file):
                            os.remove(token_file)
                        # 新しい認証フローを開始
                        flow = InstalledAppFlow.from_client_secrets_file(
                            "credentials.json", SCOPES
                        )
                        creds = flow.run_local_server(port=0)
                else:
                    # 認証が必要な場合、どのアカウントが認証されているかを表示
                    print(
                        f"### {ACCOUNTS[account_key]['email']}の認証が必要です。ブラウザが開き、ログインを求められます。 ###"
                    )
                    flow = InstalledAppFlow.from_client_secrets_file(
                        "credentials.json", SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                with open(token_file, "w") as f:
                    f.write(creds.to_json())

            return creds


def get_events(service, days=31):
    """
    指定されたサービスから現在時刻から指定された日数先までのイベントを取得します。
    """
    now = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    end_time = (
        (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            timeMax=end_time,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return events_result.get("items", [])


def delete_synced_events(service, summary):
    """
    指定されたサービスから特定のサマリー（タイトル）を持つイベントを削除します。
    これは同期によって追加されたイベントを削除するために使用されます。
    """
    events = get_events(service)
    deleted_count = 0

    for event in events:
        event_summary = event.get("summary", "")

        # 指定されたサマリー（タイトル）と一致するイベントを削除
        if event_summary == summary:
            try:
                service.events().delete(
                    calendarId="primary", eventId=event["id"]
                ).execute()
                deleted_count += 1
                print(f"🗑️  イベント削除: {event_summary}")
            except HttpError as error:
                print(f"イベント削除中にエラーが発生しました: {error}")

    return deleted_count


def main():
    """
    設定ファイルに基づいて、同期によって追加されたイベントを削除します。
    """
    try:
        # 設定ファイルの存在確認
        if not ACCOUNTS:
            print("エラー: config.jsonにアカウント情報がありません。")
            return
        if not SYNC_RULES:
            print("エラー: config.jsonに同期ルールがありません。")
            return

        # 認証とサービスの構築
        services = {}
        destination_accounts = set()
        destination_summaries = {}

        # 同期ルールから送信先アカウントとイベントタイトルを特定
        for rule in SYNC_RULES:
            dest_key = rule["destination"]
            destination_accounts.add(dest_key)

            # このルールの送信先アカウントとイベントタイトルのマッピングを追加
            if dest_key not in destination_summaries:
                destination_summaries[dest_key] = []

            # new_summaryが指定されている場合のみリストに追加
            if "new_summary" in rule and rule["new_summary"]:
                destination_summaries[dest_key].append(rule["new_summary"])

        # 各送信先アカウントの認証資格情報を取得
        for account_key in destination_accounts:
            try:
                if account_key not in ACCOUNTS:
                    print(
                        f"エラー: アカウント'{account_key}'が設定ファイルに存在しません。"
                    )
                    continue

                creds = get_credentials(account_key)
                services[account_key] = build("calendar", "v3", credentials=creds)
                print(
                    f"アカウント'{account_key}' ({ACCOUNTS[account_key]['email']})の認証に成功しました。"
                )

            except RefreshError as e:
                print(
                    f"{ACCOUNTS[account_key]['email']}の認証トークンの更新に失敗しました: {e}"
                )
                print("再度認証フローを実行して新しいトークンを取得します。")
                return
            except Exception as e:
                print(
                    f"{ACCOUNTS[account_key]['email']}の認証プロセス中に予期しないエラーが発生しました: {e}"
                )
                return

        # 各送信先アカウントから同期されたイベントを削除
        total_deleted = 0
        for dest_key, summaries in destination_summaries.items():
            if dest_key not in services:
                print(f"エラー: 送信先アカウント'{dest_key}'の認証情報がありません。")
                continue

            print("-" * 100)
            print(f"アカウント{dest_key}から同期されたイベントを削除しています...")

            for summary in summaries:
                deleted = delete_synced_events(services[dest_key], summary)
                total_deleted += deleted
                print(
                    f"アカウント{dest_key}から'{summary}'タイトルのイベントを{deleted}件削除しました。"
                )

        print("-" * 100)
        print(f"削除完了：合計{total_deleted}件のイベントを削除しました。")

    except HttpError as error:
        print(f"APIエラーが発生しました: {error}")
    except Exception as e:
        print(f"予期しないエラーが発生しました: {e}")


if __name__ == "__main__":
    main()
