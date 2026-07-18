# GCP Service Account Setup for CLIP OS

One-time setup. Takes ~20 minutes. After this, Google auth on Railway never expires.

## Step 1 — Create service account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Select your project (linked to user@example.com)
3. IAM & Admin → Service Accounts → **Create Service Account**
   - Name: `clip-os`
   - ID: `clip-os` (auto-filled)
   - Click **Create and Continue**
4. Skip role assignment (we'll use domain-wide delegation instead)
5. Click **Done**
6. Click the new service account → **Keys** tab → **Add Key** → JSON
7. Download the JSON file → save it somewhere safe (NOT in the repo)

## Step 2 — Enable APIs

In GCP Console → APIs & Services → Enable these:
- Gmail API
- Google Calendar API
- Google Drive API (optional, for future)

## Step 3 — Domain-wide delegation

1. In the service account page → **Details** tab → copy the **Client ID** (a long number)
2. Go to [admin.google.com](https://admin.google.com) (Google Workspace admin)
3. Security → Access and data control → **API controls**
4. Manage Domain Wide Delegation → **Add new**
   - Client ID: paste the number from above
   - OAuth scopes (paste all at once):
     ```
     https://www.googleapis.com/auth/gmail.readonly,
     https://www.googleapis.com/auth/gmail.send,
     https://www.googleapis.com/auth/gmail.compose,
     https://www.googleapis.com/auth/calendar.readonly,
     https://www.googleapis.com/auth/calendar.events
     ```
5. Click **Authorize**

## Step 4 — Install GWS CLI

```bash
brew install googleworkspace/tap/gws
```

Or download binary from: https://github.com/googleworkspace/cli/releases

## Step 5 — Configure GWS CLI with service account

```bash
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/clip-os-key.json
gws gmail list --limit 5  # test it works
```

## Step 6 — Add to Railway

In Railway dashboard → your CLIP OS service → Variables:
- `GOOGLE_SERVICE_ACCOUNT_B64` = base64-encode the JSON key:
  ```bash
  base64 -i /path/to/clip-os-key.json | pbcopy
  ```
  Paste the result as the value.

## Step 7 — Update server.py bootstrap

Once service account is ready, update `bootstrap_google_token()` in `tools/server.py`:
- Read `GOOGLE_SERVICE_ACCOUNT_B64` instead of `GOOGLE_TOKEN_B64`
- Write to `/tmp/service-account.json`
- Set `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/tmp/service-account.json`

## What this replaces

| Before | After |
|--------|-------|
| `fetch_gmail.py` OAuth flow | `gws gmail list` / `gws gmail get` |
| `fetch_calendar.py` OAuth flow | `gws calendar list` |
| Token expires silently | Service account never expires |
| Browser required to re-auth | Fully headless |
