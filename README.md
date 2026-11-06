# NWSGraphicast

NWSGraphicast emails you the current National Weather Service "Graphicast" forecast images for a
forecast office (default: Norman, OK, `oun`). In scheduled runs the images are hosted on an `images` branch and linked from the email (about
10 KB per email); it is sent only when the set of active graphics has changed since the last email.

## How it runs

A GitHub Actions workflow (`.github/workflows/graphicast.yml`) runs the Python package on a
schedule. Emails go out at 6am, 12pm and 6pm Central time, and only when something changed. The
cron fires at both the CDT and CST UTC hours; `graphicast/schedule.py` makes sure only the first
run in each slot does any work. The last sent state is kept on a `state` git branch.

## Image hosting

NWS reuses its image URLs, so linking to them would make old emails show new images. Instead each
send converts the images to JPEG (Pillow), commits them to the `images` branch under a unique
folder named by the UTC send time (for example `20261106T120712Z/`), and links to
`raw.githubusercontent.com`. Folders older than 7 days (`GRAPHICAST_IMAGE_DAYS`) are deleted, so
links in old emails expire. The `images` branch is force-pushed as a single commit with no
history, so it never grows. Each email also links to the current version on weather.gov. Hosting
is on when both `GRAPHICAST_IMAGES_DIR` and `GRAPHICAST_IMAGES_BASE_URL` are set (the workflow
does this); otherwise (local runs) the JPEGs are embedded inline in the email.

The earlier Raspberry Pi / Google Sheets version is preserved in git history (commit `50acc5f`).

## Setup

1. Gmail: enable 2-Step Verification, then create an App Password at
   https://myaccount.google.com/apppasswords.
2. In the repo, go to Settings > Secrets and variables > Actions and add these secrets:
   `SMTP_USER` (the Gmail address that sends), `SMTP_PASSWORD` (the App Password) and `EMAIL_TO`
   (the recipient).
3. Scheduled workflows only run from the default branch, so the workflow must be on `master`.
4. To test, open the Actions tab, choose "graphicast" and "Run workflow": first with `dry_run`
   (the rendered email is uploaded as an artifact), then with `force` to send a real email.

## Local run

```
pip install -e ".[dev]"
python -m graphicast --dry-run --ignore-schedule
pytest -q --cov=graphicast --cov-fail-under=90   # tests with the 90% coverage gate (as in CI)
GRAPHICAST_LIVE=1 pytest -m live -q              # opt-in: fetch the real feeds
```

The live test hits the real Mesonet and NWS feeds and is skipped unless `GRAPHICAST_LIVE=1`.
CI runs it weekly (Mondays) and on manual dispatch to catch feed format changes early.

A dry run writes `out/email.eml`, `out/email.html` and the converted JPEGs in `out/images/`, and
sends nothing. Other flags: `--force`,
`--ignore-schedule`, `--state PATH`, `--out DIR`, `-v`. Exit codes: 0 success (including skip and
no change), 1 all sources or SMTP failed, 2 bad configuration.

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `GRAPHICAST_OFFICE` | `oun` | NWS forecast office |
| `GRAPHICAST_TZ` | `America/Chicago` | Time zone for send slots |
| `GRAPHICAST_HOURS` | `6,12,18` | Local send hours |
| `GRAPHICAST_STATE` | `state/state.json` | State file path |
| `SMTP_USER` | none | Gmail address used to send (required to send) |
| `SMTP_PASSWORD` | none | Gmail App Password (required to send) |
| `EMAIL_TO` | `SMTP_USER` | Recipient |
| `GRAPHICAST_IMAGES_DIR` | none | Checkout of the `images` branch; with the base URL, enables hosting |
| `GRAPHICAST_IMAGES_BASE_URL` | none | Public URL prefix of that branch |
| `GRAPHICAST_IMAGE_DAYS` | `7` | Days before hosted image folders are deleted (at least 1) |

## Data sources

Graphics are fetched from the Oklahoma Mesonet JSON API first, then from the NWS XML feed
(`weather.gov/source/<office>/graphicast/graphicast.xml`) if that fails. Only graphics active at
the current time are used. If both sources fail, or sending fails, the run fails: you will see a
red run in Actions and GitHub sends its usual workflow failure email.

## License

See `LICENSE`.
