"""Offline CLI entry point and deterministic startup/shutdown orchestration.

This module composes the already-accepted configuration, SQLite, and JSONL
logging foundations into a read-only preflight flow.  It has no QMT, market
data, account, order, or trading capability (Gate 0).

Exit codes (stable contract):

    0    preflight success, or --help/--version
    1    controlled failure (config / logging / database / lifecycle)
    2    argparse usage error
    130  KeyboardInterrupt
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence

from tgrid import __version__
from tgrid import (
    configure_jsonl_logger,
    emit,
    initialize_database,
    load_config,
    shutdown_logger,
)
from tgrid.risk.exceptions import ConfigError, TGridError

LOGGER_NAME = "tgrid.preflight"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_INTERRUPT = 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tgrid",
        description="TGrid offline preflight (Gate 0): validate config and local resources "
        "without QMT, market data, or trading.",
    )
    parser.add_argument(
        "--version", action="store_true", help="print version and exit"
    )
    subparsers = parser.add_subparsers(dest="command")

    preflight = subparsers.add_parser(
        "preflight",
        help="validate config, database and logging resources (read-only; no trading)",
    )
    preflight.add_argument(
        "--config", required=True, help="path to the YAML configuration file (read-only)"
    )
    preflight.add_argument(
        "--database", required=True, help="path to the SQLite database file"
    )
    preflight.add_argument(
        "--log", required=True, help="path to the JSONL log file"
    )
    return parser


def _canonical(path: str) -> str:
    """Normalize a path for identity comparison (case-insensitive on Windows)."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _validate_distinct_paths(
    config_path: str, database_path: str, log_path: str
) -> None:
    """Reject any two of the three paths that resolve to the same location."""
    seen = {}
    for label, path in (
        ("config", config_path),
        ("database", database_path),
        ("log", log_path),
    ):
        canonical = _canonical(path)
        for other_label, other_canonical in seen.items():
            if canonical == other_canonical:
                raise ConfigError(
                    f"{label} path and {other_label} path resolve to the same "
                    f"location: {path}"
                )
        seen[label] = canonical


def _safe_message(exc: BaseException) -> str:
    """Return a stable, non-sensitive message for user-facing output.

    TGrid errors carry module-controlled, safe text (including field paths).
    Any other exception (RuntimeError, OSError, unknown) may embed secrets or
    paths, so only its type name is reported (REV-G0T004-004).
    """
    if isinstance(exc, TGridError):
        return str(exc)
    return type(exc).__name__


def _print_primary_error(exc: BaseException) -> None:
    print(f"tgrid: error: {_safe_message(exc)}", file=sys.stderr)


def _print_cleanup_error(exc: BaseException) -> None:
    print(f"tgrid: cleanup error: {_safe_message(exc)}", file=sys.stderr)


def _record_cleanup(current: Optional[BaseException], exc: BaseException) -> BaseException:
    """Keep the first cleanup failure; later ones are secondary."""
    return current if current is not None else exc


def _run_preflight(args: argparse.Namespace) -> int:
    """Run the preflight flow with explicit, deterministic resource cleanup."""
    _validate_distinct_paths(args.config, args.database, args.log)

    config = load_config(args.config)
    if config.global_config.live_trading:
        raise ConfigError(
            "live_trading must be false for preflight", "global.live_trading"
        )

    logger = configure_jsonl_logger(LOGGER_NAME, args.log)

    db_conn = None
    primary: Optional[BaseException] = None
    interrupted = False
    cleanup: Optional[BaseException] = None
    db_closed_ok = True
    startup_clean = False

    def _close_db() -> None:
        """Close the DB exactly once, even after a BaseException in the startup
        or failure-event emits.  A close failure is recorded and prevents a
        bogus shutdown_complete (REV-G0T004-001/-005)."""
        nonlocal db_conn, interrupted, cleanup, db_closed_ok
        if db_conn is None:
            return
        try:
            db_conn.close()
        except KeyboardInterrupt:
            interrupted = True
            db_closed_ok = False
        except Exception as exc:  # noqa: BLE001
            cleanup = _record_cleanup(cleanup, exc)
            db_closed_ok = False
        finally:
            db_conn = None

    try:
        # Startup phase (logger already established).  SystemExit / GeneratorExit
        # raised here are not caught and will propagate after cleanup (REV-G0T004-005).
        try:
            emit(logger, "startup_begin", "preflight starting")
            db_conn = initialize_database(args.database)
            emit(logger, "preflight_ok", "preflight passed")
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:  # noqa: BLE001 - controlled boundary
            primary = exc

        # Best-effort stable failure event (never masks the primary failure).
        if primary is not None or interrupted:
            error_type = "KeyboardInterrupt" if interrupted else type(primary).__name__
            try:
                emit(
                    logger,
                    "preflight_failed",
                    "preflight failed",
                    context={"error_type": error_type},
                )
            except KeyboardInterrupt:
                interrupted = True
            except Exception:  # noqa: BLE001 - already failing; best-effort
                pass

        # Reaching here with no uncaught BaseException marks the clean startup
        # path; a SystemExit/GeneratorExit above would have skipped this line.
        startup_clean = True
    finally:
        try:
            # DB close must be non-skippable (finally), covering startup and
            # failure emits.  A BaseException from _close_db or the shutdown
            # emit below must not skip logger shutdown (REV-G0T004-006).
            _close_db()

            # Emit shutdown_complete only on a fully clean path: no primary
            # failure, no interrupt, no cleanup failure, DB actually closed, and
            # startup completed without an uncaught BaseException.
            if startup_clean and primary is None and not interrupted and cleanup is None and db_closed_ok:
                try:
                    emit(logger, "shutdown_complete", "preflight finished")
                except KeyboardInterrupt:
                    interrupted = True
                except Exception as exc:  # noqa: BLE001
                    primary = exc
        finally:
            # Logger shutdown must always be attempted — even if DB close or the
            # shutdown emit raised SystemExit/GeneratorExit — because it lives in
            # the outermost finally of the cleanup path (REV-G0T004-006).
            try:
                shutdown_logger(LOGGER_NAME)
            except Exception as exc:  # noqa: BLE001
                cleanup = _record_cleanup(cleanup, exc)

    if interrupted:
        if cleanup is not None:
            _print_cleanup_error(cleanup)
        return EXIT_INTERRUPT
    if primary is not None:
        _print_primary_error(primary)
        if cleanup is not None:
            _print_cleanup_error(cleanup)
        return EXIT_FAILURE
    if cleanup is not None:
        _print_primary_error(cleanup)
        return EXIT_FAILURE
    print("preflight ok")
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.  Returns a stable exit code; never emits a traceback.

    Unknown exceptions are converted to exit 1 without leaking their raw text;
    ``SystemExit``/``GeneratorExit`` are not swallowed (REV-G0T004-003/-004).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"tgrid {__version__}")
        return EXIT_OK

    if args.command != "preflight":
        parser.print_usage(sys.stderr)
        return EXIT_USAGE

    try:
        return _run_preflight(args)
    except KeyboardInterrupt:
        print("tgrid: interrupted", file=sys.stderr)
        return EXIT_INTERRUPT
    except TGridError as exc:
        _print_primary_error(exc)
        return EXIT_FAILURE
    except Exception as exc:  # noqa: BLE001 - unknown exception boundary
        _print_primary_error(exc)
        return EXIT_FAILURE
