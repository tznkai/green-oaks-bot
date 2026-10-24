"""Resolution: card + trump -> Outcome, using the loaded Ruleset.

No result wording lives here. The words and values come from the rules data file
(see ruleset.py and rulesets/green_oaks.toml).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from green_oaks_bot.deck import Card, Rank, Suit
from green_oaks_bot.ruleset import Category, GrumbleOption, Ruleset


@dataclass(frozen=True)
class Outcome:
    card: Card
    trump: bool
    success: bool
    success_points: int
    failure_points: int
    keyword: str | None
    grumble: GrumbleOption
    changes_trump: bool
    special: bool

    @property
    def score(self) -> int:
        """+success_points or -failure_points (never both); advantage keeps max, disadvantage keeps min."""
        return self.success_points - self.failure_points


def category_of(rank: Rank) -> Category:
    if rank is Rank.ACE:
        return "ace"
    if rank is Rank.TWO:
        return "two"
    if rank.is_face:
        return "face"
    return "pip"


def resolve(card: Card, trump: Suit, ruleset: Ruleset) -> Outcome:
    is_trump = card.suit is trump
    cell = ruleset.cell(is_trump, category_of(card.rank))
    return Outcome(
        card=card,
        trump=is_trump,
        success=cell.success,
        success_points=cell.points if cell.success else 0,
        failure_points=0 if cell.success else cell.points,
        keyword=cell.keyword,
        grumble=cell.grumble,
        changes_trump=cell.changes_trump,
        special=cell.special,
    )


def upgrade(outcome: Outcome, ruleset: Ruleset) -> Outcome:
    if outcome.grumble is not GrumbleOption.UPGRADE:
        raise ValueError("only a grumble-upgradable failure can be upgraded")
    return replace(outcome, success=True, success_points=ruleset.upgrade_points, failure_points=0,
                   keyword=None, grumble=GrumbleOption.NONE, changes_trump=False, special=False)


def describe(outcome: Outcome, ruleset: Ruleset) -> str:
    labels = ruleset.labels
    head = labels.success if outcome.success else labels.failure
    if outcome.keyword:
        head += f" — {outcome.keyword}"
    value = (f"{labels.success_points} {outcome.success_points}" if outcome.success
             else f"{labels.failure_points} {outcome.failure_points}")
    return f"{head}, {value}"
