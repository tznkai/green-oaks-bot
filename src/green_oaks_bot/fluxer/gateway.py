"""Fluxer gateway websocket client."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import yarl

log = logging.getLogger(__name__)

FATAL_CLOSE_CODES = {4004, 4010, 4011, 4012}
SESSION_RESET_CLOSE_CODES = {4003, 4007}
HELLO_TIMEOUT = 30.0


class FatalGatewayError(Exception):
    pass


class Gateway:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str,
                 on_dispatch: Callable[[str, dict[str, Any]], Awaitable[None]], *,
                 on_ready: Callable[[str], None] | None = None,
                 rng: random.Random | None = None,
                 backoff_base: float = 1.0, backoff_max: float = 60.0,
                 invalid_session_delay: tuple[float, float] = (1.0, 5.0),
                 reconnect_delay: tuple[float, float] = (1.0, 5.0),
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.session = session
        # keep the path exactly as given (reverse proxies may route /gateway exactly)
        self.url = str(yarl.URL(url).update_query(v="1", encoding="json"))
        self.token = token
        self.on_dispatch = on_dispatch
        self.on_ready = on_ready
        self.rng = rng or random.Random()
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.invalid_session_delay = invalid_session_delay
        self.reconnect_delay = reconnect_delay
        self._sleep = sleep
        self._established = False
        self._last_close_code: int | None = None
        self.session_id: str | None = None
        self.seq: int | None = None
        self.user_id: str | None = None
        self._ready_fired = False
        self._acked = True
        self._stopping = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        attempt = 0
        while not self._stopping:
            self._established = False
            try:
                await self._connect_once()
            except FatalGatewayError:
                raise
            except Exception as exc:  # noqa: BLE001 - any other failure: log and reconnect, never die
                log.warning("gateway connection failed: %r", exc)
            if self._stopping:
                break
            if self._established:
                attempt = 0
                delay = self.rng.uniform(*self.reconnect_delay)   # small floor, avoids hammering
            else:
                attempt += 1
                delay = min(self.backoff_max, self.backoff_base * 2 ** (attempt - 1))
                delay *= 0.5 + self.rng.random() / 2      # jitter in [0.5, 1.0]
            log.info("reconnecting to gateway in %.2fs", delay)
            await self._sleep(delay)

    async def stop(self) -> None:
        self._stopping = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        for task in list(self._tasks):
            task.cancel()

    async def _connect_once(self) -> None:
        code: int | None = None
        try:
            await self._session_on_socket()
        finally:
            code = self._last_close_code
            log.info("gateway closed (code %s)", code)
            if code in FATAL_CLOSE_CODES:
                # raised from finally on purpose: a fatal close wins over any racing error
                raise FatalGatewayError(f"gateway closed with fatal code {code}")
            if code in SESSION_RESET_CLOSE_CODES:
                self.session_id = None
                self.seq = None

    async def _session_on_socket(self) -> None:
        self._last_close_code = None
        async with self.session.ws_connect(self.url) as ws:
            self._ws = ws
            try:
                msg = await asyncio.wait_for(ws.receive(), HELLO_TIMEOUT)
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    raise ConnectionError(f"socket closed before Hello ({msg.type.name} {msg.data!r})")
                hello = json.loads(msg.data)
                if hello.get("op") != 10:
                    raise ValueError(f"expected Hello, got op {hello.get('op')}")
                interval = hello["d"]["heartbeat_interval"] / 1000
                if self.session_id is not None and self.seq is not None:
                    await self._send(ws, 6, {"token": self.token, "session_id": self.session_id, "seq": self.seq})
                else:
                    await self._identify(ws)
                self._acked = True
                reader = asyncio.create_task(self._read(ws))
                heartbeat = asyncio.create_task(self._heartbeat(ws, interval))
                try:
                    done, _ = await asyncio.wait({reader, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
                    if heartbeat in done:
                        heartbeat.result()            # re-raise a send error, if any
                        # missed ACK: stop reading, then close with a resumable code
                        reader.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await reader
                        await ws.close(code=4000)
                    else:
                        reader.result()               # re-raise a handler error, if any
                finally:
                    for task in (reader, heartbeat):
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
            finally:
                self._last_close_code = ws.close_code
                self._ws = None

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type is aiohttp.WSMsgType.TEXT:
                await self._handle(ws, json.loads(msg.data))
            elif msg.type is aiohttp.WSMsgType.ERROR:
                break

    async def _send(self, ws: aiohttp.ClientWebSocketResponse, op: int, d: Any) -> None:
        await ws.send_json({"op": op, "d": d})

    async def _identify(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        await self._send(ws, 2, {
            "token": self.token,
            "properties": {"os": "linux", "browser": "green-oaks-bot", "device": "green-oaks-bot"},
        })

    async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse, interval: float) -> None:
        """Returns (without closing) when an ACK was missed; _connect_once closes with 4000."""
        await asyncio.sleep(interval * self.rng.random())
        while not ws.closed:
            if not self._acked:
                log.warning("heartbeat ACK missed; reconnecting")
                return
            self._acked = False
            await self._send(ws, 1, self.seq)
            await asyncio.sleep(interval)

    def _dispatch_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("dispatch handler failed", exc_info=task.exception())

    async def _handle(self, ws: aiohttp.ClientWebSocketResponse, p: dict[str, Any]) -> None:
        """Process one payload; sets self._established on READY/RESUMED."""
        op = p.get("op")
        if op == 0:
            if p.get("s") is not None:
                self.seq = p["s"]
            t, d = p.get("t"), p.get("d") or {}
            if t == "READY":
                self.session_id = d["session_id"]
                self.user_id = str(d["user"]["id"])
                self._established = True
                if not self._ready_fired:
                    self._ready_fired = True
                    if self.on_ready is not None:
                        self.on_ready(self.user_id)
            elif t == "RESUMED":
                self._established = True
            if t:
                task = asyncio.create_task(self.on_dispatch(t, d))
                self._tasks.add(task)
                task.add_done_callback(self._dispatch_done)
            return
        if op == 1:
            await self._send(ws, 1, self.seq)
        elif op == 11:
            self._acked = True
        elif op == 7:
            log.info("gateway requested reconnect")
            await ws.close(code=4000)
        elif op == 9:
            log.info("invalid session; identifying again")
            self.session_id = None
            self.seq = None
            lo, hi = self.invalid_session_delay
            await asyncio.sleep(self.rng.uniform(lo, hi))
            await self._identify(ws)
