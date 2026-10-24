"""Card image rendering with Pillow."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from green_oaks_bot.deck import FULL_DECK, Card, Rank
from green_oaks_bot.table import ImageMode, Tone

SMALL_DIVISOR = 10   # CapersBot's CARD_DIVISOR
GAP = 40             # px between two cards
BORDER = 16          # px marker frame around each card slot
MARK_COLOUR = (255, 196, 0, 255)
DIM_ALPHA = 0.45     # opacity multiplier for the unkept card

TONE_COLOURS: dict[str, int] = {
    "success": 0x2E7D32,
    "failure": 0xC62828,
    "special": 0xF9A825,
    "info": 0x1565C0,
    "error": 0x616161,
}


def embed_colour(tone: Tone) -> int:
    return TONE_COLOURS[tone]


def image_filename(card: Card) -> str:
    suit = card.suit.long_name.lower()
    if card.rank.is_pip or card.rank is Rank.TWO:
        return f"{card.rank.value}_of_{suit}.png"
    name = f"{card.rank.long_name.lower()}_of_{suit}"
    if card.rank in (Rank.QUEEN, Rank.KING):
        name += "2"
    return name + ".png"


def _check_layout(cards: tuple[Card, ...], kept_index: int | None) -> None:
    """Table replies give kept_index None for one card and 0 or 1 for a pair; anything else is a bug."""
    if len(cards) > 2:
        raise ValueError(f"at most two cards can be rendered, got {len(cards)}")
    if len(cards) == 2:
        if isinstance(kept_index, bool) or kept_index not in (0, 1):
            raise ValueError(f"a pair needs kept_index 0 or 1, got {kept_index!r}")
    elif kept_index is not None:
        raise ValueError(f"kept_index must be None for {len(cards)} card(s), got {kept_index!r}")


class CardImages:
    """All 40 card images, loaded once."""

    def __init__(self, asset_dir: Path) -> None:
        missing = [image_filename(c) for c in FULL_DECK if not (asset_dir / image_filename(c)).is_file()]
        if missing:
            raise FileNotFoundError(f"missing card images in {asset_dir}: {', '.join(missing)}")
        self._images: dict[str, Image.Image] = {}
        for card in FULL_DECK:
            with Image.open(asset_dir / image_filename(card)) as im:
                self._images[card.code] = im.convert("RGBA")

    def __len__(self) -> int:
        return len(self._images)

    def render(self, cards: tuple[Card, ...], kept_index: int | None, mode: ImageMode) -> bytes | None:
        _check_layout(cards, kept_index)
        if mode == "off" or not cards:
            return None
        if len(cards) == 1:
            im = self._images[cards[0].code]
        else:
            im = self._pair(cards, kept_index)
        if mode == "small":
            im = im.resize((im.width // SMALL_DIVISOR, im.height // SMALL_DIVISOR),
                           Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()

    def _pair(self, cards: tuple[Card, ...], kept_index: int) -> Image.Image:
        """Two cards side by side. `_check_layout` has already guaranteed two cards and kept_index 0 or 1."""
        first = self._images[cards[0].code]
        w, h = first.size
        slot_w = w + 2 * BORDER
        canvas = Image.new("RGBA", (2 * w + GAP + 2 * BORDER, h + 2 * BORDER), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        for i, card in enumerate(cards):
            x = i * (w + GAP)
            img = self._images[card.code]
            if i == kept_index:
                draw.rectangle([x, 0, x + slot_w - 1, h + 2 * BORDER - 1], fill=MARK_COLOUR)
            else:
                img = img.copy()
                img.putalpha(img.getchannel("A").point(lambda a: int(a * DIM_ALPHA)))
            canvas.alpha_composite(img, (x + BORDER, BORDER))
        return canvas
