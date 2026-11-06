"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from graphicast import http
from graphicast.config import ConfigError, load_config, require_smtp
from graphicast.fingerprint import EMPTY_FINGERPRINT, fingerprint
from graphicast.images import convert_all
from graphicast.model import Graphic, active_graphics
from graphicast.notify.email import send_email
from graphicast.publish import publish_images
from graphicast.render import render_email, render_html_preview
from graphicast.schedule import should_run
from graphicast.sources import AllSourcesFailed, fetch_graphics
from graphicast.state import load_state, save_state

log = logging.getLogger("graphicast")


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
    images: dict[str, bytes] = {}
    for g in graphics:
        if g.image_url in images:
            continue
        try:
            images[g.image_url] = get(g.image_url)
        except Exception as exc:
            log.warning("image download failed for %s: %s (linking by URL)", g.image_url, exc)
    return images


def main(
    argv: list[str] | None = None,
    *,
    now: datetime | None = None,
    get: Callable[..., bytes] = http.get_bytes,
    send: Callable[..., None] = send_email,
    publish: Callable[..., dict[str, str]] = publish_images,
    env: Mapping[str, str] | None = None,
) -> int:
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

    slot_iso: str | None = None
    if not (args.force or args.ignore_schedule):
        run, slot, reason = should_run(now, state.get("last_slot"), cfg.tz, cfg.hours)
        if not run:
            log.info("skip: %s", reason)
            log.info("result: skip (%s)", reason)
            return 0
        slot_iso = slot.isoformat() if slot else None

    try:
        source, graphics = fetch_graphics(cfg.office, get=get)
    except AllSourcesFailed as exc:
        log.error("all sources failed: %s", exc)
        return 1

    active = active_graphics(graphics, now)
    images = _download_images(active, get)
    fp = fingerprint(active, images) if active else EMPTY_FINGERPRINT
    previous = state.get("offices", {}).get(cfg.office, {}).get("fingerprint")

    if not active:
        send_it, outcome = False, "no active graphics"
    elif args.force:
        send_it, outcome = True, ""
    elif fp == previous:
        send_it, outcome = False, "no change"
    else:
        send_it, outcome = True, ""

    if args.dry_run and active:
        converted = convert_all(images)
        previews = {url: data for url, (data, _) in converted.items()}
        msg = render_email(
            office=cfg.office,
            graphics=active,
            images=previews,
            now=now,
            tz=cfg.tz,
            sender=cfg.smtp_user or "graphicast@example.invalid",
            to=cfg.email_to or "recipient@example.invalid",
        )
        (args.out / "images").mkdir(parents=True, exist_ok=True)
        for g in active:
            if g.image_url in converted:
                data, ext = converted[g.image_url]
                (args.out / "images" / f"{g.number}.{ext}").write_bytes(data)
        eml = args.out / "email.eml"
        html_path = args.out / "email.html"
        eml.write_bytes(msg.as_bytes())
        html_path.write_text(
            render_html_preview(office=cfg.office, graphics=active, images=previews),
            encoding="utf-8",
        )
        log.info("wrote %s and %s", eml, html_path)
        log.info("result: dry-run, %d graphics (source=%s)", len(active), source)
        return 0
    if args.dry_run:
        log.info("result: dry-run, %s", outcome)
        return 0

    sent = False
    if send_it:
        try:
            require_smtp(cfg)
        except ConfigError as exc:
            log.error("configuration error: %s", exc)
            return 2
        converted = convert_all(images)
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
            graphics=active,
            images={url: data for url, (data, _) in converted.items()},
            now=now,
            tz=cfg.tz,
            sender=cfg.smtp_user or "",
            to=cfg.email_to or "",
            hosted_urls=hosted_urls,
        )
        try:
            send(msg, user=cfg.smtp_user, password=cfg.smtp_password)
        except Exception as exc:
            log.error("sending email failed: %s", exc)
            return 1
        sent = True

    if slot_iso is not None:
        state["last_slot"] = slot_iso
    if sent or (not active and fp != previous):
        state.setdefault("offices", {})[cfg.office] = {
            "fingerprint": fp,
            "sent_at": now.astimezone(UTC).isoformat(),
        }
    save_state(state_path, state)

    if sent:
        log.info("result: sent %d graphics (source=%s)", len(active), source)
    else:
        log.info("result: %s", outcome)
    return 0
