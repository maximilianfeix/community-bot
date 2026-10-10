"""`python -m communitybot` runs the bot."""

from __future__ import annotations

import logging
import os
import sys

import discord

from .bot import CommunityBot
from .config import ConfigError, Settings
from .state import StateError


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env(os.environ)
        bot = CommunityBot(settings)
    except (ConfigError, StateError) as error:
        print(f"communitybot: {error}", file=sys.stderr)
        return 2
    try:
        # log_handler=None: logging is already set up above; discord.py would add a second handler
        bot.run(settings.token, log_handler=None)
    except discord.LoginFailure:
        # One clear line instead of a traceback; the deploy log shows this when the secret is wrong.
        print("communitybot: Discord rejected the token; check the DISCORD_TOKEN secret", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
