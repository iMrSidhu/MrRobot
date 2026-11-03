"""Structured logging: pipe-delimited records — timestamp|level|service|message."""
import logging


def get_logger(service: str) -> logging.Logger:
    logger = logging.getLogger(f"sentinel.{service}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s|%(levelname)s|%(name)s|%(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
