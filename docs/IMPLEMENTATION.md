# NWSGraphicast v2 — Implementation Spec

This is the build spec for the rewrite agreed in [`PLAN.md`](PLAN.md). It's written so that an
implementer with no other context can follow it. If this file and `PLAN.md` disagree, **this file
wins**.

> **Status (2026-11-06): implemented.** The code and the [README](../README.md) describe
> current behaviour. Where sections 1–9 below differ from the code, it's because §10 changed it:
> - **§10 supersedes §4.7 image embedding.** Scheduled sends publish JPEGs to the `images`
>   branch and link them. Only local runs ("inline mode") embed images, and they embed JPEGs.
> - **Pillow is the one runtime dependency**, an exception to "standard library only".
> - The file layout also has `graphicast/images.py` and `graphicast/publish.py`.
> - The YAML in §6 is the original. The live `.github/workflows/graphicast.yml` adds
>   `pip install .` and an `images` branch checkout (§10.6).

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

## 9. Test requirements (all WPs)

- Every public function has at least one test, covering the happy path plus each error branch.
- **Coverage gate:** `pytest --cov=graphicast --cov-fail-under=90` must pass. `pytest-cov`
  is a dev dependency, and CI runs with the gate.
- Test edge cases, not just fixtures: empty feed, `"No Image Available"` entry, missing
  required field, non-numeric times, HTML/script characters in titles (must be escaped),
  unicode text, radar loop GIF, a graphic that starts exactly at `now` (active) or ends
  exactly at `now` (inactive), corrupt state file.
- **Live test (opt-in):** `tests/test_live.py`, marked `@pytest.mark.live` and skipped unless
  `GRAPHICAST_LIVE=1`. It fetches both real feeds for `oun` and asserts each parses and its
  graphics have https image URLs. Register the `live` marker in pyproject. The CI job doesn't
  run it. A separate weekly workflow job (`ci.yml`, `schedule: cron "23 15 * * 1"` plus
  `workflow_dispatch`) runs `GRAPHICAST_LIVE=1 pytest -m live` to catch feed format changes early.
- Tests never touch the real network (except `live`), the real clock, or real SMTP. Inject
  `now`, `get` and `send`.

Phase 3 (PWA + Web Push) is **out of scope** for this spec. It gets its own spec after v2 email
has been running on Actions.

---

## 10. Change 1: hosted, expiring JPEG images (replaces inline images for scheduled sends)

**Why:** inline PNGs make each email about 5.7 MB. Linking to NWS URLs is no good either,
because NWS reuses them, so old emails would show new images. Decision: convert to JPEG,
commit to an `images` branch under a unique folder per send, link to
`raw.githubusercontent.com`, and delete folders older than 7 days. Emails become about 10 KB.

### 10.1 Behaviour

Two image modes, chosen by config:
- **hosted mode:** both `GRAPHICAST_IMAGES_DIR` and `GRAPHICAST_IMAGES_BASE_URL` are set
  (the GitHub workflow sets them). Images are published, then linked by URL. The email has
  **no attachments**.
- **inline mode:** either one is unset (local runs, tests). Same as today: CID-embedded
  images, but as JPEG.

The send path in `cli.main` (not dry-run, `send_it` true) becomes:
1. Convert the downloaded images to JPEG (§10.2). Fingerprinting still uses the **original**
   bytes, before conversion.
2. Hosted mode: `publish_images(...)` (§10.3) → `{image_url: hosted_url}`. If it raises,
   log an error, exit 1, don't send, and don't save state.
3. Render with `hosted_urls` (§10.4) and send.

`--dry-run` behaves as before (data-URI preview, no publish). It also writes the converted
JPEGs to `out/images/` so you can check their sizes.

### 10.2 `graphicast/images.py` (new)

```python
def to_jpeg(data: bytes, *, quality: int = 82) -> tuple[bytes, str]:
    """Return (bytes, extension). PNG/JPEG/other still images → RGB JPEG (Pillow,
    optimize=True), extension "jpg". Animated GIFs (Pillow `is_animated`) are returned
    unchanged with extension "gif". Bytes Pillow can't open are returned unchanged with
    extension "bin", plus a logged warning."""

def convert_all(images: dict[str, bytes]) -> dict[str, tuple[bytes, str]]:
    """Map image_url -> to_jpeg(data)."""
```
`Pillow>=10` becomes the single runtime dependency (`dependencies = ["Pillow>=10"]`). Convert
RGBA/P mode to RGB onto a white background, not black.

### 10.3 `graphicast/publish.py` (new)

```python
FOLDER_FMT = "%Y%m%dT%H%M%SZ"   # UTC, e.g. 20261106T120712Z

def publish_images(*, repo_dir: Path, base_url: str, graphics: list[Graphic],
                   converted: dict[str, tuple[bytes, str]], now: datetime,
                   retention_days: int = 7, branch: str = "images",
                   git: Callable[..., str] = run_git,
                   check_url: Callable[[str], bool] = url_ok) -> dict[str, str]:
```
1. `folder = now.astimezone(UTC).strftime(FOLDER_FMT)`. Write each graphic's converted image
   to `repo_dir/folder/<number>.<ext>`.
2. **Prune:** delete every top-level dir in `repo_dir` whose name parses with `FOLDER_FMT` and
   is older than `now - retention_days`. Leave other files, `.git` and dirs with names that
   don't parse untouched.
3. **Publish as a single history-less commit:** run `git add -A`, then `git write-tree` to
   get `tree`, then `git commit-tree <tree> -m "images <folder>"` to get `commit`, then
   `git push --force origin <commit>:refs/heads/<branch>`. Run every command with
   `cwd=repo_dir`. `run_git(*args, cwd)` is a thin `subprocess.run(["git", *args], check=True,
   capture_output=True, text=True)` wrapper that returns stripped stdout.
4. URLs: `f"{base_url.rstrip('/')}/{folder}/{number}.{ext}"`.
5. **Verify:** call `check_url` on the first URL up to 5 times, sleeping 3 s between tries
   (inject `sleep` for tests). If it never returns True, log a warning and continue. Don't
   fail the run, because the link usually works a moment later.
6. Return `{graphic.image_url: hosted_url}`.

`url_ok(url)` does an HTTP HEAD through `graphicast.http` (add `head_ok(url, timeout)` there)
and returns True on 200.

### 10.4 Rendering changes (`render.py`)

- `render_email(..., hosted_urls: dict[str, str] | None = None)`. When given, each graphic's
  `<img src>` is its hosted URL and nothing is attached. Otherwise CID-embed the converted
  JPEGs as today. The `images` passed in are now the converted bytes. Sniffing handles JPEG
  already.
- Under each image add a small link: `<a href="{original NWS image_url}">Current version on
  weather.gov</a>`. Keep the footer links (NWS office page, SPC). The plain-text part lists
  the hosted URL (if any) and the NWS URL.
- Add `alt` text and `width="100%"` so the layout holds even after hosted images expire.

### 10.5 Config additions (`config.py`)

| env | field | default |
|---|---|---|
| `GRAPHICAST_IMAGES_DIR` | `images_dir: Path \| None` | None |
| `GRAPHICAST_IMAGES_BASE_URL` | `images_base_url: str \| None` | None |
| `GRAPHICAST_IMAGE_DAYS` | `image_days: int` | 7 (must be ≥ 1, else ConfigError) |

Add the property `hosted: bool` (both set).

### 10.6 Workflow changes (`graphicast.yml`)

- Add `- run: pip install .` after setup-python, because Pillow is now required.
- Add an images worktree step next to the state one:
  ```bash
  if git fetch origin images; then git worktree add images origin/images
  else git worktree add --orphan -b images images; fi
  ```
- Run step env: `GRAPHICAST_IMAGES_DIR: images` and
  `GRAPHICAST_IMAGES_BASE_URL: https://raw.githubusercontent.com/${{ github.repository }}/images`.
- `.gitignore`: add `images/`.
- Update the README: how image hosting works, the 7-day expiry, and that the `images` branch is
  force-pushed and has no history.

### 10.7 Tests (coverage gate still 90%)

- `test_images.py`: a PNG built with Pillow in memory → JPEG magic `\xff\xd8`, ext "jpg",
  smaller than a large noisy PNG; RGBA → white background (check a pixel); animated GIF
  unchanged with ext "gif"; garbage bytes → unchanged with ext "bin".
- `test_publish.py`: use a **real temporary git repo** (`git init` in tmp_path, plus a bare
  repo as `origin`) so the git sequence is actually exercised. Check the files are written,
  the push reaches the bare repo's `images` branch with exactly one commit (no parents), old
  folders are pruned while recent ones are kept, non-matching names are untouched,
  `check_url` is retried and failure only warns, and a git failure raises.
- `test_render.py`: in hosted mode the message has no image parts, `img src` equals the hosted
  URLs, the NWS link is present, and the total `as_bytes()` is < 50 KB.
- `test_cli.py`: in hosted mode, publish is called before send (record call order); publish
  failure → exit 1, no send, state untouched; in inline mode, images are attached as JPEG.

---

## 11. Change 2: premium email design ("A", navy + amber, matched background)

**Visual reference:** `docs/email_mockup.py`. The `email()` function there is the approved
look: match its markup, spacing, colours and typography. (`app_frame()` only fakes the mail
app for screenshots; don't port it.)

### 11.1 Design tokens (light)

| Token | Value | Use |
|---|---|---|
| page | `#f7fafb` | email background (matched to the owner's mail app) |
| card | `#ffffff` | graphic cards |
| line | `#e4eaee` | card hairline border |
| navy / navy2 | `#0b1f3a` / `#14325c` | header gradient, titles |
| amber | `#f5a524` | header kicker, 4 px header bottom border, "valid" dot |
| body | `#3b4654` | descriptions |
| meta | `#7a8594` | valid-until line |
| link | `#1d4f91` | links |
| badge | bg `#fff4dc`, fg `#8a4b00` | NEW tag |
| shadow | `0 1px 2px rgba(16,24,40,.05),0 6px 16px rgba(16,24,40,.06)` | header and cards |

**Dark tokens** (applied in `@media (prefers-color-scheme: dark)` through CSS classes with
`!important`; inline styles carry the light values):
page `#0f1318`, card `#182029`, line `#26303c`, title `#e8eef6`, body `#c3cfdd`, meta
`#8b9bb0`, link `#8ab4ff`, badge bg `#3a2a0a` fg `#fcd34d`. The header stays navy.
Add `<meta name="color-scheme" content="light dark">` and
`<meta name="supported-color-schemes" content="light dark">`.

Keep the layout to tables with inline styles (`role="presentation"`), max width 640 px. No
external CSS, fonts or scripts.

### 11.2 Structure (top to bottom)

1. **Preheader:** a hidden div (`display:none;max-height:0;overflow:hidden;opacity:0`) holding
   the graphic titles joined with ` · `, NEW ones first and prefixed `New: `. Pad it with
   about 60 `&#8203;&nbsp;` so the body text doesn't leak into the inbox preview.
2. **Header card:** kicker `NWS {OFFICE_NAME upper} · GRAPHICAST`; title `Forecast update`; meta
   `{Weekday, Month D} · {h:MM AM} · {n} graphic(s)` in local time (singular when n == 1).
3. **One card per active graphic, in feed order:**
   - title, plus a `NEW` badge if it's in `new_numbers`
   - `● Valid until {Ddd h:MM AM}` in local tz, with an amber dot
   - description (if any)
   - image: hosted URL, CID or NWS URL as today. Rounded 10 px, `width="100%"`.
   - **Expired/blocked image fallback:** `alt="{title} (image unavailable, see weather.gov
     link below)"` with `font-size:13px;color:#7a8594`, so a broken image shows a tidy caption.
   - `View on weather.gov →` linking the original NWS image URL
4. **Footer:** `NWS {OFFICE_NAME}` (https://www.weather.gov/{office}) · `Storm Prediction
   Center` links. Then: `Sent when NWS {OFFICE_NAME} updates its graphics`. In hosted mode
   append ` · images expire after {image_days} days`.

**Plain-text part:** the same order. Title (prefixed `[NEW] ` when new), `Valid until …`,
description, image URL (hosted if any), `View on weather.gov: <url>`, then the footer links.

**Subject:** unchanged.

### 11.3 NEW tags: per-graphic change tracking

- `fingerprint.py`: add `graphic_hashes(graphics, images) -> dict[str, str]`, mapping
  `str(number)` to the sha256 of the same canonical per-graphic dict `fingerprint()` uses
  (refactor so both share one helper). `fingerprint()`'s value must not change.
- State, per office: `{"fingerprint", "sent_at", "graphics": {"<number>": "<hash>"}}`.
  Write `graphics` whenever `fingerprint` is written.
- `new_numbers` = graphics whose hash differs from, or is missing in, the previous
  `graphics` map. **If there's no previous map** (first run, or old state), no graphic is NEW.
  `--force` doesn't change this.
- Pass `new_numbers` to `render_email`/`render_html_preview`. Dry-run uses the same logic.

### 11.4 Config

`GRAPHICAST_OFFICE_NAME`, default `Norman`, gives the `office_name: str` field. Add it to the
README table.

### 11.5 Render API

```python
render_email(*, office, office_name, graphics, images, now, tz, sender, to,
             hosted_urls=None, new_numbers=frozenset(), image_days=None) -> EmailMessage
render_html_preview(*, office, office_name, graphics, images, now, tz,
                    new_numbers=frozenset(), image_days=None) -> str
```
Use one HTML builder for both (the preview only swaps the image `src` for `data:` URIs).
Keep `html.escape` on every feed string, including in the preheader and alt text.

### 11.6 Tests

- Render:
  - the page background is `#f7fafb`, and the header and amber border are present
  - the dark-mode `<style>` block and the color-scheme metas are present
  - the preheader holds the titles, with NEW ones first and prefixed
  - a NEW badge appears only on graphics in `new_numbers`
  - the "Valid until" text is right for a known UTC `end` in CST and in CDT
  - "1 graphic" vs "3 graphics"
  - the alt fallback text is there
  - the "images expire after N days" text appears only in hosted mode
  - `<script>` in a title or description is escaped everywhere
  - hosted email size is still < 50 KB
- Fingerprint: `graphic_hashes` is stable, changes only for the graphic whose image bytes
  changed, and `fingerprint()` keeps the value it had before this refactor (hard-code the hex
  of a fixed input, computed before the change).
- CLI:
  - first run → no NEW
  - second run with one changed image → exactly that graphic NEW, and the state `graphics`
    map is updated
  - state from before this change (no `graphics` key) → no NEW, no crash
- Coverage gate stays at 90%.

---

## 12. Change 3: layout B, compact header, severe-weather flag

Decisions (2026-11-06): layout **B** (no cards, full-width images), **compact header**,
⚠️ in the subject at **SPC Slight (2/5) or higher, or any severe/winter watch or warning**,
**email when the risk goes up**, and a soft **keyword note** in the body.

Visual reference: `docs/layout_mockup.py`. `no_cards()` is layout B and `header(severe)` is the
compact header and banner. Match it.

### 12.1 Layout B + compact header (`render.py`)

- The page background becomes **white `#ffffff`**. Cards and card shadows go away.
- **Header:** one navy bar, `border-radius:12px`, `3px solid` amber bottom border, padding
  `11px 14px`, inset 8 px from the sides. Left: `NWS {OFFICE_NAME} · GRAPHICAST` (amber,
  11 px, letter-spacing .12em). Right: `{Ddd Mon D} · {h:MM AM}` (12 px, `#c9d4e3`). Remove the
  "Forecast update" title and the graphic count.
- **Each graphic:** a text block with 10 px side padding (title 18 px/700 navy, NEW badge,
  `● Valid until`, description). Then the image at **full email width** (`padding:0`, no
  radius, `display:block;width:100%`). Then the `View on weather.gov →` link row with a
  `1px #e4eaee` bottom border, then a 14 px spacer.
- Keep: dark mode (page `#0f1318`, divider `#26303c`; text tokens as in §11.1), preheader, alt
  fallback, footer.

### 12.2 `graphicast/severity.py` (new)

```python
SPC_URL = "https://www.spc.noaa.gov/products/outlook/day{day}otlk_cat.lyr.geojson"  # day 1..3
ALERTS_URL = "https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
LEVELS = {"MRGL": (1, "Marginal"), "SLGT": (2, "Slight"), "ENH": (3, "Enhanced"),
          "MDT": (4, "Moderate"), "HIGH": (5, "High")}       # TSTM and others are ignored
FLAG_LEVEL = 2

@dataclass(frozen=True)
class Outlook:  day: int; level: int; name: str; valid: datetime   # VALID_ISO, UTC
@dataclass(frozen=True)
class Alert:    event: str; headline: str
@dataclass(frozen=True)
class Severity:
    outlooks: tuple[Outlook, ...]   # only days with level >= 1, sorted by day
    alerts: tuple[Alert, ...]
    mentions: tuple[str, ...]       # canonical keyword labels, de-duplicated, in order found
    ok: bool                        # False if any official source failed (see 12.4)
    max_level -> int                # property: 0 if no outlooks
    flagged -> bool                 # property: max_level >= FLAG_LEVEL or bool(alerts)
```

- **Point in polygon:** `point_in_geometry(lon, lat, geometry) -> bool` for GeoJSON `Polygon`
  and `MultiPolygon`. Use even-odd ray casting. The first ring is the outer boundary, later
  rings are holes. Coordinates are `[lon, lat]`. Pure stdlib.
- `parse_spc(text, day, lat, lon) -> Outlook | None` returns the **highest** level whose
  geometry contains the point, or None.
- **Alerts:** `parse_alerts(text) -> tuple[Alert, ...]` keeps features whose
  `properties.event` ends in `Watch` or `Warning` **and** contains one of: `Tornado`,
  `Severe Thunderstorm`, `Flash Flood`, `Blizzard`, `Winter Storm`, `Ice Storm`,
  `Extreme Cold`, `Extreme Heat`, `Excessive Heat`, `High Wind`, `Hurricane`,
  `Tropical Storm`, `Dust Storm`. De-duplicate by event name. The api.weather.gov request must
  send the existing User-Agent (`http.get_bytes` already does).
- **Keywords:** `find_mentions(graphics) -> tuple[str, ...]` scans titles and descriptions.
  Split them into sentences on `[.!?]` and newlines. **Skip any sentence that matches the
  negation regex** `\b(no|not|unlikely|without|none)\b|n't\b` (case-insensitive). Patterns →
  labels:
  `tornado(es)?` → tornadoes; `(large|very large|giant) hail` → large hail;
  `(damaging|destructive) winds?` → damaging winds; `severe (storms?|thunderstorms?|weather)` →
  severe storms; `blizzard` → blizzard; `ice storm|freezing rain|icing` → ice;
  `heavy snow|winter storm` → heavy snow; `flash flood(ing)?` → flash flooding.
- `assess(graphics, lat, lon, get) -> Severity` fetches days 1–3 and the alerts. **Each
  failure is logged as a warning and never raises.** Any failure sets `ok=False`. Mentions are
  computed from the graphics, which are already fetched.

### 12.3 Config

`GRAPHICAST_LAT` (default `35.2226`) and `GRAPHICAST_LON` (default `-97.4395`) are Norman.
`GRAPHICAST_SEVERITY` set to `off` disables §12 entirely: no fetches, no flag. Add them to the
README table.

### 12.4 When to email, and state

Per office, the state gains `"severity": {"max_level": int, "alerts": [sorted event names]}`.

- A run sends if **the fingerprint changed** (as today), **or** `--force`, **or** a **severity
  rise**:
  - a rise means a saved baseline exists **and** `ok` is True **and** either
    (`max_level >= FLAG_LEVEL` and `max_level > saved.max_level`) or an alert event is present
    that isn't in `saved.alerts`.
  - **No saved baseline** (first run, or state from before this change) → no rise. Just record
    the baseline.
  - Marginal (level 1) never triggers an email on its own.
- Save `severity` on every run where `ok` is True, including no-send runs, so a drop followed
  by a rise triggers again. If `ok` is False, keep the previous saved value.
- Severity is **not** part of the fingerprint, and the fingerprint and NEW logic stay
  unchanged.
- If there are no active graphics but there's a severity rise, still send nothing (there are
  no images to show). Log it.
- `outcome` logs the reason: `sent ... (reason=graphics changed|severity rose|forced)`.

### 12.5 Subject, banner, preheader, plain text

- **Subject:** if `flagged`, prepend `⚠️ ` (U+26A0 U+FE0F + space). The `[TEST]` prefix stays
  outermost: `[TEST] ⚠️ NWS OUN Graphicast — …`.
- **Banner** (under the header, as in `header(severe)` in the mockup). One line per item:
  - Outlook lines: `{Name} Risk ({level}/5) of severe storms, {day label}`. The day label is
    `today` if the outlook's `valid` date (local tz) is today, else the weekday name
    (`Saturday`). Then a smaller line: `Storm Prediction Center Day {n} outlook covers
    {OFFICE_NAME}.`
  - Alert lines: `{event}` in bold, then the headline.
  - Mentions line: `Graphics mention: tornadoes, large hail`.
- **Style:** if `flagged`, use the warning style (bg `#fff4e5`, border `#f3c27a`, title colour
  `#b42318`, ⚠️ icon). If only Marginal and/or mentions, use an info style (bg `#f3f6f9`, border
  `#dce3ea`, text `#3b4654`, no ⚠️, title "Heads up"). With nothing to show, there's no banner
  and the header keeps its amber border.
- **Preheader:** if `flagged`, start with the first banner line, then the titles as today.
- **Plain text:** the banner lines at the top, prefixed `!! ` when flagged.

### 12.6 Tests (coverage gate 90%)

- **Geometry:**
  - inside/outside a square
  - a point inside a hole → outside
  - a MultiPolygon with the point in its second polygon
  - a point near an edge
- **SPC:**
  - The real fixture `tests/fixtures/spc_day1_20261106.geojson` parses and returns None for a
    point in the Atlantic. Also assert the result for Norman's default point, whatever the real
    fixture yields; compute it when writing the test.
  - A synthetic GeoJSON with nested `MRGL`/`SLGT`/`ENH` polygons around a point → ENH (3).
  - `TSTM` only → None.
- **Alerts:** a synthetic `FeatureCollection` with `Tornado Watch`, `Wind Advisory` and
  `Winter Storm Warning` → keeps the watch and the warning. Duplicates are de-duplicated.
- **Mentions:** each must be its own test case.
  - "Tornadoes are not expected." → ()
  - "No severe weather is anticipated." → ()
  - "A few tornadoes are possible Saturday evening." → ("tornadoes",)
  - "Large hail and damaging winds are the main threats." → ("large hail", "damaging winds")
  - "Severe storms possible; tornadoes unlikely." → ("severe storms",). The negation sits in
    the same sentence, so expect `()`; write the test to the actual rule and note it in the
    docstring.
  - "Heavy snow and blizzard conditions." → ("heavy snow", "blizzard")
- **assess:** all sources succeed; one SPC day fails → `ok=False` and the others are still
  used; alerts fail → `ok=False`; never raises.
- **CLI:**
  - Slight with no baseline → no send, baseline saved.
  - baseline 1 → 2 with unchanged graphics → sends with reason "severity rose", ⚠️ in the
    subject.
  - 2 → 2 → no send.
  - 3 → 1 → no send, and 1 is saved.
  - 1 → 2 again → sends.
  - Marginal 0 → 1 → no send.
  - A new Tornado Watch → sends.
  - Severity fetch failures → the run still succeeds and the previous severity is kept.
  - `GRAPHICAST_SEVERITY=off` → no severity URLs fetched.
  - `[TEST]` + ⚠️ ordering.
- **Render:**
  - white page
  - no card borders
  - full-width image (`padding:0`)
  - the compact header has no "Forecast update"
  - warning banner vs info banner vs no banner
  - "today" vs weekday label
  - banner text escaped
- **Live:** extend `tests/test_live.py` to call `assess` against the real APIs and assert it
  returns a `Severity` (any values).
