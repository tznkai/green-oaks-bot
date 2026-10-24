"""GM role resolution against the fake REST app (AC10.7)."""

from __future__ import annotations

import aiohttp
import pytest

from green_oaks_bot.fluxer.rest import FluxerREST
from green_oaks_bot.fluxer.roles import GMResolver
from tests.fakes import FakeFluxerState, make_rest_app

TOKEN = "test.token"
ROLES_PATH = "/api/v1/guilds/1001/roles"
MEMBER_PATH = "/api/v1/guilds/1001/members/2001"
PLAYER = {"id": "r1", "name": "Player"}
GM_ROLE = {"id": "r2", "name": "gm"}


@pytest.fixture
async def fake(aiohttp_server):
    state = FakeFluxerState()
    state.roles = {"1001": [dict(PLAYER), dict(GM_ROLE)]}
    state.members = {("1001", "2001"): {"roles": ["r2"], "nick": "Gemma"}}
    server = await aiohttp_server(make_rest_app(state))
    base = str(server.make_url("/")).rstrip("/")
    return state, f"{base}/api"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


def fetches(state: FakeFluxerState, path: str) -> int:
    return len([r for r in state.requests if r.path == path])


async def test_member_with_gm_role_is_gm_case_insensitive(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", {"roles": ["r2"]}) is True
    assert fetches(state, MEMBER_PATH) == 0


async def test_member_with_other_role_is_not_gm(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", {"roles": ["r1"]}) is False
    assert fetches(state, MEMBER_PATH) == 0


async def test_member_without_roles_key_falls_back_to_member_fetch(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", {}) is True
    assert fetches(state, MEMBER_PATH) == 1


async def test_missing_member_event_falls_back_to_member_fetch(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", None) is True
    assert fetches(state, MEMBER_PATH) == 1


async def test_role_list_is_fetched_once_per_guild(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", {"roles": ["r2"]}) is True
    assert await gm.is_gm("1001", "2001", {"roles": ["r2"]}) is True
    assert fetches(state, ROLES_PATH) == 1


async def test_role_update_event_invalidates_cache(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", {"roles": ["r2"]}) is True

    state.roles["1001"] = [dict(PLAYER), {"id": "r2", "name": "Player 2"}]
    gm.handle_event("GUILD_ROLE_UPDATE", {"guild_id": "1001", "role": {"id": "r2", "name": "Player 2"}})

    assert await gm.is_gm("1001", "2001", {"roles": ["r2"]}) is False
    assert fetches(state, ROLES_PATH) == 2


async def test_role_delete_event_invalidates_cache(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", {"roles": ["r2"]}) is True

    state.roles["1001"] = [dict(PLAYER)]
    gm.handle_event("GUILD_ROLE_DELETE", {"guild_id": "1001", "role_id": "r2"})

    assert await gm.is_gm("1001", "2001", {"roles": ["r2"]}) is False
    assert fetches(state, ROLES_PATH) == 2


async def test_role_create_and_bulk_events_invalidate_cache(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    await gm.is_gm("1001", "2001", {"roles": []})
    gm.handle_event("GUILD_ROLE_CREATE", {"guild_id": "1001", "role": {"id": "r3", "name": "x"}})
    await gm.is_gm("1001", "2001", {"roles": []})
    gm.handle_event("GUILD_ROLE_UPDATE_BULK", {"guild_id": "1001", "roles": []})
    await gm.is_gm("1001", "2001", {"roles": []})
    assert fetches(state, ROLES_PATH) == 3


async def test_non_role_event_keeps_cache(fake, session):
    state, api = fake
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    await gm.is_gm("1001", "2001", {"roles": ["r2"]})
    gm.handle_event("MESSAGE_CREATE", {"guild_id": "1001", "content": "!flip"})
    await gm.is_gm("1001", "2001", {"roles": ["r2"]})
    assert fetches(state, ROLES_PATH) == 1


async def test_guild_without_configured_role_is_never_gm(fake, session):
    state, api = fake
    state.roles["1001"] = [dict(PLAYER)]
    gm = GMResolver(FluxerREST(session, api, TOKEN), "GM")
    assert await gm.is_gm("1001", "2001", {"roles": ["r1", "r2"]}) is False
