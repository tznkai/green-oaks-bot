# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AC12.6: the help text, result prompts and redraw narration read exactly as they did before
they moved into the rules file. Rules words are taken from the loaded ruleset (AC11.1)."""

from __future__ import annotations

from green_oaks_bot.commands import help_text
from green_oaks_bot.deck import Card
from green_oaks_bot.rules import describe, resolve
from tests.helpers import ALICE, BOB, default_ruleset, make_table

RULESET = default_ruleset()
L = RULESET.labels
UP = RULESET.upgrade_points


def name(code: str) -> str:
    return Card.from_code(code).text("long")


def result(code: str, trump: str) -> str:
    return describe(resolve(Card.from_code(code), Card.from_code(f"2{trump}").suit, RULESET), RULESET)


def test_help_text_is_unchanged():
    assert help_text("!", RULESET) == "\n".join([
        "**Green Oaks Bot commands**",
        "`!flip` (`!f`): flip a card and resolve it against trump",
        "`!adv` / `!dis`: flip two, keep the better / worse result",
        (f"`!grumble`: after a non-trump 3–7 flip a replacement; after a non-trump face card make it "
         f"{L.success}, {L.success_points} {UP}"),
        "`!trump`: show trump. `!trump <suit>`: set trump (GM, or the player who flipped the trump Ace)",
        "`!shuffle`: GM only. Shuffle all 40 cards and turn up a new trump",
        "`!status`: trump, pile counts, Aces drawn",
        "`!style emoji|short|long`: how card names are written",
        "`!images large|small|off`: card image size",
        "`!help`: this list",
        "Rules adapted from Green Oaks © MS Edizioni / Magic Store srl, CC BY-NC-SA 4.0 "
        "https://creativecommons.org/licenses/by-nc-sa/4.0/. See the README, Licensing.",
    ])


def test_help_text_uses_the_prefix():
    assert help_text("?", RULESET).splitlines()[1] == "`?flip` (`?f`): flip a card and resolve it against trump"


def test_replace_prompt():
    t = make_table(["5S", "KH"], trump="H")
    assert t.flip(ALICE).text == "\n".join([
        f"Alice flips **{name('5S')}**: {result('5S', 'H')}.",
        "Alice may `!grumble` to flip a replacement card.",
    ])


def test_upgrade_prompt():
    t = make_table(["KS"], trump="H")
    assert t.flip(ALICE).text == "\n".join([
        f"Alice flips **{name('KS')}**: {result('KS', 'H')}.",
        f"Alice may `!grumble` to make it {L.success}, {L.success_points} {UP}.",
    ])


def test_choose_trump_prompt_lists_suits_in_the_discards():
    t = make_table(["AH"], trump="H", discards=["5S", "KC"])
    assert t.flip(ALICE).text == "\n".join([
        f"Alice flips **{name('AH')}**: {result('AH', 'H')}.",
        "Alice, choose a new trump with `!trump <suit>`: Clubs ♣, Spades ♠.",
    ])


def test_choose_trump_prompt_with_no_other_suit_drawn():
    t = make_table(["AH"], trump="H", discards=["5H"])
    assert t.flip(ALICE).text == "\n".join([
        f"Alice flips **{name('AH')}**: {result('AH', 'H')}.",
        "Alice, no other suit has been drawn yet; the GM makes the call with `!trump <suit>`.",
    ])


def test_upgrade_narration():
    t = make_table(["KS"], trump="H")
    t.flip(ALICE)
    upgraded = (f"{L.success}, {L.success_points} {UP}")
    assert t.redraw(ALICE).text == f"Alice grumbles: **{name('KS')}** becomes {upgraded}."


def test_replace_narration_carries_the_new_prompt():
    t = make_table(["5S", "6S"], trump="H")
    t.flip(ALICE)
    assert t.redraw(ALICE).text == "\n".join([
        f"Alice grumbles and flips **{name('6S')}**: {result('6S', 'H')}.",
        "Alice may `!grumble` to flip a replacement card.",
    ])


def test_redraw_errors():
    t = make_table(["5S"], trump="H")
    assert t.redraw(ALICE).text == "There is nothing to grumble about."
    t.flip(ALICE)
    assert t.redraw(BOB).text == "Only the player who flipped that card can grumble."
    assert t.redraw(ALICE).text == "The draw pile is empty, so there is nothing to redraw."
