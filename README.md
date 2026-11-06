# NWSGraphicast

NWSGraphicast emails you the current National Weather Service "Graphicast" forecast images for a
forecast office (default: Norman, OK, `oun`). An email goes out only when the set of active
graphics has changed since the last one. The images are hosted on an `images` branch and linked,
so each email is only a few KB.

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

## Go-live checklist (moving off the Raspberry Pi)

1. Add the three secrets (see Setup).
2. Send a `[TEST]` email from the branch (next section) and check it on your phone: images,
   layout, dark mode.
3. Merge to `master`. Then Actions → graphicast → Run workflow, first with `dry_run`, then with
   `force`. That creates the `state` and `images` branches.
4. Run alongside the Pi for a few days (expect duplicates), then comment out the Pi's cron
   line (`crontab -e`).

## Testing a change by email (before merging)

`.github/workflows/test-email.yml` sends one real email from any branch except `master`. Push
a commit whose message **starts with** `[send-test-email]`. Once the workflow is on `master`, you
can also use Actions → test-email → Run workflow and pick a branch. The email's subject starts
with `[TEST]`. The run uses a throwaway state file, so the real schedule's change detection is
untouched. It publishes images to the `images` branch like a normal send. It needs the three
secrets above. If no graphics are active at that moment, nothing is sent.

## Local run

```
pip install -e ".[dev]"
python -m graphicast --dry-run --ignore-schedule
pytest -q --cov=graphicast --cov-fail-under=90   # tests with the 90% coverage gate (as in CI)
GRAPHICAST_LIVE=1 pytest -m live -q              # opt-in: fetch the real feeds
```

The live test hits the real Mesonet and NWS feeds and is skipped unless `GRAPHICAST_LIVE=1`.
CI runs it weekly (Mondays) and on manual dispatch to catch feed format changes early.

A dry run writes `out/email.eml`, `out/email.html` (a self-contained preview) and the converted
images in `out/images/`. It sends nothing, publishes nothing and doesn't save state.

| Flag | Effect |
|------|--------|
| `--dry-run` | Render to `out/` only |
| `--force` | Send even if nothing changed (also skips the schedule gate) |
| `--ignore-schedule` | Run now regardless of the 6/12/18 send slots |
| `--state PATH` | State file to use instead of `GRAPHICAST_STATE` |
| `--out DIR` | Dry-run output directory (default `out`) |
| `-v` | Debug logging |

Exit codes: 0 success (including skip and no change), 1 fetch, publish or send failed, 2 bad
configuration.

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `GRAPHICAST_OFFICE` | `oun` | NWS forecast office |
| `GRAPHICAST_OFFICE_NAME` | `Norman` | Office name shown in the email header and footer |
| `GRAPHICAST_SUBJECT_PREFIX` | none | Text put before the subject, e.g. `[TEST]` (the test-email workflow sets this) |
| `GRAPHICAST_TZ` | `America/Chicago` | Time zone for send slots |
| `GRAPHICAST_HOURS` | `6,12,18` | Local send hours |
| `GRAPHICAST_STATE` | `state/state.json` | State file path |
| `SMTP_USER` | none | Gmail address used to send (required to send) |
| `SMTP_PASSWORD` | none | Gmail App Password (required to send) |
| `EMAIL_TO` | `SMTP_USER` | Recipient |
| `GRAPHICAST_IMAGES_DIR` | none | Checkout of the `images` branch; with the base URL, enables hosting |
| `GRAPHICAST_IMAGES_BASE_URL` | none | Public URL prefix of that branch |
| `GRAPHICAST_IMAGE_DAYS` | `7` | Days before hosted image folders are deleted (at least 1) |
| `GRAPHICAST_LAT` | `35.6528` | Latitude of the point checked for severe weather (Edmond, OK) |
| `GRAPHICAST_LON` | `-97.4781` | Longitude of that point |
| `GRAPHICAST_PLACE_NAME` | `Edmond` | Place named in the banner ("outlook covers Edmond") |
| `GRAPHICAST_SEVERITY` | on | Set to `off` to disable the severe-weather flag entirely (no fetches, no flag, no banner) |

## Email design

The email is laid out without cards: a compact navy header bar (office name on the left, date and
time on the right, with an amber bottom edge), then for each graphic a text block with the title,
a "Valid until" time in your local time zone and the description, followed by the image at the
full width of the email and a "View on weather.gov" link. The page is white (near-black in dark
mode, through `prefers-color-scheme`). A graphic that is new or changed since the last send
carries a **NEW** tag (the first run, or a run with no saved per-graphic state, tags nothing). A
hidden preheader lists the graphic titles, with NEW ones first, so the inbox preview is useful.
If a hosted image has expired, a short caption shows instead of a broken image. When there is
severe weather to report, a banner joins the bottom of the header (see below). The design
references are [`docs/layout_mockup.py`](docs/layout_mockup.py) and
[`docs/email_mockup.py`](docs/email_mockup.py).

## Severe-weather flag

Each run checks the point set by `GRAPHICAST_LAT` / `GRAPHICAST_LON` (Edmond by default; it lies in the Norman office's area) against:

- the Storm Prediction Center categorical convective outlooks for days 1 to 3 (the highest
  category whose area contains the point: Marginal 1, Slight 2, Enhanced 3, Moderate 4, High 5;
  general thunderstorms are ignored);
- active alerts from api.weather.gov for that point: any Tornado, Severe Thunderstorm, Flash
  Flood, Blizzard, Winter Storm, Ice Storm, Extreme Cold/Heat, Excessive Heat, High Wind,
  Hurricane, Tropical Storm or Dust Storm **Watch** or **Warning** (advisories are ignored);
- keywords in the graphics' own titles and descriptions: tornadoes, large hail, damaging winds,
  severe storms, blizzard, ice, heavy snow and flash flooding. This is a soft note only. Text is
  split into sentences and **any sentence containing a negation (no, not, unlikely, without,
  none, n't) is skipped**, so "Tornadoes are not expected." is ignored. The same rule skips the
  whole sentence in "Severe storms possible; tornadoes unlikely."

**The flag.** The subject gets a leading warning sign, and a warning banner appears under the
header, when the outlook is **Slight (2/5) or higher** or there is any of the alerts above. A
Marginal outlook or keyword mentions alone only add a quieter "Heads up" banner, with no warning
sign in the subject.

**When it emails.** Besides the usual "graphics changed" trigger, a run sends when **the risk
rises** versus the baseline saved in the state file: the outlook reaches Slight or higher and is
above the saved level, or an alert event appears that was not in the saved set. Marginal alone
never triggers an email. The first run (or state from before this feature) only records a
baseline. The baseline is updated on every run where all sources answered, including runs that
send nothing, so a drop followed by a rise emails again. If a source fails, the failure is
logged, the run carries on, and the previous baseline is kept. Severity is not part of the
change fingerprint, and a rise with no active graphics sends nothing (there is nothing to show).
The log line says why an email went out: `reason=graphics changed`, `severity rose` or `forced`.

## Data sources

Graphics are fetched from the Oklahoma Mesonet JSON API first, then from the NWS XML feed
(`weather.gov/source/<office>/graphicast/graphicast.xml`) if that fails. Only graphics active at
the current time are used. If both sources fail, or sending fails, the run fails: you will see a
red run in Actions and GitHub sends its usual workflow failure email.

## Code layout

| Path | Purpose |
|------|---------|
| `graphicast/cli.py` | Entry point; the run sequence is documented at the top of the file |
| `graphicast/schedule.py` | 6/12/18 local send-slot gate, DST-aware |
| `graphicast/sources/` | Mesonet JSON and NWS XML parsers, plus the fallback logic |
| `graphicast/model.py` | `Graphic` dataclass and the "active now" filter |
| `graphicast/fingerprint.py` | Change detection (whole set and per graphic, for NEW tags) over titles, descriptions and image bytes |
| `graphicast/state.py` | `state.json` load/save (kept on the `state` branch) |
| `graphicast/severity.py` | Severe-weather flag: SPC outlook and alert parsing, point-in-polygon, keyword mentions |
| `graphicast/images.py` | PNG → JPEG conversion (Pillow) |
| `graphicast/publish.py` | Commit images to the `images` branch, prune old folders, push |
| `graphicast/render.py` | Email HTML and plain text |
| `graphicast/notify/email.py` | SMTP send |
| `graphicast/config.py` | Environment variable configuration |
| `graphicast/http.py` | The HTTP helpers, injectable in tests |
| `tests/` | Unit tests (no network) and an opt-in live test; `tests/fixtures/` holds real feed snapshots |
| `docs/` | The original [plan](docs/PLAN.md) and [implementation spec](docs/IMPLEMENTATION.md) |

## License

See `LICENSE`.
