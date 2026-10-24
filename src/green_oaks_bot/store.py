"""Per-channel JSON persistence with atomic writes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from green_oaks_bot.deck import Card, Deck, Suit
from green_oaks_bot.rules import GrumbleOption, Outcome
from green_oaks_bot.table import Pending, Table, new_table_notice

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
_SNOWFLAKE = re.compile(r"[0-9]{1,25}")  # fullmatch: "$" would accept a trailing newline
T = TypeVar("T")


def outcome_to_dict(o: Outcome) -> dict[str, Any]:
    return {
        "card": o.card.code, "trump": o.trump, "success": o.success,
        "haughtiness": o.haughtiness, "bother": o.bother, "keyword": o.keyword,
        "grumble": o.grumble.value, "changes_trump": o.changes_trump,
    }


def outcome_from_dict(d: dict[str, Any]) -> Outcome:
    return Outcome(
        card=Card.from_code(d["card"]), trump=bool(d["trump"]), success=bool(d["success"]),
        haughtiness=int(d["haughtiness"]), bother=int(d["bother"]), keyword=d["keyword"],
        grumble=GrumbleOption(d["grumble"]), changes_trump=bool(d["changes_trump"]),
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


def table_from_dict(d: Any, rng: random.Random, *, prefix: str) -> Table:
    if not isinstance(d, dict):
        raise TypeError("state is not a JSON object")
    if d.get("version") != FORMAT_VERSION:
        raise ValueError(f"unsupported state version: {d.get('version')!r}")
    pending = d["pending"]
    if pending is not None and pending["kind"] not in ("grumble_redraw", "grumble_upgrade", "choose_trump"):
        raise ValueError(f"bad pending kind: {pending['kind']!r}")
    if d["style"] not in ("emoji", "short", "long") or d["images"] not in ("large", "small", "off"):
        raise ValueError("bad display settings")
    return Table(
        Deck.from_codes(d["draw"], d["discards"]), Suit[d["trump"]], rng, prefix=prefix,
        aces_drawn=int(d["aces_drawn"]),
        pending=None if pending is None else Pending(str(pending["user_id"]), pending["kind"]),
        last_outcome=None if d["last_outcome"] is None else outcome_from_dict(d["last_outcome"]),
        style=d["style"], images=d["images"],
    )


class Store:
    def __init__(self, root: Path, *, prefix: str = "!", rng: random.Random | None = None) -> None:
        self.root = root
        self.prefix = prefix
        self.rng = rng if rng is not None else random.Random()
        self._tables: dict[tuple[str, str], Table] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def path(self, guild_id: str, channel_id: str) -> Path:
        for value in (guild_id, channel_id):
            if not _SNOWFLAKE.fullmatch(value):
                raise ValueError(f"not a snowflake id: {value!r}")
        return self.root / "guilds" / guild_id / f"{channel_id}.json"

    def lock(self, guild_id: str, channel_id: str) -> asyncio.Lock:
        return self._locks.setdefault((guild_id, channel_id), asyncio.Lock())

    def load(self, guild_id: str, channel_id: str) -> tuple[Table, str | None]:
        key = (guild_id, channel_id)
        if key in self._tables:
            return self._tables[key], None
        path = self.path(guild_id, channel_id)
        notice: str | None = None
        if path.exists():
            try:
                table = table_from_dict(json.loads(path.read_text("utf-8")), self.rng, prefix=self.prefix)
            except (ValueError, KeyError, TypeError) as exc:   # JSONDecodeError is a ValueError
                corrupt = path.with_name(path.name + ".corrupt")
                os.replace(path, corrupt)
                log.warning("corrupt state %s (%s); moved to %s", path, exc, corrupt)
                table = Table.new(self.rng, prefix=self.prefix)
                notice = ("Saved state for this channel was unreadable, so a fresh deck was started. "
                          + new_table_notice(table))
                self.save(guild_id, channel_id, table)
        else:
            table = Table.new(self.rng, prefix=self.prefix)
            notice = new_table_notice(table)
            self.save(guild_id, channel_id, table)
        self._tables[key] = table
        return table, notice

    def save(self, guild_id: str, channel_id: str, table: Table) -> None:
        path = self.path(guild_id, channel_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(table_to_dict(table), fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    async def transact(self, guild_id: str, channel_id: str,
                       fn: Callable[[Table, str | None], T]) -> T:
        """Serialise one command for a channel: load -> fn -> save."""
        async with self.lock(guild_id, channel_id):
            table, notice = await asyncio.to_thread(self.load, guild_id, channel_id)
            snapshot = table_to_dict(table)
            try:
                result = fn(table, notice)
                await asyncio.to_thread(self.save, guild_id, channel_id, table)
            except Exception:
                # Keep memory consistent with disk if the action or save failed.
                # Not BaseException: on cancellation the threaded save still finishes,
                # so memory already matches disk.
                self._tables[(guild_id, channel_id)] = table_from_dict(snapshot, self.rng, prefix=self.prefix)
                raise
            return result
