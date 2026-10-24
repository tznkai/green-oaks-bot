"""Wiring: one MESSAGE_CREATE -> parse -> lock -> Table -> save -> render -> send."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from green_oaks_bot.commands import Command, execute, parse
from green_oaks_bot.fluxer.rest import FluxerHTTPError, FluxerREST, reply_to_embed
from green_oaks_bot.fluxer.roles import GMResolver
from green_oaks_bot.ids import is_snowflake
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
        self._attach_warned = False

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

    async def _send_reply(self, channel_id: str, reply: Reply, png: bytes | None,
                          reply_to: str | None) -> None:
        """Send the card; a 403 on the attachment (no Attach Files permission) retries without it.

        The deck has already changed by the time we send, so a lost reply is worse than a
        text-only one. A failure of the retry falls through to the caller's error reply.
        """
        try:
            await self.rest.send_message(channel_id, reply_to_embed(reply, png is not None), png,
                                         reply_to=reply_to)
        except FluxerHTTPError as exc:
            if png is None or exc.status != 403:
                raise
            if not self._attach_warned:
                self._attach_warned = True
                log.warning("could not attach the card image (HTTP 403); the bot needs the "
                            "Attach Files permission in this channel. Sending text only.")
            await self.rest.send_message(channel_id, reply_to_embed(reply, False), None,
                                         reply_to=reply_to)

    async def on_message(self, d: dict[str, Any]) -> None:
        author = d.get("author") or {}
        if author.get("bot") or (self.user_id is not None and str(author.get("id")) == self.user_id):
            return
        # Ids below are interpolated into REST paths: drop the whole event unless they are snowflakes.
        channel_id = str(d["channel_id"])
        author_id = str(author.get("id"))
        guild_id = str(d["guild_id"]) if d.get("guild_id") else None
        if not is_snowflake(channel_id) or not is_snowflake(author_id) or \
                (guild_id is not None and not is_snowflake(guild_id)):
            log.warning("dropping message with malformed ids: channel %r, guild %r, author %r",
                        channel_id, guild_id, author_id)
            return
        cmd = parse(d.get("content") or "", self.prefix)
        if cmd is None:
            return
        # Only the reply reference is optional: a malformed message id just loses the reference.
        reply_to = str(d["id"]) if d.get("id") is not None else None
        if reply_to is not None and not is_snowflake(reply_to):
            log.warning("ignoring malformed message id %r for reply reference", reply_to)
            reply_to = None
        if not guild_id:
            if channel_id not in self._dm_notified:
                self._dm_notified.add(channel_id)
                await self.rest.send_message(channel_id, reply_to_embed(Reply(DM_TEXT), False), None)
            return
        try:
            user_id = author_id
            is_gm = await self.gm.is_gm(guild_id, user_id, d.get("member")) if _needs_gm_check(cmd) else False
            actor = Actor(user_id, _display_name(d), is_gm)
            reply, mode = await self.store.transact(
                guild_id, channel_id, lambda table, notice: (execute(cmd, table, actor, notice), table.images))
            png = await asyncio.to_thread(self.images.render, reply.cards, reply.kept_index, mode)
            await self._send_reply(channel_id, reply, png, reply_to)
        except Exception:
            log.exception("command %r failed in guild %s channel %s", cmd.name, guild_id, channel_id)
            try:
                await self.rest.send_message(channel_id, reply_to_embed(Reply(ERROR_TEXT, tone="error"), False), None)
            except Exception:
                log.exception("could not send error reply")
