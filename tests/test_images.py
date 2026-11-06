from __future__ import annotations

import io
import logging
import random

from PIL import Image

from graphicast.images import convert_all, to_jpeg


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_png_to_jpeg_smaller():
    rnd = random.Random(1)
    img = Image.new("RGB", (400, 300))
    # smooth-ish gradient with mild noise: PNG compresses poorly, JPEG well
    img.putdata(
        [(x % 256, (y * 2) % 256, rnd.randrange(120, 136)) for y in range(300) for x in range(400)]
    )
    png = png_bytes(img)
    data, ext = to_jpeg(png)
    assert data.startswith(b"\xff\xd8") and ext == "jpg"
    assert len(data) < len(png)
    assert Image.open(io.BytesIO(data)).size == (400, 300)


def test_rgba_flattened_onto_white():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    data, ext = to_jpeg(png_bytes(img))
    assert ext == "jpg"
    r, g, b = Image.open(io.BytesIO(data)).convert("RGB").getpixel((5, 5))
    assert min(r, g, b) > 240


def test_palette_png_with_transparency_white_background():
    img = Image.new("P", (10, 10), 0)
    img.putpalette([0, 0, 0] * 256)
    img.info["transparency"] = 0
    data, ext = to_jpeg(png_bytes(img))
    assert ext == "jpg"
    assert min(Image.open(io.BytesIO(data)).convert("RGB").getpixel((5, 5))) > 240


def test_jpeg_input_stays_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 10, 10)).save(buf, format="JPEG")
    data, ext = to_jpeg(buf.getvalue())
    assert data.startswith(b"\xff\xd8") and ext == "jpg"


def test_animated_gif_unchanged():
    frames = [Image.new("RGB", (8, 8), (i * 80, 0, 0)).convert("P") for i in range(3)]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    gif = buf.getvalue()
    assert to_jpeg(gif) == (gif, "gif")


def test_garbage_unchanged_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="graphicast"):
        assert to_jpeg(b"not an image") == (b"not an image", "bin")
    assert "cannot convert" in caplog.text


def test_convert_all():
    png = png_bytes(Image.new("RGB", (5, 5), (1, 2, 3)))
    out = convert_all({"a": png, "b": b"junk"})
    assert out["a"][1] == "jpg" and out["b"] == (b"junk", "bin")
