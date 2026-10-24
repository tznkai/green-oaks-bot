# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Process-level behaviour of `python -m green_oaks_bot` against in-test fakes.

Every wait is bounded (asyncio.wait_for), and a child that is still alive when a test ends is killed.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest
from aiohttp import web

from green_oaks_bot.bot import READY_LINE
from green_oaks_bot.ruleset import DEFAULT_RULES_FILE
from tests.fakes import (
    GATEWAY_STATE,
    FakeFluxerState,
    expect,
    hold,
    make_gateway_app,
    make_rest_app,
    send,
)
from tests.helpers import RULESET

BOUND = 30  # seconds: generous for a cold interpreter, still a hard stop


async def run_module(env: dict[str, str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "green_oaks_bot", env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), BOUND)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    assert proc.returncode is not None
    return proc.returncode, out.decode(), err.decode()


async def test_empty_assets_dir_fails_cleanly(tmp_path: Path):
    assets = tmp_path / "cards"
    assets.mkdir()
    code, out, err = await run_module({
        "PATH": os.environ["PATH"],
        "FLUXER_TOKEN": "x.y",
        "FLUXER_API_URL": "http://127.0.0.1:9/api",
        "CARD_ASSETS_DIR": str(assets),
        "DATA_DIR": str(tmp_path / "data"),
    })

    assert code == 1
    assert "startup failed" in out
    assert "missing card images" in out
    assert "Traceback" not in err


async def test_missing_rules_file_fails_cleanly(tmp_path: Path):
    code, out, err = await run_module({
        "PATH": os.environ["PATH"],
        "FLUXER_TOKEN": "x.y",
        "FLUXER_API_URL": "http://127.0.0.1:9/api",
        "RULES_FILE": str(tmp_path / "absent.toml"),
        "DATA_DIR": str(tmp_path / "data"),
    })

    assert code == 1
    assert "startup failed" in out
    assert "cannot read rules file" in out
    assert "Traceback" not in err


async def test_rules_file_missing_a_category_fails_cleanly(tmp_path: Path):
    # Drop the last category section from the packaged file; a broken file must be refused by name.
    text = DEFAULT_RULES_FILE.read_text("utf-8")
    before, marker, rest = text.partition("[non_trump.pip]")
    assert marker
    _, sep, tail = rest.partition("\n[")
    broken = before + ("[" + tail if sep else "")
    assert "[non_trump.pip]" not in broken
    rules = tmp_path / "rules.toml"
    rules.write_text(broken, "utf-8")

    code, out, err = await run_module({
        "PATH": os.environ["PATH"],
        "FLUXER_TOKEN": "x.y",
        "FLUXER_API_URL": "http://127.0.0.1:9/api",
        "RULES_FILE": str(rules),
        "DATA_DIR": str(tmp_path / "data"),
    })

    assert code == 1
    assert "startup failed" in out
    assert "missing [non_trump.pip] section" in out
    assert "Traceback" not in err


async def test_discovery_body_that_is_not_an_object_fails_cleanly(aiohttp_server, tmp_path):
    async def well_known(request: web.Request) -> web.Response:
        return web.json_response([1, 2])  # valid JSON, wrong shape

    app = web.Application()
    app.router.add_get("/.well-known/fluxer", well_known)
    server = await aiohttp_server(app)
    code, out, err = await run_module({
        "PATH": os.environ["PATH"],
        "FLUXER_TOKEN": "x.y",
        "FLUXER_INSTANCE_URL": str(server.make_url("/")),
        "DATA_DIR": str(tmp_path / "data"),
    })

    assert code == 1
    assert "startup failed" in out
    assert "Traceback" not in err


async def test_sigterm_after_ready_exits_zero(aiohttp_server, tmp_path):
    async def gateway_script(ws, index, state):
        await send(ws, 10, {"heartbeat_interval": 30000})
        await expect(ws, 2)
        await send(ws, 0, {"session_id": "S1", "user": {"id": "999"}}, t="READY", s=1)
        await hold(ws)

    gateway_app = make_gateway_app(gateway_script)
    gateway = await aiohttp_server(gateway_app)
    gateway_url = str(gateway.make_url("/gateway").with_scheme("ws"))
    rest = await aiohttp_server(make_rest_app(FakeFluxerState(gateway_url=gateway_url)))
    env = {
        "PATH": os.environ["PATH"],
        "FLUXER_TOKEN": "x.y",
        "FLUXER_API_URL": str(rest.make_url("/api")).rstrip("/"),
        "FLUXER_GATEWAY_URL": gateway_url,
        "DATA_DIR": str(tmp_path / "data"),
    }
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "green_oaks_bot", env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        seen: list[str] = []
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), BOUND)
            if not line:
                raise AssertionError(f"exited before ready: {seen}")
            seen.append(line.decode())
            if READY_LINE in seen[-1]:
                break
        proc.send_signal(signal.SIGTERM)
        out, err = await asyncio.wait_for(proc.communicate(), BOUND)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

    assert proc.returncode == 0
    assert "shutting down" in out.decode()
    assert "Traceback" not in err.decode()
    gateway_state = gateway_app[GATEWAY_STATE]
    assert gateway_state.errors == []
    assert len(gateway_state.connections) == 1  # the bot identified on the fake gateway


class Refused(Exception):
    """Raised by the patched discovery so run() stops at its first request."""


async def test_run_opens_the_session_with_the_bounded_http_timeout(monkeypatch, tmp_path):
    from green_oaks_bot import __main__ as entry
    from green_oaks_bot.config import DEFAULT_ASSETS_DIR, Config
    from green_oaks_bot.render import CardImages

    opened: list[object] = []

    class RecordingSession:
        def __init__(self, *args, **kwargs):
            opened.append(kwargs.get("timeout"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    async def refuse_discovery(session, config):
        raise Refused()

    monkeypatch.setattr(entry.aiohttp, "ClientSession", RecordingSession)
    monkeypatch.setattr(entry, "resolve_endpoints", refuse_discovery)
    config = Config(token="x.y", instance_url=None, api_url="http://unused.test/api", gateway_url=None,
                    gm_role_name="GM", prefix="!", data_dir=tmp_path, assets_dir=DEFAULT_ASSETS_DIR,
                    log_level="INFO")

    with pytest.raises(Refused):
        await entry.run(config, CardImages(DEFAULT_ASSETS_DIR), RULESET)

    assert opened == [entry.HTTP_TIMEOUT]  # what run() actually passed, not just the constant
    assert entry.HTTP_TIMEOUT.total == 30  # aiohttp's default is 300 s
