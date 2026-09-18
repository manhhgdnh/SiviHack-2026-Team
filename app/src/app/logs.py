"""Console logging for the app's own loggers, so a run can be followed in the terminal under
`uv run uvicorn …` or with `docker compose logs -f backend`. Uvicorn configures only its own
loggers; without this the app's INFO lines go nowhere.

    LOG_LEVEL=DEBUG   also prints the head of every prompt and the model's raw answer
"""

import logging
import sys

from app import config

_NAME = "proposal-scorer"


def configure() -> None:
    logger = logging.getLogger("app")
    if any(h.get_name() == _NAME for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_NAME)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(config.LOG_LEVEL)
