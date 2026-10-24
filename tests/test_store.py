# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-channel persistence: round-trips, atomic saves, corrupt-file recovery, transactions."""

from __future__ import annotations

import asyncio
import json
import os
import random
import stat
import threading
import time
from pathlib import Path

import pytest

from green_oaks_bot import store as store_mod
from green_oaks_bot.deck import Card, Rank, Suit
from green_oaks_bot.rules import resolve
from green_oaks_bot.ruleset import default_ruleset
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
        last_outcome=resolve(Card(Suit.CLUBS, Rank.KING), Suit.SPADES, default_ruleset()),
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
        last_outcome=resolve(Card(Suit.HEARTS, Rank.TWO), Suit.SPADES, default_ruleset()),
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
# This alternation test is the one that guards the per-channel lock. The card-count test above
# can pass without the lock, so do not delete this one as redundant.
async def test_saves_for_one_channel_never_overlap(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)

    events: list[str] = []
    real_write = Store._write

    def traced_write(self, path, data):
        events.append("start")
        time.sleep(0.001)  # runs in a worker thread; widens any overlap window
        real_write(self, path, data)
        events.append("end")

    monkeypatch.setattr(Store, "_write", traced_write)
    await asyncio.gather(*[
        store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE)) for _ in range(39)
    ])

    assert len(events) == 2 * 39
    assert all(e == ("start" if i % 2 == 0 else "end") for i, e in enumerate(events))


# AC9.6 (cancellation: the lock must outlast the orphaned save thread)
async def test_cancelled_save_keeps_lock_until_thread_finishes(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)

    events: list[str] = []
    real_write = Store._write

    def traced_write(self, path, data):
        events.append("start")
        time.sleep(0.2)  # the cancellation lands while this thread is still writing
        real_write(self, path, data)
        events.append("end")

    monkeypatch.setattr(Store, "_write", traced_write)
    task = asyncio.create_task(store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE)))
    while "start" not in events:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The thread finished before the cancellation was re-raised, so the lock was still held.
    assert events == ["start", "end"]
    assert not store.lock(GUILD, CHANNEL).locked()

    await store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE))
    assert events == ["start", "end", "start", "end"]

    # Disk ends consistent with memory: both flips are present, no card missing or doubled.
    memory, _ = store.load(GUILD, CHANNEL)
    disk, _ = Store(tmp_path).load(GUILD, CHANNEL)
    assert state(disk) == state(memory)
    assert len(unique_codes(disk)) == 40
    assert len(disk.deck.discards) == 1 + 2  # the turned-up card plus two flips


# AC9.6 (a cancelled write that has finished keeps memory, which then matches disk)
async def test_cancelled_completed_save_keeps_new_state_in_memory(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)
    real_write = Store._write
    started: list[str] = []

    def slow_write(self, path, data):
        started.append("start")
        time.sleep(0.2)
        real_write(self, path, data)

    monkeypatch.setattr(Store, "_write", slow_write)
    task = asyncio.create_task(store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE)))
    while not started:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    memory, _ = store.load(GUILD, CHANNEL)
    disk, _ = Store(tmp_path).load(GUILD, CHANNEL)
    assert len(memory.deck.discards) == 1 + 1  # the turned-up card plus the one flip
    assert state(disk) == state(memory)


async def _wait_for(events: list[str], marker: str) -> None:
    for _ in range(5000):
        if marker in events:
            return
        await asyncio.sleep(0.001)
    raise AssertionError(f"{marker!r} never reached the trace")


# AC9.6 (shutdown cancels every task on the loop, so the write thread must still hold the lock).
# The write thread blocks on an event rather than a sleep, so the cancellation always lands mid-write.
async def test_cancel_all_tasks_mid_write_keeps_lock_until_thread_finishes(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)
    before = state(store.load(GUILD, CHANNEL)[0])
    events: list[str] = []
    release = threading.Event()

    def blocked_failing_write(self, path, data):
        events.append("start")
        release.wait(10)
        events.append("end")
        raise OSError("disk full")  # fails before touching the file, so disk keeps the old state

    monkeypatch.setattr(Store, "_write", blocked_failing_write)
    task = asyncio.create_task(store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE)))
    await _wait_for(events, "start")
    for other in asyncio.all_tasks():
        if other is not asyncio.current_task():
            other.cancel()
    for _ in range(50):  # let the loop deliver the cancellation while the thread is still blocked
        await asyncio.sleep(0)
    assert events == ["start"]
    assert store.lock(GUILD, CHANNEL).locked()
    assert not task.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["start", "end"]
    assert not store.lock(GUILD, CHANNEL).locked()
    # The write raised, so memory rolls back and matches the untouched file.
    assert state(store.load(GUILD, CHANNEL)[0]) == before
    assert state(Store(tmp_path).load(GUILD, CHANNEL)[0]) == before


# AC9.6 (a write that finished after a cancel keeps the cancel as the outcome, with no masked error)
async def test_cancel_all_tasks_mid_write_on_success_keeps_new_state(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)
    real_write = Store._write
    events: list[str] = []
    release = threading.Event()

    def blocked_write(self, path, data):
        events.append("start")
        release.wait(10)
        real_write(self, path, data)
        events.append("end")

    monkeypatch.setattr(Store, "_write", blocked_write)
    task = asyncio.create_task(store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE)))
    await _wait_for(events, "start")
    for other in asyncio.all_tasks():
        if other is not asyncio.current_task():
            other.cancel()
    for _ in range(50):
        await asyncio.sleep(0)
    assert events == ["start"]
    assert store.lock(GUILD, CHANNEL).locked()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["start", "end"]
    assert not store.lock(GUILD, CHANNEL).locked()
    memory, _ = store.load(GUILD, CHANNEL)
    disk, _ = Store(tmp_path).load(GUILD, CHANNEL)
    assert len(memory.deck.discards) == 1 + 1  # the turned-up card plus the one flip
    assert state(disk) == state(memory)


# AC9.6 (rollback: a command that mutates and then raises leaves no trace)
async def test_failed_action_rolls_back_memory_and_disk(tmp_path: Path):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)
    before = state(store.load(GUILD, CHANNEL)[0])

    def flip_then_raise(t, n):
        t.flip(ALICE)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await store.transact(GUILD, CHANNEL, flip_then_raise)

    seen: list = []
    await store.transact(GUILD, CHANNEL, lambda t, n: seen.append(state(t)))
    assert seen == [before]
    assert state(Store(tmp_path).load(GUILD, CHANNEL)[0]) == before


# AC9.3 (rollback: a save that fails after the action mutated memory)
async def test_failed_save_rolls_memory_back_to_match_file(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)
    before = state(store.load(GUILD, CHANNEL)[0])

    def failing_replace(src, dst):
        raise OSError("rename refused")

    monkeypatch.setattr(store_mod.os, "replace", failing_replace)
    with pytest.raises(OSError):
        await store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE))
    monkeypatch.undo()

    seen: list = []
    await store.transact(GUILD, CHANNEL, lambda t, n: seen.append(state(t)))
    assert seen == [before]
    assert state(Store(tmp_path).load(GUILD, CHANNEL)[0]) == before


# AC9.3 (a failing directory fsync is best-effort: the replace already happened)
def test_directory_fsync_failure_does_not_fail_save(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    t = make_table(["KC"], trump="S", seed=7)
    real_fsync = os.fsync

    def failing_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("fsync refused")
        real_fsync(fd)  # the temp file's own fsync still succeeds

    monkeypatch.setattr(store_mod.os, "fsync", failing_fsync)
    store.save(GUILD, CHANNEL, t)  # must not raise
    monkeypatch.undo()
    assert state(Store(tmp_path).load(GUILD, CHANNEL)[0]) == state(t)


# AC9.3 (the rename is made durable by fsyncing the parent directory)
@pytest.mark.skipif(os.name != "posix", reason="directory fsync is POSIX-only")
def test_save_fsyncs_parent_directory(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    t = make_table(["KC"], trump="S", seed=7)
    real_fsync = os.fsync
    directory_fsyncs: list[tuple[int, int]] = []

    def recording_fsync(fd):
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            directory_fsyncs.append((st.st_dev, st.st_ino))
        real_fsync(fd)

    monkeypatch.setattr(store_mod.os, "fsync", recording_fsync)
    store.save(GUILD, CHANNEL, t)
    monkeypatch.undo()

    parent = store.path(GUILD, CHANNEL).parent
    parent_st = os.stat(parent)
    assert (parent_st.st_dev, parent_st.st_ino) in directory_fsyncs


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


# AC9.4 (a second corruption of the same channel must not overwrite the first .corrupt copy)
def test_second_corruption_keeps_first_corrupt_copy(tmp_path: Path):
    store = Store(tmp_path)
    path = store.path(GUILD, CHANNEL)
    path.parent.mkdir(parents=True)
    path.write_text("{first", encoding="utf-8")
    store.load(GUILD, CHANNEL)

    path.write_text("{second", encoding="utf-8")
    Store(tmp_path).load(GUILD, CHANNEL)

    assert path.with_name(path.name + ".corrupt").read_text(encoding="utf-8") == "{first"
    assert path.with_name(path.name + ".corrupt.1").read_text(encoding="utf-8") == "{second"


def dict_with_outcome() -> dict:
    return table_to_dict(make_table(
        ["KC", "2H"], trump="S", pending=Pending("42", "grumble_upgrade"),
        last_outcome=resolve(Card(Suit.CLUBS, Rank.KING), Suit.SPADES, default_ruleset()),
    ))


def _set(*keys):
    def apply(d: dict, value) -> None:
        target = d
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    return apply


# AC9.4 (loose values that the old loader accepted must now count as corrupt)
BAD_FIELDS = [
    ("aces_drawn_five", _set("aces_drawn"), 5),
    ("aces_drawn_negative", _set("aces_drawn"), -1),
    ("aces_drawn_true", _set("aces_drawn"), True),
    ("aces_drawn_float", _set("aces_drawn"), 1.5),
    ("aces_drawn_string", _set("aces_drawn"), "1"),
    ("version_true", _set("version"), True),
    ("trump_not_a_suit", _set("trump"), "X"),
    ("trump_not_a_string", _set("trump"), 5),
    ("draw_not_a_list", _set("draw"), "KC"),
    ("draw_entry_not_a_string", _set("draw"), [5, "2H"]),
    ("pending_not_an_object", _set("pending"), "grumble_upgrade"),
    ("pending_user_id_int", _set("pending", "user_id"), 42),
    ("pending_kind_unknown", _set("pending", "kind"), "bogus"),
    ("outcome_trump_int", _set("last_outcome", "trump"), 1),
    ("outcome_success_string", _set("last_outcome", "success"), "yes"),
    ("outcome_changes_trump_none", _set("last_outcome", "changes_trump"), None),
    ("outcome_success_points_true", _set("last_outcome", "success_points"), True),
    ("outcome_failure_points_float", _set("last_outcome", "failure_points"), 1.5),
    ("outcome_keyword_int", _set("last_outcome", "keyword"), 5),
    ("outcome_special_int", _set("last_outcome", "special"), 1),
    ("outcome_not_an_object", _set("last_outcome"), []),
    ("style_int", _set("style"), 5),
    ("images_int", _set("images"), 1),
]


# AC9.4 (loose validation)
@pytest.mark.parametrize("apply, value", [(a, v) for _, a, v in BAD_FIELDS], ids=[n for n, _, _ in BAD_FIELDS])
def test_loose_field_values_are_treated_as_corrupt(tmp_path: Path, apply, value):
    d = dict_with_outcome()
    apply(d, value)
    store = Store(tmp_path)
    path = store.path(GUILD, CHANNEL)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(d), encoding="utf-8")

    table, notice = store.load(GUILD, CHANNEL)

    assert notice is not None and "unreadable" in notice
    assert path.with_name(path.name + ".corrupt").is_file()
    assert state(Store(tmp_path).load(GUILD, CHANNEL)[0]) == state(table)


# AC9.4 (valid values still load: the stricter checks must not reject real state)
def test_strict_validation_accepts_good_state(tmp_path: Path):
    t = make_table(["KC", "2H"], trump="S", pending=Pending("42", "grumble_upgrade"),
                   last_outcome=resolve(Card(Suit.CLUBS, Rank.KING), Suit.SPADES, default_ruleset()), aces_drawn=4)
    rebuilt = table_from_dict(table_to_dict(t), random.Random(0), prefix="!")
    assert state(rebuilt) == state(t)


# AC9.4 (deeply nested JSON raises RecursionError, which must count as corrupt)
def test_deeply_nested_json_is_treated_as_corrupt(tmp_path: Path):
    store = Store(tmp_path)
    path = store.path(GUILD, CHANNEL)
    path.parent.mkdir(parents=True)
    path.write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")

    table, notice = store.load(GUILD, CHANNEL)

    assert notice is not None and "unreadable" in notice
    assert path.with_name(path.name + ".corrupt").is_file()
    assert len(table.deck.draw) + len(table.deck.discards) == 40


# AC1.7: a non-creating transaction on a channel with no deck writes nothing and caches nothing
async def test_non_creating_transact_on_missing_file_writes_nothing(tmp_path: Path):
    store = Store(tmp_path)
    seen: list = []

    result = await store.transact(GUILD, CHANNEL, lambda t, n: seen.append((t, n)) or "done",
                                  create=False)

    assert result == "done"
    assert seen == [(None, None)]
    assert not store.path(GUILD, CHANNEL).exists()
    assert not store.path(GUILD, CHANNEL).parent.exists()


# AC1.7 (no phantom table in the cache: a later load still creates and announces the deck)
async def test_non_creating_transact_does_not_cache_a_table(tmp_path: Path):
    store = Store(tmp_path)
    await store.transact(GUILD, CHANNEL, lambda t, n: None, create=False)

    table, notice = store.load(GUILD, CHANNEL)

    assert table is not None
    assert notice == new_table_notice(table)
    assert store.path(GUILD, CHANNEL).is_file()


# AC1.7 / AC1.6: a creating transact after a non-creating one creates the deck and announces it
async def test_creating_transact_after_non_creating_one_announces_new_deck(tmp_path: Path):
    store = Store(tmp_path)
    await store.transact(GUILD, CHANNEL, lambda t, n: None, create=False)

    seen: list = []
    await store.transact(GUILD, CHANNEL, lambda t, n: seen.append(n), create=True)

    assert seen[0] is not None and "New deck" in seen[0]
    assert store.path(GUILD, CHANNEL).is_file()


# AC1.7 (an existing deck is handed to a non-creating transaction, with no notice)
async def test_non_creating_transact_on_existing_deck_gets_the_table(tmp_path: Path):
    store = Store(tmp_path)
    await store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE))
    before = state(store.load(GUILD, CHANNEL)[0])

    seen: list = []
    await store.transact(GUILD, CHANNEL, lambda t, n: seen.append((state(t), n)), create=False)

    assert seen == [(before, None)]


# AC9.4 / AC1.7: a corrupt file with a non-creating transaction is set aside, and no deck is made
async def test_non_creating_transact_on_corrupt_file_sets_it_aside_without_a_deck(tmp_path: Path):
    store = Store(tmp_path)
    path = store.path(GUILD, CHANNEL)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    seen: list = []
    await store.transact(GUILD, CHANNEL, lambda t, n: seen.append((t, n)), create=False)

    (table, notice), = seen
    assert table is None
    assert notice is not None and "unreadable" in notice
    assert not path.exists()
    assert path.with_name(path.name + ".corrupt").read_text(encoding="utf-8") == "{not json"


# AC9.6: creating and non-creating transactions on one channel never overlap their saves
async def test_mixed_creating_and_non_creating_saves_never_overlap(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    store.load(GUILD, CHANNEL)

    events: list[str] = []
    real_write = Store._write

    def traced_write(self, path, data):
        events.append("start")
        time.sleep(0.001)
        real_write(self, path, data)
        events.append("end")

    monkeypatch.setattr(Store, "_write", traced_write)
    jobs = []
    for i in range(20):
        jobs.append(store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE), create=True))
        jobs.append(store.transact(GUILD, CHANNEL, lambda t, n: t.flip(ALICE), create=False))
    await asyncio.gather(*jobs)

    assert len(events) == 2 * 40
    assert all(e == ("start" if i % 2 == 0 else "end") for i, e in enumerate(events))
    table = Store(tmp_path).load(GUILD, CHANNEL)[0]
    assert len(unique_codes(table)) == 40


# AC1.7 / AC9.6: no deck yet; non-creating jobs queued first see no deck, then one creating job makes it
async def test_non_creating_jobs_before_creating_ones_see_no_deck_then_one_announces(
    tmp_path: Path, monkeypatch
):
    store = Store(tmp_path)
    path = store.path(GUILD, CHANNEL)
    events: list[str] = []
    real_write = Store._write

    def traced_write(self, path, data):
        events.append("start")
        time.sleep(0.001)
        real_write(self, path, data)
        events.append("end")

    monkeypatch.setattr(Store, "_write", traced_write)
    seen: list[tuple[str, bool, str | None, bool]] = []

    def record(tag: str):
        def fn(t, n):
            # (job, had a table, notice, file existed when the callback ran)
            seen.append((tag, t is not None, n, path.exists()))
            if t is not None:
                t.flip(ALICE)
        return fn

    jobs = []
    for _ in range(3):
        jobs.append(store.transact(GUILD, CHANNEL, record("lazy"), create=False))
    for _ in range(3):
        jobs.append(store.transact(GUILD, CHANNEL, record("create"), create=True))
    await asyncio.gather(*jobs)

    lazy = [e for e in seen if e[0] == "lazy"]
    creating = [e for e in seen if e[0] == "create"]
    assert lazy == [("lazy", False, None, False)] * 3
    assert [e[1] for e in creating] == [True, True, True]
    assert [e[2] is not None and "New deck" in e[2] for e in creating] == [True, False, False]
    assert sum(1 for e in seen if e[2] is not None) == 1
    assert len(events) == 2 * 4   # one creation save plus one flip save per creating job
    assert all(e == ("start" if i % 2 == 0 else "end") for i, e in enumerate(events))
    assert len(unique_codes(Store(tmp_path).load(GUILD, CHANNEL)[0])) == 40


# AC9.6 (cancellation during the load for a non-creating transaction still holds the lock)
async def test_cancel_during_non_creating_load_keeps_lock_until_thread_finishes(tmp_path: Path, monkeypatch):
    store = Store(tmp_path)
    real_load = store.load
    events: list[str] = []

    def slow_load(guild_id, channel_id, create=True):
        events.append("start")
        time.sleep(0.2)
        result = real_load(guild_id, channel_id, create)
        events.append("end")
        return result

    monkeypatch.setattr(store, "load", slow_load)
    task = asyncio.create_task(store.transact(GUILD, CHANNEL, lambda t, n: None, create=False))
    while "start" not in events:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == ["start", "end"]
    assert not store.lock(GUILD, CHANNEL).locked()
    assert not store.path(GUILD, CHANNEL).exists()


# FORMAT_VERSION 2: a v1 state file is set aside as corrupt, whether its body is v1-shaped or not
@pytest.mark.parametrize("v1_shaped_body", [True, False], ids=["v1_field_names", "v2_body_stamped_v1"])
def test_v1_state_file_is_set_aside_as_corrupt(tmp_path: Path, v1_shaped_body: bool):
    last = resolve(Card(Suit.HEARTS, Rank.TWO), Suit.SPADES, default_ruleset())
    old = table_to_dict(make_table(["KC"], trump="S", seed=3, last_outcome=last))
    if v1_shaped_body:
        # v1 named its two points fields after the points terms and had no `special` field.
        labels = default_ruleset().labels
        outcome = old["last_outcome"]
        outcome[labels.success_points.lower()] = outcome.pop("success_points")
        outcome[labels.failure_points.lower()] = outcome.pop("failure_points")
        del outcome["special"]
    old["version"] = 1
    path = Store(tmp_path).path(GUILD, CHANNEL)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(old), "utf-8")

    loaded, notice = Store(tmp_path).load(GUILD, CHANNEL)

    assert notice is not None and notice.startswith(store_mod.UNREADABLE_RESET)
    assert loaded.last_outcome is None
    assert len(unique_codes(loaded)) == 40
    assert json.loads(path.with_name(path.name + ".corrupt").read_text("utf-8"))["version"] == 1
    assert json.loads(path.read_text("utf-8"))["version"] == store_mod.FORMAT_VERSION == 2
