from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.services.logging_service import (
    BACKUP_COUNT,
    LOG_FILE_NAME,
    MAX_LOG_BYTES,
    RedactingFormatter,
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


def test_global_exception_handler_records_uncaught_exception(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path)
    logger = configure_logging(paths)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    install_global_exception_handler(logger)

    error = ValueError("unexpected failure")
    assert logger.handlers
    sys.excepthook(ValueError, error, None)
    flush_handlers(logger)

    content = (paths.logs_dir / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "CRITICAL | sitetask | Unhandled exception" in content
    assert "ValueError: [REDACTED]" in content
    assert "unexpected failure" not in content


def test_exception_logging_omits_private_messages_chains_and_local_paths(tmp_path):
    logger = configure_logging(AppPaths(tmp_path))
    inner_marker = "synthetic-private-task-content"
    outer_marker = "synthetic-private-provider-response"

    try:
        try:
            raise ValueError(inner_marker)
        except ValueError as error:
            raise RuntimeError(outer_marker) from error
    except RuntimeError:
        logger.exception("Operation failed", stack_info=True)
    flush_handlers(logger)

    content = (tmp_path / "logs" / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert inner_marker not in content
    assert outer_marker not in content
    assert str(Path(__file__).resolve().parent) not in content
    assert "raise RuntimeError" not in content
    assert "ValueError" not in content
    assert "RuntimeError: [REDACTED]" in content
    assert "test_logging_service.py:" in content


def test_formatter_discards_another_handlers_cached_exception():
    marker = "synthetic-private-cached-exception"
    try:
        raise ValueError(marker)
    except ValueError:
        record = logging.LogRecord(
            "sitetask", logging.ERROR, __file__, 1, "Operation failed", (),
            sys.exc_info(),
        )
    logging.Formatter().format(record)
    original_cache = record.exc_text
    assert marker in original_cache

    content = RedactingFormatter().format(record)

    assert marker not in content
    assert "ValueError: [REDACTED]" in content
    assert record.exc_text == original_cache


def test_formatter_handles_exc_info_without_an_active_exception():
    record = logging.LogRecord(
        "sitetask", logging.ERROR, __file__, 1, "Operation failed", (),
        (None, None, None),
    )

    assert "Exception: [REDACTED]" in RedactingFormatter().format(record)


def test_logging_failure_does_not_block_application_startup(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path)

    def fail_to_create_directories(self) -> None:
        raise OSError("read-only location")

    monkeypatch.setattr(AppPaths, "ensure_runtime_directories", fail_to_create_directories)

    logger = configure_logging(paths)
    logger.info("This remains recoverable")

    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)
