# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry point: python -m green_oaks_bot"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

import aiohttp

from green_oaks_bot.bot import Bot
from green_oaks_bot.config import Config, ConfigError
from green_oaks_bot.fluxer.gateway import FatalGatewayError, Gateway
from green_oaks_bot.fluxer.rest import FluxerHTTPError, FluxerREST, resolve_endpoints
from green_oaks_bot.fluxer.roles import GMResolver
from green_oaks_bot.render import CardImages
from green_oaks_bot.ruleset import Ruleset, RulesetError, load_ruleset
from green_oaks_bot.store import Store

log = logging.getLogger("green_oaks_bot")

# REST calls and discovery. The gateway websocket has its own timeouts (ws_connect), which
# this session-wide total does not limit: aiohttp applies it to plain requests only.
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def run(config: Config, images: CardImages, ruleset: Ruleset | None = None) -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        api, gateway_url = await resolve_endpoints(session, config)
        log.info("Fluxer API %s, gateway %s", api, gateway_url)
        rest = FluxerREST(session, api, config.token)
        store = Store(config.data_dir, prefix=config.prefix, ruleset=ruleset)
        bot = Bot(rest=rest, store=store, images=images,
                  gm=GMResolver(rest, config.gm_role_name), prefix=config.prefix)
        gateway = Gateway(session, gateway_url, config.token, bot.on_dispatch, on_ready=bot.on_ready)
        gw_task = asyncio.create_task(gateway.run())
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({gw_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if gw_task in done:
            stop_task.cancel()
            gw_task.result()      # re-raises FatalGatewayError
            return
        log.info("shutting down")
        await gateway.stop()
        gw_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await gw_task


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(level=config.log_level, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        ruleset = load_ruleset(config.rules_file)
        log.info("loaded rules from %s", config.rules_file)
        images = CardImages(config.assets_dir)
        log.info("loaded %d card images from %s", len(images), config.assets_dir)
        asyncio.run(run(config, images, ruleset))
    except FatalGatewayError as exc:
        log.error("%s", exc)
        return 1
    except RulesetError as exc:
        log.error("startup failed: %s", exc)
        return 1
    except (aiohttp.ClientError, FluxerHTTPError, OSError, KeyError, ValueError, TypeError) as exc:
        # e.g. missing card images, discovery or /gateway/bot failed: bad URL, instance down,
        # bad token (401), or a discovery body that is JSON but not an object
        log.error("startup failed: %r", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
