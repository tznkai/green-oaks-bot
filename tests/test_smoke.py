import importlib

MODULES = [
    "green_oaks_bot",
    "green_oaks_bot.deck",
    "green_oaks_bot.rules",
    "green_oaks_bot.ruleset",
    "green_oaks_bot.table",
    "green_oaks_bot.commands",
    "green_oaks_bot.render",
    "green_oaks_bot.store",
    "green_oaks_bot.config",
    "green_oaks_bot.fluxer",
    "green_oaks_bot.fluxer.gateway",
    "green_oaks_bot.fluxer.rest",
    "green_oaks_bot.fluxer.roles",
]


def test_all_modules_import():
    for name in MODULES:
        importlib.import_module(name)


def test_version():
    import green_oaks_bot

    assert green_oaks_bot.__version__ == "0.1.0"
