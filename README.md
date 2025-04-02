# Google Calendar Sync Tool

A tool for synchronizing events between multiple Google Calendar accounts.

*Note: [Japanese version of this README](README_ja.md) is also available.*

## Features

- Synchronize events between multiple Google Calendar accounts
- Custom sync rules (source calendar, destination calendar, event title changes, etc.)
- Synchronization of deleted events
- Automatic detection of duplicate events

## Setup

1. Create a new project in Google Cloud Platform and enable the Google Calendar API
2. Create an OAuth 2.0 Client ID and download it as credentials.json
3. Edit the `config.json` file to configure account information and sync rules
4. Install required packages: `pip install -r requirements.txt`

## Configuration

Configure the following settings in the `config.json` file:

### Account Settings

```json
"accounts": {
  "account_key": {
    "email": "your.email@example.com"
  },
  ...
}
```

- `account_key`: Arbitrary key to identify the account
- `email`: Google account email address

Authentication tokens for each account are automatically saved as `tokens/token_{account_key}.json`.

#### Using Service Account Authentication (Optional)

```json
"accounts": {
  "account_key": {
    "email": "your.email@example.com",
    "auth_type": "service_account",
    "service_account_file": "service-account-key.json"
  },
  ...
}
```

- `auth_type`: Authentication type (specify "service_account" to use service account authentication)
- `service_account_file`: Path to the service account key JSON file

### Sync Rules Settings

```json
"sync_rules": [
  {
    "source": "source_account_key",
    "destination": "destination_account_key",
    "new_summary": "Modified event title",
    "preserve_details": false
  },
  ...
]
```

- `source`: Source account key
- `destination`: Destination account key
- `new_summary`: Event title in the destination calendar (optional)
- `preserve_details`: Whether to preserve event details (true/false)

## Usage

```
python main.py
```

On first run, authentication is required for each account. A browser will open and prompt you to log in to each account.
Authentication tokens are saved in the `tokens` folder and reused.

## Directory Structure

```
.
├── config.json           # Configuration file
├── config.sample.json    # Sample configuration file
├── credentials.json      # Google API credentials (must be obtained separately)
├── main.py               # Main script
├── requirements.txt      # Required package list
└── tokens/               # Directory where authentication tokens are stored
    └── token_{account_key}.json # Authentication tokens for each account
```

## Notes

- Do not upload authentication information (credentials.json and files in the `tokens` folder) to GitHub
- Store access tokens securely
- For regular execution, use a scheduler like cron 