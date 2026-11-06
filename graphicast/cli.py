"""Command-line entry point: `python -m graphicast`.

A run is one of two modes. The workflow fires every 15 minutes; the schedule gate decides.

Watch run (any run that is not the first in a 6/12/18 local send slot): with severity on, fetch
only the SPC outlooks and active alerts. If the risk did not rise, save the snapshot and stop.
If it rose, continue with steps 2-6 below (reason=severity rose) without consuming the slot.
With severity off, skip with no fetches.

Slot run (first run in a slot, or --force / --ignore-schedule), steps 1-6:
1. Assess the official severity sources (SPC outlooks, active alerts for the configured point)
   unless GRAPHICAST_SEVERITY=off. A failed source never fails the run.
2. Fetch the office's graphics (Mesonet, falling back to the NWS XML feed).
3. Keep the graphics active now, download their images, and fingerprint the set.
4. Add keyword mentions from the active graphics to the severity result.
5. If the fingerprint changed, a severity rise was detected, or with --force, convert the
   images to JPEG, publish them (hosted mode) or embed them (inline mode), and send the email.
6. Save state: the processed slot, after a send the new fingerprint and per-graphic hashes
   (used to tag changed graphics NEW), and the severity baseline whenever it was assessed ok.

Exit codes: 0 success (including skip and no change), 1 fetch/publish/send failure,
2 configuration error.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from graphicast import http
from graphicast.config import Config, ConfigError, load_config, require_smtp
from graphicast.fingerprint import EMPTY_FINGERPRINT, fingerprint, graphic_hashes
from graphicast.images import convert_all
from graphicast.model import Graphic, active_graphics
from graphicast.notify.email import send_email
from graphicast.publish import publish_images
from graphicast.render import render_email, render_html_preview
from graphicast.schedule import should_run
from graphicast.severity import (
    Severity,
    assess_official,
    severity_rose,
    snapshot,
    with_mentions,
)
from graphicast.sources import AllSourcesFailed, fetch_graphics
from graphicast.state import load_state, save_state

log = logging.getLogger("graphicast")

# Placeholder addresses so --dry-run can render an email without SMTP settings.
DRY_RUN_SENDER = "graphicast@example.invalid"
DRY_RUN_RECIPIENT = "recipient@example.invalid"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="graphicast", description="Email NWS Graphicast images.")
    p.add_argument("--force", action="store_true", help="send even if nothing changed")
    p.add_argument("--dry-run", action="store_true", help="write out/ files; no send, no state")
    p.add_argument("--ignore-schedule", action="store_true", help="skip the schedule gate")
    p.add_argument("--state", type=Path, default=None, help="state file (overrides config)")
    p.add_argument("--out", type=Path, default=Path("out"), help="dry-run output directory")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _download_images(graphics: list[Graphic], get: Callable[..., bytes]) -> dict[str, bytes]:
    """Download each distinct image URL. Failures are logged and skipped; the email then
    links that graphic to its weather.gov URL instead."""
    images: dict[str, bytes] = {}
    for g in graphics:
        if g.image_url in images:
            continue
        try:
            images[g.image_url] = get(g.image_url)
        except Exception as exc:
            log.warning("image download failed for %s: %s (linking by URL)", g.image_url, exc)
    return images


def _new_numbers(previous: Mapping[str, str] | None, hashes: Mapping[str, str]) -> frozenset[int]:
    """Graphic numbers whose hash differs from (or is missing in) the previous send.
    With no previous map (first run, or state from before NEW tags) nothing is NEW."""
    if previous is None:
        return frozenset()
    return frozenset(int(n) for n, h in hashes.items() if previous.get(n) != h)


def _write_dry_run(
    out: Path,
    cfg: Config,
    active: list[Graphic],
    converted: dict[str, tuple[bytes, str]],
    now: datetime,
    new_numbers: frozenset[int],
    severity: Severity | None = None,
) -> None:
    """Write the email (.eml), a self-contained HTML preview and the converted images."""
    jpegs = {url: data for url, (data, _ext) in converted.items()}
    msg = render_email(
        office=cfg.office,
        office_name=cfg.office_name,
        graphics=active,
        images=jpegs,
        now=now,
        tz=cfg.tz,
        sender=cfg.smtp_user or DRY_RUN_SENDER,
        to=cfg.email_to or DRY_RUN_RECIPIENT,
        new_numbers=new_numbers,
        severity=severity,
        place_name=cfg.place_name,
    )
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for g in active:
        if g.image_url in converted:
            data, ext = converted[g.image_url]
            (images_dir / f"{g.number}.{ext}").write_bytes(data)
    (out / "email.eml").write_bytes(msg.as_bytes())
    preview = render_html_preview(
        office=cfg.office,
        office_name=cfg.office_name,
        graphics=active,
        images=jpegs,
        now=now,
        tz=cfg.tz,
        new_numbers=new_numbers,
        severity=severity,
        place_name=cfg.place_name,
    )
    (out / "email.html").write_text(preview, encoding="utf-8")
    log.info("wrote %s, %s and %s", out / "email.eml", out / "email.html", images_dir)


def _pipeline(
    args: argparse.Namespace,
    cfg: Config,
    state: dict,
    state_path: Path,
    now: datetime,
    *,
    official: Severity | None,
    slot_iso: str | None,
    watch: bool,
    get: Callable[..., bytes],
    send: Callable[..., None],
    publish: Callable[..., dict[str, str]],
) -> int:
    """Fetch graphics, render, publish, send and save state. Shared by slot and watch runs.

    `official` is the severity from the official sources (None when disabled). `watch` means
    the run was started by a severity rise: it always sends with reason=severity rose and
    never touches `last_slot` (`slot_iso` is None)."""
    try:
        source, graphics = fetch_graphics(cfg.office, get=get)
    except AllSourcesFailed as exc:
        log.error("all sources failed: %s", exc)
        return 1

    # Filter, download, fingerprint (on the original bytes, before JPEG conversion).
    active = active_graphics(graphics, now)
    images = _download_images(active, get)
    fp = fingerprint(active, images) if active else EMPTY_FINGERPRINT
    hashes = graphic_hashes(active, images)
    saved = state.get("offices", {}).get(cfg.office, {})
    previous = saved.get("fingerprint")
    new_numbers = _new_numbers(saved.get("graphics"), hashes)

    severity = with_mentions(official, active) if official is not None else None
    rose = severity is not None and severity_rose(severity, saved.get("severity"))
    if severity is not None:
        log.info(
            "severity: max_level=%d alerts=%d mentions=%s ok=%s%s",
            severity.max_level,
            len(severity.alerts),
            ", ".join(severity.mentions) or "none",
            severity.ok,
            " (rose)" if rose else "",
        )

    if not active:
        send_it, outcome = False, "no active graphics"
        if rose:
            log.info("severity rose but there are no active graphics to send")
    elif args.force:
        send_it, outcome = True, f"sent {len(active)} graphics (source={source}, reason=forced)"
    elif watch:
        send_it = True
        outcome = f"sent {len(active)} graphics (source={source}, reason=severity rose)"
    elif fp != previous:
        send_it = True
        outcome = f"sent {len(active)} graphics (source={source}, reason=graphics changed)"
    elif rose:
        send_it = True
        outcome = f"sent {len(active)} graphics (source={source}, reason=severity rose)"
    else:
        send_it, outcome = False, "no change"

    converted = convert_all(images) if active else {}

    if args.dry_run:
        if active:
            _write_dry_run(args.out, cfg, active, converted, now, new_numbers, severity)
            outcome = f"{len(active)} graphics (source={source})"
        log.info("result: dry-run, %s", outcome)
        return 0

    # Publish (hosted mode) and send.
    if send_it:
        try:
            require_smtp(cfg)
        except ConfigError as exc:
            log.error("configuration error: %s", exc)
            return 2
        hosted_urls: dict[str, str] | None = None
        if cfg.hosted:
            try:
                hosted_urls = publish(
                    repo_dir=cfg.images_dir,
                    base_url=cfg.images_base_url,
                    graphics=active,
                    converted=converted,
                    now=now,
                    retention_days=cfg.image_days,
                )
            except Exception as exc:
                log.error("publishing images failed: %s", exc)
                return 1
        msg = render_email(
            office=cfg.office,
            office_name=cfg.office_name,
            graphics=active,
            images={url: data for url, (data, _ext) in converted.items()},
            now=now,
            tz=cfg.tz,
            sender=cfg.smtp_user,
            to=cfg.email_to,
            hosted_urls=hosted_urls,
            new_numbers=new_numbers,
            image_days=cfg.image_days if hosted_urls is not None else None,
            severity=severity,
            place_name=cfg.place_name,
        )
        if cfg.subject_prefix:
            msg.replace_header("Subject", f"{cfg.subject_prefix} {msg['Subject']}")
        try:
            send(msg, user=cfg.smtp_user, password=cfg.smtp_password)
        except Exception as exc:
            log.error("sending email failed: %s", exc)
            return 1

    # Save state. An empty set is recorded too, so the next new graphic counts as a change.
    # The severity baseline is saved on every run where all sources answered, so a drop
    # followed by a rise triggers again; after a failed assessment the old baseline is kept.
    if slot_iso is not None:
        state["last_slot"] = slot_iso
    entry = dict(saved)
    if send_it or (not active and fp != previous):
        entry.update(fingerprint=fp, sent_at=now.astimezone(UTC).isoformat(), graphics=hashes)
    if severity is not None and severity.ok:
        entry["severity"] = snapshot(severity)
    if entry != saved:
        state.setdefault("offices", {})[cfg.office] = entry
    save_state(state_path, state)
    log.info("result: %s", outcome)
    return 0


def _watch_no_rise(
    args: argparse.Namespace,
    cfg: Config,
    state: dict,
    state_path: Path,
    official: Severity,
    saved: Mapping,
) -> int:
    """Finish a watch run whose risk did not rise: record the snapshot (if all sources
    answered) and log. --dry-run saves nothing."""
    if official.ok and not args.dry_run:
        state.setdefault("offices", {})[cfg.office] = {**saved, "severity": snapshot(official)}
        save_state(state_path, state)
    alerts = sorted(a.event for a in official.alerts)
    log.info(
        "result: watch (no rise; level %d, alerts %s%s)",
        official.max_level,
        alerts,
        "" if official.ok else "; a source failed, state unchanged",
    )
    return 0


def main(
    argv: list[str] | None = None,
    *,
    now: datetime | None = None,
    get: Callable[..., bytes] = http.get_bytes,
    send: Callable[..., None] = send_email,
    publish: Callable[..., dict[str, str]] = publish_images,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run once. `now`, `get`, `send`, `publish` and `env` are injectable for tests."""
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    try:
        cfg = load_config(os.environ if env is None else env)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    state_path = args.state or cfg.state_path
    state = load_state(state_path)

    # Schedule gate: pick slot or watch mode. Manual runs (--force / --ignore-schedule) are
    # slot-style runs that don't consume a slot.
    slot_iso: str | None = None
    watch = False
    if not (args.force or args.ignore_schedule):
        run, slot, reason = should_run(now, state.get("last_slot"), cfg.tz, cfg.hours)
        if run:
            slot_iso = slot.isoformat()
        else:
            if not cfg.severity:
                log.info("result: skip (%s)", reason)
                return 0
            watch = True

    official = assess_official(cfg.lat, cfg.lon, get) if cfg.severity else None
    if watch and official is not None:
        saved = state.get("offices", {}).get(cfg.office, {})
        if not severity_rose(official, saved.get("severity")):
            return _watch_no_rise(args, cfg, state, state_path, official, saved)
        log.info("watch run: severity rose, running the send path")
    return _pipeline(
        args,
        cfg,
        state,
        state_path,
        now,
        official=official,
        slot_iso=slot_iso,
        watch=watch,
        get=get,
        send=send,
        publish=publish,
    )
