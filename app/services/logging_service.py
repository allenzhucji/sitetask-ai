from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from types import TracebackType

from app.utils.paths import AppPaths


LOGGER_NAME = "sitetask"
LOG_FILE_NAME = "sitetask.log"
MAX_LOG_BYTES = 1_048_576
BACKUP_COUNT = 3


class RedactingFormatter(logging.Formatter):
    _patterns = (
        re.compile(r"(?i)(OPENAI_API_KEY\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(api[_ -]?key\s*[=:]\s*)\S+"),
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b"),
    )

    def format(self, record: logging.LogRecord) -> str:
        output = super().format(record)
        for pattern in self._patterns:
            if pattern.groups:
                output = pattern.sub(r"\1[REDACTED]", output)
            else:
                output = pattern.sub("[REDACTED]", output)
        return output


def configure_logging(paths: AppPaths | None = None) -> logging.Logger:
    paths = paths or AppPaths.discover()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, "_sitetask_handler", False):
            logger.removeHandler(handler)
            handler.close()

    try:
        paths.ensure_runtime_directories()
        handler: logging.Handler = RotatingFileHandler(
            paths.logs_dir / LOG_FILE_NAME,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.NullHandler()

    handler._sitetask_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
    )
    logger.addHandler(handler)
    return logger


def install_global_exception_handler(logger: logging.Logger) -> None:
    def handle_exception(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception, traceback)
            return
        logger.critical(
            "Unhandled exception",
            exc_info=(exception_type, exception, traceback),
        )

    sys.excepthook = handle_exception
