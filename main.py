import datetime
import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
from typing import Dict, Set, Tuple, List, Optional, Any

# Required scopes (permissions)
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Path to tokens folder
TOKENS_DIR = "tokens"


class CalendarSyncManager:
    def __init__(self, config_path: str = "config.json"):
        """Initialize the Calendar Sync Manager with configuration."""
        # Create tokens folder if it doesn't exist
        if not os.path.exists(TOKENS_DIR):
            os.makedirs(TOKENS_DIR)

        self.config = self._load_config(config_path)
        self.accounts = self.config.get("accounts", {})
        self.sync_rules = self.config.get("sync_rules", [])
        self.services = {}  # Will store authenticated calendar services

    def _load_config(self, config_path: str) -> dict:
        """Loads the configuration file."""
        try:
            # For local execution, load from file
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            print("Error: config.json file not found.")
            print("Please copy config.sample.json to config.json and edit it.")
            exit(1)
        except json.JSONDecodeError:
            print("Error: Invalid format in config.json.")
            exit(1)

    def authenticate_accounts(self) -> bool:
        """Authenticate all accounts needed for sync rules."""
        account_keys = set()

        # Identify required accounts from sync rules
        for rule in self.sync_rules:
            account_keys.add(rule["source"])
            account_keys.add(rule["destination"])

        # Get authentication credentials for each account
        for account_key in account_keys:
            try:
                if account_key not in self.accounts:
                    print(
                        f"Error: Account '{account_key}' does not exist in the configuration file."
                    )
                    continue

                creds = self._get_credentials(account_key)
                if not creds:
                    continue

                self.services[account_key] = build("calendar", "v3", credentials=creds)
                print(
                    f"Successfully authenticated account '{account_key}' ({self.accounts[account_key]['email']})."
                )

            except RefreshError as e:
                print(
                    f"Failed to refresh authentication token for {self.accounts[account_key]['email']}: {e}"
                )
                print("Running authentication flow again to get a new token.")
                return False
            except Exception as e:
                print(
                    f"Unexpected error occurred during authentication process for {self.accounts[account_key]['email']}: {e}"
                )
                return False

        return True

    def _get_credentials(self, account_key: str) -> Optional[Credentials]:
        """
        Get authentication credentials for the specified account.
        """
        if account_key not in self.accounts:
            print(
                f"Error: Account '{account_key}' does not exist in the configuration file."
            )
            return None

        # Generate token filename from account key
        token_filename = f"token_{account_key}.json"
        token_file = os.path.join(TOKENS_DIR, token_filename)

        # Check if account has service account configuration
        auth_type = self.accounts[account_key].get("auth_type")
        service_account_file = self.accounts[account_key].get("service_account_file")

        if auth_type == "service_account" and service_account_file:
            return self._get_service_account_credentials(
                account_key, service_account_file
            )
        else:
            return self._get_oauth_credentials(account_key, token_file)

    def _get_service_account_credentials(
        self, account_key: str, service_account_file: str
    ) -> Optional[Any]:
        """Handle service account authentication."""
        try:
            # Import module only for local execution
            if os.path.exists("deploy/service_account_auth.py"):
                import sys

                sys.path.append("deploy")
                from service_account_auth import get_service_credentials

                if os.path.exists(service_account_file):
                    return get_service_credentials(service_account_file)
                else:
                    print(
                        f"Error: Service account key file {service_account_file} not found"
                    )
                    return None
            else:
                print("Error: service_account_auth.py not found")
                return None
        except Exception as e:
            print(f"Service account authentication failed: {e}")
            return None

    def _get_oauth_credentials(self, account_key: str, token_file: str) -> Credentials:
        """Handle OAuth authentication flow."""
        creds = None

        if os.path.exists(token_file):
            with open(token_file, "r") as f:
                creds_data = json.load(f)
            creds = Credentials.from_authorized_user_info(creds_data)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except (RefreshError, Exception) as e:
                    print(
                        f"Failed to refresh token for {self.accounts[account_key]['email']}: {e}"
                    )
                    print(
                        "Token has expired or been revoked. Deleting token file and starting new authentication flow."
                    )
                    # Delete token file
                    if os.path.exists(token_file):
                        os.remove(token_file)
                    # Start a new authentication flow
                    creds = self._start_new_auth_flow(account_key)
            else:
                # If authentication is required, show which account is being authenticated
                print(
                    f"### Authentication required for {self.accounts[account_key]['email']}. A browser will open and prompt you to log in. ###"
                )
                creds = self._start_new_auth_flow(account_key)

            with open(token_file, "w") as f:
                f.write(creds.to_json())

        return creds

    def _start_new_auth_flow(self, account_key: str) -> Credentials:
        """Start a new OAuth authentication flow."""
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        return flow.run_local_server(port=0)

    def run_sync(self) -> None:
        """
        Run the synchronization process according to sync rules.
        """
        try:
            # Check if configuration file exists and is valid
            if not self.accounts:
                print("Error: No account information in config.json.")
                return
            if not self.sync_rules:
                print("Error: No sync rules in config.json.")
                return

            # Authenticate all accounts
            if not self.authenticate_accounts():
                return

            # Execute processing based on sync rules
            for rule in self.sync_rules:
                source_key = rule["source"]
                dest_key = rule["destination"]

                # Check if required services exist
                if source_key not in self.services or dest_key not in self.services:
                    print(
                        f"Error: Missing authentication information for accounts required by rule '{source_key}' -> '{dest_key}'."
                    )
                    continue

                # Process this sync rule
                self._process_sync_rule(rule, source_key, dest_key)

            print("Synchronization completed.")

        except HttpError as error:
            print(f"API error occurred: {error}")
        except Exception as e:
            print(f"Unexpected error occurred: {e}")

    def _process_sync_rule(self, rule: dict, source_key: str, dest_key: str) -> None:
        """Process a single synchronization rule."""
        # Collect summary list (titles) to search in destination calendar
        dest_rule_summaries = self._get_dest_rule_summaries(dest_key)

        # Get existing events from destination calendar
        existing_keys, existing_events = self._load_existing_events(
            self.services[dest_key], dest_rule_summaries
        )

        # Synchronize events from source calendar
        source_event_keys = self._sync_source_events(
            rule,
            self.services[source_key],
            self.services[dest_key],
            existing_keys,
            existing_events,
        )

        # Delete events from destination calendar that were removed from source calendar
        self._delete_removed_events(
            self.services[dest_key],
            rule,
            source_event_keys,
            existing_keys,
            existing_events,
        )

    def _get_dest_rule_summaries(self, dest_key: str) -> List[str]:
        """Get list of destination summary names for a specific destination."""
        dest_rule_summaries = []
        for rule in self.sync_rules:
            if rule["destination"] == dest_key and rule.get("new_summary"):
                dest_rule_summaries.append(rule["new_summary"])
        return dest_rule_summaries

    def _get_events(self, service: Any, days: int = 31) -> List[dict]:
        """
        Retrieve events from the specified service from the current time to the specified number of days ahead.
        """
        now = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        end_time = (
            (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=days)
            )
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

    def _should_sync_event(self, event: dict) -> bool:
        """
        Determines if an event should be synchronized.
        - Only sync events with Busy status (don't sync Free)
        - Only sync invitations that you have accepted (don't sync pending or declined)
        - Only sync events with a non-empty name
        """
        # Don't sync events with empty names
        if not event.get("summary"):
            return False

        # Don't sync events with 'transparent' transparency (Free status)
        if event.get("transparency") == "transparent":
            return False

        # For invitation events, check your response status
        # Check your status in the attendees list
        attendees = event.get("attendees", [])
        for attendee in attendees:
            # self=True indicates yourself
            if attendee.get("self", False):
                # Don't sync if responseStatus is not 'accepted'
                if attendee.get("responseStatus") != "accepted":
                    return False

        return True

    def _create_event(self, service: Any, event_data: dict) -> dict:
        """
        Create a new event in the specified service.
        Extract only the necessary fields before creating the event.
        """
        new_event = {
            "summary": event_data.get("summary", "Untitled Event"),
            "location": event_data.get("location", ""),
            "description": event_data.get("description", ""),
            "start": event_data.get("start", {}),
            "end": event_data.get("end", {}),
            "reminders": event_data.get("reminders", {"useDefault": True}),
        }

        if "colorId" in event_data:
            new_event["colorId"] = event_data["colorId"]

        return service.events().insert(calendarId="primary", body=new_event).execute()

    def _load_existing_events(
        self, service: Any, dest_rule_summaries: List[str]
    ) -> Tuple[Set[Tuple], Dict]:
        """
        Retrieve a list of keys for existing events in the destination calendar
        (combinations of start time and title).
        Used for duplicate checking.
        """
        events = self._get_events(service)
        existing_keys = set()
        existing_events = {}  # Store mapping of event IDs to keys

        for event in events:
            start = event.get("start", {})
            summary = event.get("summary", "")

            # Only track events with specific summaries (titles) targeted for synchronization
            if summary in dest_rule_summaries:
                if "dateTime" in start:
                    event_key = (start.get("dateTime"), summary)
                    existing_keys.add(event_key)
                    existing_events[event_key] = event.get("id")
                elif "date" in start:  # For all-day events
                    event_key = (start.get("date"), summary, "allday")
                    existing_keys.add(event_key)
                    existing_events[event_key] = event.get("id")

        return existing_keys, existing_events

    def _sync_source_events(
        self,
        rule: dict,
        source_service: Any,
        dest_service: Any,
        existing_keys: Set,
        existing_events: Dict,
    ) -> Set:
        """
        Synchronize events from the source calendar to the destination calendar
        based on a specific sync rule.
        """
        source_key = rule["source"]
        dest_key = rule["destination"]
        new_summary = rule.get("new_summary")
        preserve_details = rule.get("preserve_details", False)

        print("-" * 100)
        print(f"Adding events from account {source_key} to account {dest_key}...")
        events = self._get_events(source_service)

        # Collect current event keys from source calendar
        source_event_keys = set()

        for event in events:
            # Check if the event is eligible for synchronization
            if not self._should_sync_event(event):
                print(
                    f"Skip event not eligible for sync: {event.get('summary', 'Untitled')}"
                )
                continue

            start = event.get("start", {})
            # Either dateTime (normal event) or date (all-day event) will exist
            if "dateTime" in start or "date" in start:
                # Change event name
                original_summary = event.get("summary", "")

                # Use new summary if specified, otherwise keep the original summary
                if new_summary:
                    event_summary = new_summary
                else:
                    event_summary = original_summary

                # Create key based on whether it's an all-day event or normal event
                if "dateTime" in start:
                    event_key = (start.get("dateTime"), event_summary)
                else:  # "date" in start
                    event_key = (start.get("date"), event_summary, "allday")

                # Record source calendar event key
                source_event_keys.add(event_key)

                if event_key not in existing_keys:
                    # Update event information
                    event["summary"] = event_summary

                    # Remove details if not preserving them
                    if not preserve_details:
                        event["description"] = ""

                    created_event = self._create_event(dest_service, event)
                    print(f"⭐️ Event added: {original_summary}")
                    existing_keys.add(event_key)
                    existing_events[event_key] = created_event.get("id")
                else:
                    print(f"Skip duplicate event: {original_summary}")

        return source_event_keys

    def _delete_removed_events(
        self,
        dest_service: Any,
        rule: dict,
        source_event_keys: Set,
        existing_keys: Set,
        existing_events: Dict,
    ) -> None:
        """
        Delete events from the destination calendar that have been removed from the source calendar.
        """
        new_summary = rule.get("new_summary")

        # Identify events to delete
        events_to_delete = []

        for event_key in list(existing_keys):
            # Check event summary
            if len(event_key) >= 2:  # Verify key format
                summary = event_key[1]

                # Only process events corresponding to the current sync rule
                if new_summary and summary == new_summary:
                    # Add events not in source calendar to deletion list
                    if event_key not in source_event_keys:
                        event_id = existing_events.get(event_key)
                        if event_id:
                            events_to_delete.append((event_key, event_id))

        # Deletion process
        for event_key, event_id in events_to_delete:
            try:
                dest_service.events().delete(
                    calendarId="primary", eventId=event_id
                ).execute()
                print(f"⚠️ Event deleted: {event_key[1]}")
                existing_keys.remove(event_key)
                del existing_events[event_key]
            except HttpError as error:
                print(f"Error occurred while deleting event: {error}")


def main():
    """
    Synchronize events between multiple calendars based on configuration file.
    """
    sync_manager = CalendarSyncManager()
    sync_manager.run_sync()


if __name__ == "__main__":
    main()
