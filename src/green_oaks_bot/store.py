# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-channel JSON persistence with atomic writes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from green_oaks_bot.deck import Card, Deck, Suit
from green_oaks_bot.ids import require_snowflake
from green_oaks_bot.rules import Outcome
from green_oaks_bot.ruleset import RedrawOption, Ruleset, default_ruleset
from green_oaks_bot.table import Pending, Table, new_table_notice

log = logging.getLogger(__name__)

# 2: outcome points fields renamed and `special` added. 3: `grumble` renamed `redraw` (key, values and
# pending kinds). Files of any other version are set aside.
FORMAT_VERSION = 3
_PENDING_KINDS = ("redraw_replace", "redraw_upgrade", "choose_trump")
_STYLES = ("emoji", "short", "long")
_IMAGE_MODES = ("large", "small", "off")
_MAX_ACES = 4
UNREADABLE_RESET = "Saved state for this channel was unreadable, so a fresh deck was started."
UNREADABLE_SET_ASIDE = "Saved state for this channel was unreadable and has been set aside."
T = TypeVar("T")


def outcome_to_dict(o: Outcome) -> dict[str, Any]:
    return {
        "card": o.card.code, "trump": o.trump, "success": o.success,
        "success_points": o.success_points, "failure_points": o.failure_points, "keyword": o.keyword,
        "redraw": o.redraw.value, "changes_trump": o.changes_trump, "special": o.special,
    }


def _strict(value: Any, kind: type, what: str) -> Any:
    """Reject values of the wrong JSON type; bool is excluded from int because bool subclasses int."""
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise TypeError(f"{what} must be {kind.__name__}")
    return value


def _str_list(value: Any, what: str) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{what} must be a list")
    return [_strict(item, str, f"{what} entry") for item in value]


def outcome_from_dict(d: Any) -> Outcome:
    if not isinstance(d, dict):
        raise TypeError("outcome is not a JSON object")
    keyword = d["keyword"]
    if keyword is not None:
        _strict(keyword, str, "keyword")
    return Outcome(
        card=Card.from_code(_strict(d["card"], str, "outcome card")),
        trump=_strict(d["trump"], bool, "outcome trump"),
        success=_strict(d["success"], bool, "outcome success"),
        success_points=_strict(d["success_points"], int, "success_points"),
        failure_points=_strict(d["failure_points"], int, "failure_points"),
        keyword=keyword,
        redraw=RedrawOption(d["redraw"]),
        changes_trump=_strict(d["changes_trump"], bool, "changes_trump"),
        special=_strict(d["special"], bool, "special"),
    )


def table_to_dict(t: Table) -> dict[str, Any]:
    return {
        "version": FORMAT_VERSION,
        "draw": t.deck.draw_codes(),
        "discards": t.deck.discard_codes(),
        "trump": t.trump.name,
        "aces_drawn": t.aces_drawn,
        "pending": None if t.pending is None else {"user_id": t.pending.user_id, "kind": t.pending.kind},
        "last_outcome": None if t.last_outcome is None else outcome_to_dict(t.last_outcome),
        "style": t.style,
        "images": t.images,
    }


def table_from_dict(d: Any, rng: random.Random, *, prefix: str, ruleset: Ruleset | None = None) -> Table:
    if not isinstance(d, dict):
        raise TypeError("state is not a JSON object")
    version = d.get("version")
    if type(version) is not int or version != FORMAT_VERSION:
        raise ValueError(f"unsupported state version: {version!r}")
    draw = _str_list(d["draw"], "draw")
    discards = _str_list(d["discards"], "discards")
    trump = _strict(d["trump"], str, "trump")
    if trump not in Suit.__members__:
        raise ValueError(f"bad trump: {trump!r}")
    aces_drawn = _strict(d["aces_drawn"], int, "aces_drawn")
    if not 0 <= aces_drawn <= _MAX_ACES:
        raise ValueError(f"aces_drawn out of range: {aces_drawn!r}")
    pending_d = d["pending"]
    pending: Pending | None = None
    if pending_d is not None:
        if not isinstance(pending_d, dict):
            raise ValueError("pending is not a JSON object")
        kind = pending_d["kind"]
        if kind not in _PENDING_KINDS:
            raise ValueError(f"bad pending kind: {kind!r}")
        pending = Pending(_strict(pending_d["user_id"], str, "pending user_id"), kind)
    style = _strict(d["style"], str, "style")
    images = _strict(d["images"], str, "images")
    if style not in _STYLES or images not in _IMAGE_MODES:
        raise ValueError("bad display settings")
    last_outcome = None if d["last_outcome"] is None else outcome_from_dict(d["last_outcome"])
    return Table(
        Deck.from_codes(draw, discards), Suit[trump], rng, prefix=prefix,
        aces_drawn=aces_drawn, pending=pending, last_outcome=last_outcome,
        style=style, images=images, ruleset=ruleset,
    )


def _fsync_dir(directory: Path) -> None:
    """Make a rename durable. Best effort: the replace has already happened, so a failure only logs."""
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        log.warning("cannot open %s to fsync it (%s)", directory, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        log.warning("fsync of %s failed (%s)", directory, exc)
    finally:
        os.close(fd)


class _ThreadJob[R]:
    """One call run in a worker thread, whose completion is signalled by the thread itself.

    No asyncio future wraps the thread, so nothing can mark the job finished before the thread
    has returned. Only `_run` (on the thread) and `_complete` (on the loop) ever set its state.
    """

    def __init__(self, fn: Callable[..., R], *args: Any) -> None:
        self._loop = asyncio.get_running_loop()
        self._finished = asyncio.Event()
        self._value: R | None = None
        self._error: BaseException | None = None
        self._loop.run_in_executor(None, self._run, fn, args)

    def _run(self, fn: Callable[..., R], args: tuple[Any, ...]) -> None:
        try:
            value = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - every outcome, including errors, is handed to the task
            self._loop.call_soon_threadsafe(self._complete, None, exc)
        else:
            self._loop.call_soon_threadsafe(self._complete, value, None)

    def _complete(self, value: R | None, error: BaseException | None) -> None:
        self._value = value
        self._error = error
        self._finished.set()

    @property
    def succeeded(self) -> bool:
        return self._finished.is_set() and self._error is None

    async def settle(self) -> None:
        """Wait until the thread has finished, even if this task is cancelled.

        The caller holds the channel lock across this await, so the lock must not be released
        while the thread may still touch the files. A cancellation is re-raised once the thread is done.
        """
        cancelled = False
        while not self._finished.is_set():
            try:
                await self._finished.wait()
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError()

    def result(self) -> R:
        """The thread's return value or its exception; only meaningful after `settle` has returned."""
        if self._error is not None:
            raise self._error
        return self._value  # type: ignore[return-value]


class Store:
    def __init__(self, root: Path, *, prefix: str = "!", rng: random.Random | None = None,
                 ruleset: Ruleset | None = None) -> None:
        self.root = root
        self.prefix = prefix
        self.ruleset: Ruleset = ruleset if ruleset is not None else default_ruleset()
        self.rng = rng if rng is not None else random.Random()
        self._tables: dict[tuple[str, str], Table] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def path(self, guild_id: str, channel_id: str) -> Path:
        require_snowflake(guild_id)
        require_snowflake(channel_id)
        return self.root / "guilds" / guild_id / f"{channel_id}.json"

    def lock(self, guild_id: str, channel_id: str) -> asyncio.Lock:
        return self._locks.setdefault((guild_id, channel_id), asyncio.Lock())

    def load(self, guild_id: str, channel_id: str, create: bool = True) -> tuple[Table | None, str | None]:
        """Return the channel's table and a notice for the first command that sees it.

        With `create=True` a missing deck is made, saved and announced, so the table is never None.
        With `create=False` a missing deck gives `(None, None)`: nothing is written and nothing is
        cached, so a later load still creates and announces it. A corrupt file is set aside either
        way; with `create=False` no replacement is made and the notice says the state was unreadable.
        """
        key = (guild_id, channel_id)
        if key in self._tables:
            return self._tables[key], None
        path = self.path(guild_id, channel_id)
        notice: str | None = None
        if path.exists():
            try:
                table = table_from_dict(json.loads(path.read_text("utf-8")), self.rng, prefix=self.prefix,
                                        ruleset=self.ruleset)
            except (ValueError, KeyError, TypeError, RecursionError) as exc:   # JSONDecodeError is a ValueError
                corrupt = self._corrupt_target(path)
                os.replace(path, corrupt)
                log.warning("corrupt state %s (%s); moved to %s", path, exc, corrupt)
                if not create:
                    return None, UNREADABLE_SET_ASIDE
                table = Table.new(self.rng, prefix=self.prefix, ruleset=self.ruleset)
                notice = f"{UNREADABLE_RESET} {new_table_notice(table)}"
                self.save(guild_id, channel_id, table)
        elif create:
            table = Table.new(self.rng, prefix=self.prefix, ruleset=self.ruleset)
            notice = new_table_notice(table)
            self.save(guild_id, channel_id, table)
        else:
            return None, None
        self._tables[key] = table
        return table, notice

    @staticmethod
    def _corrupt_target(path: Path) -> Path:
        """First corruption is `<name>.corrupt`; later ones get `.corrupt.1`, `.corrupt.2`, ... so none is overwritten."""
        target = path.with_name(path.name + ".corrupt")
        n = 0
        while target.exists():
            n += 1
            target = path.with_name(f"{path.name}.corrupt.{n}")
        return target

    def save(self, guild_id: str, channel_id: str, table: Table) -> None:
        self._write(self.path(guild_id, channel_id), table_to_dict(table))

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        """Atomically replace `path` with `data`. Runs in a worker thread and touches no shared state."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        _fsync_dir(path.parent)

    async def transact(self, guild_id: str, channel_id: str,
                       fn: Callable[[Table | None, str | None], T], *, create: bool = True) -> T:
        """Serialise one command for a channel: load -> fn -> save.

        `fn(table, notice)` runs with the channel's table. `notice` is set for the first command
        that sees a new or reset deck, and says so.

        With `create=True` (the default) a missing deck is created first, so `table` is never None.
        With `create=False` a missing deck is not created: `fn(None, notice)` runs, nothing is
        written and nothing is cached. `notice` is set when a corrupt file was set aside.

        The lock is held until every worker thread for this channel has finished, including when
        this task is cancelled, so two threads never touch the channel's file at once.
        """
        key = (guild_id, channel_id)
        path = self.path(guild_id, channel_id)
        async with self.lock(guild_id, channel_id):
            load = _ThreadJob(self.load, guild_id, channel_id, create)
            await load.settle()
            table, notice = load.result()
            if table is None:
                return fn(None, notice)
            snapshot = table_to_dict(table)
            write: _ThreadJob[None] | None = None
            try:
                result = fn(table, notice)
                # Built on the event loop, so the worker thread never reads the live Table.
                data = table_to_dict(table)
                write = _ThreadJob(self._write, path, data)
                await write.settle()
                write.result()
            except BaseException:
                # Roll memory back unless the new state is already on disk. A write that
                # completed before a cancellation keeps memory and disk in step.
                if write is None or not write.succeeded:
                    self._tables[key] = table_from_dict(snapshot, self.rng, prefix=self.prefix,
                                                        ruleset=self.ruleset)
                raise
            return result
