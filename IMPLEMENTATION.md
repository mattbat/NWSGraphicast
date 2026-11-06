# NWSGraphicast v2 — Implementation Spec

This is the build spec for the rewrite agreed in `PLAN.md`. It's written so that an implementer
with no other context can follow it. If this file and `PLAN.md` disagree, **this file wins**.

**Rules for implementers**
- Work only on branch `claude/eloquent-sagan-has6f5`. Never touch `master`.
- Runtime code uses the **Python standard library only** (Python ≥ 3.11). Dev tools: `pytest`, `ruff`.
- No network access in tests. Use the fixtures in `tests/fixtures/` and monkeypatching.
- Never commit secrets, email addresses or passwords. Read them from environment variables.
- Keep functions small and typed. No global mutable state.
- "Done" means `ruff check .`, `ruff format --check .` and `pytest -q` all pass.

---

## 1. Behaviour summary

Every run of `python -m graphicast`:

1. **Schedule gate** (skipped with `--force` or `--ignore-schedule`): decide whether this run
   is the first run for the current send slot (6:00, 12:00, 18:00 `America/Chicago`). If not,
   log `skip: ...` and exit 0. (§4.6)
2. **Fetch** graphics for office `oun`: Mesonet JSON first, then NWS XML. If both fail, exit 1.
   (§4.3)
3. **Filter** to graphics active now (`start <= now < end`), sorted by `order`.
4. **Download images** for active graphics. If one image fails, log a warning and fall back to
   linking that image by URL. That one failure doesn't fail the run.
5. **Fingerprint** the active set. (§4.4)
6. Decide whether to send:
   - With `--force`: always send (if there's at least one active graphic).
   - With **no active graphics**: don't send. Store the empty fingerprint.
   - If the fingerprint equals `state.offices[office].fingerprint`: don't send ("no change").
   - Otherwise: send.
7. **Render** the email with images embedded inline (CID). **Send** it via Gmail SMTP, or with
   `--dry-run` write it to `out/` and don't send.
8. **Save state** (unless `--dry-run`): `last_slot` always, and `fingerprint`/`sent_at`
   when the email was sent or the active set became empty.

Exit codes: `0` success (including skip and no change); `1` all sources failed or SMTP
failed; `2` bad configuration (missing env var).

---

## 2. File layout (create exactly this)

```
pyproject.toml
graphicast/
  __init__.py          # __version__ = "2.0.0"
  __main__.py          # from graphicast.cli import main; raise SystemExit(main())
  model.py
  http.py
  sources/
    __init__.py        # fetch_graphics(), AllSourcesFailed
    mesonet.py
    nws_xml.py
  fingerprint.py
  state.py
  schedule.py
  render.py
  notify/
    __init__.py
    email.py
  config.py
  cli.py
tests/
  conftest.py
  fixtures/mesonet_oun.json   # ALREADY PRESENT, do not modify
  fixtures/nws_oun.xml        # ALREADY PRESENT, do not modify
  test_sources.py
  test_model.py
  test_fingerprint.py
  test_state.py
  test_schedule.py
  test_render.py
  test_cli.py
.github/workflows/ci.yml
.github/workflows/graphicast.yml
README.md                     # rewrite
```
Delete `main.py` (it's preserved in git history).

**Fixture facts** (both captured at the same moment):
`FIXTURE_NOW = 1793968439` (Unix seconds, 2026-11-06 ~11:14 UTC).
- `mesonet_oun.json`: a JSON list of 3 graphics, numbers 2, 4, 1, all active at FIXTURE_NOW.
- `nws_oun.xml`: 7 `<graphicast>` elements under `<graphicasts>`. Only numbers 2, 4, 1 are
  active at FIXTURE_NOW; 3, 5, 6, 7 are expired.
- Titles and descriptions have leading/trailing whitespace and newlines, which must be stripped.
- Active titles: 1 "Next 7 Days", 2 "Friday Morning Fog", 4 "Cool This Weekend; Warming Next Week".
- Image URLs look like `https://www.weather.gov/images/oun/graphicast/2.png`. In the JSON the
  slashes are escaped (`https:\/\/`), which `json.loads` already decodes.

---

## 3. `pyproject.toml`

```toml
[project]
name = "graphicast"
version = "2.0.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6"]

[tool.setuptools]
packages = ["graphicast", "graphicast.sources", "graphicast.notify"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## 4. Modules

### 4.1 `model.py`

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Graphic:
    number: int              # graphicNumber
    order: int               # order (sort key)
    title: str               # stripped
    description: str | None  # stripped; None if empty or equals "none" (case-insensitive)
    image_url: str           # ImageLoop if radar == "1" and ImageLoop non-empty, else FullImage
    start: datetime          # tz-aware UTC, from StartTime epoch seconds
    end: datetime            # tz-aware UTC, from EndTime epoch seconds

    def is_active(self, now: datetime) -> bool:  # start <= now < end
        ...

def active_graphics(graphics: list[Graphic], now: datetime) -> list[Graphic]:
    """Active ones sorted by (order, number)."""

def graphic_from_fields(fields: dict[str, str]) -> Graphic:
    """Shared builder used by both sources. `fields` uses the raw feed keys:
    graphicNumber, order, title, description, FullImage, ImageLoop, radar, StartTime, EndTime.
    Raises ValueError (with the bad key named) on missing or invalid required fields
    (graphicNumber, StartTime, EndTime, FullImage). Missing order → use number."""
```

### 4.2 `http.py`

```python
USER_AGENT = "NWSGraphicast/2.0 (+https://github.com/mattbat/NWSGraphicast)"

def get_bytes(url: str, timeout: float = 20.0) -> bytes:
    """urllib.request GET with USER_AGENT header. Raises on HTTP errors (urllib default)."""
```
This is the only module that touches the network. Everything else takes bytes or a callable,
so tests can replace it.

### 4.3 `sources/`

- `mesonet.py`
  - `URL = "http://www.mesonet.org/index.php/api/nws_products/graphicast_info/{office}"`
  - `parse(text: str) -> list[Graphic]`: `json.loads`; it must be a list of dicts. Skip entries
    whose `Office == "No Image Available"`, which means no graphics. Build each with
    `graphic_from_fields`. If the top level isn't a list, raise `ValueError`.
- `nws_xml.py`
  - `URL = "https://www.weather.gov/source/{office}/graphicast/graphicast.xml"`
  - `parse(text: str) -> list[Graphic]`: `xml.etree.ElementTree.fromstring`. For each
    `.//graphicast` element, build a dict `{child.tag: child.text or ""}` and pass it to
    `graphic_from_fields`. If `<graphicasts>` is missing, raise `ValueError`.
- `__init__.py`

```python
class AllSourcesFailed(Exception): ...

SOURCES = [("mesonet", mesonet.URL, mesonet.parse), ("nws_xml", nws_xml.URL, nws_xml.parse)]

def fetch_graphics(office: str, get=http.get_bytes) -> tuple[str, list[Graphic]]:
    """Try each source in order. Return (source_name, graphics) from the first one that
    downloads AND parses without an exception. Log (logging.warning) each failure with
    the source name and error. If all fail, raise AllSourcesFailed listing every error.
    The office is lowercased before formatting the URL."""
```
An empty list from a source that parsed fine counts as success.

### 4.4 `fingerprint.py`

```python
def fingerprint(graphics: list[Graphic], images: dict[str, bytes]) -> str:
    """sha256 hex over a canonical JSON (sort_keys=True, separators=(",", ":")) of a list,
    sorted by number, of:
      {"number", "title", "description", "image_url",
       "image_sha256": sha256(images[url]).hexdigest() if url in images else None}
    Do NOT include start/end, so extending a graphic's validity isn't a change.
    The empty list gives a stable value; expose it as EMPTY_FINGERPRINT."""
```

### 4.5 `state.py`

The state file is JSON, kept on the `state` git branch (see §6):
```json
{"version": 1,
 "last_slot": "2026-11-06T06:00:00-06:00",
 "offices": {"oun": {"fingerprint": "<hex>", "sent_at": "2026-11-06T12:01:07+00:00"}}}
```
```python
def load_state(path: Path) -> dict:   # missing file or empty → {"version": 1, "last_slot": None, "offices": {}}
                                      # invalid JSON → log warning, return the same default
def save_state(path: Path, state: dict) -> None:  # mkdir parents; write indent=2 + "\n";
                                                  # atomic: write temp file in same dir then os.replace
```

### 4.6 `schedule.py`

```python
DEFAULT_TZ = "America/Chicago"
DEFAULT_HOURS = (6, 12, 18)
WINDOW = timedelta(hours=3)

def current_slot(now: datetime, tz: str = DEFAULT_TZ, hours=DEFAULT_HOURS) -> datetime | None:
    """The latest local slot time (today's or yesterday's) at or before `now`, as a
    tz-aware datetime in `tz`, if now - slot < WINDOW. Otherwise None.
    `now` is tz-aware (any zone). Use zoneinfo so DST is handled correctly."""

def should_run(now: datetime, last_slot_iso: str | None, tz=DEFAULT_TZ, hours=DEFAULT_HOURS
               ) -> tuple[bool, datetime | None, str]:
    """(run?, slot, reason). Run if current_slot is not None and slot.isoformat() != last_slot_iso."""
```
Required test cases (`test_schedule.py`):
- 2026-07-15 11:05 UTC (06:05 CDT) → slot 06:00 CDT, run.
- 2026-07-15 12:05 UTC (07:05 CDT), last_slot = that day's 06:00 → don't run (already done).
- 2026-07-15 12:05 UTC, last_slot None → run (catches a delayed or missed run).
- 2026-01-15 12:05 UTC (06:05 CST) → slot 06:00 CST, run.
- 2026-01-15 11:05 UTC (05:05 CST) → no slot (yesterday's 18:00 is > 3 h ago) → don't run.
- 2026-01-16 00:10 UTC (18:10 CST on Jan 15) → slot 2026-01-15 18:00 CST.
- DST-change days: 2026-03-08 and 2026-11-01 at 12:00 UTC and 13:00 UTC → correct local slot.

### 4.7 `render.py`

```python
def render_email(*, office: str, graphics: list[Graphic], images: dict[str, bytes],
                 now: datetime, tz: str, sender: str, to: str) -> email.message.EmailMessage:
```
- `Subject`: `f"NWS {office.upper()} Graphicast — {local:%a %b} {local.day}, {local:%-I:%M %p}"`.
  Avoid `%-I` (not portable): format the hour as `str(int(local.strftime("%I")))`.
- `From` = sender, `To` = to, `Date` = `email.utils.format_datetime(now)`.
- Body: `msg.set_content(plain_text)`, then `msg.add_alternative(html, subtype="html")`. Then
  for each graphic whose `image_url` is in `images`, add the image as a related part of the
  HTML alternative with `make_msgid()` CID. Sniff the subtype from the magic bytes:
  PNG `\x89PNG`, GIF `GIF8`, JPEG `\xff\xd8`, else `octet-stream`.
- HTML: minimal inline-styled markup. For each graphic in order: `<h2>` title, `<p>`
  description (if any), `<img src="cid:...">` (or `src="<image_url>"` if not downloaded) with
  `alt=title` and `style="max-width:100%;height:auto"`. Footer links:
  `https://www.weather.gov/{office}` ("NWS {OFFICE}") and `https://www.spc.noaa.gov/`
  ("Storm Prediction Center"). **Escape all feed text with `html.escape`.**
- Plain text: title, description, image URL for each graphic, then the footer links.
- Also `def render_html_preview(...) -> str` that returns the HTML with images inlined as
  `data:` URIs, for `--dry-run` previews.

### 4.8 `notify/email.py`

```python
def send_email(msg: EmailMessage, *, user: str, password: str,
               host: str = "smtp.gmail.com", port: int = 465, timeout: float = 30.0) -> None:
    """smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=timeout);
    login; send_message(msg)."""
```

### 4.9 `config.py`

```python
@dataclass(frozen=True)
class Config:
    office: str            # env GRAPHICAST_OFFICE, default "oun"
    tz: str                # env GRAPHICAST_TZ, default "America/Chicago"
    hours: tuple[int, ...] # env GRAPHICAST_HOURS "6,12,18"
    state_path: Path       # env GRAPHICAST_STATE, default "state/state.json"
    smtp_user: str | None  # env SMTP_USER
    smtp_password: str | None  # env SMTP_PASSWORD
    email_to: str | None   # env EMAIL_TO, default = smtp_user

def load_config(env: Mapping[str, str] = os.environ) -> Config: ...
class ConfigError(Exception): ...
def require_smtp(cfg: Config) -> None:  # raise ConfigError naming the missing vars
```
SMTP vars are only required when actually sending (not for `--dry-run` or skip/no-change runs).

### 4.10 `cli.py`

```python
def main(argv: list[str] | None = None, *, now: datetime | None = None,
         get=http.get_bytes, send=notify.email.send_email,
         env: Mapping[str, str] | None = None) -> int:
```
argparse flags: `--force`, `--dry-run`, `--ignore-schedule`, `--state PATH` (overrides config),
`--out DIR` (default `out`), `-v/--verbose`. Set up `logging.basicConfig` with level INFO
(DEBUG with -v), format `"%(levelname)s %(message)s"`.

It implements §1 exactly. With `--dry-run`, write `out/email.eml` (`msg.as_bytes()`) and
`out/email.html` (`render_html_preview`), log their paths, and don't send or save state.
Log one line at the end summarising the outcome, e.g. `result: sent 3 graphics (source=mesonet)`,
`result: no change`, `result: skip (slot 2026-11-06T06:00:00-06:00 already processed)`.
Image downloads use the injected `get`.

`test_cli.py` must cover (with fake `get` serving fixtures and fake PNG bytes, a fake `send`
that records messages, `tmp_path` state, and `now=FIXTURE_NOW` in UTC unless stated):
- First run (`--ignore-schedule`) → 1 email sent, 3 images attached, state written.
- Second identical run → no email, exit 0.
- Same graphics but one image's bytes changed → email sent.
- Mesonet raises → NWS XML used, same 3 graphics.
- Both raise → exit 1, no email, state untouched.
- `--dry-run` → files in out dir, no send, no state file.
- `--force` with an unchanged fingerprint → sent.
- Schedule gate: `now` = 07:30 Central with last_slot = today's 06:00 → skip, no fetch calls.
- Missing SMTP_USER when a send is needed → exit 2.
- One image download fails → email still sent, that image linked by URL, other two embedded.

---

## 5. `.github/workflows/ci.yml`

Runs on `push` and `pull_request`. One job on `ubuntu-latest`: checkout (`actions/checkout@v4`),
`actions/setup-python@v5` with `python-version: "3.12"`, `pip install -e ".[dev]"`,
`ruff check .`, `ruff format --check .`, `pytest -q`.

## 6. `.github/workflows/graphicast.yml`

```yaml
name: graphicast
on:
  schedule:
    # 6am/12pm/6pm Central in both CDT (11,17,23 UTC) and CST (12,18,0 UTC).
    # The script decides which run is the real one (see graphicast/schedule.py).
    - cron: "7 0,11,12,17,18,23 * * *"
  workflow_dispatch:
    inputs:
      force:
        description: "Send even if nothing changed"
        type: boolean
        default: false
      dry_run:
        description: "Render only; upload the email as an artifact, don't send"
        type: boolean
        default: false
permissions:
  contents: write   # push state branch
  actions: write    # keepalive
concurrency:
  group: graphicast
  cancel-in-progress: false
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Check out state branch
        run: |
          git config user.name "graphicast-bot"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          if git fetch origin state; then
            git worktree add state origin/state
          else
            git worktree add --orphan -b state state
          fi
      - name: Run
        env:
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          EMAIL_TO: ${{ secrets.EMAIL_TO }}
          GRAPHICAST_STATE: state/state.json
        run: |
          args=""
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then args="--ignore-schedule"; fi
          if [ "${{ inputs.force }}" = "true" ]; then args="$args --force"; fi
          if [ "${{ inputs.dry_run }}" = "true" ]; then args="$args --dry-run"; fi
          python -m graphicast $args
      - name: Save state
        if: ${{ inputs.dry_run != true }}
        run: |
          cd state
          git add state.json 2>/dev/null || exit 0
          git diff --cached --quiet && exit 0
          git commit -m "state: $(date -u +%FT%TZ)"
          git push origin HEAD:state
      - name: Upload preview
        if: ${{ inputs.dry_run == true }}
        uses: actions/upload-artifact@v4
        with: { name: email-preview, path: out/ }
      - uses: liskin/gh-workflow-keepalive@v1
```
Notes:
- Minute `7` avoids GitHub's top-of-the-hour congestion.
- `git worktree add --orphan` needs git ≥ 2.42, which ubuntu-latest has.
- `worktree add state origin/state` gives a detached HEAD, which is why the push is `HEAD:state`.
- The `state` directory must be in `.gitignore` on the main branch (add `state/` and `out/`).

## 7. `README.md` (rewrite)

Sections:
1. What it does (one paragraph).
2. How it runs: GitHub Actions schedule, 6am/12pm/6pm Central, emails only on change.
3. Setup:
   - Gmail: enable 2-Step Verification, create an App Password at
     https://myaccount.google.com/apppasswords.
   - Repo → Settings → Secrets and variables → Actions: `SMTP_USER`, `SMTP_PASSWORD`,
     `EMAIL_TO`.
   - Scheduled workflows only run from the default branch. The workflow must be on `master`.
   - Actions tab → graphicast → "Run workflow" with dry_run, then with force, to test.
4. Local run: `pip install -e ".[dev]"`, `python -m graphicast --dry-run --ignore-schedule`,
   `pytest`.
5. Configuration env vars table (§4.9).
6. Data sources and the fallback (Mesonet → NWS XML), and the fact that a failure means a red
   run plus GitHub's failure email.

---

## 8. Work packages (for parallel implementers)

| WP | Owns files | Depends on |
|----|-----------|------------|
| **A. Core** | `pyproject.toml`, `graphicast/__init__.py`, `model.py`, `http.py`, `sources/*`, `fingerprint.py`, `state.py`, `schedule.py`, `tests/conftest.py`, `tests/test_{sources,model,fingerprint,state,schedule}.py` | — |
| **B. App** | `render.py`, `notify/*`, `config.py`, `cli.py`, `__main__.py`, `tests/test_{render,cli}.py` | A's interfaces (§4.1–4.6) |
| **C. Ops** | `.github/workflows/*`, `README.md`, `.gitignore`, delete `main.py` | — |

`tests/conftest.py` (WP A) provides fixtures `FIXTURE_NOW` (a tz-aware UTC datetime),
`mesonet_text`, `nws_text` and `fake_get(mapping)`. `fake_get` returns a callable that serves
bytes by URL, or raises `urllib.error.URLError` for URLs mapped to an Exception.

Phase 3 (PWA + Web Push) is **out of scope** for this spec. It gets its own spec after v2 email
has been running on Actions.
