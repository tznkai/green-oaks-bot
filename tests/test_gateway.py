"""Fluxer gateway client tests against the fake gateway (real aiohttp websockets).

Every wait is bounded: `until` and `expect` have deadlines, and each scenario ends
with `hold`, so a bug fails in about five seconds instead of hanging.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import random
import socket
from typing import Any

import aiohttp
import pytest

from green_oaks_bot.fluxer import gateway as gateway_mod
from green_oaks_bot.fluxer.gateway import FatalGatewayError, Gateway
from tests.fakes import GATEWAY_STATE, expect, hold, make_gateway_app, send

TIMEOUT = 5
FAST: dict[str, Any] = {
    "backoff_base": 0.01,
    "backoff_max": 0.05,
    "invalid_session_delay": (0.0, 0.0),
    "reconnect_delay": (0.0, 0.0),
}
HELLO_30 = {"heartbeat_interval": 30}
READY = {"session_id": "S1", "user": {"id": "B"}}
RESUME_SESSION = {"token": "tok", "session_id": "S1", "seq": 7}


class Events:
    def __init__(self) -> None:
        self.dispatches: list[tuple[str, dict[str, Any]]] = []
        self.ready: list[str] = []

    async def on_dispatch(self, t: str, d: dict[str, Any]) -> None:
        self.dispatches.append((t, d))

    def on_ready(self, user_id: str) -> None:
        self.ready.append(user_id)

    def names(self) -> list[str]:
        return [t for t, _ in self.dispatches]


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


async def until(cond, state, timeout: float = TIMEOUT) -> None:
    """Poll until `cond()`; fail fast if the fake recorded a script error."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not cond():
        if state.errors:
            raise AssertionError(f"fake gateway script failed: {state.errors}")
        if loop.time() > deadline:
            raise AssertionError("condition not met before timeout")
        await asyncio.sleep(0.005)


def frames(state, index: int) -> list[dict[str, Any]]:
    return state.connections[index] if index < len(state.connections) else []


def ws_url(server, path: str = "/") -> str:
    return str(server.make_url(path).with_scheme("ws"))


def make_gateway(session, server, events: Events, path: str = "/", **overrides: Any) -> Gateway:
    kwargs: dict[str, Any] = {**FAST, "rng": random.Random(0), **overrides}
    return Gateway(session, ws_url(server, path), "tok", events.on_dispatch,
                   on_ready=events.on_ready, **kwargs)


@contextlib.asynccontextmanager
async def running(gateway: Gateway):
    task = asyncio.create_task(gateway.run())
    try:
        yield task
    finally:
        await gateway.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, TIMEOUT)


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- AC10.2: identify and heartbeats -------------------------------------------------

async def test_identify_carries_token_properties_and_no_intents(aiohttp_server, session):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    gw = make_gateway(session, server, events)
    async with running(gw):
        await until(lambda: len(frames(state, 0)) >= 1, state)

    first = state.connections[0][0]
    assert first["op"] == 2
    d = first["d"]
    assert set(d) == {"token", "properties"}  # Fluxer has no intents: the key must be absent
    assert d["token"] == "tok"
    assert all(isinstance(d["properties"][k], str) for k in ("os", "browser", "device"))
    assert state.queries[0] == {"v": "1", "encoding": "json"}


async def test_heartbeats_follow_interval_and_carry_last_seq(aiohttp_server, session):
    beats: list[tuple[float, Any]] = []

    async def script(ws, i, state):
        loop = asyncio.get_running_loop()
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        for _ in range(2):
            beat = await expect(ws, 1)
            beats.append((loop.time(), beat["d"]))
        await send(ws, 0, {"id": "m0"}, t="MESSAGE_CREATE", s=5)
        for _ in range(10):
            beat = await expect(ws, 1)
            beats.append((loop.time(), beat["d"]))
            if beat["d"] == 5:
                break
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events())
    async with running(gw):
        await until(lambda: beats and beats[-1][1] == 5, state)

    assert [d for _, d in beats[:2]] == [None, None]  # nothing dispatched yet
    assert beats[-1][1] == 5  # the beat after dispatch s=5 carries 5
    gaps = [b[0] - a[0] for a, b in itertools.pairwise(beats)]
    assert gaps and all(0.015 <= g <= 0.1 for g in gaps), gaps


async def test_server_requested_heartbeat_is_answered_promptly(aiohttp_server, session):
    # A 60 s interval means only the reply to the server's op 1 can satisfy the expect.
    timings: list[float] = []

    async def script(ws, i, state):
        loop = asyncio.get_running_loop()
        await send(ws, 10, {"heartbeat_interval": 60_000})
        await expect(ws, 2)
        started = loop.time()
        await send(ws, 1)
        await expect(ws, 1, timeout=1)
        timings.append(loop.time() - started)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events())
    async with running(gw):
        await until(lambda: len(timings) == 1, state)
    assert timings[0] < 0.5


# --- Dispatch ------------------------------------------------------------------------

async def test_dispatches_arrive_in_order_and_on_ready_fires_with_user_id(aiohttp_server, session):
    message = {"id": "m1", "channel_id": "c1", "content": "!gm"}

    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await send(ws, 0, READY, t="READY", s=1)
        await send(ws, 0, message, t="MESSAGE_CREATE", s=2)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    gw = make_gateway(session, server, events)
    async with running(gw):
        await until(lambda: len(events.dispatches) == 2, state)

    assert events.dispatches == [("READY", READY), ("MESSAGE_CREATE", message)]
    assert gw.user_id == "B"
    assert events.ready == ["B"]


# --- AC10.3: resume, op 9, op 7 ------------------------------------------------------

async def test_drop_then_resume_on_new_socket_and_on_ready_only_once(aiohttp_server, session):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        if i == 0:
            await expect(ws, 2)
            await send(ws, 0, READY, t="READY", s=1)
            await send(ws, 0, {"id": "m1"}, t="MESSAGE_CREATE", s=7)
            await ws.close(code=1001)
            return
        await expect(ws, 6)
        await send(ws, 0, {}, t="RESUMED", s=8)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    gw = make_gateway(session, server, events)
    async with running(gw):
        await until(lambda: "RESUMED" in events.names(), state)

    assert len(state.connections) == 2
    assert state.connections[1][0] == {"op": 6, "d": RESUME_SESSION}
    assert events.ready == ["B"]  # AC10.9: READY fired once across the reconnect


async def test_op9_false_reidentifies_on_same_socket(aiohttp_server, session):
    release = asyncio.Event()

    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 6)
        await send(ws, 9, False)
        await expect(ws, 2)
        await asyncio.wait_for(release.wait(), TIMEOUT)
        await send(ws, 0, READY, t="READY", s=1)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    gw = make_gateway(session, server, events)
    gw.session_id = "S0"
    gw.seq = 3
    async with running(gw):
        await until(lambda: len(frames(state, 0)) >= 2, state)
        assert len(state.connections) == 1  # same socket, no reconnect
        assert gw.session_id is None  # cleared by op 9 before the new identify
        release.set()
        await until(lambda: gw.session_id == "S1", state)

    assert state.connections[0][0] == {"op": 6, "d": {"token": "tok", "session_id": "S0", "seq": 3}}
    assert state.connections[0][1]["op"] == 2
    assert events.ready == ["B"]


async def test_op7_closes_with_4000_and_resumes_on_new_socket(aiohttp_server, session):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        if i == 0:
            await expect(ws, 2)
            await send(ws, 0, READY, t="READY", s=1)
            await send(ws, 7)
            await hold(ws)
            return
        await expect(ws, 6)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events())
    async with running(gw):
        await until(lambda: len(frames(state, 1)) >= 1 and state.close_codes[0] is not None, state)

    assert state.close_codes[0] == 4000
    assert state.connections[1][0] == {"op": 6, "d": {"token": "tok", "session_id": "S1", "seq": 1}}


# --- AC10.4: missed ACK ---------------------------------------------------------------

async def test_missed_heartbeat_ack_closes_with_4000_then_resumes(aiohttp_server, session):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        if i == 0:
            state.ack = False  # never ACK on this connection
            await expect(ws, 2)
            await send(ws, 0, READY, t="READY", s=1)
            await hold(ws)
            return
        state.ack = True
        await expect(ws, 6)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events())
    async with running(gw):
        await until(lambda: len(frames(state, 1)) >= 1 and state.close_codes[0] is not None, state)

    assert state.close_codes[0] == 4000
    assert state.connections[1][0]["op"] == 6


# --- Robustness: bad first frames reconnect instead of dying --------------------------

async def test_close_before_hello_reconnects_without_raising(aiohttp_server, session):
    async def script(ws, i, state):
        if i == 0:
            await ws.close(code=1012)
            return
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await send(ws, 0, READY, t="READY", s=1)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    gw = make_gateway(session, server, events)
    async with running(gw) as task:
        await until(lambda: events.ready == ["B"], state)
        assert not task.done()
    assert state.connections[1][0]["op"] == 2


async def test_hello_without_d_reconnects(aiohttp_server, session):
    async def script(ws, i, state):
        if i == 0:
            await ws.send_json({"op": 10})
            await hold(ws)
            return
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await send(ws, 0, READY, t="READY", s=1)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    gw = make_gateway(session, server, events)
    async with running(gw) as task:
        await until(lambda: events.ready == ["B"], state)
        assert not task.done()
    assert len(state.connections) == 2


# --- URL handling ---------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/gateway"])
async def test_connects_to_configured_path_with_v1_json_query(aiohttp_server, session, path):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events(), path=path)
    async with running(gw):
        await until(lambda: len(frames(state, 0)) >= 1, state)

    assert state.paths[0] == path
    assert state.queries[0] == {"v": "1", "encoding": "json"}


# --- Fatal and session-reset close codes ----------------------------------------------

@pytest.mark.parametrize("code", [4004, 4010, 4011, 4012])
async def test_fatal_close_code_raises_and_stops(aiohttp_server, session, code):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await ws.close(code=code)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events())
    try:
        with pytest.raises(FatalGatewayError):
            await asyncio.wait_for(gw.run(), TIMEOUT)
    finally:
        await gw.stop()
    assert len(state.connections) == 1
    assert state.errors == []


@pytest.mark.parametrize("code", [4003, 4007])
async def test_session_reset_close_codes_identify_on_next_socket(aiohttp_server, session, code):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        if i == 0:
            await expect(ws, 2)
            await send(ws, 0, READY, t="READY", s=1)
            await ws.close(code=code)
            return
        await expect(ws, 2)
        await send(ws, 0, READY, t="READY", s=1)  # a second READY: on_ready must not fire again
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    gw = make_gateway(session, server, events)
    async with running(gw):
        await until(lambda: events.names().count("READY") == 2, state)

    assert state.connections[1][0]["op"] == 2  # identify, not resume
    assert len(state.connections) == 2
    assert events.ready == ["B"]  # AC10.9: on_ready once, even across a re-identify


# --- Reconnect delays -----------------------------------------------------------------

async def test_backoff_grows_exponentially_with_jitter(session):
    delays: list[float] = []
    gw: Gateway | None = None

    async def record(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 5:
            assert gw is not None
            await gw.stop()

    gw = Gateway(session, f"ws://127.0.0.1:{closed_port()}/", "tok", Events().on_dispatch,
                 rng=random.Random(0), backoff_base=1, backoff_max=4, sleep=record)
    await asyncio.wait_for(gw.run(), TIMEOUT)

    assert len(delays) == 5
    for n, delay in enumerate(delays, start=1):
        cap = min(4, 2 ** (n - 1))
        assert 0.5 * cap <= delay <= cap, (n, delay)


async def test_reconnect_after_established_session_uses_reconnect_delay(aiohttp_server, session):
    delays: list[float] = []
    gw: Gateway | None = None

    async def record(delay: float) -> None:
        delays.append(delay)
        assert gw is not None
        await gw.stop()

    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await send(ws, 0, READY, t="READY", s=1)
        await ws.close(code=1001)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = Gateway(session, ws_url(server), "tok", Events().on_dispatch, rng=random.Random(0),
                 backoff_base=1, backoff_max=4, reconnect_delay=(0.01, 0.02), sleep=record)
    await asyncio.wait_for(gw.run(), TIMEOUT)

    assert state.errors == []
    assert len(delays) == 1
    assert 0.01 <= delays[0] <= 0.02


# --- shutdown, timeouts and handler errors -------------------------------------------

async def test_stop_alone_ends_run_without_cancelling_it(aiohttp_server, session):
    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events())
    task = asyncio.create_task(gw.run())
    await until(lambda: len(frames(state, 0)) >= 1, state)

    await asyncio.wait_for(gw.stop(), TIMEOUT)
    await asyncio.wait_for(task, TIMEOUT)  # no task.cancel(): run() must return on its own
    assert not task.cancelled()
    assert state.close_codes[0] is not None


async def test_stop_lets_running_handler_finish(aiohttp_server, session):
    started = asyncio.Event()
    finished: list[str] = []

    async def handler(t: str, d: dict[str, Any]) -> None:
        started.set()
        await asyncio.sleep(0.2)
        finished.append(t)

    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await send(ws, 0, {}, t="MESSAGE_CREATE", s=1)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = Gateway(session, ws_url(server), "tok", handler,
                 **{**FAST, "rng": random.Random(0), "drain_timeout": TIMEOUT})
    task = asyncio.create_task(gw.run())
    await asyncio.wait_for(started.wait(), TIMEOUT)

    await asyncio.wait_for(gw.stop(), TIMEOUT)
    assert finished == ["MESSAGE_CREATE"]  # stop() returned only after the handler completed
    await asyncio.wait_for(task, TIMEOUT)
    assert state.errors == []


async def test_handler_exceeding_drain_timeout_is_cancelled(aiohttp_server, session):
    started = asyncio.Event()
    outcome: list[str] = []

    async def handler(t: str, d: dict[str, Any]) -> None:
        started.set()
        try:
            await asyncio.sleep(30)
            outcome.append("finished")
        except asyncio.CancelledError:
            outcome.append("cancelled")
            raise

    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await send(ws, 0, {}, t="MESSAGE_CREATE", s=1)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = Gateway(session, ws_url(server), "tok", handler,
                 **{**FAST, "rng": random.Random(0), "drain_timeout": 0.2})
    task = asyncio.create_task(gw.run())
    await asyncio.wait_for(started.wait(), TIMEOUT)

    loop = asyncio.get_running_loop()
    began = loop.time()
    await asyncio.wait_for(gw.stop(), TIMEOUT)
    assert loop.time() - began < TIMEOUT
    assert outcome == ["cancelled"]
    await asyncio.wait_for(task, TIMEOUT)
    assert state.errors == []


async def test_hello_timeout_reconnects(aiohttp_server, session, monkeypatch):
    monkeypatch.setattr(gateway_mod, "HELLO_TIMEOUT", 0.2)

    async def script(ws, i, state):
        await hold(ws)  # never sends Hello

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = make_gateway(session, server, Events())
    async with running(gw):
        await until(lambda: len(state.connections) >= 2, state)

    assert all(frames(state, i) == [] for i in range(2))  # nothing identified without Hello


async def test_dispatch_handler_error_is_logged_with_traceback(aiohttp_server, session, caplog):
    async def handler(t: str, d: dict[str, Any]) -> None:
        raise RuntimeError("handler boom")

    async def script(ws, i, state):
        await send(ws, 10, HELLO_30)
        await expect(ws, 2)
        await send(ws, 0, {}, t="MESSAGE_CREATE", s=1)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    gw = Gateway(session, ws_url(server), "tok", handler, **{**FAST, "rng": random.Random(0)})
    with caplog.at_level(logging.ERROR, logger="green_oaks_bot.fluxer.gateway"):
        async with running(gw):
            await until(lambda: any(r.levelno == logging.ERROR for r in caplog.records), state)

    (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.getMessage() == "dispatch handler failed"
    assert isinstance(record.exc_info[1], RuntimeError)
    assert str(record.exc_info[1]) == "handler boom"



async def test_session_total_timeout_does_not_cut_the_websocket(aiohttp_server):
    """The production session has a total timeout (HTTP_TIMEOUT); the socket must outlive it."""
    async def script(ws, i, state):
        await send(ws, 10, {"heartbeat_interval": 30000})  # no heartbeat during the sleep below
        await expect(ws, 2)
        await asyncio.sleep(0.8)  # well past the session total below
        await send(ws, 0, {}, t="MESSAGE_CREATE", s=1)
        await hold(ws)

    state = (app := make_gateway_app(script))[GATEWAY_STATE]
    server = await aiohttp_server(app)
    events = Events()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=0.2)) as session:
        gw = make_gateway(session, server, events)
        async with running(gw):
            await until(lambda: events.names() == ["MESSAGE_CREATE"], state)
    assert state.close_codes[0] is not None
    assert state.connections[0][0]["op"] == 2  # identified on the one and only socket
