"""Configuration from environment variables (see the README table). Secrets never live in files."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from graphicast.schedule import DEFAULT_HOURS, DEFAULT_TZ

DEFAULT_OFFICE = "oun"
DEFAULT_STATE_PATH = "state/state.json"
DEFAULT_IMAGE_DAYS = 7
DEFAULT_OFFICE_NAME = "Norman"


class ConfigError(Exception):
    """Missing or invalid configuration."""


@dataclass(frozen=True)
class Config:
    office: str
    tz: str
    hours: tuple[int, ...]
    state_path: Path
    smtp_user: str | None
    smtp_password: str | None
    email_to: str | None
    images_dir: Path | None = None
    images_base_url: str | None = None
    image_days: int = DEFAULT_IMAGE_DAYS
    office_name: str = DEFAULT_OFFICE_NAME

    @property
    def hosted(self) -> bool:
        """True when images are published to the images branch and linked, not embedded."""
        return self.images_dir is not None and self.images_base_url is not None


def _opt(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key, "").strip()
    return value or None


def _parse_hours(raw: str | None) -> tuple[int, ...]:
    if raw is None:
        return DEFAULT_HOURS
    try:
        hours = tuple(int(p) for p in raw.split(",") if p.strip())
    except ValueError:
        raise ConfigError(f"GRAPHICAST_HOURS must be comma-separated integers: {raw!r}") from None
    if not hours or any(not 0 <= h <= 23 for h in hours):
        raise ConfigError(f"GRAPHICAST_HOURS must be hours 0-23: {raw!r}")
    return hours


def _parse_days(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_IMAGE_DAYS
    try:
        days = int(raw)
    except ValueError:
        raise ConfigError(f"GRAPHICAST_IMAGE_DAYS must be an integer: {raw!r}") from None
    if days < 1:
        raise ConfigError(f"GRAPHICAST_IMAGE_DAYS must be at least 1: {raw!r}")
    return days


def load_config(env: Mapping[str, str] = os.environ) -> Config:
    smtp_user = _opt(env, "SMTP_USER")
    images_dir = _opt(env, "GRAPHICAST_IMAGES_DIR")
    return Config(
        office=(_opt(env, "GRAPHICAST_OFFICE") or DEFAULT_OFFICE).lower(),
        tz=_opt(env, "GRAPHICAST_TZ") or DEFAULT_TZ,
        hours=_parse_hours(_opt(env, "GRAPHICAST_HOURS")),
        state_path=Path(_opt(env, "GRAPHICAST_STATE") or DEFAULT_STATE_PATH),
        smtp_user=smtp_user,
        smtp_password=_opt(env, "SMTP_PASSWORD"),
        email_to=_opt(env, "EMAIL_TO") or smtp_user,
        images_dir=Path(images_dir) if images_dir else None,
        images_base_url=_opt(env, "GRAPHICAST_IMAGES_BASE_URL"),
        image_days=_parse_days(_opt(env, "GRAPHICAST_IMAGE_DAYS")),
        office_name=_opt(env, "GRAPHICAST_OFFICE_NAME") or DEFAULT_OFFICE_NAME,
    )


def require_smtp(cfg: Config) -> None:
    """Raise ConfigError naming any missing SMTP variable. Only called when sending."""
    missing = [
        name
        for name, value in (
            ("SMTP_USER", cfg.smtp_user),
            ("SMTP_PASSWORD", cfg.smtp_password),
            ("EMAIL_TO", cfg.email_to),
        )
        if not value
    ]
    if missing:
        raise ConfigError("missing required environment variable(s): " + ", ".join(missing))
