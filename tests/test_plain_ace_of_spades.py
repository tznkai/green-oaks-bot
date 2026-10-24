# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AC11.5 (art): the Ace of Spades carries a plain centre pip, not the third-party ornate spade.

The asset is produced by tools/make_plain_ace_of_spades.py. These tests check the committed PNG
is exactly what the script produces, that no ornate artwork remains, that the new pip matches the
centre pip of the other plain aces, and that every deck asset is still 500x726 RGBA.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image

from green_oaks_bot.deck import FULL_DECK
from green_oaks_bot.render import image_filename

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "assets" / "cards"
SCRIPT = REPO / "tools" / "make_plain_ace_of_spades.py"
CARD_SIZE = (500, 726)


def load_script():
    spec = importlib.util.spec_from_file_location("make_plain_ace_of_spades", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CENTRE_WINDOW = (100, 120, 400, 600)  # clear of both corner indices and the card edge


def test_committed_ace_of_spades_is_byte_identical_to_script_output(tmp_path: Path) -> None:
    script = load_script()
    out = tmp_path / "ace_of_spades.png"
    script.build(ASSETS, out)
    assert out.read_bytes() == (ASSETS / "ace_of_spades.png").read_bytes()


def test_script_is_deterministic(tmp_path: Path) -> None:
    script = load_script()
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    script.build(ASSETS, first)
    script.build(ASSETS, second)
    assert first.read_bytes() == second.read_bytes()


def test_ace_of_spades_is_card_sized_rgba() -> None:
    im = Image.open(ASSETS / "ace_of_spades.png")
    assert im.format == "PNG"
    assert im.size == CARD_SIZE
    assert im.mode == "RGBA"


def dark_components(im: Image.Image, box: tuple[int, int, int, int]) -> int:
    """Number of separate dark blobs (4-connected) inside `box`."""
    px = im.convert("RGBA").load()
    x0, y0, x1, y1 = box
    dark = {
        (x, y)
        for y in range(y0, y1)
        for x in range(x0, x1)
        if px[x, y][3] > 0 and min(px[x, y][:3]) < 128
    }
    blobs = 0
    while dark:
        blobs += 1
        stack = [dark.pop()]
        while stack:
            x, y = stack.pop()
            for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nb in dark:
                    dark.remove(nb)
                    stack.append(nb)
    return blobs


def test_ornate_centre_is_gone() -> None:
    # The ornate spade is hundreds of separate filigree strokes; a plain spade is one solid blob.
    im = Image.open(ASSETS / "ace_of_spades.png")
    assert dark_components(im, CENTRE_WINDOW) == 1


def test_new_pip_matches_other_aces_centre_pip() -> None:
    script = load_script()
    reference = []
    for name in ("ace_of_hearts.png", "ace_of_clubs.png"):
        im = Image.open(ASSETS / name).convert("RGBA")
        box = script.pip_box(im)
        assert box is not None
        reference.append(box)
    ref_h = sum(y1 - y0 + 1 for _, y0, _, y1 in reference) / len(reference)
    im = Image.open(ASSETS / "ace_of_spades.png").convert("RGBA")
    pip = script.pip_box(im)
    assert pip is not None
    height = pip[3] - pip[1] + 1
    assert abs(height - ref_h) <= 0.05 * ref_h
    cx = (pip[0] + pip[2]) / 2
    cy = (pip[1] + pip[3]) / 2
    ref_cx = sum((x0 + x1) / 2 for x0, _, x1, _ in reference) / len(reference)
    ref_cy = sum((y0 + y1) / 2 for _, y0, _, y1 in reference) / len(reference)
    assert abs(cx - ref_cx) <= 6
    assert abs(cy - ref_cy) <= 6


def test_every_deck_asset_is_500x726_rgba() -> None:
    # Replaces a pinned total-bytes check: per-file dimensions and mode are what the renderer needs.
    names = sorted({image_filename(card) for card in FULL_DECK})
    assert len(names) == 40
    for name in names:
        im = Image.open(ASSETS / name)
        assert im.size == CARD_SIZE, name
        assert im.mode == "RGBA", name
