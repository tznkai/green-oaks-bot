"""40-card deck: suits, ranks, cards, draw and discard piles."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

TextStyle = Literal["emoji", "short", "long"]


class Suit(Enum):
    CLUBS = "C"
    DIAMONDS = "D"
    HEARTS = "H"
    SPADES = "S"

    @property
    def symbol(self) -> str:
        return _SUIT_SYMBOLS[self]

    @property
    def long_name(self) -> str:
        return self.name.capitalize()


_SUIT_SYMBOLS = {
    Suit.CLUBS: "♣",
    Suit.DIAMONDS: "♦",
    Suit.HEARTS: "♥",
    Suit.SPADES: "♠",
}


class Rank(Enum):
    ACE = "A"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"

    @property
    def long_name(self) -> str:
        return self.name.capitalize()

    @property
    def is_face(self) -> bool:
        return self in (Rank.JACK, Rank.QUEEN, Rank.KING)

    @property
    def is_pip(self) -> bool:
        """3 to 7."""
        return self in (Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX, Rank.SEVEN)


@dataclass(frozen=True)
class Card:
    suit: Suit
    rank: Rank

    @property
    def code(self) -> str:
        return self.rank.value + self.suit.value

    @classmethod
    def from_code(cls, code: str) -> Card:
        if len(code) != 2:
            raise ValueError(f"bad card code: {code!r}")
        try:
            return cls(suit=Suit(code[1]), rank=Rank(code[0]))
        except ValueError as exc:
            raise ValueError(f"bad card code: {code!r}") from exc

    def text(self, style: TextStyle) -> str:
        if style == "emoji":
            return self.rank.value + self.suit.symbol
        if style == "short":
            return self.code
        return f"{self.rank.long_name} of {self.suit.long_name}"


FULL_DECK: tuple[Card, ...] = tuple(Card(s, r) for s in Suit for r in Rank)


@dataclass
class Deck:
    draw: list[Card] = field(default_factory=list)
    discards: list[Card] = field(default_factory=list)

    @classmethod
    def fresh(cls) -> Deck:
        return cls(draw=list(FULL_DECK), discards=[])

    def shuffle(self, rng: random.Random) -> None:
        cards = list(FULL_DECK)
        rng.shuffle(cards)
        self.draw = cards
        self.discards = []

    def flip(self) -> Card | None:
        if not self.draw:
            return None
        card = self.draw.pop(0)
        self.discards.insert(0, card)
        return card

    def draw_codes(self) -> list[str]:
        return [c.code for c in self.draw]

    def discard_codes(self) -> list[str]:
        return [c.code for c in self.discards]

    @classmethod
    def from_codes(cls, draw: list[str], discards: list[str]) -> Deck:
        d = [Card.from_code(c) for c in draw]
        x = [Card.from_code(c) for c in discards]
        allc = d + x
        if len(allc) != len(FULL_DECK) or set(allc) != set(FULL_DECK):
            raise ValueError("deck must contain each of the 40 cards exactly once")
        return cls(draw=d, discards=x)
