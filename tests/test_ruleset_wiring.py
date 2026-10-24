# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The configured ruleset reaches every path that words or values a result.

A distinct ruleset (other labels, another points value, another upgrade value, other help and
hint text) is built from a modified copy of the packaged file and passed in as the configuration
would pass it. Every assertion looks for the custom wording or value, so a path that quietly used
the packaged file (or nothing at all) fails here even though the packaged-file tests still pass.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from green_oaks_bot.commands import help_text, parse, standalone_reply
from green_oaks_bot.deck import Suit
from green_oaks_bot.rules import describe, resolve
from green_oaks_bot.ruleset import Ruleset
from green_oaks_bot.store import Store
from tests.helpers import ALICE, BOB, CUSTOM_TITLE, RULESET, custom_ruleset, make_table

GUILD, CHANNEL = "111", "222"


@pytest.fixture
def custom() -> Ruleset:
    return custom_ruleset()


def deal(table, codes: list[str], trump: str) -> None:
    """Make the table's next flips exactly `codes`, keeping the table's own ruleset."""
    table.deck = make_table(codes, trump=trump, ruleset=table.ruleset).deck
    table.trump = Suit(trump)


async def flip_through(store: Store, actor, codes: list[str], trump: str = "H"):
    def run(table, notice):
        deal(table, codes, trump)
        return table.flip(actor)
    return await store.transact(GUILD, CHANNEL, run)


async def test_store_create_and_flip_use_the_custom_ruleset(tmp_path: Path, custom: Ruleset):
    store = Store(tmp_path, ruleset=custom, rng=random.Random(3))
    table, _ = store.load(GUILD, CHANNEL)
    assert table.ruleset is custom

    reply = await flip_through(store, ALICE, ["5S"])
    card = reply.cards[0]
    expected = describe(resolve(card, Suit.HEARTS, custom), custom)
    assert expected.startswith("Defeat") and "Shame" in expected
    assert reply.text.splitlines()[0] == f"Alice flips **{card.text('long')}**: {expected}."
    assert "for a fresh card." in reply.text  # the custom may_replace hint, from the same file


async def test_custom_points_and_upgrade_value_reach_the_reply(tmp_path: Path, custom: Ruleset):
    store = Store(tmp_path, ruleset=custom, rng=random.Random(3))
    reply = await flip_through(store, ALICE, ["2H"])  # a trump two: a success worth the custom points
    keyword = RULESET.cell(True, "two").keyword  # read from the rules file, never spelled out here
    assert f"Victory — {keyword}, Glory 9." in reply.text

    reply = await flip_through(store, BOB, ["KS"])  # a non-trump face card: upgrade offered
    assert "Defeat, Shame 2." in reply.text
    assert "Bob may `!grumble` to make it Victory, Glory 7." in reply.text


async def test_reload_from_disk_keeps_the_custom_ruleset(tmp_path: Path, custom: Ruleset):
    first = Store(tmp_path, ruleset=custom, rng=random.Random(3))
    await flip_through(first, ALICE, ["5S"])

    fresh = Store(tmp_path, ruleset=custom, rng=random.Random(4))
    loaded, notice = fresh.load(GUILD, CHANNEL)
    assert notice is None
    assert loaded.ruleset is custom
    assert loaded.last_outcome is not None
    assert describe(loaded.last_outcome, custom) == describe(
        resolve(loaded.last_outcome.card, Suit.HEARTS, custom), custom)

    reply = await flip_through(fresh, BOB, ["6S"])
    assert "Defeat, Shame 1." in reply.text


async def test_a_rolled_back_table_keeps_the_custom_ruleset(tmp_path: Path, custom: Ruleset):
    store = Store(tmp_path, ruleset=custom, rng=random.Random(3))
    await flip_through(store, ALICE, ["5S"])

    def fail_after_flipping(table, notice):
        deal(table, ["6S"], "H")
        table.flip(BOB)
        raise RuntimeError("simulated failure before the save")

    with pytest.raises(RuntimeError):
        await store.transact(GUILD, CHANNEL, fail_after_flipping)

    def inspect(table, notice):
        deal(table, ["5S"], "H")
        return table.ruleset, table.flip(ALICE).text

    ruleset_seen, text = await store.transact(GUILD, CHANNEL, inspect)
    assert ruleset_seen is custom
    assert "Defeat, Shame 1." in text


async def test_store_rebuilds_a_corrupt_file_with_the_custom_ruleset(tmp_path: Path, custom: Ruleset):
    path = tmp_path / "guilds" / GUILD / f"{CHANNEL}.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", "utf-8")
    store = Store(tmp_path, ruleset=custom, rng=random.Random(3))
    table, notice = store.load(GUILD, CHANNEL)
    assert notice is not None and "fresh deck" in notice
    assert table.ruleset is custom


def test_standalone_help_shows_the_custom_help(custom: Ruleset):
    reply = standalone_reply(parse("!help", "!"), "!", custom)
    assert reply is not None
    assert reply.text.splitlines()[0] == CUSTOM_TITLE
    assert reply.text == help_text("!", custom)
    assert "**Green Oaks Bot commands**" not in reply.text


def test_help_text_is_built_from_the_ruleset_it_is_given(custom: Ruleset):
    assert help_text("!", custom).splitlines()[0] == CUSTOM_TITLE
    assert help_text("!", RULESET).splitlines()[0] != CUSTOM_TITLE
