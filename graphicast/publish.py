"""Publish converted images to a history-less git branch for linking from email."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from graphicast import http
from graphicast.model import Graphic

log = logging.getLogger("graphicast")

FOLDER_FMT = "%Y%m%dT%H%M%SZ"  # UTC, e.g. 20261106T120712Z
VERIFY_TRIES = 5
VERIFY_DELAY = 3.0


def run_git(*args: str, cwd: Path) -> str:
    """Run git in `cwd` and return stripped stdout. Raises CalledProcessError on failure."""
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def url_ok(url: str) -> bool:
    return http.head_ok(url)


def _folder_time(name: str) -> datetime | None:
    try:
        return datetime.strptime(name, FOLDER_FMT).replace(tzinfo=UTC)
    except ValueError:
        return None


def prune(repo_dir: Path, now: datetime, retention_days: int) -> list[str]:
    """Delete timestamped top-level folders older than the retention period."""
    cutoff = now.astimezone(UTC) - timedelta(days=retention_days)
    removed = []
    for child in sorted(repo_dir.iterdir()):
        if not child.is_dir():
            continue
        stamp = _folder_time(child.name)
        if stamp is not None and stamp < cutoff:
            shutil.rmtree(child)
            removed.append(child.name)
    return removed


def publish_images(
    *,
    repo_dir: Path,
    base_url: str,
    graphics: list[Graphic],
    converted: dict[str, tuple[bytes, str]],
    now: datetime,
    retention_days: int = 7,
    branch: str = "images",
    git: Callable[..., str] = run_git,
    check_url: Callable[[str], bool] = url_ok,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Write images into a new folder, prune old ones, force-push a single parentless commit.

    Returns {original image_url: hosted url}. Raises if a git command fails.
    """
    folder = now.astimezone(UTC).strftime(FOLDER_FMT)
    target = repo_dir / folder
    target.mkdir(parents=True, exist_ok=True)
    hosted: dict[str, str] = {}
    base = base_url.rstrip("/")
    for g in graphics:
        if g.image_url not in converted or g.image_url in hosted:
            continue
        data, ext = converted[g.image_url]
        name = f"{g.number}.{ext}"
        (target / name).write_bytes(data)
        hosted[g.image_url] = f"{base}/{folder}/{name}"

    removed = prune(repo_dir, now, retention_days)
    if removed:
        log.info("pruned %d old image folder(s): %s", len(removed), ", ".join(removed))

    git("add", "-A", cwd=repo_dir)
    tree = git("write-tree", cwd=repo_dir)
    commit = git("commit-tree", tree, "-m", f"images {folder}", cwd=repo_dir)
    git("push", "--force", "origin", f"{commit}:refs/heads/{branch}", cwd=repo_dir)

    if hosted:
        first = next(iter(hosted.values()))
        for attempt in range(VERIFY_TRIES):
            if check_url(first):
                break
            if attempt < VERIFY_TRIES - 1:
                sleep(VERIFY_DELAY)
        else:
            log.warning("hosted image not reachable yet: %s (sending anyway)", first)
    return hosted
