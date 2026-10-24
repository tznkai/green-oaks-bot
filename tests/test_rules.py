# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from green_oaks_bot.deck import FULL_DECK, Card, Rank, Suit
from green_oaks_bot.rules import describe, resolve, upgrade
from green_oaks_bot.ruleset import RedrawOption, default_ruleset

RULESET = default_ruleset()
LABELS = RULESET.labels
TRUMP = Suit.HEARTS
OTHER = Suit.SPADES
FACES = [Rank.JACK, Rank.QUEEN, Rank.KING]
PIPS = [Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX, Rank.SEVEN]


def trump(rank):
    return Card(TRUMP, rank)


def non_trump(rank):
    return Card(OTHER, rank)


def res(card, trump_suit=TRUMP):
    return resolve(card, trump_suit, RULESET)


# AC2.1
def test_trump_ace_is_success_with_keyword_and_trump_change():
    o = res(trump(Rank.ACE))
    assert o.success is True
    assert o.keyword == RULESET.cell(True, "ace").keyword
    assert o.success_points == 5
    assert o.failure_points == 0
    assert o.changes_trump is True
    assert o.special is True
    assert o.redraw is RedrawOption.NONE
    assert o.trump is True


# AC2.2
def test_non_trump_ace_is_failure_with_keyword():
    o = res(non_trump(Rank.ACE))
    assert o.success is False
    assert o.keyword == RULESET.cell(False, "ace").keyword
    assert o.failure_points == 4
    assert o.success_points == 0
    assert o.redraw is RedrawOption.NONE
    assert o.changes_trump is False
    assert o.special is False
    assert o.trump is False


# AC2.3
def test_trump_two_is_success_with_keyword():
    o = res(trump(Rank.TWO))
    assert o.success is True
    assert o.keyword == RULESET.cell(True, "two").keyword
    assert o.success_points == 4
    assert o.failure_points == 0
    assert o.changes_trump is False
    assert o.special is False


# AC2.4
def test_non_trump_two_is_failure_with_keyword():
    o = res(non_trump(Rank.TWO))
    assert o.success is False
    assert o.keyword == RULESET.cell(False, "two").keyword
    assert o.failure_points == 3
    assert o.redraw is RedrawOption.NONE
    assert o.changes_trump is False


# AC2.5
@pytest.mark.parametrize("rank", FACES)
def test_trump_face_is_success_worth_two(rank):
    o = res(trump(rank))
    assert o.success is True
    assert o.success_points == 2
    assert o.failure_points == 0
    assert o.keyword is None
    assert o.redraw is RedrawOption.NONE
    assert o.changes_trump is False


# AC2.6
@pytest.mark.parametrize("rank", FACES)
def test_non_trump_face_is_failure_worth_two_with_upgrade_redraw(rank):
    o = res(non_trump(rank))
    assert o.success is False
    assert o.failure_points == 2
    assert o.success_points == 0
    assert o.keyword is None
    assert o.redraw is RedrawOption.UPGRADE


@pytest.mark.parametrize("rank", FACES)
def test_upgrade_turns_non_trump_face_into_success_worth_the_upgrade_points(rank):
    before = res(non_trump(rank))
    after = upgrade(before, RULESET)
    assert after.success is True
    assert after.success_points == RULESET.upgrade_points == 3
    assert after.failure_points == 0
    assert after.card == before.card
    assert after.redraw is RedrawOption.NONE
    assert after.changes_trump is False
    assert after.special is False


def test_upgrade_rejects_outcome_without_upgrade_redraw():
    with pytest.raises(ValueError):
        upgrade(res(trump(Rank.FIVE)), RULESET)


# AC2.7
@pytest.mark.parametrize("rank", PIPS)
def test_trump_pip_is_success_worth_two(rank):
    o = res(trump(rank))
    assert o.success is True
    assert o.success_points == 2
    assert o.failure_points == 0
    assert o.redraw is RedrawOption.NONE
    assert o.changes_trump is False


@pytest.mark.parametrize("trump_suit", list(Suit))
def test_only_trump_ace_changes_trump_for_every_card(trump_suit):
    for card in FULL_DECK:
        o = res(card, trump_suit)
        assert o.changes_trump == (card.suit is trump_suit and card.rank is Rank.ACE), card


# AC2.8
@pytest.mark.parametrize("rank", PIPS)
def test_non_trump_pip_is_failure_worth_one_with_replace_redraw(rank):
    o = res(non_trump(rank))
    assert o.success is False
    assert o.failure_points == 1
    assert o.success_points == 0
    assert o.redraw is RedrawOption.REPLACE


# AC2.9
def test_representative_scores_are_ordered():
    cases = [
        trump(Rank.ACE),
        trump(Rank.TWO),
        trump(Rank.KING),
        trump(Rank.FIVE),
        non_trump(Rank.FIVE),
        non_trump(Rank.KING),
        non_trump(Rank.TWO),
        non_trump(Rank.ACE),
    ]
    scores = [res(c).score for c in cases]
    assert scores == [5, 4, 2, 2, -1, -2, -3, -4]


def test_every_success_scores_above_every_failure():
    outcomes = [res(c) for c in FULL_DECK]
    successes = [o.score for o in outcomes if o.success]
    failures = [o.score for o in outcomes if not o.success]
    assert min(successes) > max(failures)


@pytest.mark.parametrize("trump_suit", list(Suit))
def test_score_equals_success_points_minus_failure_points_for_every_card(trump_suit):
    for card in FULL_DECK:
        o = res(card, trump_suit)
        assert o.score == o.success_points - o.failure_points


def test_describe_trump_ace_mentions_success_keyword_and_points():
    text = describe(res(trump(Rank.ACE)), RULESET)
    assert text
    assert LABELS.success in text
    assert RULESET.cell(True, "ace").keyword in text
    assert f"{LABELS.success_points} 5" in text


def test_describe_non_trump_five_mentions_failure_and_failure_points():
    text = describe(res(non_trump(Rank.FIVE)), RULESET)
    assert text
    assert LABELS.failure in text
    assert f"{LABELS.failure_points} 1" in text
