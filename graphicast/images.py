"""Convert downloaded images to compact JPEGs for email."""

from __future__ import annotations

import io
import logging

from PIL import Image, UnidentifiedImageError

log = logging.getLogger("graphicast")


def to_jpeg(data: bytes, *, quality: int = 82) -> tuple[bytes, str]:
    """Return (bytes, extension).

    Still images become RGB JPEGs ("jpg"). Animated GIFs are returned unchanged ("gif").
    Bytes Pillow cannot open are returned unchanged ("bin") with a warning.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            if getattr(img, "is_animated", False):
                return data, "gif"
            img.load()
            if img.mode in ("RGBA", "LA", "P", "PA"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
            else:
                flat = img.convert("RGB")
            out = io.BytesIO()
            flat.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue(), "jpg"
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        log.warning("cannot convert image (%d bytes), keeping original: %s", len(data), exc)
        return data, "bin"


def convert_all(images: dict[str, bytes]) -> dict[str, tuple[bytes, str]]:
    """Map image_url -> to_jpeg(data)."""
    return {url: to_jpeg(data) for url, data in images.items()}
