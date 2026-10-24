# Fluxer live observations

Recorded 2026-10-24 from a live run against a self-hosted Fluxer instance (Phase 5, Task 9).
Instance hostnames, user IDs and tokens are deliberately omitted.

## Discovery and gateway

- `GET {instance}/.well-known/fluxer` returned `endpoints.api_public = https://<instance>/api`
  and `endpoints.gateway = wss://<instance>/gateway`, both on the instance host and the default port.
- `GET {api}/v1/gateway/bot` (bot auth) returned the same `wss://<instance>/gateway` URL.
  No `FLUXER_GATEWAY_URL` override was needed.
- Identify without an `intents` field was accepted; READY arrived and the bot printed
  `Green Oaks bot ready`.
- SIGTERM shut down cleanly (exit code 0).

## MESSAGE_CREATE payload

- `author.bot` **is present** (`true`) on messages sent by a bot, so the bot's own replies
  are ignored by that check as well as by the own-user-ID check.
- `member` **is present** in guild channels and includes `roles` (array of snowflake strings)
  and `nick` (may be `null`). Other keys seen: `accent_color`, `avatar`, `banner`,
  `communication_disabled_until`, `deaf`, `guild_id`, `joined_at`, `mute`.
  The GM check therefore uses `member.roles` directly; the member fetch is only a fallback.

## Replies

- Multipart messages with `payload_json` + `files[0]` (`card.png`) were accepted. Fluxer
  rewrites the embed's `image.url` from `attachment://card.png` to a hosted media URL
  (with `proxy_url`, `width`, `height`, `content_type`). The echoed message's top-level
  `attachments` list was empty: the image lives in the embed only.
- Replies arrived within roughly 0.2–0.9 s of the command.

## Network note

The bot reaches the instance through its public hostname. On a LAN behind the same router this
relies on NAT hairpinning, and a network-isolated host or container needs an explicit firewall
allow to the instance's reverse proxy on TCP 443 (API and gateway share that port here).
