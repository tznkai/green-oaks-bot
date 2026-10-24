"""Test helpers: build table state directly so tests never depend on shuffle order."""

from __future__ import annotations

import random

from green_oaks_bot.deck import FULL_DECK, Card, Deck, Suit
from green_oaks_bot.table import Actor, Table

ALICE = Actor("1", "Alice", False)
BOB = Actor("2", "Bob", False)
GM = Actor("9", "Gemma", True)


def make_table(draw_codes: list[str], trump: str = "H", discards: list[str] | None = None,
               *, seed: int = 0, aces_drawn: int = 0, **kwargs) -> Table:
    """Build a Table whose next flips are exactly `draw_codes`, in order.

    discards is None: the draw is exactly `draw_codes`; every other card is in discards
    in canonical FULL_DECK order.
    discards given: the draw is `draw_codes` followed by every card in neither list
    (canonical order); discards are exactly the given cards.

    `aces_drawn` is set explicitly, because the discards may hold Aces that were never
    flipped in the scenario.
    """
    draw = [Card.from_code(c) for c in draw_codes]
    if discards is None:
        discard_cards = [c for c in FULL_DECK if c not in draw]
    else:
        discard_cards = [Card.from_code(c) for c in discards]
        named = set(draw) | set(discard_cards)
        draw = draw + [c for c in FULL_DECK if c not in named]
    deck = Deck(draw=draw, discards=discard_cards)
    assert len(deck.draw) + len(deck.discards) == 40
    assert len(set(deck.draw) | set(deck.discards)) == 40
    return Table(deck, Suit(trump), random.Random(seed), aces_drawn=aces_drawn, **kwargs)
