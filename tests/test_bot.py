"""Bot wiring against the fake REST app, real Store and real CardImages (AC10.8-10.10, AC3.1, AC8.1)."""

from __future__ import annotations

import io
import logging
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from PIL import Image

from green_oaks_bot import bot as bot_mod
from green_oaks_bot.bot import Bot
from green_oaks_bot.config import DEFAULT_ASSETS_DIR
from green_oaks_bot.fluxer.rest import FluxerREST
from green_oaks_bot.fluxer.roles import GMResolver
from green_oaks_bot.render import CardImages, embed_colour
from green_oaks_bot.store import Store
from tests.fakes import FakeFluxerState, Override, make_rest_app

TOKEN = "test.token"
GUILD = "100"
CHANNEL = "200"
MESSAGES = f"/api/v1/channels/{CHANNEL}/messages"
ROLES = f"/api/v1/guilds/{GUILD}/roles"
GM_ROLE = {"id": "r9", "name": "GM"}


@pytest.fixture
async def fake(aiohttp_server):
    state = FakeFluxerState()
    state.roles = {GUILD: [{"id": "r1", "name": "Player"}, dict(GM_ROLE)]}
    server = await aiohttp_server(make_rest_app(state))
    base = str(server.make_url("/")).rstrip("/")
    return state, f"{base}/api"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


@pytest.fixture(scope="module")
def images() -> CardImages:
    return CardImages(DEFAULT_ASSETS_DIR)


def make_bot(session, api, tmp_path: Path, images: CardImages) -> Bot:
    rest = FluxerREST(session, api, TOKEN)
    return Bot(
        rest=rest,
        store=Store(tmp_path / "data", prefix="!", rng=random.Random(3)),
        images=images,
        gm=GMResolver(rest, "GM"),
        prefix="!",
    )


def event(content: str, *, id: str = "40001", author_id: str = "1", name: str = "Alice",
          roles: list[str] | None = None, guild: str | None = GUILD, channel: str = CHANNEL,
          bot: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": id,
        "channel_id": channel,
        "content": content,
        "author": {"id": author_id, "username": name, **({"bot": True} if bot else {})},
    }
    if guild is not None:
        d["guild_id"] = guild
        d["member"] = {"roles": [] if roles is None else roles, "nick": name}
    return d


def messages(state: FakeFluxerState):
    return [r for r in state.requests if r.path == MESSAGES]


def roles_fetches(state: FakeFluxerState) -> int:
    return len([r for r in state.requests if r.path == ROLES])


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(io.BytesIO(data)) as im:
        return im.size


# AC3.1, AC8.1, AC10.5: end to end through Store, CardImages and FluxerREST


async def test_flip_sends_multipart_reply_with_card_image(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40001"))

    (sent,) = messages(state)
    assert sent.content_type == "multipart/form-data"
    embed = sent.payload["embeds"][0]
    assert "Alice flips" in embed["description"]
    assert "New deck for this channel" in embed["description"]  # first command in the channel
    assert embed["image"] == {"url": "attachment://card.png"}
    assert sent.payload["message_reference"] == {"message_id": "40001"}
    ((filename, data),) = sent.files
    assert filename == "card.png"
    assert png_size(data) == (500, 726)


async def test_images_off_sends_json_without_attachment(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!images off", id="40001"))
    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40002"))

    flip = messages(state)[-1]
    assert flip.content_type == "application/json"
    assert "image" not in flip.payload["embeds"][0]
    assert flip.files == []


async def test_images_small_sends_half_size_png(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!images small", id="40001"))
    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40002"))

    ((_, data),) = messages(state)[-1].files
    assert png_size(data) == (50, 72)


async def test_state_is_saved_per_channel(fake, session, tmp_path, images):
    _, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!flip"))

    assert (tmp_path / "data" / "guilds" / GUILD / f"{CHANNEL}.json").is_file()


# GM path


async def test_shuffle_by_gm_succeeds(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!shuffle", roles=["r9"]))

    embed = messages(state)[-1].payload["embeds"][0]
    assert "shuffles" in embed["description"]
    assert embed["color"] == embed_colour("info")


async def test_shuffle_by_non_gm_is_refused(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!shuffle", roles=[]))

    embed = messages(state)[-1].payload["embeds"][0]
    assert "Only the GM can shuffle." in embed["description"]
    assert embed["color"] == embed_colour("error")


async def test_flip_never_fetches_roles(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    for n in range(3):
        await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id=f"m{n}", roles=["r9"]))

    assert len(messages(state)) == 3
    assert roles_fetches(state) == 0


# AC10.8: ignored messages and DMs


async def test_bot_authored_message_is_ignored(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", bot=True))

    assert state.requests == []


async def test_own_user_message_is_ignored(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)
    bot.on_ready("B")

    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", author_id="B"))

    assert state.requests == []


async def test_message_without_prefix_is_ignored(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("hello there"))

    assert state.requests == []


async def test_dm_gets_server_only_notice_once_per_channel(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="d1", guild=None, channel="300"))
    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="d2", guild=None, channel="300"))

    (notice,) = [r for r in state.requests if r.path == "/api/v1/channels/300/messages"]
    assert notice.content_type == "application/json"
    assert "server channels only" in notice.payload["embeds"][0]["description"]


# AC10.9: ready line


def test_ready_line_printed_exactly_once(capsys, fake, session, tmp_path, images):
    _, api = fake
    bot = make_bot(session, api, tmp_path, images)

    bot.on_ready("B")
    bot.on_ready("B")

    assert capsys.readouterr().out.count("Green Oaks bot ready") == 1


def test_ready_line_printed_even_when_logging_is_error_only(capsys, fake, session, tmp_path, images):
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.ERROR)
    try:
        bot = make_bot(session, fake[1], tmp_path, images)
        bot.on_ready("B")
    finally:
        root.setLevel(previous)

    assert "Green Oaks bot ready" in capsys.readouterr().out


# AC10.10: unexpected exceptions are logged and the bot keeps running


async def test_unexpected_error_is_logged_and_bot_keeps_running(
    fake, session, tmp_path, images, monkeypatch, caplog
):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(bot_mod, "execute", boom)
    with caplog.at_level(logging.ERROR, logger="green_oaks_bot"):
        await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40001"))

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and errors[0].exc_info is not None
    (failure,) = messages(state)
    assert "Something went wrong" in failure.payload["embeds"][0]["description"]

    monkeypatch.undo()
    await bot.on_dispatch("MESSAGE_CREATE", event("!status", id="40002"))
    assert "Trump:" in messages(state)[-1].payload["embeds"][0]["description"]


async def test_command_missing_channel_id_is_dropped_without_a_traceback(
    fake, session, tmp_path, images, caplog
):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)
    malformed = event("!flip")
    del malformed["channel_id"]

    with caplog.at_level(logging.WARNING, logger="green_oaks_bot"):
        await bot.on_dispatch("MESSAGE_CREATE", malformed)

    (warning,) = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning.levelno == logging.WARNING
    assert "malformed ids" in warning.getMessage()
    assert warning.exc_info is None
    assert state.requests == []


@pytest.mark.parametrize("missing", [True, False])
async def test_non_command_with_malformed_channel_id_is_silent(
    fake, session, tmp_path, images, caplog, missing
):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)
    message = event("hello there", channel="../x")
    if missing:
        del message["channel_id"]

    with caplog.at_level(logging.INFO, logger="green_oaks_bot"):
        await bot.on_dispatch("MESSAGE_CREATE", message)

    assert state.requests == []
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


async def test_rest_failure_during_reply_is_contained(fake, session, tmp_path, images, caplog):
    state, api = fake
    state.overrides[f"POST {MESSAGES}"] = Override(
        status=500, body=b'{"code":"INTERNAL","message":"down"}'
    )
    bot = make_bot(session, api, tmp_path, images)

    with caplog.at_level(logging.ERROR, logger="green_oaks_bot"):
        await bot.on_dispatch("MESSAGE_CREATE", event("!flip"))

    assert any(r.exc_info is not None for r in caplog.records)


# Process-level startup behaviour


def run_module(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "green_oaks_bot"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_missing_token_is_a_configuration_error():
    result = run_module({"PATH": os.environ["PATH"]})

    assert result.returncode == 2
    assert "Configuration error: FLUXER_TOKEN is required" in result.stderr


def test_unreachable_instance_fails_cleanly(tmp_path):
    result = run_module({
        "PATH": os.environ["PATH"],
        "FLUXER_TOKEN": "x.y",
        "FLUXER_API_URL": "http://127.0.0.1:9/api",
        "DATA_DIR": str(tmp_path / "data"),
    })

    assert result.returncode == 1
    assert "startup failed" in result.stdout
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "data").exists()


# Event ids are interpolated into REST paths: malformed ids drop the event (nothing sent)


@pytest.mark.parametrize("bad_channel", ["../x", "1?x", "1#x", "12a", ""])
async def test_malformed_channel_id_sends_nothing(fake, session, tmp_path, images, bad_channel):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", channel=bad_channel))

    assert state.requests == []


async def test_malformed_dm_channel_id_sends_nothing(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!flip", guild=None, channel="../x"))

    assert state.requests == []


async def test_malformed_guild_id_sends_nothing_even_for_gm_check(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!shuffle", guild="100/../../x"))

    assert state.requests == []


async def test_malformed_author_id_sends_nothing(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!shuffle", author_id="2?x"))

    assert state.requests == []


async def test_malformed_message_id_drops_only_the_reply_reference(fake, session, tmp_path, images):
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)

    await bot.on_dispatch("MESSAGE_CREATE", event("!status", id="../4"))

    (sent,) = messages(state)
    assert sent.path == MESSAGES
    assert "message_reference" not in sent.payload
    assert "Trump:" in sent.payload["embeds"][0]["description"]


# Without the Attach Files permission the card is still saved: the reply goes out text-only


async def test_403_on_attachment_retries_text_only_and_warns_once(fake, session, tmp_path, images, caplog):
    state, api = fake
    state.forbid_attachments = True
    bot = make_bot(session, api, tmp_path, images)

    with caplog.at_level(logging.WARNING, logger="green_oaks_bot"):
        await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40001"))
        await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40002"))

    sent = messages(state)
    assert [(r.content_type, r.status) for r in sent] == [
        ("multipart/form-data", 403), ("application/json", 200),
        ("multipart/form-data", 403), ("application/json", 200),
    ]
    for reply in sent[1::2]:
        description = reply.payload["embeds"][0]["description"]
        assert "image" not in reply.payload["embeds"][0]
        assert "Something went wrong" not in description
        assert description  # the command's own text, not the generic error
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "Attach Files" in r.getMessage()]
    assert len(warnings) == 1


async def test_403_on_json_send_is_not_resent(fake, session, tmp_path, images, caplog):
    """Images off: a 403 on a JSON-only send is not about attachments, so nothing is retried."""
    state, api = fake
    bot = make_bot(session, api, tmp_path, images)
    await bot.on_dispatch("MESSAGE_CREATE", event("!images off", id="40001"))
    state.overrides[f"POST {MESSAGES}"] = Override(
        status=403, body=b'{"code":"MISSING_PERMISSIONS","message":"Missing Permissions"}'
    )

    with caplog.at_level(logging.WARNING, logger="green_oaks_bot"):
        await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40002"))

    command_post, error_reply = messages(state)[1:]
    assert (command_post.content_type, command_post.status) == ("application/json", 403)
    assert "flips" in command_post.payload["embeds"][0]["description"]
    assert "Something went wrong" in error_reply.payload["embeds"][0]["description"]
    assert len(messages(state)) == 3  # the command once, then the error reply
    assert not [r for r in caplog.records if "Attach Files" in r.getMessage()]


async def test_403_on_text_only_retry_falls_through_to_error_reply(
    fake, session, tmp_path, images, caplog
):
    state, api = fake
    state.forbid_attachments = True
    state.overrides[f"POST {MESSAGES}"] = Override(
        status=403, body=b'{"code":"MISSING_PERMISSIONS","message":"Missing Permissions"}'
    )
    bot = make_bot(session, api, tmp_path, images)

    with caplog.at_level(logging.WARNING, logger="green_oaks_bot"):
        await bot.on_dispatch("MESSAGE_CREATE", event("!flip", id="40001"))

    sent = messages(state)
    assert [(r.content_type, r.status) for r in sent] == [
        ("multipart/form-data", 403),  # the card
        ("application/json", 403),     # the text-only retry, refused too
        ("application/json", 403),     # the generic error reply, attempted
    ]
    assert "Something went wrong" in sent[-1].payload["embeds"][0]["description"]
    assert [r for r in caplog.records if r.getMessage() == "could not send error reply"]
    assert len([r for r in caplog.records if "Attach Files" in r.getMessage()]) == 1
