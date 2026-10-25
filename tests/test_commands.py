# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
import random

import pytest

from green_oaks_bot.commands import (
    Command,
    creates_deck,
    execute,
    no_deck,
    parse,
    parse_suit,
    standalone_reply,
)
from green_oaks_bot.deck import Card, Suit
from green_oaks_bot.table import Table, new_table_notice
from tests.helpers import ALICE, BOB, GM, RULESET, SOURCE_URL, make_table


def card(code: str) -> Card:
    return Card.from_code(code)


# AC7.5: parsing and unknown/help replies
def test_parse_ignores_messages_without_prefix_or_command_word():
    assert parse("hello", "!") is None
    assert parse("", "!") is None
    assert parse("!", "!") is None


def test_parse_returns_command_for_prefixed_message():
    assert parse("!flip", "!") == Command("flip", ())


def test_parse_resolves_aliases():
    assert parse("!f", "!") == Command("flip", ())
    assert parse("!advantage", "!") == Command("adv", ())
    assert parse("!disadvantage", "!") == Command("dis", ())


def test_parse_command_names_are_case_insensitive():
    assert parse("!FLIP", "!") == Command("flip", ())


def test_parse_tolerates_surrounding_whitespace_and_splits_args():
    assert parse("   !flip   ", "!") == Command("flip", ())
    assert parse("!trump   s  ", "!") == Command("trump", ("s",))


def test_unknown_command_gets_help_hint():
    reply = execute(parse("!dance", "!"), make_table([]), ALICE, SOURCE_URL)
    assert reply.tone == "error"
    assert "`!help`" in reply.text


def test_help_lists_every_command():
    reply = execute(parse("!help", "!"), make_table(["5S"]), ALICE, SOURCE_URL)
    for name in ["flip", "adv", "dis", "grumble", "trump", "shuffle", "status", "style",
                 "images", "help"]:
        assert f"`!{name}" in reply.text, name


def test_help_ends_with_rules_attribution_line():
    # CC BY-NC-SA 4.0 s.3(a)(1): the credit names the publisher, the licence with its URI, and that
    # the material is adapted. The credit is the rules file's, so it names no game terms here.
    lines = execute(parse("!help", "!"), make_table(["5S"]), ALICE, SOURCE_URL).text.splitlines()
    assert lines[-2].startswith("Rules adapted from Green Oaks")
    assert "MS Edizioni" in lines[-2]
    assert "CC BY-NC-SA 4.0 https://creativecommons.org/licenses/by-nc-sa/4.0/." in lines[-2]


def test_help_ends_with_the_engine_source_line():
    lines = execute(parse("!help", "!"), make_table(["5S"]), ALICE, SOURCE_URL).text.splitlines()
    assert lines[-1] == f"Source: {SOURCE_URL} (AGPL-3.0-or-later)"


# AC7.6: configurable prefix
def test_prefix_is_configurable_single_character():
    assert parse("!flip", "?") is None
    assert parse("?flip", "?") == Command("flip", ())


def test_prefix_is_configurable_multi_character():
    assert parse("gob flip", "gob ") == Command("flip", ())
    assert parse("flip", "gob ") is None


def test_table_with_custom_prefix_uses_it_in_help_unknown_and_shuffle_hint():
    table = make_table([], prefix="?")
    help_reply = execute(parse("?help", "?"), table, ALICE, SOURCE_URL)
    assert "`?flip`" in help_reply.text
    assert "`!flip`" not in help_reply.text
    assert "GM: time to `?shuffle`" in help_reply.hints

    unknown = execute(parse("?dance", "?"), table, ALICE, SOURCE_URL)
    assert "`?help`" in unknown.text
    assert "GM: time to `?shuffle`" in unknown.hints


# AC6.6: suit parsing
@pytest.mark.parametrize("token,suit", [
    ("clubs", Suit.CLUBS), ("club", Suit.CLUBS), ("C", Suit.CLUBS), ("c", Suit.CLUBS),
    ("♣", Suit.CLUBS), ("♧", Suit.CLUBS),
    ("Hearts", Suit.HEARTS), ("HEARTS", Suit.HEARTS), ("h", Suit.HEARTS), ("♥", Suit.HEARTS),
    ("♡", Suit.HEARTS), ("♥\ufe0f", Suit.HEARTS),
    ("spade", Suit.SPADES), ("♠", Suit.SPADES), ("♤", Suit.SPADES), ("s", Suit.SPADES),
    ("d", Suit.DIAMONDS), ("♦", Suit.DIAMONDS),
])
def test_parse_suit_accepts_names_initials_and_symbols(token, suit):
    assert parse_suit(token) is suit


@pytest.mark.parametrize("token", ["x", "stars", ""])
def test_parse_suit_rejects_unknown_tokens(token):
    assert parse_suit(token) is None


def test_heart_with_variation_selector_token_contains_fe0f():
    # Guard: ensures the "\ufe0f" case really carries the selector, so the
    # strip in parse_suit is what is being exercised.
    token = "\u2665\ufe0f"
    assert len(token) == 2 and "\ufe0f" in token
    assert parse_suit(token) is Suit.HEARTS


def test_trump_with_invalid_suit_lists_options_and_leaves_trump_unchanged():
    table = make_table(["5S"], trump="H")
    reply = execute(parse("!trump stars", "!"), table, GM, SOURCE_URL)
    assert reply.tone == "error"
    assert "clubs, diamonds, hearts, spades" in reply.text
    assert table.trump is Suit.HEARTS


def test_trump_with_initial_sets_suit_for_gm():
    table = make_table(["5S"], trump="H")
    execute(parse("!trump s", "!"), table, GM, SOURCE_URL)
    assert table.trump is Suit.SPADES


# AC7.4: settings
def test_style_and_images_change_channel_settings():
    table = make_table(["5S"])
    execute(parse("!style short", "!"), table, ALICE, SOURCE_URL)
    execute(parse("!images small", "!"), table, ALICE, SOURCE_URL)
    assert table.style == "short"
    assert table.images == "small"


@pytest.mark.parametrize("line", ["!style fancy", "!style"])
def test_invalid_style_is_error_listing_options_and_setting_unchanged(line):
    table = make_table(["5S"])
    reply = execute(parse(line, "!"), table, ALICE, SOURCE_URL)
    assert reply.tone == "error"
    assert "emoji|short|long" in reply.text
    assert table.style == "long"


def test_invalid_images_is_error_listing_options_and_setting_unchanged():
    table = make_table(["5S"])
    reply = execute(parse("!images huge", "!"), table, ALICE, SOURCE_URL)
    assert reply.tone == "error"
    assert "large|small|off" in reply.text
    assert table.images == "large"


# Routing: each command reaches the matching Table method
def test_bare_trump_shows_current_trump():
    reply = execute(parse("!trump", "!"), make_table(["5S"], trump="H"), ALICE, SOURCE_URL)
    assert "Hearts" in reply.text
    assert reply.tone == "info"


def test_adv_routes_to_advantage_and_keeps_higher():
    table = make_table(["5S", "KH"], trump="H")
    reply = execute(parse("!adv", "!"), table, ALICE, SOURCE_URL)
    assert reply.cards == (card("5S"), card("KH"))
    assert reply.kept_index == 1


def test_dis_routes_to_disadvantage_and_keeps_lower():
    table = make_table(["5S", "KH"], trump="H")
    reply = execute(parse("!dis", "!"), table, ALICE, SOURCE_URL)
    assert reply.cards == (card("5S"), card("KH"))
    assert reply.kept_index == 0


def test_grumble_routes_to_grumble_redraw():
    table = make_table(["5S", "KH"], trump="H")
    execute(parse("!flip", "!"), table, ALICE, SOURCE_URL)
    reply = execute(parse("!grumble", "!"), table, ALICE, SOURCE_URL)
    assert reply.cards == (card("KH"),)


def test_shuffle_routes_to_table_and_gm_only_is_enforced_there():
    table = make_table(["5S"], trump="H")
    refused = execute(parse("!shuffle", "!"), table, ALICE, SOURCE_URL)
    assert refused.tone == "error"
    assert refused.cards == ()

    done = execute(parse("!shuffle", "!"), table, GM, SOURCE_URL)
    assert "shuffles" in done.text
    assert len(done.cards) == 1


def test_status_routes_to_table_status():
    table = make_table(["5S", "KH"], trump="H")
    reply = execute(parse("!status", "!"), table, ALICE, SOURCE_URL)
    assert "Draw: 2" in reply.text
    assert "Discards: 38" in reply.text


# AC1.6: first-command notice is prepended
def test_notice_is_prepended_as_its_own_line():
    reply = execute(parse("!status", "!"), make_table(["5S"]), ALICE, SOURCE_URL, notice="N")
    assert reply.text.startswith("N\n")


def test_no_notice_leaves_text_unprefixed():
    reply = execute(parse("!status", "!"), make_table(["5S"]), ALICE, SOURCE_URL)
    assert not reply.text.startswith("\n")
    assert reply.text.startswith("Trump:")


def test_new_table_notice_comes_first_on_first_command_in_new_channel():
    table = Table.new(random.Random(7), ruleset=RULESET)
    notice = new_table_notice(table)
    reply = execute(parse("!status", "!"), table, ALICE, SOURCE_URL, notice=new_table_notice(table))
    assert reply.text.startswith(notice + "\n")
    assert table.trump.long_name in notice


# Hints: help and unknown replies carry the shuffle hint when needed
def test_help_and_unknown_carry_shuffle_hint_when_draw_empty():
    table = make_table([])
    assert "GM: time to `!shuffle`" in execute(parse("!help", "!"), table, ALICE, SOURCE_URL).hints
    assert "GM: time to `!shuffle`" in execute(parse("!dance", "!"), table, ALICE, SOURCE_URL).hints


def test_help_carries_no_hint_when_not_needed():
    table = make_table(["5S"])
    assert execute(parse("!help", "!"), table, BOB, SOURCE_URL).hints == ()


# AC7.5: help and unknown commands are answered without any table
def test_standalone_help_and_unknown_need_no_table():
    help_reply = standalone_reply(parse("!help", "!"), "!", RULESET, SOURCE_URL)
    assert help_reply is not None and "`!flip`" in help_reply.text
    unknown = standalone_reply(parse("!dance", "!"), "!", RULESET, SOURCE_URL)
    assert unknown is not None and unknown.tone == "error" and "`!help`" in unknown.text


def test_standalone_reply_is_none_for_table_commands():
    assert standalone_reply(parse("!flip", "!"), "!", RULESET, SOURCE_URL) is None
    assert standalone_reply(parse("!status", "!"), "!", RULESET, SOURCE_URL) is None


def test_standalone_reply_uses_configured_prefix():
    assert "`?help`" in standalone_reply(parse("?dance", "?"), "?", RULESET, SOURCE_URL).text


# AC1.7 / AC1.8: which commands are allowed to start a deck
@pytest.mark.parametrize("line, is_gm, expected", [
    ("!flip", False, True), ("!f", False, True), ("!adv", False, True), ("!dis", False, True),
    ("!shuffle", True, True), ("!shuffle", False, False),
    ("!status", False, False), ("!status", True, False), ("!trump", True, False),
    ("!trump s", True, False), ("!grumble", False, False), ("!style short", False, False),
    ("!images off", False, False), ("!help", False, False), ("!dance", False, False),
])
def test_creates_deck_only_for_flip_adv_dis_and_gm_shuffle(line, is_gm, expected):
    assert creates_deck(parse(line, "!"), is_gm) is expected


# AC1.7: the no-deck hint names the commands that start a deck, with the configured prefix
def test_no_deck_hint_names_starting_commands_with_custom_prefix():
    reply = no_deck(parse("?status", "?"), ALICE, "?")
    assert reply.tone == "info"
    for name in ["`?flip`", "`?adv`", "`?dis`", "`?shuffle`"]:
        assert name in reply.text
    assert "`!" not in reply.text


# AC1.8: a non-GM shuffle with no deck is refused and carries the hint
def test_non_gm_shuffle_without_deck_is_refused_with_hint():
    reply = no_deck(parse("!shuffle", "!"), ALICE, "!")
    assert reply.tone == "error"
    assert "Only the GM can shuffle." in reply.text
    assert "`!flip`" in reply.text


def test_no_deck_notice_is_prepended_when_given():
    reply = no_deck(parse("!trump", "!"), ALICE, "!", notice="Saved state was unreadable.")
    assert reply.text.startswith("Saved state was unreadable.\n")
    assert "`!flip`" in reply.text


# AC1.8: a GM shuffle in a new channel is the creation shuffle: the deck is not shuffled again
def test_gm_shuffle_on_new_deck_announces_without_a_second_shuffle():
    table = Table.new(random.Random(11), ruleset=RULESET)
    notice = new_table_notice(table)
    before = (table.deck.draw_codes(), table.deck.discard_codes(), table.trump)

    reply = execute(parse("!shuffle", "!"), table, GM, SOURCE_URL, notice=notice)

    assert (table.deck.draw_codes(), table.deck.discard_codes(), table.trump) == before
    assert reply.text == notice
    assert reply.text.count("turned up") == 1
    assert reply.cards == (table.deck.discards[0],)


# AC1.8: the store's creation notice never lets a non-GM shuffle through; it is refused as usual
def test_non_gm_shuffle_with_notice_is_refused_not_reshuffled():
    t = Table.new(random.Random(12), ruleset=RULESET)
    notice = new_table_notice(t)
    before = (t.deck.draw_codes(), t.deck.discard_codes(), t.trump)

    reply = execute(parse("!shuffle", "!"), t, ALICE, SOURCE_URL, notice=notice)

    assert reply.tone == "error"
    assert "Only the GM can shuffle" in reply.text
    assert (t.deck.draw_codes(), t.deck.discard_codes(), t.trump) == before
