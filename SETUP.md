# CLIP Setup Guide — New API Keys & Services

Follow this when setting up CLIP for the first time or adding new integrations.

---

## 1. Tavily API (web search brain)

Used by: `lead_scan.py`, `opportunity_scan.py`

1. Go to **https://app.tavily.com** → Sign up (free)
2. Dashboard → API Keys → copy your key
3. Add to `.env`:
   ```
   TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
4. Test:
   ```bash
   python3 -c "from tavily import TavilyClient; print(TavilyClient('YOUR_KEY').search('test', max_results=1))"
   ```

Install:
```bash
pip3 install tavily-python
```

---

## 2. Apollo.io API (contact enrichment)

Used by: `outreach_draft.py` (optional — enriches leads with email + name)

1. Go to **https://app.apollo.io** → Sign up (free tier: 50 credits/month)
2. Settings → Integrations → API → copy your API key
3. Add to `.env`:
   ```
   APOLLO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
4. Test: the enrichment runs automatically in `outreach_draft.py`

---

## 3. Anthropic API key (for outreach_draft.py)

Used by: `outreach_draft.py` to call Claude and write cold emails

1. Go to **https://console.anthropic.com** → API Keys → Create key
2. Add to `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
3. Test:
   ```bash
   python3 -c "import anthropic; print(anthropic.Anthropic().models.list())"
   ```

Install:
```bash
pip3 install anthropic
```

---

## 4. Gmail SMTP App Password (for scheduled email digests)

Used by: `send_digest.py`, `lead_scan.py`, `opportunity_scan.py`, `pipeline_stale.py`

This lets Python send emails via Gmail without OAuth (simpler for server-side scripts).

**Steps:**
1. Go to your Google Account → **Security** → 2-Step Verification (must be ON)
2. After enabling 2FA → search "App passwords" in Google Account
3. Click **App passwords** → Select app: Mail → Select device: Other → name it "CLIP"
4. Google gives you a **16-character password** (e.g. `abcd efgh ijkl mnop`)
5. Add to `.env`:
   ```
   GMAIL_FROM=user@example.com
   GMAIL_APP_PASSWORD=abcdefghijklmnop
   GMAIL_TO=user@example.com
   ```
   (Remove spaces from the password — use `abcdefghijklmnop` not `abcd efgh ijkl mnop`)

6. Test:
   ```bash
   python3 tools/send_digest.py --subject "CLIP Test" --body "Working!"
   ```
   Check your inbox.

---

## 5. Install Python dependencies

```bash
pip3 install tavily-python anthropic flask
```

---

## 6. Test each tool locally before scheduling

```bash
# Lead scan (dry run — no API calls)
python3 tools/lead_scan.py --dry-run

# Lead scan (real — needs TAVILY_API_KEY)
python3 tools/lead_scan.py --no-email

# Opportunity scan
python3 tools/opportunity_scan.py --no-email

# Pipeline stale check
python3 tools/pipeline_stale.py --no-email

# Outreach draft (needs a lead in data/leads.json first)
python3 tools/outreach_draft.py --list
python3 tools/outreach_draft.py --company "Company Name"

# Email test
python3 tools/send_digest.py --subject "Test" --body "CLIP is working"
```

---

## 7. n8n on Railway (scheduled automation)

See `n8n/README.md` for full deployment steps.

**Short version:**
1. Deploy n8n to Railway using their n8n template
2. Deploy `n8n/clip_api.py` as a separate Railway service (Python)
3. Set all env vars in Railway dashboard
4. Create 4 cron workflows in n8n (see README for cron expressions)
5. Test each workflow manually from the n8n UI

---

## 8. Google Workspace MCP (Gmail + Calendar + Drive)

Replaces the old single-purpose Gmail MCP. One server, one OAuth token, 95+ tools.

**8a. GCP Setup (one-time, browser)**
1. Go to `console.cloud.google.com` → create project **"CLIP OS"**
2. APIs & Services → Enable: **Gmail API**, **Google Calendar API**, **Google Drive API**
3. OAuth consent screen → Internal → add scopes for all 3 APIs
4. Credentials → Create OAuth 2.0 Client ID → Desktop app → download + rename to `credentials.json`
5. Move credentials file:
   ```bash
   mkdir -p ~/.google-mcp
   mv credentials.json ~/.google-mcp/credentials.json
   ```

**8b. Install + Authenticate**
```bash
npx google-workspace-mcp setup          # verify credentials
npx google-workspace-mcp accounts add acmestudio   # opens browser → sign in with user@example.com
```

**8c. Add to `.mcp.json`** (project root — already done for CLIP):
```json
{
  "mcpServers": {
    "google-workspace": {
      "command": "npx",
      "args": ["-y", "google-workspace-mcp"],
      "env": {
        "GOOGLE_CREDENTIALS_FILE": "/Users/user/.google-mcp/credentials.json",
        "GOOGLE_ACCOUNTS_FILE": "/Users/user/.google-mcp/accounts.json"
      }
    }
  }
}
```

**8d. Test**
- Ask CLIP: `/clean-inbox` — should show user@example.com inbox
- Ask CLIP: "what's on my calendar today?" — should show today's events
- Restart Claude Code after editing settings.json

---

## .env file template

```env
# Gmail (acmestudio — requires DKIM verified + 2FA + App Password)
GMAIL_FROM=user@example.com
GMAIL_APP_PASSWORD=your16charpassword
GMAIL_TO=user@example.com

# APIs
TAVILY_API_KEY=tvly-xxx
APOLLO_API_KEY=xxx
ANTHROPIC_API_KEY=sk-ant-xxx

# n8n API (set when deployed)
CLIP_API_TOKEN=choose-a-secret-token
```

Never commit `.env` to git. It's already in `.gitignore`.
