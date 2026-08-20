from __future__ import annotations

import os
from pathlib import Path

from kingdom_tech_desk.bot import KingdomTechDeskBot
from kingdom_tech_desk.config import load_config
from kingdom_tech_desk.logging_setup import configure_logging


def _load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def main() -> None:
    _load_env_file()
    config = load_config()
    configure_logging(
        config.storage.log_dir,
        secrets=[config.token, config.server_context.authentication_token],
    )
    bot = KingdomTechDeskBot(config)
    bot.run(config.token, log_handler=None)


if __name__ == "__main__":
    main()
