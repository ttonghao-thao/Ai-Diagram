"""SQLite metadata store (docs/04 section 4). File snapshots live on disk;
the database only tracks diagram/version/ai-job metadata. A single connection
with serialized access is sufficient for the single-node MVP.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagrams (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  name TEXT NOT NULL,
  diagram_type TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagram_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  diagram_id TEXT NOT NULL REFERENCES diagrams(id),
  version INTEGER NOT NULL,
  parent_version INTEGER,
  graph_path TEXT NOT NULL,
  drawio_path TEXT NOT NULL,
  patch_path TEXT,
  manifest_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(diagram_id, version)
);
CREATE TABLE IF NOT EXISTS ai_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  diagram_id TEXT,
  version INTEGER,
  request_type TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT,
  status TEXT NOT NULL,
  error_code TEXT,
  duration_ms INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_settings (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  version INTEGER NOT NULL,
  options_json TEXT NOT NULL,
  api_key_ciphertext BLOB
);
CREATE INDEX IF NOT EXISTS idx_versions_diagram ON diagram_versions(diagram_id, version);
"""


@dataclass
class DiagramRow:
    id: str
    project_id: str
    name: str
    diagram_type: str
    current_version: int
    created_at: str
    updated_at: str


@dataclass
class VersionRow:
    diagram_id: str
    version: int
    parent_version: Optional[int]
    graph_path: str
    drawio_path: str
    patch_path: Optional[str]
    manifest_path: str
    sha256: str
    origin: str
    created_at: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- diagrams ----------------------------------------------------------

    @staticmethod
    def _create_diagram(conn: sqlite3.Connection, diagram_id: str, name: str, diagram_type: str, created_at: str) -> None:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (diagram_id, name, created_at, created_at),
        )
        conn.execute(
            "INSERT INTO diagrams (id, project_id, name, diagram_type, current_version, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 0, ?, ?)",
            (diagram_id, diagram_id, name, diagram_type, created_at, created_at),
        )

    def get_diagram(self, diagram_id: str) -> Optional[DiagramRow]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM diagrams WHERE id = ?", (diagram_id,)).fetchone()
        return DiagramRow(**dict(row)) if row else None

    def list_diagrams(self) -> list[DiagramRow]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM diagrams ORDER BY updated_at DESC").fetchall()
        return [DiagramRow(**dict(r)) for r in rows]

    # ---- versions ----------------------------------------------------------

    def insert_version(self, row: VersionRow, *, new_diagram: Optional[tuple[str, str]] = None) -> None:
        with self.transaction() as conn:
            if new_diagram:
                self._create_diagram(conn, row.diagram_id, *new_diagram, row.created_at)
            current = row.parent_version or 0
            cur = conn.execute(
                "UPDATE diagrams SET current_version = ?, updated_at = ? WHERE id = ? AND current_version = ?",
                (row.version, row.created_at, row.diagram_id, current),
            )
            if cur.rowcount != 1:
                from app.schemas.api import ApiException, ErrorCode

                raise ApiException(ErrorCode.VERSION_CONFLICT, "diagram version changed during commit")
            conn.execute(
                "INSERT INTO diagram_versions (diagram_id, version, parent_version, graph_path, drawio_path,"
                " patch_path, manifest_path, sha256, origin, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    row.diagram_id, row.version, row.parent_version, row.graph_path, row.drawio_path,
                    row.patch_path, row.manifest_path, row.sha256, row.origin, row.created_at,
                ),
            )

    @staticmethod
    def _to_version_row(row: sqlite3.Row) -> VersionRow:
        data = {k: row[k] for k in row.keys() if k != "id"}  # drop the autoincrement pk
        return VersionRow(**data)

    def get_version(self, diagram_id: str, version: int) -> Optional[VersionRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM diagram_versions WHERE diagram_id = ? AND version = ?",
                (diagram_id, version),
            ).fetchone()
        return self._to_version_row(row) if row else None

    def get_latest_version(self, diagram_id: str) -> Optional[VersionRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM diagram_versions WHERE diagram_id = ? ORDER BY version DESC LIMIT 1",
                (diagram_id,),
            ).fetchone()
        return self._to_version_row(row) if row else None

    def list_versions(self, diagram_id: str) -> list[VersionRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM diagram_versions WHERE diagram_id = ? ORDER BY version",
                (diagram_id,),
            ).fetchall()
        return [self._to_version_row(r) for r in rows]

    # ---- ai jobs (metadata only; no raw prompt/topology text is stored) -----

    def record_ai_job(
        self, request_type: str, provider: str, model: Optional[str], status: str,
        error_code: Optional[str], duration_ms: int, diagram_id: Optional[str] = None, version: Optional[int] = None,
        created_at: str = "",
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO ai_jobs (diagram_id, version, request_type, provider, model, status, error_code,"
                " duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (diagram_id, version, request_type, provider, model, status, error_code, duration_ms, created_at),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
