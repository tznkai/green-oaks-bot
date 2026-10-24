"""GM role resolution and cache."""

from __future__ import annotations

from typing import Any

from green_oaks_bot.fluxer.rest import FluxerREST


class GMResolver:
    def __init__(self, rest: FluxerREST, role_name: str) -> None:
        self.rest = rest
        self.role_name = role_name.casefold()
        self._gm_role_ids: dict[str, set[str]] = {}

    async def _role_ids(self, guild_id: str) -> set[str]:
        if guild_id not in self._gm_role_ids:
            roles = await self.rest.get_roles(guild_id)
            self._gm_role_ids[guild_id] = {
                str(r["id"]) for r in roles if str(r.get("name", "")).casefold() == self.role_name
            }
        return self._gm_role_ids[guild_id]

    async def is_gm(self, guild_id: str, user_id: str, member: dict[str, Any] | None) -> bool:
        if member is not None and isinstance(member.get("roles"), list):
            roles = member["roles"]
        else:
            roles = (await self.rest.get_member(guild_id, user_id)).get("roles", [])
        return bool({str(r) for r in roles} & await self._role_ids(guild_id))

    def invalidate(self, guild_id: str) -> None:
        self._gm_role_ids.pop(guild_id, None)

    def handle_event(self, event: str, data: dict[str, Any]) -> None:
        if event.startswith("GUILD_ROLE_") and "guild_id" in data:
            self.invalidate(str(data["guild_id"]))
