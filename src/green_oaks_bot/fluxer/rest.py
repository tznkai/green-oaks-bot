"""Fluxer REST client."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from green_oaks_bot.config import Config
from green_oaks_bot.ids import require_snowflake
from green_oaks_bot.render import embed_colour
from green_oaks_bot.table import Reply

log = logging.getLogger(__name__)

ATTACHMENT_NAME = "card.png"
EMBED_DESCRIPTION_MAX = 4096


class FluxerHTTPError(Exception):
    def __init__(self, status: int, code: str | None, message: str) -> None:
        super().__init__(f"HTTP {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


def reply_to_embed(reply: Reply, has_image: bool) -> dict[str, Any]:
    description = reply.text
    if reply.hints:
        description += "\n\n" + "\n".join(reply.hints)
    if len(description) > EMBED_DESCRIPTION_MAX:
        description = description[: EMBED_DESCRIPTION_MAX - 1] + "…"
    embed: dict[str, Any] = {"description": description, "color": embed_colour(reply.tone)}
    if has_image:
        embed["image"] = {"url": f"attachment://{ATTACHMENT_NAME}"}
    return embed


async def discover_api(session: aiohttp.ClientSession, instance_url: str) -> str:
    async with session.get(instance_url.rstrip("/") + "/.well-known/fluxer") as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    return data["endpoints"]["api_public"]


class FluxerREST:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_base: str,
        token: str,
        *,
        max_retries: int = 5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.session = session
        self.api_base = api_base.rstrip("/")
        self._headers = {"Authorization": f"Bot {token}"}
        self.max_retries = max_retries
        self._sleep = sleep

    def _url(self, path: str) -> str:
        return f"{self.api_base}/v1{path}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        form: Callable[[], aiohttp.FormData] | None = None,
    ) -> Any:
        for attempt in range(self.max_retries + 1):
            kwargs: dict[str, Any] = {}
            if form is not None:
                kwargs["data"] = form()  # FormData is single-use: rebuild per attempt
            elif json_body is not None:
                kwargs["json"] = json_body
            async with self.session.request(
                method, self._url(path), headers=self._headers, **kwargs
            ) as resp:
                if resp.status == 429 and attempt < self.max_retries:
                    delay = await self._retry_after(resp)
                    log.warning("rate limited on %s %s; retrying in %.3fs", method, path, delay)
                    await self._sleep(delay)
                    continue
                if resp.status >= 400:
                    try:
                        body = await resp.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError):
                        body = {}
                    if not isinstance(body, dict):
                        body = {}
                    raise FluxerHTTPError(
                        resp.status,
                        body.get("code"),
                        body.get("message", resp.reason or ""),
                    )
                if resp.status == 204:
                    return None
                return await resp.json(content_type=None)
        raise AssertionError("unreachable")

    @staticmethod
    async def _retry_after(resp: aiohttp.ClientResponse) -> float:
        try:
            body = await resp.json(content_type=None)
            return max(float(body["retry_after"]), 0.001)
        except (ValueError, KeyError, TypeError, aiohttp.ContentTypeError):
            try:
                return float(resp.headers.get("Retry-After", "1"))
            except ValueError:
                return 1.0

    async def get_gateway_url(self) -> str:
        return (await self.request("GET", "/gateway/bot"))["url"]

    async def send_message(
        self,
        channel_id: str,
        embed: dict[str, Any],
        image: bytes | None,
        reply_to: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"embeds": [embed]}
        if reply_to:
            # the reference lives in the JSON body only, never in the URL
            payload["message_reference"] = {"message_id": require_snowflake(reply_to)}
        path = f"/channels/{require_snowflake(channel_id)}/messages"
        if image is None:
            return await self.request("POST", path, json_body=payload)

        def form() -> aiohttp.FormData:
            fd = aiohttp.FormData()
            fd.add_field("payload_json", json.dumps(payload), content_type="application/json")
            fd.add_field("files[0]", image, filename=ATTACHMENT_NAME, content_type="image/png")
            return fd

        return await self.request("POST", path, form=form)

    async def get_roles(self, guild_id: str) -> list[dict[str, Any]]:
        return await self.request("GET", f"/guilds/{require_snowflake(guild_id)}/roles")

    async def get_member(self, guild_id: str, user_id: str) -> dict[str, Any]:
        path = f"/guilds/{require_snowflake(guild_id)}/members/{require_snowflake(user_id)}"
        return await self.request("GET", path)


async def resolve_endpoints(session: aiohttp.ClientSession, config: Config) -> tuple[str, str]:
    """(api_base, gateway_url): explicit overrides win over discovery."""
    api = config.api_url or await discover_api(session, config.instance_url or "")
    gateway = config.gateway_url or await FluxerREST(session, api, config.token).get_gateway_url()
    return api, gateway
