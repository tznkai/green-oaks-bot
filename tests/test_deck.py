import random
from itertools import product

import pytest

from green_oaks_bot.deck import Card, Deck, Rank, Suit


def all_pairs():
    return {(s, r) for s, r in product(Suit, Rank)}


# AC1.1
def test_rank_has_exactly_ten_members_in_order():
    assert [r.value for r in Rank] == ["A", "2", "3", "4", "5", "6", "7", "J", "Q", "K"]


def test_suits_are_four():
    assert {s.value for s in Suit} == {"C", "D", "H", "S"}


def test_fresh_deck_has_40_unique_cards():
    deck = Deck.fresh()
    assert len(deck.draw) == 40
    assert len(set(deck.draw)) == 40
    assert deck.discards == []
    assert {(c.suit, c.rank) for c in deck.draw} == all_pairs()


def test_fresh_deck_contains_no_eight_nine_ten():
    ranks = {c.rank for c in Deck.fresh().draw}
    assert ranks == set(Rank)
    assert len(ranks) == 10


# AC1.1 (shuffle)
def test_shuffle_keeps_the_same_40_cards_in_draw():
    deck = Deck.fresh()
    deck.shuffle(random.Random(1))
    assert len(deck.draw) == 40
    assert {(c.suit, c.rank) for c in deck.draw} == all_pairs()
    assert deck.discards == []


def test_same_seed_gives_same_order():
    a = Deck.fresh()
    b = Deck.fresh()
    a.shuffle(random.Random(42))
    b.shuffle(random.Random(42))
    assert a.draw == b.draw


def test_shuffle_after_flips_returns_all_cards_to_draw():
    deck = Deck.fresh()
    for _ in range(5):
        deck.flip()
    deck.shuffle(random.Random(7))
    assert len(deck.draw) == 40
    assert deck.discards == []
    assert {(c.suit, c.rank) for c in deck.draw} == all_pairs()


# AC1.2
def test_flip_moves_top_draw_card_to_top_of_discards():
    deck = Deck.fresh()
    top = deck.draw[0]
    before = len(deck.draw)
    card = deck.flip()
    assert card == top
    assert deck.discards[0] == top
    assert len(deck.draw) == before - 1


def test_second_flip_goes_on_top_of_first():
    deck = Deck.fresh()
    first = deck.flip()
    second = deck.flip()
    assert deck.discards[0] == second
    assert deck.discards[1] == first
    assert len(deck.draw) == 38


def test_flip_empty_draw_returns_none_and_changes_nothing():
    deck = Deck(draw=[], discards=[Card(Suit.CLUBS, Rank.ACE)])
    assert deck.flip() is None
    assert deck.draw == []
    assert deck.discards == [Card(Suit.CLUBS, Rank.ACE)]


# AC1.3
def test_text_styles_for_five_of_hearts():
    c = Card(Suit.HEARTS, Rank.FIVE)
    assert c.text("emoji") == "5♥"
    assert c.text("short") == "5H"
    assert c.text("long") == "Five of Hearts"


def test_text_styles_for_ace_of_spades():
    c = Card(Suit.SPADES, Rank.ACE)
    assert c.text("emoji") == "A♠"
    assert c.text("short") == "AS"
    assert c.text("long") == "Ace of Spades"


def test_text_styles_for_king_of_clubs():
    c = Card(Suit.CLUBS, Rank.KING)
    assert c.text("emoji") == "K♣"
    assert c.text("short") == "KC"
    assert c.text("long") == "King of Clubs"


def test_card_codes_round_trip_for_all_40():
    for s, r in product(Suit, Rank):
        c = Card(s, r)
        assert Card.from_code(c.code) == c


def test_deck_codes_round_trip_preserves_order():
    deck = Deck.fresh()
    deck.shuffle(random.Random(3))
    deck.flip()
    deck.flip()
    rebuilt = Deck.from_codes(deck.draw_codes(), deck.discard_codes())
    assert rebuilt.draw == deck.draw
    assert rebuilt.discards == deck.discards


def test_from_codes_rejects_unknown_code():
    codes = Deck.fresh().draw_codes()
    codes[0] = "8H"
    with pytest.raises(ValueError):
        Deck.from_codes(codes, [])


def test_from_codes_rejects_duplicate_card():
    codes = Deck.fresh().draw_codes()
    codes[1] = codes[0]
    with pytest.raises(ValueError):
        Deck.from_codes(codes, [])


def test_from_codes_rejects_wrong_total():
    codes = Deck.fresh().draw_codes()
    with pytest.raises(ValueError):
        Deck.from_codes(codes[:39], [])
    with pytest.raises(ValueError):
        Deck.from_codes(codes, [codes[0]])
