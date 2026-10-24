"""Card image rendering: asset loading, single and paired layouts, embed colours."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageStat

from green_oaks_bot.deck import FULL_DECK, Card, Rank, Suit
from green_oaks_bot.render import (
    BORDER,
    GAP,
    MARK_COLOUR,
    CardImages,
    embed_colour,
    image_filename,
)
from green_oaks_bot.table import Tone

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "cards"
CARD_W, CARD_H = 500, 726


@pytest.fixture(scope="module")
def images() -> CardImages:
    return CardImages(ASSETS)


def decode(data: bytes | None) -> Image.Image:
    assert data is not None
    im = Image.open(io.BytesIO(data))
    assert im.format == "PNG"
    im.load()
    return im


def slot_x(index: int) -> int:
    return index * (CARD_W + GAP)


# --- AC8.3: asset loading and filenames -------------------------------------

def test_loads_one_image_per_card_in_full_deck(images: CardImages) -> None:
    assert len(images) == 40 == len(FULL_DECK)


@pytest.mark.parametrize(
    ("card", "filename"),
    [
        (Card(Suit.SPADES, Rank.ACE), "ace_of_spades.png"),
        (Card(Suit.HEARTS, Rank.QUEEN), "queen_of_hearts2.png"),
        (Card(Suit.CLUBS, Rank.KING), "king_of_clubs2.png"),
        (Card(Suit.DIAMONDS, Rank.JACK), "jack_of_diamonds.png"),
        (Card(Suit.HEARTS, Rank.FIVE), "5_of_hearts.png"),
    ],
)
def test_image_filename_follows_asset_naming(card: Card, filename: str) -> None:
    assert image_filename(card) == filename


def test_every_deck_card_has_an_existing_asset_file() -> None:
    for card in FULL_DECK:
        assert (ASSETS / image_filename(card)).is_file(), image_filename(card)


def test_missing_asset_names_the_missing_file(tmp_path: Path) -> None:
    missing = "queen_of_hearts2.png"
    for card in FULL_DECK:
        name = image_filename(card)
        if name != missing:
            shutil.copy(ASSETS / name, tmp_path / name)
    with pytest.raises(FileNotFoundError) as info:
        CardImages(tmp_path)
    assert missing in str(info.value)


# --- AC8.1: single card sizes and modes -------------------------------------

def test_large_single_card_is_full_size_png(images: CardImages) -> None:
    im = decode(images.render((Card(Suit.SPADES, Rank.ACE),), None, "large"))
    assert im.size == (CARD_W, CARD_H)


def test_small_single_card_is_scaled_down_png(images: CardImages) -> None:
    im = decode(images.render((Card(Suit.SPADES, Rank.ACE),), None, "small"))
    assert im.size == (50, 72)


def test_off_mode_returns_none(images: CardImages) -> None:
    assert images.render((Card(Suit.SPADES, Rank.ACE),), None, "off") is None


@pytest.mark.parametrize("mode", ["large", "small", "off"])
def test_empty_card_tuple_returns_none_in_every_mode(images: CardImages, mode: str) -> None:
    assert images.render((), None, mode) is None  # type: ignore[arg-type]


# --- AC8.2: paired layout with the kept card marked --------------------------

PAIR = (Card(Suit.HEARTS, Rank.QUEEN), Card(Suit.CLUBS, Rank.FIVE))
PAIR_W = 2 * CARD_W + GAP + 2 * BORDER
PAIR_H = CARD_H + 2 * BORDER
MARK_Y = (CARD_H + 2 * BORDER) // 2


def test_pair_is_one_png_wide_enough_for_two_cards(images: CardImages) -> None:
    im = decode(images.render(PAIR, 1, "large"))
    assert im.size == (PAIR_W, PAIR_H)


def test_pair_marks_kept_card_and_not_unkept(images: CardImages) -> None:
    im = decode(images.render(PAIR, 1, "large"))
    kept_mark = im.getpixel((slot_x(1) + BORDER // 2, MARK_Y))
    unkept_border = im.getpixel((slot_x(0) + BORDER // 2, MARK_Y))
    assert kept_mark == MARK_COLOUR == (255, 196, 0, 255)
    assert unkept_border != MARK_COLOUR


def test_kept_index_zero_marks_first_card(images: CardImages) -> None:
    im = decode(images.render(PAIR, 0, "large"))
    assert im.getpixel((slot_x(0) + BORDER // 2, MARK_Y)) == MARK_COLOUR
    assert im.getpixel((slot_x(1) + BORDER // 2, MARK_Y)) != MARK_COLOUR


def _alpha_mean(im: Image.Image, slot: int) -> float:
    x = slot_x(slot) + BORDER
    region = im.crop((x, BORDER, x + CARD_W, BORDER + CARD_H))
    return ImageStat.Stat(region.getchannel("A")).mean[0]


@pytest.mark.parametrize("kept_index", [0, 1])
def test_unkept_card_is_dimmed(images: CardImages, kept_index: int) -> None:
    # The kept slot sits over an opaque marker, so only the unkept slot shows the card's own alpha.
    card = Card(Suit.SPADES, Rank.ACE)
    raw = decode(images.render((card,), None, "large"))
    raw_mean = ImageStat.Stat(raw.getchannel("A")).mean[0]
    im = decode(images.render((card, card), kept_index, "large"))
    unkept_slot = 1 - kept_index
    assert _alpha_mean(im, unkept_slot) == pytest.approx(0.45 * raw_mean, abs=2.0)


def test_pair_small_divides_both_dimensions_by_ten(images: CardImages) -> None:
    im = decode(images.render(PAIR, 1, "small"))
    assert im.size == (PAIR_W // 10, PAIR_H // 10)


# --- AC8.4: embed colour per tone ------------------------------------------

TONES: tuple[Tone, ...] = ("success", "failure", "rumor", "info", "error")


@pytest.mark.parametrize("tone", TONES)
def test_embed_colour_is_a_24_bit_int(tone: Tone) -> None:
    colour = embed_colour(tone)
    assert isinstance(colour, int)
    assert 0 <= colour <= 0xFFFFFF


def test_embed_colours_are_distinct_per_tone() -> None:
    colours = {embed_colour(t) for t in TONES}
    assert len(colours) == len(TONES)
