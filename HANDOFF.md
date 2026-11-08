# NWSGraphicast handoff

Repo: `mattbat/NWSGraphicast`. Work branch: `claude/quirky-galileo-l232g5` (pushed, no PR opened).
Previous session: https://claude.ai/code/session_014vMVHh9u5PJpDNLbfuccti

## What the project does
Emails the NWS Norman (`oun`) Graphicast images at 6am, 12pm and 6pm Central. Python 3.11+,
dependency: Pillow. Entry point `python -m graphicast` (`graphicast/cli.py`). Runs every 15 min;
`graphicast/schedule.py` decides which run is the slot send (3-hour window after each slot, each
slot processed once via `last_slot` in state).

## Changes made this session (all committed and pushed)
1. **Always send on slot runs** (`graphicast/cli.py`). Previously emailed only when the graphics
   fingerprint changed. Now every slot run sends. Change detection is kept: it still drives the NEW
   tags on changed images and the "severity rose" / "risk lowered" notes. Log reason is
   `graphics changed`, `severity rose` or `scheduled`.
2. **No active graphics** now sends a warning email (it may signal an error): subject prefixed
   "⚠️ No graphics available · ", a note saying images were unavailable, weather widget still
   included. Not sent on severity-rise watch runs between slots (those stay silent without graphics).
   `--dry-run` also writes the warning email.
3. Tests updated (338 pass, 5 skipped): `python -m pytest -q` (needs `pip install pytest .`).
4. **Raspberry Pi installer**: `deploy/pi/install.sh` and `deploy/pi/graphicast.env.example`;
   README has a "Running on a Raspberry Pi" section. Creates `~/graphicast/venv`, `run.sh`, a
   local `state.json`, and a cron entry every 15 min. Images are embedded (inline mode), no hosting.

## Why the Pi
GitHub Actions scheduled runs were badly delayed: only 7 scheduled runs in ~28 h (expected 96), the
6pm slot ran at 7:26pm CST, 6am at 7:43am, 12pm at 12:21pm. The code is fine; GitHub's cron is
best-effort. Options discussed: external timer triggering `workflow_dispatch`/`repository_dispatch`,
Pi cron (chosen), small VPS, hybrid.

## Status / next steps
- The user is installing on the Pi themselves (no SSH access from the cloud session).
  Steps: clone, `git checkout claude/quirky-galileo-l232g5`, `bash deploy/pi/install.sh`, edit
  `~/graphicast/graphicast.env` (SMTP_USER, SMTP_PASSWORD, EMAIL_TO; never ask for the password in
  chat), then `run.sh --dry-run --ignore-schedule --out /tmp/preview`, then `run.sh --force`.
- **Untested:** the cron step of the installer (sandbox had no `crontab`). Dry run and install of
  the venv were verified. Debug from `~/graphicast/graphicast.log` if the user reports problems.
- After the Pi works: disable the GitHub workflow (Actions, graphicast, Disable) to avoid duplicate
  emails, and merge the branch (PR not yet opened; only open one if the user asks).
- Possible follow-ups: the workflow docs in `docs/PLAN.md` / `docs/IMPLEMENTATION.md` still
  partly describe the old "email only on change" behavior (one line was patched).

## Notes
- Central time is CST (UTC-6) since Nov 1; the code handles DST via `America/Chicago`.
- Commit messages end with the Co-Authored-By / Claude-Session lines; do not add model names to
  repo artifacts.
