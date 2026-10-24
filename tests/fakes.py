"""Fake Fluxer servers built on aiohttp.web, driven through pytest-aiohttp's aiohttp_server.

`FakeFluxerState` is the single place tests configure and inspect the fake. Routes are
added to `make_rest_app(state)`; the gateway fake will extend this module with its own
app factory that shares the same state object.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import web

TIMEOUT_DEFAULT = 2.0
RATE_LIMIT_BODY = {"code": "RATE_LIMITED", "message": "slow", "global": False, "retry_after": 0.25}


@dataclass
class Override:
    """A canned raw response for `"METHOD /path"`, used to exercise error shapes."""

    status: int
    body: bytes
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Recorded:
    method: str
    path: str
    authorization: str | None
    content_type: str
    status: int
    payload: Any = None
    files: list[tuple[str, bytes]] = field(default_factory=list)  # (filename, bytes)


@dataclass
class FakeFluxerState:
    gateway_url: str = "ws://fake-gateway.test/gateway"
    roles: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    members: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # The next N message POSTs answer 429 (RATE_LIMIT_BODY).
    rate_limit_next: int = 0
    # Keyed by "METHOD /path"; checked before any default behaviour.
    overrides: dict[str, Override] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)
    # Gateway fake: when False the fake never ACKs heartbeats (op 1 gets no op 11).
    ack: bool = True
    # One entry per websocket connection: the client frames it received, in order.
    connections: list[list[dict[str, Any]]] = field(default_factory=list)
    close_codes: list[int | None] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    queries: list[dict[str, str]] = field(default_factory=list)
    # repr() of any exception a scenario script raised (tests fail fast on these).
    errors: list[str] = field(default_factory=list)

    def requests_to(self, path: str) -> list[Recorded]:
        return [r for r in self.requests if r.path == path]


def _send(
    state: FakeFluxerState,
    request: web.Request,
    status: int,
    body: Any,
    *,
    payload: Any = None,
    files: list[tuple[str, bytes]] | None = None,
) -> web.Response:
    key = f"{request.method} {request.path}"
    override = state.overrides.get(key)
    if override is not None:
        state.requests.append(_record(request, override.status, payload, files))
        return web.Response(
            status=override.status,
            body=override.body,
            content_type=override.content_type,
            headers=override.headers,
        )
    state.requests.append(_record(request, status, payload, files))
    return web.json_response(body, status=status)


def _record(request: web.Request, status: int, payload: Any, files: list[tuple[str, bytes]] | None) -> Recorded:
    return Recorded(
        method=request.method,
        path=request.path,
        authorization=request.headers.get("Authorization"),
        content_type=request.content_type,
        status=status,
        payload=payload,
        files=files or [],
    )


def make_rest_app(state: FakeFluxerState) -> web.Application:
    async def well_known(request: web.Request) -> web.Response:
        base = str(request.url.origin())
        body = {
            "api_code_version": 1,
            "endpoints": {"api_public": f"{base}/api", "gateway": "ws://unused"},
        }
        return _send(state, request, 200, body)

    async def gateway_bot(request: web.Request) -> web.Response:
        return _send(state, request, 200, {"url": state.gateway_url, "shards": 1})

    async def create_message(request: web.Request) -> web.Response:
        if request.content_type == "multipart/form-data":
            form = await request.post()
            payload = json.loads(form["payload_json"])
            files = [
                (value.filename, value.file.read())
                for name, value in form.items()
                if name.startswith("files[") and hasattr(value, "filename")
            ]
        else:
            payload = await request.json()
            files = []
        if state.rate_limit_next > 0:
            state.rate_limit_next -= 1
            return _send(state, request, 429, RATE_LIMIT_BODY, payload=payload, files=files)
        return _send(state, request, 200, {"id": "m1"}, payload=payload, files=files)

    async def roles(request: web.Request) -> web.Response:
        guild = request.match_info["gid"]
        if guild not in state.roles:
            return _send(state, request, 404, {"code": "UNKNOWN_GUILD", "message": "Unknown guild"})
        return _send(state, request, 200, state.roles[guild])

    async def member(request: web.Request) -> web.Response:
        key = (request.match_info["gid"], request.match_info["uid"])
        if key not in state.members:
            return _send(state, request, 404, {"code": "UNKNOWN_MEMBER", "message": "Unknown member"})
        return _send(state, request, 200, state.members[key])

    app = web.Application()
    app.router.add_get("/.well-known/fluxer", well_known)
    app.router.add_get("/api/v1/gateway/bot", gateway_bot)
    app.router.add_post("/api/v1/channels/{cid}/messages", create_message)
    app.router.add_get("/api/v1/guilds/{gid}/roles", roles)
    app.router.add_get("/api/v1/guilds/{gid}/members/{uid}", member)

    async def unmatched(request: web.Request) -> web.Response:
        # recorded like any other call, so a request to a path nobody expects still shows up
        return _send(state, request, 404, {"code": "NOT_FOUND", "message": "no such route"})

    app.router.add_route("*", "/{tail:.*}", unmatched)
    return app


# ---------------------------------------------------------------------------
# Gateway fake: a websocket route on "/" and "/gateway". Each connection runs
# `script(ws, conn_index, state)`; the helpers below read/write frames on `ws`.
# ---------------------------------------------------------------------------

GatewayScript = Callable[[web.WebSocketResponse, int, FakeFluxerState], Awaitable[None]]
GATEWAY_STATE: web.AppKey[FakeFluxerState] = web.AppKey("gateway_state", FakeFluxerState)


async def send(ws: web.WebSocketResponse, op: int, d: Any = None, t: str | None = None, s: int | None = None) -> None:
    payload: dict[str, Any] = {"op": op, "d": d}
    if t is not None:
        payload["t"] = t
    if s is not None:
        payload["s"] = s
    await ws.send_json(payload)


async def _receive(ws: web.WebSocketResponse, timeout: float) -> dict[str, Any] | None:
    """Next client frame, recorded on its connection and ACKed if it is a heartbeat.

    Returns None once the client has closed the socket.
    """
    msg = await asyncio.wait_for(ws.receive(), timeout)
    if msg.type is not aiohttp.WSMsgType.TEXT:
        return None
    frame: dict[str, Any] = json.loads(msg.data)
    ws.fake_frames.append(frame)  # type: ignore[attr-defined]
    if frame.get("op") == 1 and ws.fake_state.ack:  # type: ignore[attr-defined]
        await send(ws, 11)
    return frame


async def expect(ws: web.WebSocketResponse, op: int, timeout: float = TIMEOUT_DEFAULT) -> dict[str, Any]:
    """Wait for the next client frame with `op` (overall deadline, heartbeats ACKed meanwhile)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        frame = await _receive(ws, deadline - loop.time())
        if frame is None:
            raise AssertionError(f"client closed while waiting for op {op}")
        if frame.get("op") == op:
            return frame


async def hold(ws: web.WebSocketResponse, timeout: float = 5.0) -> None:
    """Keep reading and ACKing heartbeats until the client closes the socket."""
    while await _receive(ws, timeout) is not None:
        pass


def make_gateway_app(script: GatewayScript) -> web.Application:
    """Fake gateway app. The shared state is `app[GATEWAY_STATE]`."""
    state = FakeFluxerState()

    async def gateway_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        index = len(state.connections)
        frames: list[dict[str, Any]] = []
        state.connections.append(frames)
        state.close_codes.append(None)
        state.paths.append(request.path)
        state.queries.append(dict(request.query))
        ws.fake_frames = frames  # type: ignore[attr-defined]
        ws.fake_state = state  # type: ignore[attr-defined]
        try:
            await script(ws, index, state)
        except Exception as exc:  # noqa: BLE001 - surfaced by tests as a fast failure
            state.errors.append(repr(exc))
        finally:
            await ws.close()
            state.close_codes[index] = ws.close_code
        return ws

    app = web.Application()
    app[GATEWAY_STATE] = state
    app.router.add_get("/", gateway_ws)
    app.router.add_get("/gateway", gateway_ws)
    return app
