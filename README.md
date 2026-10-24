# Green Oaks Bot

A Fluxer chat bot that resolves Green Oaks "ArterioscleroSys" card checks with one shared 40-card deck per channel.

Status: under construction. Setup, deployment and the command reference arrive in later phases.

## Development

    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -e '.[dev]'
    .venv/bin/python -m pytest
