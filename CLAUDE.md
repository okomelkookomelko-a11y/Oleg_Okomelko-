# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

Source code for a DigitalOcean VPS that runs two things:
1. **`agent_bot.py`** — a Telegram bot powered by Claude (Anthropic), with email tools and notes. Runs as `my-bot.service`.
2. **`gmail_register.py`** — a Playwright automation that registers a Gmail account, driven remotely via a GitHub relay. Runs on-demand via the relay.

The VPS itself lives at `/home/bot/my-bot/` and is controlled entirely through the **GitHub relay** (see below). You cannot SSH in directly — all commands go through the relay.

## GitHub Relay (how to control the VPS)

The relay polls `cmds/pending.json` in the `okomelkookomelko-a11y/my-bot` GitHub repo every 30 seconds via systemd (`git-relay.timer` → `git-relay.service` → `cmd_runner.py`).

**To run a command on the VPS**, write a task to `cmds/pending.json`:
```python
import json, base64, urllib.request
GH_TOKEN = "..."  # from env
REPO = "okomelkookomelko-a11y/my-bot"
headers = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
# GET current SHA, then PUT new content:
task = {"id": "my-task-001", "cmd": "echo hello", "status": "pending"}
# optionally: "timeout": 600  (default 60s)
```

The result appears in `cmds/result.json`. Poll until `result["id"] == task_id`.

**Key relay rules:**
- `cmd_runner.py` (deployed version at `/home/bot/my-bot/cmd_runner.py`) marks task `"running"` immediately, preventing duplicate execution by concurrent timer instances.
- While a task is `"running"`, new tasks are ignored — the relay is single-tasking.
- The `timeout` field in the task JSON overrides the default 60s limit (use `600` for gmail_register runs).
- Output is truncated to 8000 chars in `result.json`; redirect to log files for long output.

**Safe pkill pattern** for stopping gmail_register.py without hitting cmd_runner:
```bash
pkill -f 'python3 -u'   # only gmail_register.py is launched with -u flag
```

## Deploying Code to the VPS

Always deploy with a specific commit SHA (bypasses GitHub CDN cache):
```bash
COMMIT_SHA=$(git rev-parse HEAD)
curl -sf "https://raw.githubusercontent.com/okomelkookomelko-a11y/Oleg_Okomelko-/${COMMIT_SHA}/gmail_register.py" \
  -o /home/bot/my-bot/gmail_register.py
```

## gmail_register.py — Architecture

Runs as a direct foreground subprocess of `cmd_runner.py` (not daemonized) so it stays in the systemd cgroup and isn't killed. Output is redirected to `/home/bot/my-bot/gmail_register.log`.

**Flow**: warm_up → open signup URL → fill_name → fill_bday → fill_user → fill_pass → fill_phone → wait_sms → fill_sms → accept_tos → done

**Known Google behaviors on this VPS (DigitalOcean IP):**
- Always redirects bday→username through `collectemailphone` gate. Fix: click "Don't have an email address or phone number?" button.
- Username radio buttons are `input[name="usernameRadio"]`, NOT `div[role="radio"]`.
- Username `input[name="Username"]` is React-managed and hidden; must use the native setter + dispatchEvent trick, never `page.fill()`.
- After password, Google shows `mophoneverification/initial` (a splash page with no `<input>` elements — uses custom components). Must click through to get the actual phone input form.
- After too many failed attempts from the same IP, Google returns `signup/error/1` ("Sorry, we could not create your Google Account."). Wait ~4 hours before retrying.

**SMS code delivery**: `wait_for_sms()` polls both the local `sms_code.txt` file AND `cmds/sms_code.txt` in the `okomelkookomelko-a11y/my-bot` GitHub repo (using `GH_TOKEN` env var). To provide the SMS code while a long relay run is in progress, write it directly to the GitHub repo via API.

**Config**: `/home/bot/my-bot/gmail_config.json` — `first_name`, `last_name`, `username`, `password`, `phone`. Update via relay command before retrying with a new username.

## Environment Variables (VPS `.env`)

```
TG_TOKEN         — Telegram bot token
ANTHROPIC_KEY    — Anthropic API key
GH_TOKEN         — GitHub PAT (used by cmd_runner.py and gmail_register.py)
GH_REPO          — okomelkookomelko-a11y/my-bot
EMAIL_ADDRESS    — Gmail address for agent_bot email tools
EMAIL_APP_PASSWORD — Gmail app password
```

## VPS Systemd Services

| Service | What it does |
|---|---|
| `my-bot.service` | Telegram agent bot (`agent_bot.py`), always-on |
| `git-relay.timer` | Triggers `git-relay.service` every 30s |
| `git-relay.service` | `Type=oneshot` — runs `cmd_runner.py` once |
| `bot-deploy.timer` | Auto-pulls `main` branch and restarts `my-bot` every minute |

**Critical**: `git-relay.service` is `Type=oneshot` with default `KillMode=control-group`. When `cmd_runner.py` exits, systemd kills **all processes in the cgroup** — including any background/daemonized children. This is why `launcher.py` is broken and `gmail_register.py` must run as a foreground subprocess.

## cmd_runner_new.py vs cmd_runner.py

`cmd_runner_new.py` in this repo is the updated version (with `timeout` field support and `"running"` state) that has been deployed to `/home/bot/my-bot/cmd_runner.py` on the VPS. The file in this repo is kept for reference; the live version on the VPS is what matters.

## Initial VPS Setup

```bash
TG_TOKEN=... ANTHROPIC_KEY=... GH_TOKEN=... bash vps_setup.sh
```
