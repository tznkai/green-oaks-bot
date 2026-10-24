from itertools import product

import pytest

from green_oaks_bot.deck import FULL_DECK, Card, Rank, Suit
from green_oaks_bot.rules import (
    OBITUARY,
    RANT,
    RUMOR,
    WISE_WORDS,
    GrumbleOption,
    describe,
    resolve,
    upgrade,
)

TRUMP = Suit.HEARTS
OTHER = Suit.SPADES
FACES = [Rank.JACK, Rank.QUEEN, Rank.KING]
PIPS = [Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX, Rank.SEVEN]


def trump(rank):
    return Card(TRUMP, rank)


def non_trump(rank):
    return Card(OTHER, rank)


# AC2.1
def test_trump_ace_is_success_rumor_with_trump_change():
    o = resolve(trump(Rank.ACE), TRUMP)
    assert o.success is True
    assert o.keyword == RUMOR
    assert o.haughtiness == 5
    assert o.bother == 0
    assert o.changes_trump is True
    assert o.grumble is GrumbleOption.NONE
    assert o.trump is True


# AC2.2
def test_non_trump_ace_is_failure_obituary():
    o = resolve(non_trump(Rank.ACE), TRUMP)
    assert o.success is False
    assert o.keyword == OBITUARY
    assert o.bother == 4
    assert o.haughtiness == 0
    assert o.grumble is GrumbleOption.NONE
    assert o.changes_trump is False
    assert o.trump is False


# AC2.3
def test_trump_two_is_success_wise_words():
    o = resolve(trump(Rank.TWO), TRUMP)
    assert o.success is True
    assert o.keyword == WISE_WORDS
    assert o.haughtiness == 4
    assert o.bother == 0
    assert o.changes_trump is False


# AC2.4
def test_non_trump_two_is_failure_rant():
    o = resolve(non_trump(Rank.TWO), TRUMP)
    assert o.success is False
    assert o.keyword == RANT
    assert o.bother == 3
    assert o.grumble is GrumbleOption.NONE
    assert o.changes_trump is False


# AC2.5
@pytest.mark.parametrize("rank", FACES)
def test_trump_face_is_success_haughtiness_two(rank):
    o = resolve(trump(rank), TRUMP)
    assert o.success is True
    assert o.haughtiness == 2
    assert o.bother == 0
    assert o.keyword is None
    assert o.grumble is GrumbleOption.NONE


# AC2.6
@pytest.mark.parametrize("rank", FACES)
def test_non_trump_face_is_failure_bother_two_with_upgrade_grumble(rank):
    o = resolve(non_trump(rank), TRUMP)
    assert o.success is False
    assert o.bother == 2
    assert o.haughtiness == 0
    assert o.keyword is None
    assert o.grumble is GrumbleOption.UPGRADE


@pytest.mark.parametrize("rank", FACES)
def test_upgrade_turns_non_trump_face_into_success_haughtiness_three(rank):
    before = resolve(non_trump(rank), TRUMP)
    after = upgrade(before)
    assert after.success is True
    assert after.haughtiness == 3
    assert after.bother == 0
    assert after.card == before.card
    assert after.grumble is GrumbleOption.NONE
    assert after.changes_trump is False


def test_upgrade_rejects_outcome_without_upgrade_grumble():
    with pytest.raises(ValueError):
        upgrade(resolve(trump(Rank.FIVE), TRUMP))


# AC2.7
@pytest.mark.parametrize("rank", PIPS)
def test_trump_pip_is_success_haughtiness_two(rank):
    o = resolve(trump(rank), TRUMP)
    assert o.success is True
    assert o.haughtiness == 2
    assert o.bother == 0
    assert o.grumble is GrumbleOption.NONE


# AC2.8
@pytest.mark.parametrize("rank", PIPS)
def test_non_trump_pip_is_failure_bother_one_with_redraw_grumble(rank):
    o = resolve(non_trump(rank), TRUMP)
    assert o.success is False
    assert o.bother == 1
    assert o.haughtiness == 0
    assert o.grumble is GrumbleOption.REDRAW


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
    scores = [resolve(c, TRUMP).score for c in cases]
    assert scores == [5, 4, 2, 2, -1, -2, -3, -4]


def test_every_success_scores_above_every_failure():
    outcomes = [resolve(c, TRUMP) for c in FULL_DECK]
    successes = [o.score for o in outcomes if o.success]
    failures = [o.score for o in outcomes if not o.success]
    assert min(successes) > max(failures)


@pytest.mark.parametrize("trump_suit", list(Suit))
def test_score_equals_haughtiness_minus_bother_for_every_card(trump_suit):
    for card in FULL_DECK:
        o = resolve(card, trump_suit)
        assert o.score == o.haughtiness - o.bother


def test_describe_trump_ace_mentions_success_rumor_and_haughtiness():
    text = describe(resolve(trump(Rank.ACE), TRUMP))
    assert text
    assert "Success" in text
    assert "Rumor!" in text
    assert "Haughtiness 5" in text


def test_describe_non_trump_five_mentions_failure_and_bother():
    text = describe(resolve(non_trump(Rank.FIVE), TRUMP))
    assert text
    assert "Failure" in text
    assert "Bother 1" in text
