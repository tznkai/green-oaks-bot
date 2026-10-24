import random

import pytest

from green_oaks_bot.commands import Command, execute, parse, parse_suit
from green_oaks_bot.deck import Card, Suit
from green_oaks_bot.table import Table, new_table_notice
from tests.helpers import ALICE, BOB, GM, make_table


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
    reply = execute(parse("!dance", "!"), make_table([]), ALICE)
    assert reply.tone == "error"
    assert "`!help`" in reply.text


def test_help_lists_every_command():
    reply = execute(parse("!help", "!"), make_table(["5S"]), ALICE)
    for name in ["flip", "adv", "dis", "grumble", "trump", "shuffle", "status", "style",
                 "images", "help"]:
        assert f"`!{name}" in reply.text, name


# AC7.6: configurable prefix
def test_prefix_is_configurable_single_character():
    assert parse("!flip", "?") is None
    assert parse("?flip", "?") == Command("flip", ())


def test_prefix_is_configurable_multi_character():
    assert parse("gob flip", "gob ") == Command("flip", ())
    assert parse("flip", "gob ") is None


def test_table_with_custom_prefix_uses_it_in_help_unknown_and_shuffle_hint():
    table = make_table([], prefix="?")
    help_reply = execute(parse("?help", "?"), table, ALICE)
    assert "`?flip`" in help_reply.text
    assert "`!flip`" not in help_reply.text
    assert "GM: time to `?shuffle`" in help_reply.hints

    unknown = execute(parse("?dance", "?"), table, ALICE)
    assert "`?help`" in unknown.text
    assert "GM: time to `?shuffle`" in unknown.hints


# AC6.6: suit parsing
@pytest.mark.parametrize("token,suit", [
    ("clubs", Suit.CLUBS), ("club", Suit.CLUBS), ("C", Suit.CLUBS), ("c", Suit.CLUBS),
    ("♣", Suit.CLUBS), ("♧", Suit.CLUBS),
    ("Hearts", Suit.HEARTS), ("HEARTS", Suit.HEARTS), ("h", Suit.HEARTS), ("♥", Suit.HEARTS),
    ("♡", Suit.HEARTS), ("♥️", Suit.HEARTS),
    ("spade", Suit.SPADES), ("♠", Suit.SPADES), ("♤", Suit.SPADES), ("s", Suit.SPADES),
    ("d", Suit.DIAMONDS), ("♦", Suit.DIAMONDS),
])
def test_parse_suit_accepts_names_initials_and_symbols(token, suit):
    assert parse_suit(token) is suit


@pytest.mark.parametrize("token", ["x", "stars", ""])
def test_parse_suit_rejects_unknown_tokens(token):
    assert parse_suit(token) is None


def test_trump_with_invalid_suit_lists_options_and_leaves_trump_unchanged():
    table = make_table(["5S"], trump="H")
    reply = execute(parse("!trump stars", "!"), table, GM)
    assert reply.tone == "error"
    assert "clubs, diamonds, hearts, spades" in reply.text
    assert table.trump is Suit.HEARTS


def test_trump_with_initial_sets_suit_for_gm():
    table = make_table(["5S"], trump="H")
    execute(parse("!trump s", "!"), table, GM)
    assert table.trump is Suit.SPADES


# AC7.4: settings
def test_style_and_images_change_channel_settings():
    table = make_table(["5S"])
    execute(parse("!style short", "!"), table, ALICE)
    execute(parse("!images small", "!"), table, ALICE)
    assert table.style == "short"
    assert table.images == "small"


@pytest.mark.parametrize("line", ["!style fancy", "!style"])
def test_invalid_style_is_error_listing_options_and_setting_unchanged(line):
    table = make_table(["5S"])
    reply = execute(parse(line, "!"), table, ALICE)
    assert reply.tone == "error"
    assert "emoji|short|long" in reply.text
    assert table.style == "long"


def test_invalid_images_is_error_listing_options_and_setting_unchanged():
    table = make_table(["5S"])
    reply = execute(parse("!images huge", "!"), table, ALICE)
    assert reply.tone == "error"
    assert "large|small|off" in reply.text
    assert table.images == "large"


# Routing: each command reaches the matching Table method
def test_bare_trump_shows_current_trump():
    reply = execute(parse("!trump", "!"), make_table(["5S"], trump="H"), ALICE)
    assert "Hearts" in reply.text
    assert reply.tone == "info"


def test_adv_routes_to_advantage_and_keeps_higher():
    table = make_table(["5S", "KH"], trump="H")
    reply = execute(parse("!adv", "!"), table, ALICE)
    assert reply.cards == (card("5S"), card("KH"))
    assert reply.kept_index == 1


def test_dis_routes_to_disadvantage_and_keeps_lower():
    table = make_table(["5S", "KH"], trump="H")
    reply = execute(parse("!dis", "!"), table, ALICE)
    assert reply.cards == (card("5S"), card("KH"))
    assert reply.kept_index == 0


def test_grumble_routes_to_grumble_redraw():
    table = make_table(["5S", "KH"], trump="H")
    execute(parse("!flip", "!"), table, ALICE)
    reply = execute(parse("!grumble", "!"), table, ALICE)
    assert reply.cards == (card("KH"),)


def test_shuffle_routes_to_table_and_gm_only_is_enforced_there():
    table = make_table(["5S"], trump="H")
    refused = execute(parse("!shuffle", "!"), table, ALICE)
    assert refused.tone == "error"
    assert refused.cards == ()

    done = execute(parse("!shuffle", "!"), table, GM)
    assert "shuffles" in done.text
    assert len(done.cards) == 1


def test_status_routes_to_table_status():
    table = make_table(["5S", "KH"], trump="H")
    reply = execute(parse("!status", "!"), table, ALICE)
    assert "Draw: 2" in reply.text
    assert "Discards: 38" in reply.text


# AC1.6: first-command notice is prepended
def test_notice_is_prepended_as_its_own_line():
    reply = execute(parse("!status", "!"), make_table(["5S"]), ALICE, notice="N")
    assert reply.text.startswith("N\n")


def test_no_notice_leaves_text_unprefixed():
    reply = execute(parse("!status", "!"), make_table(["5S"]), ALICE)
    assert not reply.text.startswith("\n")
    assert reply.text.startswith("Trump:")


def test_new_table_notice_comes_first_on_first_command_in_new_channel():
    table = Table.new(random.Random(7))
    notice = new_table_notice(table)
    reply = execute(parse("!status", "!"), table, ALICE, notice=new_table_notice(table))
    assert reply.text.startswith(notice + "\n")
    assert table.trump.long_name in notice


# Hints: help and unknown replies carry the shuffle hint when needed
def test_help_and_unknown_carry_shuffle_hint_when_draw_empty():
    table = make_table([])
    assert "GM: time to `!shuffle`" in execute(parse("!help", "!"), table, ALICE).hints
    assert "GM: time to `!shuffle`" in execute(parse("!dance", "!"), table, ALICE).hints


def test_help_carries_no_hint_when_not_needed():
    table = make_table(["5S"])
    assert execute(parse("!help", "!"), table, BOB).hints == ()
