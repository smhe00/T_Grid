"""TGrid reporting (Gate 0 foundation).

Provides structured JSONL logging with explicit lifecycle management.
"""

from tgrid.reporting.logging import (
    SCHEMA_VERSION,
    JsonlFormatter,
    configure_jsonl_logger,
    emit,
    shutdown_logger,
)

__all__ = [
    "SCHEMA_VERSION",
    "JsonlFormatter",
    "configure_jsonl_logger",
    "emit",
    "shutdown_logger",
]
