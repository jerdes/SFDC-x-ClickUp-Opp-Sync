# SFDC x ClickUp Opportunity Sync

One-way sync from a Salesforce opportunity report (delivered as a Gmail CSV attachment) to a ClickUp list. Runs via system cron every weekday morning.

## What it does

| Action | When |
|---|---|
| **Create** a new ClickUp task | Opportunity exists in CSV but not yet in ClickUp |
| **Update** an existing task | Opportunity already has a ClickUp task (matched by SF Opportunity ID) |
| **Close** a task | Opportunity stage is `Closed Won` or `Closed Lost` |

All 34 Salesforce report fields are synced as ClickUp custom fields.

---

## One-time setup

### 1. Google Cloud — Gmail API credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project.
2. Enable the **Gmail API** (APIs & Services → Library).
3. Create an **OAuth 2.0 Client ID** (APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app).
4. Download the JSON and save it as `auth/credentials.json`.

### 2. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Fill in at minimum:
- `CLICKUP_API_TOKEN` — your ClickUp personal API token (Settings → Apps)
- `CLICKUP_LIST_ID` — the list ID from the ClickUp URL

### 4. Create ClickUp custom fields

In your ClickUp list, create a custom field for each column in the report. The most important one to create first is **"Salesforce ID"** (Text type) — this is the matching key.

Then discover the field UUIDs:

```bash
curl -s -H "Authorization: YOUR_CLICKUP_TOKEN" \
  "https://api.clickup.com/api/v2/list/YOUR_LIST_ID/field" | python3 -m json.tool
```

Copy each field's `id` into the corresponding `CLICKUP_FIELD_ID_*` variable in `.env`.

### 5. Run the OAuth consent flow (one-time, interactive)

```bash
python3 main.py
```

A browser window will open asking you to authorize Gmail access. After approving, `auth/token.json` is saved. All future runs are headless.

### 6. Set up cron

Open your crontab:

```bash
crontab -e
```

Add this line (adjust the Python path and time as needed):

```cron
# Run SF → ClickUp sync every weekday at 7:00 AM
0 7 * * 1-5 /usr/bin/python3 /home/user/SFDC-x-ClickUp-Opp-Sync/main.py >> /home/user/SFDC-x-ClickUp-Opp-Sync/logs/cron.log 2>&1
```

Verify your Python path with `which python3`.

---

## Verifying the sync

```bash
# First run — should show created=N updated=0 closed=0 errors=0
python3 main.py

# Second run with same CSV — should show created=0 updated=N closed=0 errors=0
python3 main.py
```

Logs are written to `logs/sync.log` (rotating, 5 MB × 5 files).

---

## Project structure

```
SFDC-x-ClickUp-Opp-Sync/
├── main.py                  # Entry point
├── config/settings.py       # All configuration
├── auth/gmail_auth.py       # Gmail OAuth2
├── gmail/client.py          # Fetch CSV from Gmail
├── sync/
│   ├── parser.py            # CSV → Opportunity objects
│   ├── matcher.py           # Match to ClickUp tasks
│   └── engine.py            # Create / update / close loop
├── clickup/
│   ├── client.py            # ClickUp REST API calls
│   └── models.py            # Custom field helpers
├── utils/logger.py          # Logging setup
├── .env.example             # Config template
└── requirements.txt
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing required environment variable: CLICKUP_API_TOKEN` | Copy `.env.example` → `.env` and fill in the token |
| `No Gmail messages found matching subject` | Check `GMAIL_SUBJECT_PATTERN` matches your report email's subject exactly |
| `Email has no attachment matching '.csv'` | Check `GMAIL_ATTACHMENT_NAME_PATTERN`; try setting it to just `.csv` |
| ClickUp tasks created but fields are blank | Field IDs in `.env` are wrong — re-run the `GET /field` curl and re-copy the UUIDs |
| `CLICKUP_FIELD_ID_SF_OPPORTUNITY_ID is not set` | This field is required — create it in ClickUp and add its UUID to `.env` |