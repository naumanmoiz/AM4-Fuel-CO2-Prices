from __future__ import annotations

import logging

from .bot import AM4Bot
from .config import Config


def main() -> None:
    config = Config.from_env()
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bot = AM4Bot(config)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
