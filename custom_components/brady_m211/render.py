"""Render text or images to 1-bit rows for the M211 (203 dpi)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .const import (
    DEFAULT_PRINTABLE_WIDTH_IN,
    DPI,
    MAX_LABEL_LENGTH_IN,
    MIN_LABEL_LENGTH_IN,
)
from .vgl import inches_to_dots

_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _to_rows(image: Image.Image) -> list[list[int]]:
    mono = image.convert("1")
    width, height = mono.size
    pixels = mono.load()
    rows: list[list[int]] = []
    for y in range(height):
        row = [0 if pixels[x, y] else 1 for x in range(width)]
        rows.append(row)
    return rows


def fit_canvas(
    *,
    printable_width: int | None,
    printable_height: int | None,
    length_in: float | None = None,
) -> tuple[int, int]:
    """Choose a 203 dpi canvas from PICL geometry and optional length."""
    width = printable_width or inches_to_dots(DEFAULT_PRINTABLE_WIDTH_IN)
    if printable_height and printable_height > 0:
        height = printable_height
    else:
        length = length_in if length_in is not None else MIN_LABEL_LENGTH_IN
        length = min(max(length, MIN_LABEL_LENGTH_IN), MAX_LABEL_LENGTH_IN)
        height = inches_to_dots(length)
    return width, height


def render_text(
    text: str,
    *,
    printable_width: int | None,
    printable_height: int | None,
    length_in: float | None = None,
    margin: int = 4,
) -> list[list[int]]:
    """Render wrapped black text on a white tape-sized canvas."""
    width, height = fit_canvas(
        printable_width=printable_width,
        printable_height=printable_height,
        length_in=length_in,
    )
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    font_size = max(12, min(36, height - 2 * margin))
    font = _load_font(font_size)
    message = text.strip() or " "
    while font_size >= 10:
        font = _load_font(font_size)
        wrapped = _wrap_text(draw, message, font, width - 2 * margin)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=2)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w <= width - 2 * margin and text_h <= height - 2 * margin:
            break
        font_size -= 2
    wrapped = _wrap_text(draw, message, font, width - 2 * margin)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=2)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = max(margin, (width - text_w) // 2 - bbox[0])
    y = max(margin, (height - text_h) // 2 - bbox[1])
    draw.multiline_text((x, y), wrapped, fill=0, font=font, spacing=2, align="center")
    return _to_rows(image)


def render_image_bytes(
    data: bytes,
    *,
    printable_width: int | None,
    printable_height: int | None,
    length_in: float | None = None,
) -> list[list[int]]:
    """Fit an image file onto the printable tape area."""
    with Image.open(BytesIO(data)) as src:
        src = ImageOps.exif_transpose(src)
        src = src.convert("L")
    width, height = fit_canvas(
        printable_width=printable_width,
        printable_height=printable_height,
        length_in=length_in,
    )
    fitted = ImageOps.contain(src, (width, height), method=Image.Resampling.LANCZOS)
    canvas = Image.new("L", (width, height), 255)
    ox = (width - fitted.width) // 2
    oy = (height - fitted.height) // 2
    canvas.paste(fitted, (ox, oy))
    return _to_rows(canvas.convert("1", dither=Image.Dither.FLOYDSTEINBERG))


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return "\n".join(lines)
