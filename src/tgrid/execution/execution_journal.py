"""Durable execution journal — ported from reverse_repo AtomicJournal.

Ports ``reverse_repo/repo_execution_core.py`` AtomicJournal semantics
(pinned c9ecc70): every external side effect (submit/cancel) is preceded by a
durable journal transition written with a temp-file + fsync + os.replace
atomic replace, so a crash never leaves a half-written JSON and a restart can
reconstruct the machine state from the last committed snapshot.

* schema_version=2 with strategy/trade_date triple validation — a mismatched
  journal requires manual review and is never auto-rebuilt;
* ``transition`` appends a sequenced history record (kept at most 500) and
  atomically writes the machine payload + data updates;
* the journal payload is bound to the state-machine transition spec and the
  execution source (``journal_matches_verification``), so a code change
  invalidates old journals — they are no longer trusted.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tgrid.risk.exceptions import TGridError


class ExecutionJournalError(TGridError):
    """Base class for execution journal failures."""


class JournalSchemaError(ExecutionJournalError):
    """The journal schema/strategy/trade_date does not match; manual review."""


class JournalIntegrityError(ExecutionJournalError):
    """The journal content is corrupt or bound hashes do not match."""


JOURNAL_SCHEMA_VERSION = 2
MAX_HISTORY = 500


@dataclass(frozen=True)
class JournalVerification:
    """The hashes a journal payload is bound to (reverse_repo semantics)."""

    transition_spec_sha256: str
    execution_source_sha256: str


class ExecutionJournal:
    """Atomically-persisted machine journal (strategy + trade_date bound)."""

    def __init__(
        self,
        path: object,
        *,
        strategy: str,
        trade_date: str,
    ) -> None:
        if type(strategy) is not str or not strategy:
            raise ExecutionJournalError("strategy must be a non-empty string")
        if type(trade_date) is not str or not trade_date:
            raise ExecutionJournalError("trade_date must be a non-empty string")
        self.path = Path(path)
        self.strategy = strategy
        self.trade_date = trade_date
        self.payload: dict = {}
        self._exists = False
        self.load_or_initialize()

    @property
    def machine(self) -> dict:
        return dict(self.payload.get("machine") or {})

    @property
    def data(self) -> dict:
        return dict(self.payload.get("data") or {})

    def load_or_initialize(self) -> tuple[dict, bool]:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise JournalIntegrityError(
                    "execution journal is unreadable"
                ) from exc
            if not isinstance(payload, dict):
                raise JournalSchemaError(
                    "execution journal must be a JSON object"
                )
            if int(payload.get("schema_version", -1)) != JOURNAL_SCHEMA_VERSION:
                raise JournalSchemaError(
                    "unexpected execution journal schema; manual review required"
                )
            if payload.get("strategy") != self.strategy:
                raise JournalSchemaError(
                    "execution journal strategy mismatch; manual review required"
                )
            if payload.get("trade_date") != self.trade_date:
                raise JournalSchemaError(
                    "execution journal trade_date mismatch; manual review required"
                )
            self.payload = payload
            self._exists = True
            return payload, True
        self.payload = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "strategy": self.strategy,
            "trade_date": self.trade_date,
            "created_at": datetime.now().astimezone().isoformat(),
            "updated_at": datetime.now().astimezone().isoformat(),
            "event_count": 0,
            "machine": {},
            "history": [],
            "data": {},
        }
        self.write()
        self._exists = False
        return self.payload, False

    def transition(
        self,
        event: object,
        machine_payload: Mapping,
        *,
        details: Mapping | None = None,
        data_updates: Mapping | None = None,
    ) -> dict:
        """Atomically record one machine transition (reverse_repo semantics)."""
        record = {
            "sequence": int(self.payload.get("event_count", 0)) + 1,
            "at": datetime.now().astimezone().isoformat(),
            "event": str(getattr(event, "value", event)),
            "state": str(machine_payload.get("state") or ""),
            "details": dict(details or {}),
        }
        history = list(self.payload.get("history") or [])
        history.append(record)
        self.payload["history"] = history[-MAX_HISTORY:]
        self.payload["event_count"] = record["sequence"]
        self.payload["machine"] = dict(machine_payload)
        if data_updates:
            data = dict(self.payload.get("data") or {})
            data.update(dict(data_updates))
            self.payload["data"] = data
        self.payload["updated_at"] = record["at"]
        self.write()
        return record

    def update_data(self, **updates) -> None:
        data = dict(self.payload.get("data") or {})
        data.update(updates)
        self.payload["data"] = data
        self.payload["updated_at"] = datetime.now().astimezone().isoformat()
        self.write()

    def write(self) -> None:
        self._atomic_write_json(self.payload)

    def _atomic_write_json(self, payload: dict) -> None:
        """temp + fsync + os.replace (never a half-written journal)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False,
                          indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(20):
                try:
                    os.replace(temporary, self.path)
                    return
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.05)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def journal_matches_verification(
        self,
        verification: JournalVerification,
    ) -> bool:
        """True when this journal's bound hashes equal the current code's."""
        formal = self.payload.get("data", {}).get("formal_verification")
        if not isinstance(formal, dict):
            return False
        return (
            formal.get("transition_spec_sha256") == verification.transition_spec_sha256
            and formal.get("execution_source_sha256") == verification.execution_source_sha256
        )

    def bind_verification(self, verification: JournalVerification) -> None:
        self.update_data(formal_verification={
            "transition_spec_sha256": verification.transition_spec_sha256,
            "execution_source_sha256": verification.execution_source_sha256,
        })
