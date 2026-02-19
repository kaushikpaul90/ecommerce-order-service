import logging
from pythonjsonlogger import jsonlogger
from app.config import settings

def configure_logging():
    logger = logging.getLogger()
    logger.setLevel(settings.LOG_LEVEL)

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)

    logger.handlers = []
    logger.addHandler(handler)
