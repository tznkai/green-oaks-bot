"""Wiring: one MESSAGE_CREATE -> parse -> lock -> Table -> save -> render -> send."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from green_oaks_bot.commands import Command, execute, parse
from green_oaks_bot.fluxer.rest import FluxerREST, reply_to_embed
from green_oaks_bot.fluxer.roles import GMResolver
from green_oaks_bot.render import CardImages
from green_oaks_bot.store import Store
from green_oaks_bot.table import Actor, Reply

log = logging.getLogger("green_oaks_bot")

READY_LINE = "Green Oaks bot ready"
DM_TEXT = "Green Oaks Bot works in server channels only."
ERROR_TEXT = "Something went wrong handling that command. The GM can check the bot's logs."


def _needs_gm_check(cmd: Command) -> bool:
    return cmd.name == "shuffle" or (cmd.name == "trump" and bool(cmd.args))


def _display_name(d: dict[str, Any]) -> str:
    member = d.get("member") or {}
    author = d.get("author") or {}
    return (member.get("nick") or author.get("global_name") or author.get("username")
            or str(author.get("id", "someone")))


class Bot:
    def __init__(self, *, rest: FluxerREST, store: Store, images: CardImages,
                 gm: GMResolver, prefix: str) -> None:
        self.rest = rest
        self.store = store
        self.images = images
        self.gm = gm
        self.prefix = prefix
        self.user_id: str | None = None
        self._ready_logged = False
        self._dm_notified: set[str] = set()

    def on_ready(self, user_id: str) -> None:
        self.user_id = user_id
        if not self._ready_logged:
            self._ready_logged = True
            # Printed, not logged: the Pterodactyl done string must appear whatever LOG_LEVEL is.
            print(READY_LINE, flush=True)

    async def on_dispatch(self, event: str, data: dict[str, Any]) -> None:
        try:
            if event.startswith("GUILD_ROLE_"):
                self.gm.handle_event(event, data)
            elif event == "MESSAGE_CREATE":
                await self.on_message(data)
        except Exception:
            log.exception("unhandled error processing %s", event)

    async def on_message(self, d: dict[str, Any]) -> None:
        author = d.get("author") or {}
        if author.get("bot") or (self.user_id is not None and str(author.get("id")) == self.user_id):
            return
        cmd = parse(d.get("content") or "", self.prefix)
        if cmd is None:
            return
        channel_id = str(d["channel_id"])
        guild_id = d.get("guild_id")
        if not guild_id:
            if channel_id not in self._dm_notified:
                self._dm_notified.add(channel_id)
                await self.rest.send_message(channel_id, reply_to_embed(Reply(DM_TEXT), False), None)
            return
        guild_id = str(guild_id)
        try:
            user_id = str(author["id"])
            is_gm = await self.gm.is_gm(guild_id, user_id, d.get("member")) if _needs_gm_check(cmd) else False
            actor = Actor(user_id, _display_name(d), is_gm)
            reply, mode = await self.store.transact(
                guild_id, channel_id, lambda table, notice: (execute(cmd, table, actor, notice), table.images))
            png = await asyncio.to_thread(self.images.render, reply.cards, reply.kept_index, mode)
            await self.rest.send_message(channel_id, reply_to_embed(reply, png is not None), png,
                                         reply_to=d.get("id"))
        except Exception:
            log.exception("command %r failed in guild %s channel %s", cmd.name, guild_id, channel_id)
            try:
                await self.rest.send_message(channel_id, reply_to_embed(Reply(ERROR_TEXT, tone="error"), False), None)
            except Exception:
                log.exception("could not send error reply")
