"""Environment-variable configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "cards"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(ValueError):
    pass


def _opt(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class Config:
    token: str
    instance_url: str | None
    api_url: str | None
    gateway_url: str | None
    gm_role_name: str
    prefix: str
    data_dir: Path
    assets_dir: Path
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        token = _opt(env, "FLUXER_TOKEN")
        if token is None:
            raise ConfigError("FLUXER_TOKEN is required")
        instance_url = _opt(env, "FLUXER_INSTANCE_URL")
        api_url = _opt(env, "FLUXER_API_URL")
        if instance_url is None and api_url is None:
            raise ConfigError("set FLUXER_INSTANCE_URL (or FLUXER_API_URL)")
        log_level = (_opt(env, "LOG_LEVEL") or "INFO").upper()
        if log_level not in LOG_LEVELS:
            raise ConfigError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
        prefix = env.get("COMMAND_PREFIX", "")
        return cls(
            token=token,
            instance_url=instance_url,
            api_url=api_url,
            gateway_url=_opt(env, "FLUXER_GATEWAY_URL"),
            gm_role_name=_opt(env, "GM_ROLE_NAME") or "GM",
            prefix=prefix if prefix.strip() else "!",
            data_dir=Path(_opt(env, "DATA_DIR") or "data"),
            assets_dir=Path(_opt(env, "CARD_ASSETS_DIR") or DEFAULT_ASSETS_DIR),
            log_level=log_level,
        )
