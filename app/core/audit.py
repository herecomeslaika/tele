"""A2A_min_v1 Persistent Audit Logger — file-backed, queryable audit trail."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AuditEntry:
    session_id: str
    corr_id: str
    event: str
    timestamp: float = field(default_factory=time.time)
    model: Optional[str] = None
    provider: Optional[str] = None
    request_summary: Optional[dict] = None
    response_summary: Optional[dict] = None
    error_code: Optional[str] = None
    error_msg: Optional[str] = None
    duration_ms: Optional[float] = None
    trace_id: Optional[str] = None
    extra: dict = field(default_factory=dict)


@dataclass
class AuditLogger:
    """Persistent audit trail for gateway requests.

    Writes entries to a JSONL file on every record() call.
    On init, loads any existing JSONL files in log_dir to rebuild
    the in-memory index — enabling queries across restarts.
    """

    log_dir: str = "evidence/audit"
    _entries: list[AuditEntry] = field(default_factory=list)
    _file_path: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        os.makedirs(self.log_dir, exist_ok=True)
        self._file_path = os.path.join(
            self.log_dir, f"audit_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        )
        self._load_existing()

    def _load_existing(self) -> None:
        """Replay all existing JSONL audit files into the in-memory index."""
        for fname in sorted(os.listdir(self.log_dir)):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(self.log_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        entry = AuditEntry(
                            session_id=data.get("session_id", ""),
                            corr_id=data.get("corr_id", ""),
                            event=data.get("event", ""),
                            timestamp=data.get("timestamp", 0.0),
                            model=data.get("model"),
                            provider=data.get("provider"),
                            request_summary=data.get("request_summary"),
                            response_summary=data.get("response_summary"),
                            error_code=data.get("error_code"),
                            error_msg=data.get("error_msg"),
                            duration_ms=data.get("duration_ms"),
                            trace_id=data.get("trace_id"),
                            extra=data.get("extra", {}),
                        )
                        # Only load entries not already in memory (avoid duplicates)
                        if not any(
                            e.session_id == entry.session_id
                            and e.corr_id == entry.corr_id
                            and e.event == entry.event
                            and e.timestamp == entry.timestamp
                            for e in self._entries
                        ):
                            self._entries.append(entry)
            except (json.JSONDecodeError, OSError):
                continue

    def _serialize_entry(self, entry: AuditEntry) -> dict:
        return {k: v for k, v in entry.__dict__.items() if v is not None}

    def record(self, entry: AuditEntry) -> None:
        """Record an entry: append to in-memory list AND write to JSONL file."""
        self._entries.append(entry)
        line = json.dumps(self._serialize_entry(entry), default=str, ensure_ascii=False)
        with open(self._file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def query(self, session_id: Optional[str] = None,
              corr_id: Optional[str] = None,
              event: Optional[str] = None,
              start_time: Optional[float] = None,
              end_time: Optional[float] = None) -> list[AuditEntry]:
        """Flexible query: filter by any combination of fields."""
        results = self._entries
        if session_id is not None:
            results = [e for e in results if e.session_id == session_id]
        if corr_id is not None:
            results = [e for e in results if e.corr_id == corr_id]
        if event is not None:
            results = [e for e in results if e.event == event]
        if start_time is not None:
            results = [e for e in results if e.timestamp >= start_time]
        if end_time is not None:
            results = [e for e in results if e.timestamp <= end_time]
        return results

    def query_by_corr_id(self, corr_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.corr_id == corr_id]

    def query_by_session_id(self, session_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.session_id == session_id]

    def query_by_time_range(self, start: float, end: float) -> list[AuditEntry]:
        return [e for e in self._entries if start <= e.timestamp <= end]

    def export_all(self) -> list[dict]:
        return [self._serialize_entry(e) for e in self._entries]

    def export_to_file(self, path: str) -> str:
        """Export all entries to a standalone JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.export_all(), f, indent=2, ensure_ascii=False, default=str)
        return path

    def count(self) -> int:
        return len(self._entries)