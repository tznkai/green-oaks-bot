# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test helpers: build table state directly so tests never depend on shuffle order."""

from __future__ import annotations

import copy
import random
import tomllib
from functools import cache

from green_oaks_bot.deck import FULL_DECK, Card, Deck, Suit
from green_oaks_bot.ruleset import (
    DEFAULT_RULES_FILE,
    Ruleset,
    load_ruleset,
    ruleset_from_dict,
)
from green_oaks_bot.table import Actor, Table

ALICE = Actor("1", "Alice", False)
BOB = Actor("2", "Bob", False)
GM = Actor("9", "Gemma", True)


@cache
def default_ruleset() -> Ruleset:
    """The packaged rules file, loaded once. Tests pass it explicitly; production names its file."""
    return load_ruleset(DEFAULT_RULES_FILE)


RULESET = default_ruleset()

# A ruleset that differs from the packaged one in every kind of text and in one value, so a path
# that quietly used the packaged file shows up in a test. See tests/test_ruleset_wiring.py.
CUSTOM_TITLE = "**Custom commands**"


def custom_ruleset_data() -> dict:
    data = copy.deepcopy(tomllib.loads(DEFAULT_RULES_FILE.read_text("utf-8")))
    data["labels"].update(success="Victory", failure="Defeat", success_points="Glory",
                          failure_points="Shame", redraw="Rethink")
    data["redraw"]["upgrade_points"] = 7
    data["trump"]["two"]["points"] = 9
    data["help"]["title"] = CUSTOM_TITLE
    data["hints"]["may_replace"] = "{name} may {redraw_cmd} for a fresh card."
    return data


@cache
def custom_ruleset() -> Ruleset:
    ruleset = ruleset_from_dict(custom_ruleset_data(), source="custom.toml")
    assert ruleset != RULESET
    return ruleset


def make_table(draw_codes: list[str], trump: str = "H", discards: list[str] | None = None,
               *, seed: int = 0, aces_drawn: int = 0, ruleset: Ruleset = RULESET, **kwargs) -> Table:
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
    return Table(deck, Suit(trump), random.Random(seed), aces_drawn=aces_drawn, ruleset=ruleset, **kwargs)
