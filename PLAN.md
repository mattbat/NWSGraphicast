# NWSGraphicast — Modernization Plan

Status: **planning only**. No code has changed. This file lives on branch
`claude/eloquent-sagan-has6f5` and must not be merged to `main`/`master` until the
rewrite is agreed.

---

## 1. What the current code does (as of `50acc5f`)

`main.py` (~230 lines, Python 3), run by cron on a Raspberry Pi 3×/day:

1. Reads Gmail username/password from `config.ini`.
2. Logs into a Google Sheet ("NWSGraphicast" → "Responses") with a service-account JSON
   key and reads every subscriber row: email, zip code, frequency, image size.
3. For each subscriber: resolves zip → NWS office by scraping the redirect of
   `forecast.weather.gov/zipcity.php`.
4. Downloads `mesonet.org/.../graphicast_info/<office>` to `graphicast.data.<office>`.
5. Byte-compares it to `graphicast.data.<office>.last_update`; if different (or `-f`),
   builds an HTML email with `<img src="...">` links to weather.gov and sends via Gmail SMTP.
6. Renames every data file to `*.last_update` for the next run.

### Problems found while reading it

| # | Issue | Impact |
|---|-------|--------|
| 1 | State lives in files next to the script | Can't run on an ephemeral runner as-is |
| 2 | Images are hot-linked, and NWS reuses URLs (`.../graphicast/2.png` gets overwritten) | An old email opened later shows *today's* image, not the one it was sent with. `MIMEImage` is imported but never used |
| 3 | Change detection compares raw bytes of the whole feed, including expired items | Emails fire on irrelevant changes. Expired items silently stop showing without triggering anything |
| 4 | Same image URL, new picture → bytes of the feed may not change | Possible missed updates |
| 5 | `ast.literal_eval` on remote data; a single source with no fallback and no alert when it breaks | Fragile; a silent outage means you just stop getting emails (see §2) |
| 6 | Global mutable `html_images`; string-concatenated HTML, no escaping | Hard to maintain/test |
| 7 | Plaintext Gmail password in `config.ini`; `-c` still asks for an office that's no longer used | Confusing, insecure |
| 8 | Feed is re-downloaded (and zip re-resolved) once per subscriber, not once per office | Wasteful; would race if runs overlap |
| 9 | Subject timestamp uses the host's local time | Would be UTC on GitHub Actions |
| 10 | No tests, no dependency file, README says itself it's out of date | Maintainability |

## 2. Data sources (verified working 2026-11-06)

History: before March 2017 (`6c2031b`) the script read NWS directly from
`http://www.srh.noaa.gov/images/fxc/<office>/graphicast/graphicast.xml`. That broke when
NWS retired the regional `srh.noaa.gov` hosts, and the script switched to Mesonet. Mesonet
has been the stable choice ever since.

- **Mesonet JSON** (current, primary): `http://www.mesonet.org/index.php/api/nws_products/graphicast_info/<office>`
  — reliable since 2017. Keep it as the **primary** source.
- **NWS XML** (new location, fallback): `https://www.weather.gov/source/<office>/graphicast/graphicast.xml`
  — same fields (`StartTime`, `EndTime`, `title`, `description`, `FullImage`, ...). This file
  feeds weather.gov's own graphicast widget, but it isn't a documented API, and NWS has moved
  it before. Use it only as a **fallback**. It has a `<creation-date>` that changes on every
  refresh, so change detection must hash normalized content, not raw bytes.
- Both parse into one `Graphic` model behind a `Source` interface, so swapping or adding a
  source changes one file.
- **Breakage detection:** if every source fails (HTTP error, parse error, missing fields),
  the run fails loudly. GitHub then emails you, and an optional ntfy alert can tell you too.
  The run never silently sends nothing. Saved copies of the feeds in `tests/fixtures/`
  catch format changes in CI.
- Optional: log when Mesonet and NWS disagree, as early warning that one has drifted.
- Images: `https://www.weather.gov/images/<office>/graphicast/<n>.png` — 200 OK.
- Zip → office: not needed if the office is configured directly. If wanted, use
  `api.weather.gov/points/<lat>,<lon>` → `properties.cwa` (official API, no scraping).

## 3. Can it run on GitHub Actions instead of the Pi? **Yes.**

- `on: schedule` cron + `workflow_dispatch` (manual "send now" button = the old `-f`).
- Gmail SMTP (port 465) works from GitHub-hosted runners. Use a **Gmail App Password**
  (requires 2FA on the sending account) stored as repo secrets `SMTP_USER`, `SMTP_PASSWORD`.
  Recipients can also be a secret if the repo is public.
- Cost: ~30 s per run. Public repo = free; private repo = well within the 2,000 free min/month
  even if run hourly.
- **State between runs** (the only real design decision). Options:
  1. **Commit a small `state.json` to a dedicated `state` branch** — durable, auditable,
     and doubles as history. ← recommended
  2. `actions/cache` — simple but caches can be evicted (7 days unused).
  3. No state, fixed digest 3×/day — simplest, but emails even when nothing changed.
- Caveats to know:
  - Cron is UTC and **can be delayed 5–30+ min** at busy times; fine for this use.
  - GitHub **disables scheduled workflows after 60 days with no repo activity** (public repos).
    Committing state to a branch may or may not count; add a tiny keepalive or just re-enable
    when GitHub emails you. Will verify during implementation.
  - The workflow emails *you* on failure automatically, which is better monitoring than the Pi has.

## 4. Proposed rewrite (shape)

Small, stdlib-first Python package; zero Google dependencies.

```
graphicast/
  config.py      # load config.yaml/toml + env secrets → dataclasses
  sources/       # mesonet.py (primary), nws_xml.py (fallback) → list[Graphic]
  model.py       # Graphic dataclass, is_active(now), content fingerprint
  state.py       # load/save {office: {fingerprint, sent_at, image_hashes}}
  render.py      # HTML + plain-text email via a template (proper escaping)
  notify/
    email.py     # SMTP, images embedded inline as CID attachments
    ntfy.py      # optional push (see §5)
  cli.py         # `python -m graphicast run [--force] [--dry-run] [--office OUN]`
config.toml      # offices, recipients, image size, quiet hours (no secrets)
tests/           # fixture XML → parsing, active-window filter, change detection, render
.github/workflows/graphicast.yml
```

Behaviour changes:
- Only consider **currently active** graphics; fingerprint = sorted (title, description,
  image URL, image SHA-256). Email only when the active set changes, or on `--force`.
- Fetch each office once, fan out to all recipients for it.
- Embed images in the email so it's a true snapshot.
- `--dry-run` writes the rendered HTML to a file (and the workflow uploads it as an artifact) for easy preview.
- Times rendered in the office's timezone (`zoneinfo`).
- Tooling: `pyproject.toml`, `uv`, `ruff`, `pytest`, CI on push.

## 5. Ideas beyond email (pick any, in rough order of effort)

1. **ntfy.sh push** — one HTTP POST per update with the image attached; free app on
   iOS/Android; zero infrastructure. Biggest win for least effort.
2. **Static web page / PWA on GitHub Pages** — the Action renders `index.html` with the
   current graphics plus a browsable **history archive** (images committed to the state/pages
   branch). Installable to home screen, works offline for the last snapshot.
3. **True Web Push from the PWA** — PWA subscribes with VAPID keys; for a single user the
   subscription JSON can be stored as a repo secret and the Action sends with `pywebpush`.
   No server needed. iOS supports this only for home-screen-installed PWAs (16.4+).
   Multi-user would need a tiny store (e.g. Cloudflare Worker + KV) — probably overkill.
4. Other channels behind the same `notify/` interface: Discord/Slack webhook, Telegram bot,
   Pushover.
5. **Add NWS alerts** (`api.weather.gov/alerts/active?zone=...`) so a warning/watch
   triggers a notification even when no new graphicast is posted.
6. Quiet hours / "digest at 7am, immediate during severe weather" modes.
7. Optional one-paragraph plain-language summary across all graphics (LLM) — only if wanted.

## 6. Task list

Phase 0 — decisions (see open questions)
- [ ] Answer open questions below

Phase 1 — rewrite, email parity
- [ ] Scaffold package, `pyproject.toml`, ruff, pytest
- [ ] Source interface: Mesonet (primary) + NWS XML (fallback), saved fixtures, fail loudly if all sources fail
- [ ] Active-window filter + content fingerprint (incl. image hashes)
- [ ] State store (JSON) + change detection; per-office fan-out
- [ ] Email renderer (HTML + text) with CID-embedded images
- [ ] SMTP sender using env secrets; `--dry-run`, `--force`
- [ ] Config file replacing Google Sheet; delete gspread/oauth2client code
- [ ] Rewrite README (setup, secrets, App Password, local run)

Phase 2 — move off the Pi
- [ ] Workflow: schedule + `workflow_dispatch(force)`; state committed to `state` branch
- [ ] Concurrency guard so overlapping runs don't race on state
- [ ] Run in parallel with the Pi for a few days, compare emails, then remove the cron job

Phase 3 — extras (as chosen)
- [ ] ntfy notifier
- [ ] GitHub Pages page + archive
- [ ] PWA manifest/service worker + Web Push
- [ ] NWS alerts integration

## 7. Decisions (2026-11-06)

| Topic | Decision |
|---|---|
| Recipients | Just the owner. One office: **OUN (Norman)**. No signup and no zip lookup; office and recipient set in config/secrets |
| Sending | **Gmail SMTP + App Password** (free, same as today). Secrets: `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` |
| Repo | **Public**: nothing personal in committed files; email address lives in a secret |
| Cadence | **3×/day**, email only when the active graphics changed. Exact times TBD; must handle Central time DST since cron is UTC |
| Image size | One size only (`FullImage`; NWS serves the same file for both today). Drop the option |
| Phone | iPhone. ntfy is an optional extra, not a requirement |
| Archive | No |
| Language | Python |
| Other Pi duties | None. Turn off the Pi cron once the Actions version is verified |

Dropped from scope: Google Sheets, gspread/oauth2client, zip→office lookup, multi-subscriber
fan-out, history archive, multi-user Web Push.

## 8. Remaining open questions

1. Exact send times (Central)? Suggestion: ~6:30am, 12:30pm, 5:30pm.
2. Email only on change (current behaviour), or always send at those times?
3. Want ntfy push in phase 1, later, or never?
