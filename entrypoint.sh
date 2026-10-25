#!/bin/bash
# SPDX-FileCopyrightText: 2026 K. Chen
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Pterodactyl yolk-style entrypoint: expand {{VAR}} in $STARTUP, then exec it.
set -e
cd /home/container
STARTUP="${STARTUP:-python -m green_oaks_bot}"
PARSED=$(echo "${STARTUP}" | sed -e 's/{{/${/g' -e 's/}}/}/g')
printf '\033[1m\033[33mcontainer~ \033[0m%s\n' "${PARSED}"
# STARTUP must be a single command, because it is exec'd so Python receives signals from tini.
eval "exec ${PARSED}"
