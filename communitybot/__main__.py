"""`python -m communitybot` runs the bot."""

from __future__ import annotations

import logging
import os
import sys

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
    # log_handler=None: logging is already set up above; discord.py would add a second handler
    bot.run(settings.token, log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
