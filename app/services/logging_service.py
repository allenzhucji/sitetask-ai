from __future__ import annotations

import logging
import re
import sys
from copy import copy
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
        # Other formatters may cache a complete exception (including task text)
        # on the shared record. Never reuse that cache or mutate other handlers.
        safe_record = copy(record)
        safe_record.exc_text = None
        output = super().format(safe_record)
        for pattern in self._patterns:
            if pattern.groups:
                output = pattern.sub(r"\1[REDACTED]", output)
            else:
                output = pattern.sub("[REDACTED]", output)
        return output

    def formatException(
        self,
        exc_info: tuple[
            type[BaseException] | None, BaseException | None, TracebackType | None
        ],
    ) -> str:
        # Exception messages, chains and source lines can include task contents,
        # credentials and local user paths. Keep only useful code locations.
        exception_type, _, traceback = exc_info
        locations = []
        while traceback is not None:
            code = traceback.tb_frame.f_code
            filename = re.split(r"[\\/]", code.co_filename)[-1]
            locations.append(
                f"  {filename}:{traceback.tb_lineno} in {code.co_name}"
            )
            traceback = traceback.tb_next
        # logging accepts exc_info=True even outside an exception handler.
        name = exception_type.__name__ if exception_type is not None else "Exception"
        locations.append(f"{name}: [REDACTED]")
        return "\n".join(locations)

    def formatStack(self, stack_info: str) -> str:
        # Preformatted stack text contains absolute paths and source lines.
        return "Stack details: [REDACTED]"


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
