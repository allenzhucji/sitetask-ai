from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.services.logging_service import (
    BACKUP_COUNT,
    LOG_FILE_NAME,
    MAX_LOG_BYTES,
    configure_logging,
    install_global_exception_handler,
)
from app.utils.paths import AppPaths


def flush_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def test_configure_logging_creates_rotating_log_file(tmp_path):
    paths = AppPaths(tmp_path)
    logger = configure_logging(paths)

    logger.info("Application started")
    flush_handlers(logger)

    handler = next(
        handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)
    )
    assert handler.maxBytes == MAX_LOG_BYTES
    assert handler.backupCount == BACKUP_COUNT
    assert (paths.logs_dir / LOG_FILE_NAME).read_text(encoding="utf-8").endswith(
        "INFO | sitetask | Application started\n"
    )


def test_log_formatter_redacts_api_keys_in_messages_and_tracebacks(tmp_path):
    paths = AppPaths(tmp_path)
    logger = configure_logging(paths)

    logger.error("OPENAI_API_KEY=sk-message-secret123")
    try:
        raise RuntimeError("api_key: sk-traceback-secret456")
    except RuntimeError:
        logger.exception("Credential operation failed")
    flush_handlers(logger)

    content = (paths.logs_dir / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "sk-message-secret123" not in content
    assert "sk-traceback-secret456" not in content
    assert content.count("[REDACTED]") >= 2


def test_global_exception_handler_records_uncaught_exception(tmp_path):
    paths = AppPaths(tmp_path)
    logger = configure_logging(paths)
    install_global_exception_handler(logger)

    error = ValueError("unexpected failure")
    assert logger.handlers
    import sys

    sys.excepthook(ValueError, error, None)
    flush_handlers(logger)

    content = (paths.logs_dir / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "CRITICAL | sitetask | Unhandled exception" in content
    assert "ValueError: unexpected failure" in content


def test_logging_failure_does_not_block_application_startup(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path)

    def fail_to_create_directories(self) -> None:
        raise OSError("read-only location")

    monkeypatch.setattr(AppPaths, "ensure_runtime_directories", fail_to_create_directories)

    logger = configure_logging(paths)
    logger.info("This remains recoverable")

    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)
