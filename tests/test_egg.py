# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Pterodactyl egg passes the panel's own model validation.

The panel validates an imported egg on save (``Egg::$validationRules`` and
``EggVariable::$validationRules`` in pterodactyl/panel ``app/Models``). A failure
raises ``DataValidationException``, whose status code is 500, so a bad field shows
up as a bare "500 server error" on import rather than a form error. These checks
mirror those rules so CI catches a mismatch before anyone imports the file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from green_oaks_bot.bot import READY_LINE

EGG = Path(__file__).resolve().parents[1] / "egg-green-oaks-bot.json"

# Egg::$validationRules['docker_images.*'] regex, verbatim.
DOCKER_IMAGE_RE = re.compile(r"^[\w#\.\/\- ]*\|?~?[\w\.\/\-:@ ]*$")
# EggVariable::$validationRules['env_variable'] regex and reserved names, verbatim.
ENV_RE = re.compile(r"^[\w]{1,191}$")
RESERVED_ENV_NAMES = {
    "SERVER_MEMORY", "SERVER_IP", "SERVER_PORT", "ENV", "HOME", "USER", "STARTUP", "SERVER_UUID", "UUID",
}
# Laravel's `email` rule is stricter than this; this catches the failure that matters
# (a name instead of an address).
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_egg() -> dict:
    return json.loads(EGG.read_text("utf-8"))


def test_egg_is_ptdl_v2_with_ready_line_as_done_string():
    egg = load_egg()
    assert egg["meta"]["version"] == "PTDL_v2"
    assert json.loads(egg["config"]["startup"])["done"] == READY_LINE


def test_egg_author_is_an_email_address():
    # Egg::$validationRules['author'] = 'required|string|email'
    assert EMAIL_RE.match(load_egg()["author"]), "the panel rejects a non-email author with a 500"


def test_egg_fields_pass_the_panel_egg_rules():
    egg = load_egg()
    assert isinstance(egg["name"], str) and 0 < len(egg["name"]) <= 191
    assert egg["description"] is None or isinstance(egg["description"], str)
    assert egg["features"] is None or isinstance(egg["features"], list)
    assert isinstance(egg["file_denylist"], list)
    assert isinstance(egg["docker_images"], dict) and egg["docker_images"]
    for image in egg["docker_images"].values():
        assert isinstance(image, str) and len(image) <= 191 and DOCKER_IMAGE_RE.match(image), image
    assert isinstance(egg["startup"], str) and egg["startup"]
    assert isinstance(egg["config"]["stop"], str) and len(egg["config"]["stop"]) <= 191
    for key in ("startup", "logs", "files"):
        json.loads(egg["config"][key])  # rule: nullable|json


def test_egg_variables_pass_the_panel_variable_rules():
    variables = load_egg()["variables"]
    assert len(variables) == 9
    for var in variables:
        name = var["env_variable"]
        assert ENV_RE.match(name) and name not in RESERVED_ENV_NAMES, name
        assert isinstance(var["name"], str) and 1 <= len(var["name"]) <= 191, name
        assert isinstance(var["description"], str), name
        assert isinstance(var["default_value"], str), name
        assert isinstance(var["user_viewable"], bool) and isinstance(var["user_editable"], bool), name
        assert isinstance(var["rules"], str) and var["rules"], name


def test_egg_token_is_hidden_from_server_users():
    token = next(v for v in load_egg()["variables"] if v["env_variable"] == "FLUXER_TOKEN")
    assert token["user_viewable"] is False and token["user_editable"] is False
