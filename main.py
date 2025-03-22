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

# tokensフォルダのパス
TOKENS_DIR = "tokens"

# tokensフォルダが存在しない場合は作成
if not os.path.exists(TOKENS_DIR):
    os.makedirs(TOKENS_DIR)


# 設定ファイルを読み込む
def load_config():
    """設定ファイルを読み込みます。"""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("エラー: config.jsonファイルが見つかりません。")
        print("config.sample.jsonをconfig.jsonにコピーして編集してください。")
        exit(1)
    except json.JSONDecodeError:
        print("エラー: config.jsonの形式が正しくありません。")
        exit(1)


# 設定を読み込む
CONFIG = load_config()
ACCOUNTS = CONFIG.get("accounts", {})
SYNC_RULES = CONFIG.get("sync_rules", [])


def get_credentials(account_key):
    """
    指定されたアカウントの認証情報を取得します。
    トークンファイルが存在する場合は読み込み、有効でなければリフレッシュまたは新規に取得します。
    リフレッシュが失敗した場合は、トークンファイルを削除して新しい認証フローを開始します。
    """
    if account_key not in ACCOUNTS:
        print(f"エラー: アカウント '{account_key}' が設定ファイルに存在しません。")
        exit(1)

    creds = None
    # アカウントキーからトークンファイル名を生成
    token_filename = f"token_{account_key}.json"
    token_file = os.path.join(TOKENS_DIR, token_filename)

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
                    f"{ACCOUNTS[account_key]['email']} のトークンリフレッシュに失敗しました: {e}"
                )
                print(
                    "トークンが期限切れまたは取り消されました。トークンファイルを削除して新しい認証フローを開始します。"
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
                    f"{ACCOUNTS[account_key]['email']} のトークンリフレッシュ中に予期しないエラーが発生しました: {e}"
                )
                print("トークンファイルを削除して新しい認証フローを開始します。")
                # トークンファイルを削除
                if os.path.exists(token_file):
                    os.remove(token_file)
                # 新しい認証フローを開始
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", SCOPES
                )
                creds = flow.run_local_server(port=0)
        else:
            # 認証が必要な場合、ユーザーに対してどのアカウントの認証かを表示
            print(
                f"### {ACCOUNTS[account_key]['email']} の認証が必要です。ブラウザが開かれ、ログインが求められます。 ###"
            )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


def get_events(service, days=21):
    """
    指定されたサービスから、現在時刻から指定日数先までの予定を取得します。
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


def should_sync_event(event):
    """
    イベントが同期対象かどうかを判断します。
    - Busy状態のイベントのみ同期（Freeは同期しない）
    - 自分が承諾した招待のみ同期（未承諾や辞退したものは同期しない）
    - イベント名が空でないもののみ同期
    """
    # イベント名が空の場合は同期しない
    if not event.get("summary"):
        return False

    # transparency が 'transparent' の場合は Free 状態なので同期しない
    if event.get("transparency") == "transparent":
        return False

    # 招待イベントの場合、自分の応答状態をチェック
    # attendees リストの中から自分のステータスを確認
    attendees = event.get("attendees", [])
    for attendee in attendees:
        # self=True は自分自身を表す
        if attendee.get("self", False):
            # responseStatus が 'accepted' でない場合は同期しない
            if attendee.get("responseStatus") != "accepted":
                return False

    return True


def create_event(service, event_data):
    """
    指定されたサービスに新しいイベントを作成します。
    必要なフィールドのみ抽出してからイベントを作成します。
    """
    new_event = {
        "summary": event_data.get("summary", "無題のイベント"),
        "location": event_data.get("location", ""),
        "description": event_data.get("description", ""),
        "start": event_data.get("start", {}),
        "end": event_data.get("end", {}),
        "reminders": event_data.get("reminders", {"useDefault": True}),
    }

    if "colorId" in event_data:
        new_event["colorId"] = event_data["colorId"]

    return service.events().insert(calendarId="primary", body=new_event).execute()


def load_existing_events(service, dest_rule_summaries):
    """
    宛先カレンダーの既存イベントのキー一覧（開始時刻とタイトルの組み合わせ）を取得します。
    重複チェック用に利用します。
    """
    events = get_events(service)
    existing_keys = set()
    existing_events = {}  # イベントIDとキーの対応を保存

    for event in events:
        start = event.get("start", {})
        summary = event.get("summary", "")

        # 同期対象の特定のサマリー（タイトル）を持つイベントのみ追跡
        if summary in dest_rule_summaries:
            if "dateTime" in start:
                event_key = (start.get("dateTime"), summary)
                existing_keys.add(event_key)
                existing_events[event_key] = event.get("id")
            elif "date" in start:  # 終日イベントの場合
                event_key = (start.get("date"), summary, "allday")
                existing_keys.add(event_key)
                existing_events[event_key] = event.get("id")

    return existing_keys, existing_events


def sync_source_events(
    rule, source_service, dest_service, existing_keys, existing_events
):
    """
    特定の同期ルールに基づいてソースカレンダーのイベントを宛先カレンダーへ同期します。
    """
    source_key = rule["source"]
    dest_key = rule["destination"]
    new_summary = rule.get("new_summary")
    preserve_details = rule.get("preserve_details", False)

    print("-" * 100)
    print(f"アカウント {source_key} の予定をアカウント {dest_key} に追加中...")
    events = get_events(source_service)

    # ソースカレンダーの現在のイベントキーを収集
    source_event_keys = set()

    for event in events:
        # イベントが同期対象かどうかをチェック
        if not should_sync_event(event):
            print(
                f"同期対象外のイベントをスキップしました: {event.get('summary', '無題')}"
            )
            continue

        start = event.get("start", {})
        # dateTime（通常イベント）または date（終日イベント）のどちらかが存在する
        if "dateTime" in start or "date" in start:
            # イベント名を変更
            original_summary = event.get("summary", "")

            # 新しいサマリーが指定されている場合は使用、そうでなければ元のサマリーを保持
            if new_summary:
                event_summary = new_summary
            else:
                event_summary = original_summary

            # 終日イベントか通常イベントかに応じてキーを作成
            if "dateTime" in start:
                event_key = (start.get("dateTime"), event_summary)
            else:  # "date" in start
                event_key = (start.get("date"), event_summary, "allday")

            # ソースカレンダーのイベントキーを記録
            source_event_keys.add(event_key)

            if event_key not in existing_keys:
                # イベント情報を更新
                event["summary"] = event_summary

                # 詳細情報を保持しない場合は削除
                if not preserve_details:
                    event["description"] = ""

                created_event = create_event(dest_service, event)
                print(f"イベントを追加しました: {original_summary}")
                existing_keys.add(event_key)
                existing_events[event_key] = created_event.get("id")
            else:
                print(f"重複イベントをスキップしました: {original_summary}")

    return source_event_keys


def delete_removed_events(
    dest_service, rule, source_event_keys, existing_keys, existing_events
):
    """
    ソースカレンダーから削除されたイベントを宛先カレンダーからも削除します。
    """
    new_summary = rule.get("new_summary")

    # 削除対象のイベントを特定
    events_to_delete = []

    for event_key in list(existing_keys):
        # イベントのサマリーをチェック
        if len(event_key) >= 2:  # キーの形式を確認
            summary = event_key[1]

            # 対象の同期ルールに対応するイベントのみ処理
            if new_summary and summary == new_summary:
                # ソースカレンダーに存在しないイベントを削除対象に
                if event_key not in source_event_keys:
                    event_id = existing_events.get(event_key)
                    if event_id:
                        events_to_delete.append((event_key, event_id))

    # 削除処理
    for event_key, event_id in events_to_delete:
        try:
            dest_service.events().delete(
                calendarId="primary", eventId=event_id
            ).execute()
            print(f"イベントを削除しました: {event_key[1]}")
            existing_keys.remove(event_key)
            del existing_events[event_key]
        except HttpError as error:
            print(f"イベント削除中にエラーが発生しました: {error}")


def main():
    """
    設定ファイルに基づいて、複数のカレンダー間で予定を同期します。
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
        account_keys = set()

        # 同期ルールから必要なアカウントを特定
        for rule in SYNC_RULES:
            account_keys.add(rule["source"])
            account_keys.add(rule["destination"])

        # 各アカウントの認証情報取得
        for account_key in account_keys:
            try:
                if account_key not in ACCOUNTS:
                    print(
                        f"エラー: アカウント '{account_key}' が設定ファイルに存在しません。"
                    )
                    continue

                creds = get_credentials(account_key)
                services[account_key] = build("calendar", "v3", credentials=creds)
                print(
                    f"アカウント '{account_key}' ({ACCOUNTS[account_key]['email']}) の認証に成功しました。"
                )

            except RefreshError as e:
                print(
                    f"{ACCOUNTS[account_key]['email']} 認証トークンのリフレッシュに失敗しました: {e}"
                )
                print("認証フローを再実行して新しいトークンを取得します。")
                return
            except Exception as e:
                print(
                    f"{ACCOUNTS[account_key]['email']} 認証処理中に予期しないエラーが発生しました: {e}"
                )
                return

        # 同期ルールに基づいて処理を実行
        for rule in SYNC_RULES:
            source_key = rule["source"]
            dest_key = rule["destination"]

            # 必要なサービスが存在するか確認
            if source_key not in services or dest_key not in services:
                print(
                    f"エラー: ルール '{source_key}' -> '{dest_key}' に必要なアカウントの認証情報が不足しています。"
                )
                continue

            # 宛先カレンダーで検索するサマリーリスト（タイトル）を収集
            dest_rule_summaries = []
            for r in SYNC_RULES:
                if r["destination"] == dest_key and r.get("new_summary"):
                    dest_rule_summaries.append(r["new_summary"])

            # 宛先カレンダーの既存イベントを取得
            existing_keys, existing_events = load_existing_events(
                services[dest_key], dest_rule_summaries
            )

            # ソースカレンダーからイベントを同期
            source_event_keys = sync_source_events(
                rule,
                services[source_key],
                services[dest_key],
                existing_keys,
                existing_events,
            )

            # ソースカレンダーから削除されたイベントを宛先カレンダーからも削除
            delete_removed_events(
                services[dest_key],
                rule,
                source_event_keys,
                existing_keys,
                existing_events,
            )

        print("同期が完了しました。")

    except HttpError as error:
        print(f"APIエラーが発生しました: {error}")
    except Exception as e:
        print(f"予期しないエラーが発生しました: {e}")


if __name__ == "__main__":
    main()
