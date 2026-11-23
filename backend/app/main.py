from __future__ import annotations

import logging

from .bot.app import build_application
from .config import get_settings
from .logging_setup import setup_logging


def main() -> None:
    s = get_settings()
    setup_logging(s.log_level, to_file=s.log_to_file, log_dir=s.log_path(), secrets=[s.telegram_bot_token.get_secret_value(), s.groq_api_key.get_secret_value()])
    app = build_application(s)
    logging.getLogger("nexus").info("NEXUS-IA arrancando (polling)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
