# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import pytest

from green_oaks_bot.config import Config, ConfigError

BASE = {"FLUXER_TOKEN": "tok", "FLUXER_INSTANCE_URL": "https://fluxer.example"}


def test_minimal_env_applies_defaults():
    cfg = Config.from_env(dict(BASE))

    assert cfg.token == "tok"
    assert cfg.instance_url == "https://fluxer.example"
    assert cfg.api_url is None
    assert cfg.gateway_url is None
    assert cfg.gm_role_name == "GM"
    assert cfg.prefix == "!"
    assert cfg.data_dir == Path("data")
    assert cfg.log_level == "INFO"
    assert str(cfg.assets_dir).endswith("assets/cards")
    assert cfg.assets_dir.is_dir()


def test_empty_strings_count_as_unset():
    env = {
        "FLUXER_TOKEN": "tok",
        "FLUXER_INSTANCE_URL": "https://fluxer.example",
        "FLUXER_API_URL": "",
        "FLUXER_GATEWAY_URL": "",
        "GM_ROLE_NAME": "",
        "COMMAND_PREFIX": "",
        "DATA_DIR": "",
        "CARD_ASSETS_DIR": "",
        "LOG_LEVEL": "",
    }

    cfg = Config.from_env(env)

    assert cfg.api_url is None
    assert cfg.gateway_url is None
    assert cfg.gm_role_name == "GM"
    assert cfg.prefix == "!"
    assert cfg.data_dir == Path("data")
    assert cfg.log_level == "INFO"
    assert str(cfg.assets_dir).endswith("assets/cards")


def test_prefix_override():
    cfg = Config.from_env({**BASE, "COMMAND_PREFIX": "?"})

    assert cfg.prefix == "?"


def test_gm_role_name_is_preserved():
    cfg = Config.from_env({**BASE, "GM_ROLE_NAME": "Game Master"})

    assert cfg.gm_role_name == "Game Master"


def test_asset_and_data_dir_overrides(tmp_path):
    assets = tmp_path / "cards"
    assets.mkdir()
    cfg = Config.from_env(
        {**BASE, "CARD_ASSETS_DIR": str(assets), "DATA_DIR": str(tmp_path / "d")}
    )

    assert cfg.assets_dir == assets
    assert cfg.data_dir == tmp_path / "d"


def test_api_and_gateway_overrides_are_read():
    cfg = Config.from_env(
        {
            "FLUXER_TOKEN": "tok",
            "FLUXER_API_URL": "https://api.example",
            "FLUXER_GATEWAY_URL": "wss://gw.example",
        }
    )

    assert cfg.instance_url is None
    assert cfg.api_url == "https://api.example"
    assert cfg.gateway_url == "wss://gw.example"


def test_missing_token_raises():
    with pytest.raises(ConfigError):
        Config.from_env({"FLUXER_INSTANCE_URL": "https://fluxer.example"})


def test_blank_token_raises():
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "FLUXER_TOKEN": "   "})


def test_no_instance_or_api_url_raises():
    with pytest.raises(ConfigError):
        Config.from_env({"FLUXER_TOKEN": "tok"})


def test_invalid_log_level_raises():
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "LOG_LEVEL": "loud"})


def test_log_level_is_normalised_to_upper():
    cfg = Config.from_env({**BASE, "LOG_LEVEL": "debug"})

    assert cfg.log_level == "DEBUG"


def test_rules_file_defaults_to_the_packaged_file_and_can_be_overridden():
    from green_oaks_bot.ruleset import DEFAULT_RULES_FILE

    base = {"FLUXER_TOKEN": "x.y", "FLUXER_INSTANCE_URL": "https://fluxer.test"}
    assert Config.from_env(base).rules_file == DEFAULT_RULES_FILE
    assert Config.from_env({**base, "RULES_FILE": "/srv/rules.toml"}).rules_file == Path("/srv/rules.toml")
