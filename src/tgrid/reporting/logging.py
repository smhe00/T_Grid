"""Structured JSONL logging for TGrid.

The caller explicitly supplies a log file path; this module never discovers a
default path from configuration, environment, or account state.  Every emitted
event is one complete, parseable JSON object per line (UTF-8), so later Gate
audit and forensics can consume it mechanically.

Design constraints (INV / protocol):

- Only TGrid's own named logger is configured; the root logger's handlers,
  level, and propagate flag are left untouched.
- The TGrid logger sets ``propagate=False`` to avoid double-writing to root.
- Only ``tgrid`` / ``tgrid.<child>`` names are accepted; ``root`` and
  third-party names are rejected.
- Configuration, serialization, and write failures raise explicit
  :class:`tgrid.risk.exceptions.LoggingError` subclasses and are not silently
  swallowed via ``logging.raiseExceptions``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Dict

from tgrid.risk.exceptions import (
    LoggingConfigError,
    LoggingEmitError,
)

SCHEMA_VERSION = 1

# Reserved top-level event keys that callers must not shadow via context.
_RESERVED_FIELDS = frozenset(
    {
        "schema_version",
        "timestamp",
        "level",
        "logger",
        "event",
        "message",
        "context",
    }
)

# Only explicit standard logging integer levels are accepted (REV-G0T003-005).
# bool, NOTSET, negatives, and unknown integers are rejected so a synthesized
# level name like "Level 12345" can never appear in output.
_STANDARD_LEVELS = frozenset(
    {
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    }
)
_LEVEL_NAMES = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

# Registry of TGrid-owned handlers per logger name, guarded for concurrent
# (re)configuration.  Values are handlers we installed so shutdown can remove
# and close them deterministically, and emit() can prove the logger is still
# live (REV-G0T003-001).
_registry: Dict[str, logging.Handler] = {}
_registry_lock = threading.Lock()

# Per-logger reentrant locks serialize the full lifecycle state transitions for
# a given logger name: emit (resolve + write), configure (open + drop + add +
# register), and shutdown (drop + close).  This makes emit-vs-shutdown and
# concurrent-configure deterministic without sleeps (REV-G0T003-006/-007).
_logger_locks: Dict[str, threading.RLock] = {}
_logger_locks_guard = threading.Lock()


def _get_logger_lock(name: str) -> threading.RLock:
    with _logger_locks_guard:
        lock = _logger_locks.get(name)
        if lock is None:
            lock = threading.RLock()
            _logger_locks[name] = lock
        return lock


def _validate_logger_name(name: str) -> None:
    """Only ``tgrid`` or ``tgrid.<child>`` names are allowed (REV-G0T003-002)."""
    if not isinstance(name, str) or not name.strip():
        raise LoggingConfigError("logger name must be a non-empty string")
    if name == "tgrid":
        return
    if name.startswith("tgrid.") and len(name) > len("tgrid."):
        return
    raise LoggingConfigError(
        f"logger name {name!r} is not allowed; must be 'tgrid' or 'tgrid.<child>'"
    )


def _validate_level(level: Any, error_cls) -> None:
    if isinstance(level, bool) or type(level) is not int:
        raise error_cls(
            f"level must be a standard logging integer, got {type(level).__name__}"
        )
    if level not in _STANDARD_LEVELS:
        raise error_cls(
            f"level {level!r} is not a standard logging level "
            "(DEBUG/INFO/WARNING/ERROR/CRITICAL)"
        )


def _validate_and_dump(
    event: str,
    message: str,
    level_name: str,
    logger_name: str,
    context: Dict[str, Any],
) -> str:
    """Validate a structured event and serialize it to a single JSON line.

    Performs the fail-closed checks (context shape, reserved fields, JSON
    serializability) synchronously and returns the serialized line.  Raising
    here — before the event reaches ``logging``'s error-swallowing emit path —
    is what guarantees callers observe an explicit exception rather than a
    silently dropped or half-written line.
    """
    if not isinstance(event, str) or not event.strip():
        raise LoggingEmitError("event name must be a non-empty string")
    if not isinstance(message, str):
        raise LoggingEmitError("message must be a string")
    if not isinstance(context, dict):
        raise LoggingEmitError("context must be a JSON object (dict)")
    for key in context:
        if not isinstance(key, str) or not key:
            raise LoggingEmitError("context keys must be non-empty strings")
        if key in _RESERVED_FIELDS:
            raise LoggingEmitError(f"context key {key!r} is reserved")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level_name,
        "logger": logger_name,
        "event": event,
        "message": message,
        "context": context,
    }
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=False)
    except (TypeError, ValueError) as exc:
        raise LoggingEmitError(f"cannot serialize log event: {exc}") from exc


class JsonlFormatter(logging.Formatter):
    """Serialize a log record into one JSON object per physical line.

    All fail-closed validation happens in :func:`_validate_and_dump`, which
    :func:`emit` calls synchronously before the record reaches this formatter.
    The formatter therefore only re-serializes already-validated data.
    """

    def format(self, record: logging.LogRecord) -> str:
        return _validate_and_dump(
            record.event,
            record.getMessage(),
            record.levelname,
            record.name,
            getattr(record, "context", {}) or {},
        )


class _JsonlFileHandler(logging.FileHandler):
    """FileHandler that fails closed on write/flush/format errors.

    Standard ``logging`` swallows handler errors via ``handleError`` (gated by
    ``raiseExceptions``).  TGrid must not depend on that flag to surface
    production failures, so this handler re-raises any emit error as
    :class:`LoggingEmitError`.
    """

    def handleError(self, record: logging.LogRecord) -> None:
        exc = sys.exc_info()[1]
        if exc is not None:
            raise LoggingEmitError(
                f"log handler failed for {record.name!r}: {exc}"
            ) from exc
        raise LoggingEmitError(f"log handler failed for {record.name!r}")


def _validate_path(path: str) -> None:
    if not isinstance(path, str) or not path.strip():
        raise LoggingConfigError("log file path must be a non-empty string")
    if os.path.isdir(path):
        raise LoggingConfigError(f"log file path is a directory: {path}")
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise LoggingConfigError(
                f"cannot create log parent directory {parent!r}: {exc}"
            ) from exc


def _drop_tgrid_handler(logger: logging.Logger) -> None:
    """Remove and close any handler we previously installed on ``logger``.

    ``close`` is attempted even when ``flush`` fails, so a failed flush never
    leaks an unmanaged file handle (REV-G0T003-004).
    """
    with _registry_lock:
        handler = _registry.pop(logger.name, None)
    if handler is None:
        return
    logger.removeHandler(handler)
    first_error = None
    try:
        handler.flush()
    except OSError as exc:
        first_error = exc
    try:
        handler.close()
    except OSError as exc:
        if first_error is None:
            first_error = exc
    if first_error is not None:
        raise LoggingEmitError(
            f"failed to flush/close previous handler for {logger.name!r}: {first_error}"
        ) from first_error


def _resolve_configured_handler(logger: Any) -> logging.Handler:
    """Prove ``logger`` is the live, registered, TGrid-owned logger and return
    its registered handler.

    Raises :class:`LoggingEmitError` if the object is not a real
    :class:`logging.Logger`, was never configured, has been shut down, or is a
    forged object that merely shares a name (REV-G0T003-001).
    """
    if not isinstance(logger, logging.Logger):
        raise LoggingEmitError("logger must be a logging.Logger instance")
    with _registry_lock:
        handler = _registry.get(logger.name)
    if handler is None:
        raise LoggingEmitError(f"logger {logger.name!r} is not configured for JSONL output")
    # The registered object must be the same object the caller holds, and it
    # must still be attached to the live logger.
    if logging.getLogger(logger.name) is not logger:
        raise LoggingEmitError(f"logger {logger.name!r} is not the registered logger")
    if handler not in logger.handlers:
        raise LoggingEmitError(f"logger {logger.name!r} has lost its JSONL handler")
    return handler


def configure_jsonl_logger(
    name: str,
    path: str,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure a named TGrid logger writing JSONL to ``path``.

    Reconfiguring the same logger replaces its previous TGrid-owned handler
    (flush + close) so no duplicate handlers or duplicate lines accumulate.
    Raises :class:`LoggingConfigError` / :class:`LoggingEmitError` on failure.
    """
    _validate_logger_name(name)
    _validate_level(level, LoggingConfigError)
    _validate_path(path)

    # Serialize the full transition (open + drop + add + register) per logger
    # name so concurrent configuration of the same name cannot leave two
    # attached handlers (REV-G0T003-007).
    lock = _get_logger_lock(name)
    with lock:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False

        try:
            handler = _JsonlFileHandler(path, encoding="utf-8")
        except OSError as exc:
            raise LoggingConfigError(
                f"cannot open log file {path!r}: {exc}"
            ) from exc
        handler.setFormatter(JsonlFormatter())
        # The handler must never filter out an explicit emit() call: the
        # per-event level is recorded in the JSON payload, not used to drop.
        handler.setLevel(logging.DEBUG)

        # Replace any prior handler (idempotent reconfiguration).
        try:
            _drop_tgrid_handler(logger)
        except LoggingEmitError:
            handler.close()
            raise
        try:
            logger.addHandler(handler)
        except Exception as exc:
            handler.close()
            raise LoggingConfigError(
                f"cannot attach handler to {name!r}: {exc}"
            ) from exc

        with _registry_lock:
            _registry[name] = handler
        return logger


def emit(
    logger: logging.Logger,
    event: str,
    message: str,
    level: int = logging.INFO,
    context: Dict[str, Any] | None = None,
) -> None:
    """Write one structured JSONL event.

    ``logger`` must be a currently-configured TGrid logger; ``event`` a
    non-empty string; ``context`` a JSON-compatible dict with non-empty string
    keys that do not shadow reserved fields.  Any validation, serialization, or
    write failure raises :class:`LoggingEmitError` synchronously — a "success"
    return always means exactly one complete line was written.
    """
    _validate_level(level, LoggingEmitError)
    if context is None:
        context = {}
    if not isinstance(logger, logging.Logger):
        raise LoggingEmitError("logger must be a logging.Logger instance")

    # Hold the per-logger lock across "resolve live handler + write" so a
    # concurrent shutdown/reconfigure cannot close the handler between the
    # liveness check and the write, or reopen the file after shutdown returns
    # (REV-G0T003-006).
    lock = _get_logger_lock(logger.name)
    with lock:
        handler = _resolve_configured_handler(logger)
        # Validate + serialize up front so bad input raises here, not inside
        # logging's error-swallowing emit path.
        _validate_and_dump(event, message, _LEVEL_NAMES[level], logger.name, context)

        record = logger.makeRecord(
            logger.name,
            level,
            "(unknown)",
            0,
            message,
            None,
            None,
        )
        record.event = event
        record.context = dict(context)
        # Deliver directly to the registered handler so an explicit emit() is
        # never dropped by the logger's own level threshold.
        try:
            handler.handle(record)
        except LoggingEmitError:
            raise
        except Exception as exc:
            raise LoggingEmitError(f"failed to emit log event: {exc}") from exc


def shutdown_logger(name: str) -> None:
    """Idempotently remove and close a TGrid-owned handler.

    After this returns, the log file handle is released so the file can be
    moved or deleted on Windows.  The per-logger lock guarantees any in-flight
    ``emit`` has completed before the handler is closed (REV-G0T003-006).
    """
    lock = _get_logger_lock(name)
    with lock:
        logger = logging.getLogger(name)
        _drop_tgrid_handler(logger)
