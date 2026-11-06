from pathlib import Path

import pytest

from graphicast.config import Config, ConfigError, load_config, require_smtp


def test_defaults():
    cfg = load_config({})
    assert cfg.office == "oun"
    assert cfg.tz == "America/Chicago"
    assert cfg.hours == (6, 12, 18)
    assert cfg.state_path == Path("state/state.json")
    assert cfg.smtp_user is None and cfg.smtp_password is None and cfg.email_to is None


def test_overrides_and_email_to_default():
    cfg = load_config(
        {
            "GRAPHICAST_OFFICE": "TUL",
            "GRAPHICAST_TZ": "UTC",
            "GRAPHICAST_HOURS": "1, 2",
            "GRAPHICAST_STATE": "s.json",
            "SMTP_USER": "u@x.com",
            "SMTP_PASSWORD": "pw",
        }
    )
    assert (cfg.office, cfg.tz, cfg.hours) == ("tul", "UTC", (1, 2))
    assert cfg.state_path == Path("s.json")
    assert cfg.email_to == "u@x.com"
    assert load_config({"SMTP_USER": "u", "EMAIL_TO": "t"}).email_to == "t"


@pytest.mark.parametrize("raw", ["a,b", "25", ",", "-1"])
def test_bad_hours(raw):
    with pytest.raises(ConfigError):
        load_config({"GRAPHICAST_HOURS": raw})


def test_require_smtp():
    ok = Config("oun", "UTC", (6,), Path("s"), "u", "p", "t")
    require_smtp(ok)
    bad = Config("oun", "UTC", (6,), Path("s"), None, None, None)
    with pytest.raises(ConfigError, match="SMTP_USER.*SMTP_PASSWORD.*EMAIL_TO"):
        require_smtp(bad)


def test_image_hosting_defaults_and_hosted_property():
    cfg = load_config({})
    assert cfg.images_dir is None and cfg.images_base_url is None and cfg.image_days == 7
    assert not cfg.hosted
    only_dir = load_config({"GRAPHICAST_IMAGES_DIR": "images"})
    assert only_dir.images_dir == Path("images") and not only_dir.hosted
    both = load_config(
        {
            "GRAPHICAST_IMAGES_DIR": "images",
            "GRAPHICAST_IMAGES_BASE_URL": "https://x/y",
            "GRAPHICAST_IMAGE_DAYS": "3",
        }
    )
    assert both.hosted and both.images_base_url == "https://x/y" and both.image_days == 3


@pytest.mark.parametrize("raw", ["0", "-2", "x"])
def test_bad_image_days(raw):
    with pytest.raises(ConfigError, match="GRAPHICAST_IMAGE_DAYS"):
        load_config({"GRAPHICAST_IMAGE_DAYS": raw})


def test_office_name():
    assert load_config({}).office_name == "Norman"
    assert load_config({"GRAPHICAST_OFFICE_NAME": " Tulsa "}).office_name == "Tulsa"


def test_subject_prefix():
    assert load_config({}).subject_prefix == ""
    assert load_config({"GRAPHICAST_SUBJECT_PREFIX": " [TEST] "}).subject_prefix == "[TEST]"
