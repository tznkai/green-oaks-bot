# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Replace the ornate centre of assets/cards/ace_of_spades.png with a plain spade pip.

The frame and corner indices of the card are kept (Byron Knoll, public domain). The ornate
centre spade is attributed to another artist without a public-domain statement, so it is removed:

1. Measure the centre pip of ace_of_hearts.png and ace_of_clubs.png (ink bounding boxes).
2. Measure the upright spade pip at the top of 2_of_spades.png (also Knoll).
3. Fill the old centre region with the card's background colour, sampled from the card.
4. Scale the 2_of_spades pip with LANCZOS to the mean height of the reference pips and paste it
   centred on the mean reference centre.

The output is deterministic and idempotent: running it again on its own output gives the same
bytes, because the fill region covers the whole new pip. The original ornate art is still in git
history if it is ever needed again.

Usage: python tools/make_plain_ace_of_spades.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "assets" / "cards"
CARD_SIZE = (500, 726)

# Window holding the centre pip of the plain aces, clear of both corner indices.
CENTRE_WINDOW = (100, 120, 400, 600)
# Window holding the upright (top) spade pip on 2_of_spades; the lower pip is excluded.
SOURCE_PIP_WINDOW = (100, 60, 400, 300)
# Fill region for the ornate spade: wide enough to cover it, clear of both corner indices.
FILL_BOX = (92, 130, 408, 560)  # inclusive
# Corner index regions that must not overlap the fill region.
TOP_LEFT_INDEX = (0, 0, 120, 200)
BOTTOM_RIGHT_INDEX = (380, 520, 499, 725)
PIP_PADDING = 2
INK_THRESHOLD = 128  # a pixel with min(R, G, B) below this counts as pip ink


def ink_box(im: Image.Image, window: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Inclusive bounding box of opaque, visibly dark pixels inside `window` (x0, y0, x1, y1)."""
    px = im.load()
    x0, y0, x1, y1 = window
    xs: list[int] = []
    ys: list[int] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b, a = px[x, y]
            if a > 0 and min(r, g, b) < INK_THRESHOLD:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise ValueError(f"no pip ink in window {window}")
    return min(xs), min(ys), max(xs), max(ys)


def pip_box(im: Image.Image) -> tuple[int, int, int, int]:
    """Inclusive bounding box of the centre pip on a plain ace."""
    return ink_box(im, CENTRE_WINDOW)


def pip_colour(im: Image.Image) -> tuple[int, int, int]:
    """Most common colour among the solid ink pixels of a pip."""
    px = im.load()
    counts: Counter[tuple[int, int, int]] = Counter(
        px[x, y][:3] for x in range(im.width) for y in range(im.height)
        if px[x, y][3] == 255 and max(px[x, y][:3]) < INK_THRESHOLD
    )
    colour, _ = max(counts.items(), key=lambda item: (item[1], item[0]))
    return colour


def ink_only(im: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    """Turn a white-background pip into a transparent overlay: alpha is how much ink each pixel has."""
    ink = im.convert("L").point(lambda v: 255 - v)
    alpha = ink
    out = Image.new("RGBA", im.size, colour + (0,))
    out.putalpha(alpha)
    return out


def background_colour(im: Image.Image) -> tuple[int, int, int, int]:
    """Most common opaque colour in a strip of the card's plain background, above the pip."""
    px = im.load()
    counts: Counter[tuple[int, int, int, int]] = Counter(
        px[x, y] for x in range(150, 351) for y in range(40, 101) if px[x, y][3] == 255
    )
    colour, _ = max(counts.items(), key=lambda item: (item[1], item[0]))
    return colour


def assert_fill_clear_of_indices(im: Image.Image) -> None:
    """The fill region must not touch the corner indices, which are kept as they are."""
    for corner in (TOP_LEFT_INDEX, BOTTOM_RIGHT_INDEX):
        cx0, cy0, cx1, cy1 = corner
        px = im.load()
        for y in range(cy0, cy1 + 1):
            for x in range(cx0, cx1 + 1):
                r, g, b, a = px[x, y]
                in_fill = FILL_BOX[0] <= x <= FILL_BOX[2] and FILL_BOX[1] <= y <= FILL_BOX[3]
                if a > 0 and min(r, g, b) < INK_THRESHOLD and in_fill:
                    raise ValueError(f"corner index ink at {(x, y)} inside fill region")


def build(assets: Path, out: Path) -> None:
    """Write the plain-centre Ace of Spades to `out`, reading the other cards from `assets`."""
    hearts = Image.open(assets / "ace_of_hearts.png").convert("RGBA")
    clubs = Image.open(assets / "ace_of_clubs.png").convert("RGBA")
    two = Image.open(assets / "2_of_spades.png").convert("RGBA")
    original = Image.open(assets / "ace_of_spades.png").convert("RGBA")
    for im in (hearts, clubs, two, original):
        if im.size != CARD_SIZE:
            raise ValueError(f"expected {CARD_SIZE}, got {im.size}")

    # Target geometry: mean height and mean centre of the reference centre pips.
    refs = [ink_box(hearts, CENTRE_WINDOW), ink_box(clubs, CENTRE_WINDOW)]
    target_h = sum(y1 - y0 + 1 for _, y0, _, y1 in refs) / len(refs)
    centre_x = sum((x0 + x1) / 2 for x0, _, x1, _ in refs) / len(refs)
    centre_y = sum((y0 + y1) / 2 for _, y0, _, y1 in refs) / len(refs)

    # Source pip, padded so that anti-aliased edges survive the crop.
    sx0, sy0, sx1, sy1 = ink_box(two, SOURCE_PIP_WINDOW)
    crop = two.crop((sx0 - PIP_PADDING, sy0 - PIP_PADDING, sx1 + PIP_PADDING + 1, sy1 + PIP_PADDING + 1))
    scale = target_h / (sy1 - sy0 + 1)
    new_size = (round(crop.width * scale), round(target_h + 2 * PIP_PADDING * scale))
    pip = ink_only(crop.resize(new_size, Image.Resampling.LANCZOS), pip_colour(crop))

    # Remove the ornate art by filling its region with the sampled background colour.
    assert_fill_clear_of_indices(original)
    result = original.copy()
    fx0, fy0, fx1, fy1 = FILL_BOX
    background = background_colour(original)
    result.paste(background, (fx0, fy0, fx1 + 1, fy1 + 1))

    # Paste the plain pip centred where the other aces' pips are.
    left = round(centre_x - new_size[0] / 2)
    top = round(centre_y - new_size[1] / 2)
    overlay = Image.new("RGBA", result.size, (0, 0, 0, 0))
    overlay.paste(pip, (left, top))
    result = Image.alpha_composite(result, overlay)

    result.save(out, format="PNG")


def main() -> None:
    build(ASSETS, ASSETS / "ace_of_spades.png")


if __name__ == "__main__":
    main()
