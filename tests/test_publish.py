from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from graphicast import http, publish
from graphicast.model import Graphic
from graphicast.publish import publish_images, run_git

NOW = datetime(2026, 11, 6, 12, 7, 12, tzinfo=UTC)
FOLDER = "20261106T120712Z"
BASE = "https://raw.example/owner/repo/images"
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def sh(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_git():
    """git wrapper that supplies a committer identity so tests work in CI."""

    def git(*args: str, cwd: Path) -> str:
        return run_git(*IDENT, *args, cwd=cwd)

    return git


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    sh("init", "--bare", str(origin), cwd=tmp_path)
    work = tmp_path / "images"
    work.mkdir()
    sh("init", "-q", cwd=work)
    sh("remote", "add", "origin", str(origin), cwd=work)
    return origin, work


def graphic(n: int) -> Graphic:
    return Graphic(n, n, f"T{n}", None, f"https://nws/{n}.png", NOW, NOW)


def call(work, *, check_url=lambda _url: True, sleeps=None, graphics=None, converted=None, **kw):
    graphics = graphics or [graphic(1), graphic(2)]
    converted = converted or {
        g.image_url: (b"\xff\xd8" + str(g.number).encode(), "jpg") for g in graphics
    }
    return publish_images(
        repo_dir=work,
        base_url=BASE + "/",
        graphics=graphics,
        converted=converted,
        now=NOW,
        git=make_git(),
        check_url=check_url,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        **kw,
    )


def test_writes_files_pushes_single_parentless_commit(repos):
    origin, work = repos
    urls = call(work)
    assert urls == {
        "https://nws/1.png": f"{BASE}/{FOLDER}/1.jpg",
        "https://nws/2.png": f"{BASE}/{FOLDER}/2.jpg",
    }
    assert (work / FOLDER / "1.jpg").read_bytes() == b"\xff\xd81"
    commits = sh("rev-list", "images", cwd=origin).split()
    assert len(commits) == 1
    assert sh("rev-list", "--parents", "-n1", "images", cwd=origin) == commits[0]
    assert sh("log", "-1", "--format=%s", "images", cwd=origin) == f"images {FOLDER}"
    files = sh("ls-tree", "-r", "--name-only", "images", cwd=origin).split()
    assert files == [f"{FOLDER}/1.jpg", f"{FOLDER}/2.jpg"]


def test_second_publish_replaces_history_and_prunes(repos):
    origin, work = repos
    old = work / "20261020T000000Z"
    recent = work / "20261105T000000Z"
    for d in (old, recent):
        d.mkdir()
        (d / "1.jpg").write_bytes(b"x")
    (work / "notes.txt").write_text("keep")
    (work / "random-dir").mkdir()
    (work / "random-dir" / "f").write_text("keep")
    call(work)
    assert not old.exists() and recent.exists()
    assert (work / "notes.txt").exists() and (work / "random-dir" / "f").exists()
    # a later publish still ends up as one parentless commit
    sh("fetch", "origin", cwd=work)
    later = datetime(2026, 11, 6, 18, 0, 0, tzinfo=UTC)
    publish_images(
        repo_dir=work,
        base_url=BASE,
        graphics=[graphic(1)],
        converted={"https://nws/1.png": (b"\xff\xd8z", "jpg")},
        now=later,
        git=make_git(),
        check_url=lambda _url: True,
    )
    assert len(sh("rev-list", "images", cwd=origin).split()) == 1
    files = sh("ls-tree", "-r", "--name-only", "images", cwd=origin).split()
    assert "20261106T180000Z/1.jpg" in files and f"{FOLDER}/1.jpg" in files
    assert "notes.txt" in files and not any(f.startswith("20261020") for f in files)


def test_retention_days_respected(repos):
    _, work = repos
    d = work / "20261105T000000Z"
    d.mkdir()
    (d / "a").write_text("x")
    call(work, retention_days=1)
    assert not d.exists()


def test_check_url_retried_then_warns(repos, caplog):
    _, work = repos
    seen, sleeps = [], []

    def never(url):
        seen.append(url)
        return False

    with caplog.at_level(logging.WARNING, logger="graphicast"):
        urls = call(work, check_url=never, sleeps=sleeps)
    assert len(urls) == 2
    assert seen == [f"{BASE}/{FOLDER}/1.jpg"] * 5
    assert sleeps == [3.0] * 4
    assert "not reachable" in caplog.text


def test_check_url_stops_when_ok(repos):
    _, work = repos
    results = iter([False, False, True])
    seen = []

    def flaky(url):
        seen.append(url)
        return next(results)

    call(work, check_url=flaky)
    assert len(seen) == 3


def test_git_failure_raises(tmp_path):
    work = tmp_path / "images"
    work.mkdir()
    sh("init", "-q", cwd=work)  # no origin remote -> push fails
    with pytest.raises(subprocess.CalledProcessError):
        call(work)


def test_not_a_repo_raises(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        call(tmp_path)


def test_skips_graphics_without_converted_and_dedupes(repos):
    _, work = repos
    a = graphic(1)
    dup = Graphic(9, 9, "dup", None, a.image_url, NOW, NOW)
    missing = graphic(2)
    urls = call(work, graphics=[a, dup, missing], converted={a.image_url: (b"\xff\xd8", "jpg")})
    assert urls == {a.image_url: f"{BASE}/{FOLDER}/1.jpg"}


def test_url_ok_uses_head_ok(monkeypatch):
    monkeypatch.setattr(http, "head_ok", lambda url: url == "https://good")
    assert publish.url_ok("https://good") and not publish.url_ok("https://bad")


def test_head_ok(monkeypatch):
    class Resp:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_urlopen(req, timeout):
        seen["method"] = req.get_method()
        return Resp(200)

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    assert http.head_ok("https://x") is True and seen["method"] == "HEAD"
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda req, timeout: Resp(404))
    assert http.head_ok("https://x") is False

    def boom(req, timeout):
        raise OSError("down")

    monkeypatch.setattr(http.urllib.request, "urlopen", boom)
    assert http.head_ok("https://x") is False
