"""ArterioscleroSys resolution: card + trump -> Outcome.

Rule text lives here and in commands.py help only, so corrections stay local.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from green_oaks_bot.deck import Card, Rank, Suit

RUMOR = "Rumor!"
WISE_WORDS = "Wise Words"
RANT = "Rant!"
OBITUARY = "Obituary!"

UPGRADE_HAUGHTINESS = 3


class GrumbleOption(Enum):
    NONE = "none"
    REDRAW = "redraw"    # non-trump 3-7: flip a replacement card
    UPGRADE = "upgrade"  # non-trump face: becomes Success, Haughtiness 3


@dataclass(frozen=True)
class Outcome:
    card: Card
    trump: bool
    success: bool
    haughtiness: int
    bother: int
    keyword: str | None
    grumble: GrumbleOption
    changes_trump: bool

    @property
    def score(self) -> int:
        """Haughtiness minus bother: positive for success, negative for failure."""
        return self.haughtiness - self.bother


def _success(card: Card, h: int, keyword: str | None = None, changes_trump: bool = False) -> Outcome:
    return Outcome(card, True, True, h, 0, keyword, GrumbleOption.NONE, changes_trump)


def _failure(card: Card, b: int, keyword: str | None = None,
             grumble: GrumbleOption = GrumbleOption.NONE) -> Outcome:
    return Outcome(card, False, False, 0, b, keyword, grumble, False)


def resolve(card: Card, trump: Suit) -> Outcome:
    if card.suit is trump:
        if card.rank is Rank.ACE:
            return _success(card, 5, RUMOR, changes_trump=True)
        if card.rank is Rank.TWO:
            return _success(card, 4, WISE_WORDS)
        return _success(card, 2)
    if card.rank is Rank.ACE:
        return _failure(card, 4, OBITUARY)
    if card.rank is Rank.TWO:
        return _failure(card, 3, RANT)
    if card.rank.is_face:
        return _failure(card, 2, grumble=GrumbleOption.UPGRADE)
    return _failure(card, 1, grumble=GrumbleOption.REDRAW)


def upgrade(outcome: Outcome) -> Outcome:
    if outcome.grumble is not GrumbleOption.UPGRADE:
        raise ValueError("only a non-trump face card can be upgraded")
    return replace(outcome, success=True, haughtiness=UPGRADE_HAUGHTINESS, bother=0,
                   keyword=None, grumble=GrumbleOption.NONE, changes_trump=False)


def describe(outcome: Outcome) -> str:
    head = "Success" if outcome.success else "Failure"
    if outcome.keyword:
        head += f" — {outcome.keyword}"
    value = (f"Haughtiness {outcome.haughtiness}" if outcome.success
             else f"Bother {outcome.bother}")
    return f"{head}, {value}"
