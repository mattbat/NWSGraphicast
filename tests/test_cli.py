from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, datetime

from PIL import Image

from graphicast import cli
from graphicast.fingerprint import EMPTY_FINGERPRINT
from graphicast.sources import mesonet, nws_xml


def make_png(color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, format="PNG")
    return buf.getvalue()


PNG = make_png()
ENV = {"SMTP_USER": "me@example.com", "SMTP_PASSWORD": "pw"}
MES = mesonet.URL.format(office="oun")
NWS = nws_xml.URL.format(office="oun")


class Sender:
    def __init__(self, exc=None):
        self.msgs = []
        self.exc = exc

    def __call__(self, msg, *, user, password):
        if self.exc:
            raise self.exc
        self.msgs.append((msg, user, password))


class Getter:
    def __init__(self, inner):
        self.inner = inner
        self.urls = []

    def __call__(self, url, timeout=20.0):
        self.urls.append(url)
        return self.inner(url)


def image_urls(mesonet_text):
    return [json.loads(mesonet_text)[i]["FullImage"] for i in range(3)]


def setup(tmp_path, fake_get, mesonet_text, nws_text, images=None, **over):
    mapping = {MES: mesonet_text.encode(), NWS: nws_text.encode()}
    for url in image_urls(mesonet_text):
        mapping[url] = PNG
    mapping.update(over)
    return Getter(fake_get(mapping)), tmp_path / "state.json", tmp_path / "out"


def run(argv, state, get, send, now, env=ENV):
    return cli.main([*argv, "--state", str(state)], now=now, get=get, send=send, env=env)


def n_images(msg):
    return len([p for p in msg.walk() if p.get_content_maintype() == "image"])


def test_first_run_sends_and_saves_state(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender()
    assert run(["--ignore-schedule"], state, get, send, FIXTURE_NOW) == 0
    assert len(send.msgs) == 1
    msg, user, pw = send.msgs[0]
    assert (user, pw) == ("me@example.com", "pw")
    assert msg["To"] == "me@example.com"
    assert n_images(msg) == 3
    assert {p.get_content_type() for p in msg.walk() if p.get_content_maintype() == "image"} == {
        "image/jpeg"
    }
    data = json.loads(state.read_text())
    assert data["offices"]["oun"]["sent_at"] == FIXTURE_NOW.isoformat()
    assert data["last_slot"] is None


def test_second_run_no_change(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender()
    run(["--ignore-schedule"], state, get, send, FIXTURE_NOW)
    assert run(["--ignore-schedule"], state, get, send, FIXTURE_NOW) == 0
    assert len(send.msgs) == 1


def test_changed_image_bytes_sends(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender()
    run(["--ignore-schedule"], state, get, send, FIXTURE_NOW)
    url = image_urls(mesonet_text)[0]
    get2, _, _ = setup(tmp_path, fake_get, mesonet_text, nws_text, **{url: PNG + b"changed"})
    assert run(["--ignore-schedule"], state, get2, send, FIXTURE_NOW) == 0
    assert len(send.msgs) == 2


def test_fallback_to_nws(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(
        tmp_path, fake_get, mesonet_text, nws_text, **{MES: urllib.error.URLError("down")}
    )
    send = Sender()
    assert run(["--ignore-schedule"], state, get, send, FIXTURE_NOW) == 0
    assert n_images(send.msgs[0][0]) == 3


def test_all_sources_fail(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    err = urllib.error.URLError("down")
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text, **{MES: err, NWS: err})
    send = Sender()
    assert run(["--ignore-schedule"], state, get, send, FIXTURE_NOW) == 1
    assert send.msgs == [] and not state.exists()


def test_dry_run(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, out = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender()
    argv = ["--ignore-schedule", "--dry-run", "--out", str(out)]
    assert run(argv, state, get, send, FIXTURE_NOW, env={}) == 0
    assert (out / "email.eml").read_bytes().startswith(b"Content-Type") or (
        out / "email.eml"
    ).exists()
    assert "data:image/jpeg;base64," in (out / "email.html").read_text()
    assert "Friday Morning Fog" in (out / "email.html").read_text()
    jpgs = sorted((out / "images").glob("*.jpg"))
    assert len(jpgs) == 3 and all(p.read_bytes().startswith(b"\xff\xd8") for p in jpgs)
    assert send.msgs == [] and not state.exists()


def test_dry_run_no_active(tmp_path, fake_get, mesonet_text, nws_text):
    get, state, out = setup(tmp_path, fake_get, mesonet_text, nws_text)
    late = datetime(2030, 1, 1, tzinfo=UTC)
    assert (
        run(["--ignore-schedule", "--dry-run", "--out", str(out)], state, get, Sender(), late) == 0
    )
    assert not out.exists()


def test_force_sends_unchanged(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender()
    run(["--ignore-schedule"], state, get, send, FIXTURE_NOW)
    assert run(["--force"], state, get, send, FIXTURE_NOW) == 0
    assert len(send.msgs) == 2


def test_schedule_gate_skips_before_fetch(tmp_path, fake_get, mesonet_text, nws_text):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    state.write_text(
        json.dumps({"version": 1, "last_slot": "2026-11-06T06:00:00-06:00", "offices": {}})
    )
    now = datetime(2026, 11, 6, 13, 30, tzinfo=UTC)  # 07:30 CST
    send = Sender()
    assert run([], state, get, send, now) == 0
    assert get.urls == [] and send.msgs == []


def test_schedule_gate_runs_and_records_slot(tmp_path, fake_get, mesonet_text, nws_text):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    now = datetime(2026, 11, 6, 12, 5, tzinfo=UTC)  # 06:05 CST
    send = Sender()
    assert run([], state, get, send, now) == 0
    # feed fixtures are not active at this time, so nothing sent; slot still recorded
    data = json.loads(state.read_text())
    assert data["last_slot"] == "2026-11-06T06:00:00-06:00"


def test_gate_outside_window_skips(tmp_path, fake_get, mesonet_text, nws_text):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    now = datetime(2026, 11, 6, 11, 5, tzinfo=UTC)  # 05:05 CST
    assert run([], state, get, Sender(), now) == 0
    assert get.urls == []


def test_missing_smtp_exit_2(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender()
    assert run(["--ignore-schedule"], state, get, send, FIXTURE_NOW, env={}) == 2
    assert send.msgs == [] and not state.exists()


def test_bad_config_exit_2(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    env = {**ENV, "GRAPHICAST_HOURS": "x"}
    assert run(["--ignore-schedule"], state, get, Sender(), FIXTURE_NOW, env=env) == 2


def test_image_failure_links_by_url(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    bad = image_urls(mesonet_text)[1]
    get, state, _ = setup(
        tmp_path, fake_get, mesonet_text, nws_text, **{bad: urllib.error.URLError("404")}
    )
    send = Sender()
    assert run(["--ignore-schedule"], state, get, send, FIXTURE_NOW) == 0
    msg = send.msgs[0][0]
    assert n_images(msg) == 2
    assert f'src="{bad}"' in msg.get_body(preferencelist=("html",)).get_content()


def test_smtp_failure_exit_1_state_untouched(
    tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW
):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender(exc=OSError("smtp down"))
    assert run(["--ignore-schedule"], state, get, send, FIXTURE_NOW) == 1
    assert not state.exists()


def test_no_active_graphics_stores_empty_fingerprint(tmp_path, fake_get, mesonet_text, nws_text):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    late = datetime(2030, 1, 1, tzinfo=UTC)
    send = Sender()
    assert run(["--ignore-schedule"], state, get, send, late) == 0
    assert send.msgs == []
    assert json.loads(state.read_text())["offices"]["oun"]["fingerprint"] == EMPTY_FINGERPRINT
    # second time: already empty, nothing changes
    before = state.read_text()
    run(["--ignore-schedule"], state, get, send, late)
    assert state.read_text() == before


def test_naive_now_and_verbose(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    send = Sender()
    naive = FIXTURE_NOW.replace(tzinfo=None)
    assert run(["--ignore-schedule", "-v"], state, get, send, naive) == 0
    assert len(send.msgs) == 1


def test_default_env_and_now(monkeypatch, tmp_path, fake_get, mesonet_text, nws_text):
    # Real clock and os.environ; dry-run so nothing is sent whatever is active.
    get, state, out = setup(tmp_path, fake_get, mesonet_text, nws_text)
    monkeypatch.delenv("SMTP_USER", raising=False)
    argv = ["--ignore-schedule", "--dry-run", "--out", str(out), "--state", str(state)]
    assert cli.main(argv, get=get) == 0


HOSTED_ENV = {
    **ENV,
    "GRAPHICAST_IMAGES_DIR": "imgdir",
    "GRAPHICAST_IMAGES_BASE_URL": "https://img.example/images",
}


class Recorder:
    """Records call order across publish and send."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.kwargs = None

    def publish(self, **kwargs):
        self.calls.append("publish")
        self.kwargs = kwargs
        if self.fail:
            raise RuntimeError("git push failed")
        return {
            g.image_url: f"https://img.example/images/f/{g.number}.jpg" for g in kwargs["graphics"]
        }

    def send(self, msg, *, user, password):
        self.calls.append("send")
        self.msg = msg


def hosted_run(state, get, rec, now, env=HOSTED_ENV):
    argv = ["--ignore-schedule", "--state", str(state)]
    return cli.main(argv, now=now, get=get, send=rec.send, publish=rec.publish, env=env)


def test_hosted_publishes_before_send(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    rec = Recorder()
    assert hosted_run(state, get, rec, FIXTURE_NOW) == 0
    assert rec.calls == ["publish", "send"]
    assert rec.kwargs["base_url"] == "https://img.example/images"
    assert rec.kwargs["retention_days"] == 7
    assert all(ext == "jpg" for _, ext in rec.kwargs["converted"].values())
    assert n_images(rec.msg) == 0
    html = rec.msg.get_body(preferencelist=("html",)).get_content()
    assert html.count("https://img.example/images/f/") == 3
    assert len(rec.msg.as_bytes()) < 50_000
    assert json.loads(state.read_text())["offices"]["oun"]["sent_at"]


def test_hosted_publish_failure_exit_1(tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    rec = Recorder(fail=True)
    assert hosted_run(state, get, rec, FIXTURE_NOW) == 1
    assert rec.calls == ["publish"] and not state.exists()


def test_inline_mode_when_only_one_hosting_var(
    tmp_path, fake_get, mesonet_text, nws_text, FIXTURE_NOW
):
    get, state, _ = setup(tmp_path, fake_get, mesonet_text, nws_text)
    rec = Recorder()
    env = {**ENV, "GRAPHICAST_IMAGES_DIR": "imgdir"}
    assert hosted_run(state, get, rec, FIXTURE_NOW, env=env) == 0
    assert rec.calls == ["send"] and n_images(rec.msg) == 3
