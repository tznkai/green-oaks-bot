# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
import random

import pytest

from green_oaks_bot.deck import Card, Rank, Suit
from green_oaks_bot.rules import describe, resolve
from green_oaks_bot.ruleset import default_ruleset
from green_oaks_bot.table import Pending, Table, new_table_notice
from tests.helpers import ALICE, BOB, GM, make_table

RULESET = default_ruleset()

HINT = "GM: time to `!shuffle`"


def snapshot(t: Table):
    return (list(t.deck.draw), list(t.deck.discards), t.trump, t.pending,
            t.last_outcome, t.aces_drawn)


def card(code: str) -> Card:
    return Card.from_code(code)


# AC1.4
def test_flip_with_empty_draw_is_refused_with_hint_and_state_unchanged():
    t = make_table(["5S"])
    t.flip(ALICE)  # draw now empty, Alice's Grumble pending
    before = snapshot(t)
    reply = t.flip(BOB)
    assert reply.tone == "error"
    assert HINT in reply.hints
    assert snapshot(t) == before
    assert t.pending == Pending(ALICE.user_id, "redraw_replace")


# AC1.5
def test_channels_have_independent_decks_and_state():
    a = Table.new(random.Random(1))
    b = Table.new(random.Random(1))
    b_before = snapshot(b)
    a.flip(ALICE)
    assert snapshot(b) == b_before
    assert len(a.deck.discards) == 2


def test_actions_in_one_channel_do_not_touch_another_after_shuffle():
    a = Table.new(random.Random(1))
    b = Table.new(random.Random(2))
    b_before = snapshot(b)
    a.shuffle(GM)
    assert snapshot(b) == b_before


# AC1.6
def test_new_table_has_39_draw_one_discard_trump_matching_it():
    t = Table.new(random.Random(3))
    assert len(t.deck.draw) == 39
    assert len(t.deck.discards) == 1
    turned = t.deck.discards[0]
    assert turned.suit is t.trump
    assert t.aces_drawn == (1 if turned.rank is Rank.ACE else 0)


def test_new_table_notice_names_trump_suit():
    t = Table.new(random.Random(3))
    assert t.trump.long_name in new_table_notice(t)


# AC3.1
@pytest.mark.parametrize(
    ("code", "tone"),
    [("5H", "success"), ("5S", "failure"), ("AH", "special")],
)
def test_flip_reply_has_card_outcome_and_tone(code, tone):
    t = make_table([code], trump="H")
    reply = t.flip(ALICE)
    expected = resolve(card(code), Suit.HEARTS, RULESET)
    assert card(code).text("long") in reply.text
    assert describe(expected, RULESET) in reply.text
    assert reply.cards == (card(code),)
    assert reply.kept_index is None
    assert reply.tone == tone


# AC3.2
def test_four_aces_drawn_puts_hint_on_every_reply():
    t = make_table(["AC", "AD", "AS", "AH", "5S"], trump="H")
    for _ in range(4):
        reply = t.flip(ALICE)
    assert HINT in reply.hints
    assert t.aces_drawn == 4
    assert HINT in t.status(ALICE).hints
    assert HINT in t.show_trump(ALICE).hints
    assert HINT in t.set_style(ALICE, "short").hints
    assert HINT in t.set_images(ALICE, "small").hints
    refused = t.redraw(ALICE)
    assert refused.tone == "error"
    assert HINT in refused.hints


def test_three_aces_with_cards_left_gives_no_hints():
    t = make_table(["AC", "AD", "AS", "5S"], trump="H")
    for _ in range(3):
        reply = t.flip(ALICE)
    assert t.aces_drawn == 3
    assert reply.hints == ()
    assert t.status(ALICE).hints == ()


# AC3.3
def test_flip_taking_last_draw_card_carries_hint_without_four_aces():
    t = make_table(["5S"], trump="H")
    assert t.aces_drawn == 0
    reply = t.flip(ALICE)
    assert t.deck.draw == []
    assert HINT in reply.hints


# AC3.4
@pytest.mark.parametrize("seed", range(10))
def test_shuffle_resets_aces_drawn_to_trump_card_ace_status(seed):
    t = make_table(["AC", "AD", "AS", "AH", "5S"], trump="H", seed=seed)
    for _ in range(4):
        t.flip(ALICE)
    assert t.aces_drawn == 4
    reply = t.shuffle(GM)
    turned = reply.cards[0]
    expected = 1 if turned.rank is Rank.ACE else 0
    assert t.aces_drawn == expected
    assert f"Aces drawn: {expected}/4" in t.status(GM).text


# AC4.1
def test_advantage_keeps_higher_card_and_discards_both():
    t = make_table(["5S", "KH"], trump="H")
    reply = t.advantage(ALICE)
    assert reply.kept_index == 1
    assert t.deck.discards[0:2] == [card("KH"), card("5S")]
    assert reply.cards == (card("5S"), card("KH"))
    assert "Kept **King of Hearts**" in reply.text


# AC4.2
def test_disadvantage_keeps_lower_card():
    t = make_table(["5S", "KH"], trump="H")
    reply = t.disadvantage(ALICE)
    assert reply.kept_index == 0
    assert "Kept **Five of Spades**" in reply.text
    assert t.deck.discards[0:2] == [card("KH"), card("5S")]


# AC4.3
@pytest.mark.parametrize("action", ["advantage", "disadvantage"])
def test_equal_scores_keep_first_card(action):
    t = make_table(["3H", "4H"], trump="H")
    reply = getattr(t, action)(ALICE)
    assert reply.kept_index == 0


# AC4.4
def test_disadvantage_keeping_trump_ace_is_ignored_grumble_is_pending():
    # AH scores +5, 5S scores -1: disadvantage keeps 5S, the non-trump 3-7.
    t = make_table(["AH", "5S"], trump="H")
    t.disadvantage(ALICE)
    assert t.last_outcome.card == card("5S")
    assert t.pending == Pending(ALICE.user_id, "redraw_replace")
    assert t.pending.kind != "choose_trump"


def test_advantage_keeping_trump_king_leaves_no_pending_even_though_5S_was_grumblable():
    t = make_table(["5S", "KH"], trump="H")
    t.advantage(ALICE)
    assert t.pending is None


# AC4.5
def test_both_advantage_cards_count_toward_aces_drawn():
    t = make_table(["AC", "AD"], trump="H")
    t.advantage(ALICE)
    assert t.aces_drawn == 2


# AC4.6
@pytest.mark.parametrize("action", ["advantage", "disadvantage"])
def test_two_flip_with_fewer_than_two_cards_is_refused_with_hint(action):
    t = make_table(["5S"], trump="H")
    before = snapshot(t)
    reply = getattr(t, action)(ALICE)
    assert reply.tone == "error"
    assert HINT in reply.hints
    assert snapshot(t) == before


# AC5.1
def test_grumble_redraws_and_outcome_replaces_old_one():
    t = make_table(["5S", "KH"], trump="H")
    t.flip(ALICE)
    reply = t.redraw(ALICE)
    assert t.last_outcome.card == card("KH")
    assert t.last_outcome.success
    assert reply.cards == (card("KH"),)
    assert t.pending is None


# AC5.2
def test_grumble_redraw_can_be_grumbled_again_to_upgrade():
    t = make_table(["5S", "6C", "QD"], trump="H")
    t.flip(ALICE)
    t.redraw(ALICE)
    assert t.pending == Pending(ALICE.user_id, "redraw_replace")
    t.redraw(ALICE)
    assert t.pending == Pending(ALICE.user_id, "redraw_upgrade")


# AC5.3
def test_grumble_on_face_card_upgrades_without_drawing():
    t = make_table(["KS", "5C"], trump="H")
    t.flip(ALICE)
    draw_before = len(t.deck.draw)
    reply = t.redraw(ALICE)
    assert reply.tone == "success"
    assert t.last_outcome.success
    assert t.last_outcome.success_points == 3
    assert len(t.deck.draw) == draw_before
    assert t.pending is None


# AC5.4
def test_grumble_by_other_player_is_refused_and_pending_remains():
    t = make_table(["5S", "5C"], trump="H")
    t.flip(ALICE)
    before = snapshot(t)
    reply = t.redraw(BOB)
    assert reply.tone == "error"
    assert snapshot(t) == before
    assert t.pending == Pending(ALICE.user_id, "redraw_replace")


# AC5.5
def test_grumble_with_nothing_pending_is_refused():
    t = make_table(["6C", "5S"], trump="H")
    reply = t.redraw(ALICE)
    assert reply.tone == "error"
    assert t.pending is None


def test_grumble_after_trump_result_is_refused():
    t = make_table(["KH", "5S"], trump="H")
    t.flip(ALICE)
    assert t.pending is None
    assert t.redraw(ALICE).tone == "error"


def test_grumble_after_non_trump_ace_is_refused():
    t = make_table(["AC", "5S"], trump="H")
    t.flip(ALICE)
    assert t.pending is None
    assert t.redraw(ALICE).tone == "error"


def test_grumble_after_non_trump_two_is_refused():
    t = make_table(["2C", "5S"], trump="H")
    t.flip(ALICE)
    assert t.pending is None
    assert t.redraw(ALICE).tone == "error"


# AC5.6
def test_next_flip_by_anyone_clears_pending_grumble():
    t = make_table(["5S", "2C", "5D"], trump="H")
    t.flip(ALICE)
    t.flip(BOB)  # a non-trump two: no grumble
    assert t.pending is None
    assert t.redraw(ALICE).tone == "error"


def test_next_flip_sets_pending_only_for_its_own_card():
    t = make_table(["5S", "2C", "5D"], trump="H")
    t.flip(ALICE)
    t.flip(BOB)
    t.flip(BOB)
    assert t.pending == Pending(BOB.user_id, "redraw_replace")


# AC5.7
def test_grumble_redraw_on_empty_draw_is_refused_with_hint_and_stays_pending():
    t = make_table(["5S"], trump="H")
    t.flip(ALICE)
    reply = t.redraw(ALICE)
    assert reply.tone == "error"
    assert HINT in reply.hints
    assert t.pending == Pending(ALICE.user_id, "redraw_replace")


# AC6.1
def test_show_trump_names_suit_and_symbol():
    t = make_table(["5S"], trump="H")
    text = t.show_trump(ALICE).text
    assert "Hearts" in text
    assert "♥" in text


# AC6.2
def test_kept_trump_ace_prompts_flipper_with_non_trump_suits_in_discards_and_sets_trump():
    t = make_table(["AH"], trump="H", discards=["3C", "4S"])
    t.flip(ALICE)
    assert t.pending == Pending(ALICE.user_id, "choose_trump")
    assert [s.long_name for s in t.valid_trump_choices()] == ["Clubs", "Spades"]
    reply = t.set_trump(ALICE, Suit.CLUBS)
    assert t.trump is Suit.CLUBS
    assert "Clubs" in reply.text
    assert t.pending is None


def test_trump_prompt_lists_only_non_trump_suits_in_discards():
    t = make_table(["AH"], trump="H", discards=["3C", "4S"])
    reply = t.flip(ALICE)
    prompt = reply.text.split("\n")[-1]
    assert "Clubs" in prompt
    assert "Spades" in prompt
    assert "Hearts" not in prompt
    assert "Diamonds" not in prompt


# AC6.3
def test_trump_flipper_may_name_suit_absent_from_discards_and_it_is_accepted():
    t = make_table(["AH"], trump="H", discards=["3C", "4S"])
    t.flip(ALICE)
    reply = t.set_trump(ALICE, Suit.DIAMONDS)
    assert reply.tone != "error"
    assert t.trump is Suit.DIAMONDS
    assert "Diamonds" in reply.text
    assert t.pending is None


# AC6.7
def test_trump_prompt_with_no_other_suit_drawn_asks_gm_to_call_it():
    t = make_table(["AH"], trump="H", discards=["2H", "KH"])
    reply = t.flip(ALICE)
    prompt = reply.text.split("\n")[-1]
    assert "no other suit has been drawn yet" in prompt
    assert "`!trump <suit>`" in prompt
    for label in ("Clubs", "Spades", "Diamonds"):
        assert label not in prompt
    assert t.pending == Pending(ALICE.user_id, "choose_trump")


def test_trump_prompt_with_no_other_suit_keeps_flippers_pending_choice_settable():
    t = make_table(["AH"], trump="H", discards=["2H", "KH"])
    t.flip(ALICE)
    reply = t.set_trump(ALICE, Suit.SPADES)
    assert reply.tone != "error"
    assert t.trump is Suit.SPADES
    assert t.pending is None


def test_trump_prompt_uses_configured_prefix_when_no_other_suit_drawn():
    t = make_table(["AH"], trump="H", discards=["2H", "KH"], prefix="?")
    reply = t.flip(ALICE)
    assert "`?trump <suit>`" in reply.text.split("\n")[-1]


# AC6.4
def test_non_gm_without_pending_cannot_set_trump():
    t = make_table(["5S"], trump="H")
    before = snapshot(t)
    reply = t.set_trump(BOB, Suit.SPADES)
    assert reply.tone == "error"
    assert snapshot(t) == before


def test_other_player_cannot_set_trump_during_flippers_choice():
    t = make_table(["AH"], trump="H", discards=["3C", "4S"])
    t.flip(ALICE)
    before = snapshot(t)
    reply = t.set_trump(BOB, Suit.SPADES)
    assert reply.tone == "error"
    assert snapshot(t) == before


# AC6.5
def test_gm_can_set_any_suit_with_nothing_pending():
    t = make_table(["5S"], trump="H", discards=["3C", "4S"])
    reply = t.set_trump(GM, Suit.DIAMONDS)
    assert reply.tone != "error"
    assert t.trump is Suit.DIAMONDS


def test_gm_set_clears_flippers_pending_trump_choice():
    t = make_table(["AH"], trump="H", discards=["3C", "4S"])
    t.flip(ALICE)
    t.set_trump(GM, Suit.DIAMONDS)
    assert t.trump is Suit.DIAMONDS
    assert t.pending is None


# AC7.1
def test_gm_shuffle_returns_all_cards_turns_trump_and_clears_state():
    t = make_table(["5S", "6C"], trump="H")
    t.flip(ALICE)  # sets pending, last_outcome
    reply = t.shuffle(GM)
    assert len(t.deck.draw) == 39
    assert len(t.deck.discards) == 1
    assert len({*t.deck.draw, *t.deck.discards}) == 40
    turned = t.deck.discards[0]
    assert t.trump is turned.suit
    assert turned.text("long") in reply.text
    assert t.trump.long_name in reply.text
    assert reply.cards == (turned,)
    assert t.pending is None
    assert t.last_outcome is None


def test_same_seed_shuffles_identically():
    a = Table.new(random.Random(9))
    b = Table.new(random.Random(9))
    a.shuffle(GM)
    b.shuffle(GM)
    assert a.deck.draw == b.deck.draw
    assert a.trump is b.trump


# AC7.2
def test_non_gm_shuffle_is_refused_and_state_unchanged():
    t = make_table(["5S", "6C"], trump="H")
    t.flip(ALICE)
    before = snapshot(t)
    reply = t.shuffle(ALICE)
    assert reply.tone == "error"
    assert snapshot(t) == before


# AC7.3
def test_status_shows_trump_counts_and_aces():
    t = make_table(["AC", "5S"], trump="H")
    t.flip(ALICE)
    text = t.status(ALICE).text
    assert "Hearts" in text
    assert "Draw: 1" in text
    assert "Discards: 39" in text
    assert "Aces drawn: 1/4" in text


# AC7.4
def test_style_change_affects_next_flip_names():
    t = make_table(["5H"], trump="H")
    t.set_style(ALICE, "emoji")
    assert t.style == "emoji"
    reply = t.flip(ALICE)
    assert "5♥" in reply.text


def test_images_setting_is_stored():
    t = make_table(["5H"], trump="H")
    t.set_images(ALICE, "off")
    assert t.images == "off"

