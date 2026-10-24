"""Per-channel persistence: round-trips, atomic saves, corrupt-file recovery, transactions."""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path

import pytest

from green_oaks_bot import store as store_mod
from green_oaks_bot.deck import Card, Rank, Suit
from green_oaks_bot.rules import resolve
from green_oaks_bot.store import Store, table_from_dict, table_to_dict
from green_oaks_bot.table import Pending, Table, new_table_notice
from tests.helpers import ALICE, make_table

GUILD = "111"
CHANNEL = "222"


def state(t: Table):
    return (t.deck.draw_codes(), t.deck.discard_codes(), t.trump, t.aces_drawn,
            t.pending, t.last_outcome, t.style, t.images)


def unique_codes(t: Table) -> set[str]:
    return set(t.deck.draw_codes()) | set(t.deck.discard_codes())


def good_dict() -> dict:
    return table_to_dict(Table.new(random.Random(1)))


# AC9.1
def test_save_and_load_round_trip_every_attribute():
    t = make_table(
        ["KC", "2H", "AS", "7D"], trump="S", discards=["7C", "AD"],
        aces_drawn=2, pending=Pending("42", "grumble_upgrade"),
        last_outcome=resolve(Card(Suit.CLUBS, Rank.KING), Suit.SPADES),
        style="emoji", images="small",
    )
    rebuilt = table_from_dict(table_to_dict(t), random.Random(0), prefix="!")
    assert state(rebuilt) == state(t)
    assert rebuilt.deck.draw[:4] == [Card.from_code(c) for c in ["KC", "2H", "AS", "7D"]]


# AC9.1 (through a real file, with a new Store)
def test_round_trip_through_file_and_new_store(tmp_path: Path):
    t = make_table(
        ["KC", "2H", "AS"], trump="S", discards=["7C"], aces_drawn=1,
        pending=Pending("42", "grumble_redraw"),
        last_outcome=resolve(Card(Suit.HEARTS, Rank.TWO), Suit.SPADES),
        style="short", images="off",
    )
    Store(tmp_path).save(GUILD, CHANNEL, t)
    loaded, notice = Store(tmp_path).load(GUILD, CHANNEL)
    assert notice is None
    assert state(loaded) == state(t)


# AC9.1 (defaults: no pending, no last outcome)
def test_round_trip_with_pending_and_last_outcome_none(tmp_path: Path):
    t = make_table(["5S"], trump="H")
    assert t.pending is None and t.last_outcome is None
    Store(tmp_path).save(GUILD, CHANNEL, t)
    loaded, _ = Store(tmp_path).load(GUILD, CHANNEL)
    assert loaded.pending is None
    assert loaded.last_outcome is None
    assert state(loaded) == state(t)


# AC9.2
def test_path_is_guild_then_channel_json(tmp_path: Path):
    assert Store(tmp_path).path("111", "222") == tmp_path / "guilds" / "111" / "222.json"


# AC9.2
def test_same_channel_id_in_two_guilds_gives_two_independent_files(tmp_path: Path):
    store = Store(tmp_path)
    t1 = make_table(["5S"], trump="H", seed=1)
    t2 = make_table(["KD"], trump="C", seed=2)
    store.save("111", "222", t1)
    store.save("333", "222", t2)
    assert store.path("111", "222") != store.path("333", "222")
    assert store.path("111", "222").is_file() and store.path("333", "222").is_file()
    a, _ = Store(tmp_path).load("111", "222")
    b, _ = Store(tmp_path).load("333", "222")
    assert state(a) == state(t1)
    assert state(b) == state(t2)


# AC9.2
@pytest.mark.parametrize("guild, channel", [
    ("../x", "1"),
    ("1", "2/3"),
    ("", "1"),
    ("1", ".."),
    ("1" * 26, "1"),
    ("1\n", "1"),
    ("\u0661\u0662", "1"),  # Arabic-Indic digits, not ASCII
    ("abc", "1"),
])
def test_non_snowflake_ids_are_rejected(tmp_path: Path, guild: str, channel: str):
    with pytest.raises(ValueError):
        Store(tmp_path).path(guild, channel)


# AC9.3
def test_failed_mid_write_leaves_previous_file_intact(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    original = make_table(["KC"], trump="S", seed=3)
    store.save(GUILD, CHANNEL, original)
    before = store.path(GUILD, CHANNEL).read_bytes()

    def partial_dump(obj, fh, **kwargs):
        fh.write('{"version": 1, "draw": [')
        raise OSError("disk full")

    monkeypatch.setattr(store_mod.json, "dump", partial_dump)
    modified = make_table(["2D"], trump="H", seed=4)
    with pytest.raises(OSError):
        store.save(GUILD, CHANNEL, modified)

    assert store.path(GUILD, CHANNEL).read_bytes() == before
    loaded, _ = Store(tmp_path).load(GUILD, CHANNEL)
    assert state(loaded) == state(original)
    assert not [p for p in store.path(GUILD, CHANNEL).parent.iterdir() if p.name.endswith(".tmp")]


# AC9.3
def test_failed_replace_leaves_previous_file_and_no_temp_file(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    original = make_table(["KC"], trump="S", seed=5)
    store.save(GUILD, CHANNEL, original)
    directory = store.path(GUILD, CHANNEL).parent

    def failing_replace(src, dst):
        raise OSError("rename refused")

    monkeypatch.setattr(store_mod.os, "replace", failing_replace)
    with pytest.raises(OSError):
        store.save(GUILD, CHANNEL, make_table(["2D"], trump="H", seed=6))
    monkeypatch.undo()

    loaded, _ = Store(tmp_path).load(GUILD, CHANNEL)
    assert state(loaded) == state(original)
    assert not [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


CORRUPT_TEXTS = {
    "not_json": "{not json",
    "bad_card_code": json.dumps({**good_dict(), "draw": ["ZZ", *good_dict()["draw"][1:]]}),
    "missing_draw_key": json.dumps({k: v for k, v in good_dict().items() if k != "draw"}),
    "json_array": "[]",
    "json_null": "null",
    "json_number": "42",
}


# AC9.4
@pytest.mark.parametrize("text", list(CORRUPT_TEXTS.values()), ids=list(CORRUPT_TEXTS))
def test_corrupt_file_is_renamed_and_replaced_with_fresh_deck(tmp_path: Path, text: str):
    store = Store(tmp_path)
    path = store.path(GUILD, CHANNEL)
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")

    table, notice = store.load(GUILD, CHANNEL)

    assert notice is not None
    assert "unreadable" in notice
    assert table.trump.long_name in notice
    assert len(table.deck.draw) + len(table.deck.discards) == 40
    assert len(unique_codes(table)) == 40
    corrupt = path.with_name(path.name + ".corrupt")
    assert corrupt.read_text(encoding="utf-8") == text
    # The replacement is a valid file that a new Store reads back.
    reloaded, _ = Store(tmp_path).load(GUILD, CHANNEL)
    assert state(reloaded) == state(table)


# AC9.4 (through transact, so the notice reaches the command)
async def test_transact_passes_corrupt_reset_notice_to_fn(tmp_path: Path):
    store = Store(tmp_path)
    path = store.path(GUILD, CHANNEL)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    seen: list[str | None] = []
    await store.transact(GUILD, CHANNEL, lambda t, n: seen.append(n))
    assert seen[0] is not None and "unreadable" in seen[0]


# AC9.5
async def test_state_survives_a_new_store(tmp_path: Path):
    store_a = Store(tmp_path)
    await store_a.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE))
    await store_a.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE))
    expected_draw = store_a.load(GUILD, CHANNEL)[0].deck.draw_codes()
    expected_discards = store_a.load(GUILD, CHANNEL)[0].deck.discard_codes()

    store_b = Store(tmp_path)
    table, notice = store_b.load(GUILD, CHANNEL)
    assert notice is None
    assert table.deck.draw_codes() == expected_draw
    assert table.deck.discard_codes() == expected_discards
    assert len(table.deck.discards) == 1 + 2  # the turned-up card plus two flips
    assert table.aces_drawn == store_a.load(GUILD, CHANNEL)[0].aces_drawn


# AC9.6
async def test_concurrent_flips_in_one_channel_lose_and_duplicate_no_card(tmp_path: Path):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)  # create the fresh table

    replies = await asyncio.gather(*[
        store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE)) for _ in range(39)
    ])

    assert all(r.tone != "error" for r in replies)
    assert len({r.cards[0].code for r in replies}) == 39
    table = Store(tmp_path).load(GUILD, CHANNEL)[0]
    assert table.deck.draw == []
    assert len(table.deck.discards) == 40
    assert len(unique_codes(table)) == 40


# AC9.6 (serialisation is checked directly, not by timing)
async def test_saves_for_one_channel_never_overlap(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)

    events: list[str] = []
    real_save = Store.save

    def traced_save(self, guild_id, channel_id, table):
        events.append("start")
        time.sleep(0.001)  # runs in a worker thread; widens any overlap window
        real_save(self, guild_id, channel_id, table)
        events.append("end")

    monkeypatch.setattr(Store, "save", traced_save)
    await asyncio.gather(*[
        store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE)) for _ in range(39)
    ])

    assert len(events) == 2 * 39
    assert all(e == ("start" if i % 2 == 0 else "end") for i, e in enumerate(events))


# AC1.6
def test_missing_file_gives_fresh_table_with_trump_notice_and_writes_file(tmp_path: Path):
    store = Store(tmp_path)
    table, notice = store.load(GUILD, CHANNEL)
    assert notice == new_table_notice(table)
    assert store.path(GUILD, CHANNEL).is_file()


# AC1.6 (second load is served from the in-memory cache)
def test_second_load_on_same_store_returns_no_notice(tmp_path: Path):
    store = Store(tmp_path)
    first, _ = store.load(GUILD, CHANNEL)
    second, notice = store.load(GUILD, CHANNEL)
    assert second is first
    assert notice is None
