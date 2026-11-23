"""Version store: atomic diagram version snapshots on the filesystem.

Layout (docs/04 section 4):
    storage/diagrams/<diagram-id>/v000N/{graph.json, diagram.drawio, manifest.json[, patch.json]}

Transaction rules (docs/04 section 5):
  1. current_version is read and checked against the caller's baseVersion.
  2. All files are written to a temporary directory first; hashes are
     computed there.
  3. The directory is atomically renamed to its final version path, then the
     database advances current_version. If the DB step fails, the renamed
     directory is removed again (best-effort recovery, tested by V-03).
  4. Existing versions are never modified or overwritten.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.schemas.api import ApiException, ErrorCode
from app.storage.db import Database, VersionRow


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class VersionStore:
    def __init__(self, storage_root: Path, db: Database) -> None:
        self.root = storage_root
        self.db = db
        self.root.mkdir(parents=True, exist_ok=True)

    def diagram_dir(self, diagram_id: str) -> Path:
        return self.root / "diagrams" / diagram_id

    def version_dir(self, diagram_id: str, version: int) -> Path:
        return self.diagram_dir(diagram_id) / f"v{version:04d}"

    # ---- transactional write ----------------------------------------------

    def commit_new_version(
        self,
        diagram_id: str,
        diagram_name: str,
        diagram_type: str,
        graph: Dict[str, Any],
        drawio_bytes: bytes,
        origin: str,
        patch: Optional[Dict[str, Any]] = None,
        expected_base_version: Optional[int] = None,
        manifest_extra: Optional[Dict[str, Any]] = None,
    ) -> VersionRow:
        """Validate baseVersion, stage files, atomically publish a new version."""
        diagram = self.db.get_diagram(diagram_id)
        if diagram is None:
            raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
        current = diagram.current_version
        if expected_base_version is not None and expected_base_version != current:
            raise ApiException(
                ErrorCode.VERSION_CONFLICT,
                f"baseVersion {expected_base_version} does not match current version {current}",
                {"currentVersion": current, "baseVersion": expected_base_version},
            )
        parent_version = current if current > 0 else None
        next_version = current + 1

        staged = self.diagram_dir(diagram_id) / f".tmp-{uuid.uuid4().hex}"
        published = self.version_dir(diagram_id, next_version)
        published.parent.mkdir(parents=True, exist_ok=True)
        try:
            staged.mkdir(parents=True)
            graph_path = staged / "graph.json"
            drawio_path = staged / "diagram.drawio"
            graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
            drawio_path.write_bytes(drawio_bytes)
            graph_sha = sha256_file(graph_path)
            drawio_sha = sha256_file(drawio_path)
            manifest = {
                "schemaVersion": "1.0",
                "diagramId": diagram_id,
                "diagramName": diagram_name,
                "diagramType": diagram_type,
                "version": next_version,
                "parentVersion": parent_version,
                "origin": origin,
                "createdAt": utc_now(),
                "sha256": {
                    "graph.json": graph_sha,
                    "diagram.drawio": drawio_sha,
                },
            }
            patch_path: Optional[Path] = None
            if patch is not None:
                patch_path = staged / "patch.json"
                patch_path.write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
                manifest["patch.json"] = sha256_file(patch_path)
            if manifest_extra:
                manifest.update(manifest_extra)
            manifest_path = staged / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            # Atomic publish: rename(2) within the same filesystem.
            staged.rename(published)
        finally:
            shutil.rmtree(staged, ignore_errors=True)

        row = VersionRow(
            diagram_id=diagram_id,
            version=next_version,
            parent_version=parent_version,
            graph_path=str(published / "graph.json"),
            drawio_path=str(published / "diagram.drawio"),
            patch_path=str(patch_path) if patch_path else None,
            manifest_path=str(published / "manifest.json"),
            sha256=drawio_sha,
            origin=origin,
            created_at=manifest["createdAt"],
        )
        try:
            self.db.insert_version(row)
            advanced = self.db.set_current_version(diagram_id, next_version, row.created_at)
            if not advanced:
                raise ApiException(
                    ErrorCode.VERSION_CONFLICT,
                    f"concurrent update: diagram '{diagram_id}' already advanced beyond v{next_version}",
                    {"currentVersion": self.db.get_diagram(diagram_id).current_version},
                )
        except ApiException:
            self._recover(published)
            raise
        except Exception as exc:  # DB failure: recover the published directory.
            self._recover(published)
            raise ApiException(
                ErrorCode.INTERNAL_ERROR,
                f"failed to record version v{next_version}: {exc}",
            ) from exc
        return row

    def _recover(self, published: Path) -> None:
        """Remove a published-but-unrecorded version directory (V-03)."""
        shutil.rmtree(published, ignore_errors=True)

    # ---- reads --------------------------------------------------------------

    def read_graph(self, diagram_id: str, version: int) -> Dict[str, Any]:
        row = self.db.get_version(diagram_id, version)
        if row is None:
            raise ApiException(ErrorCode.VERSION_NOT_FOUND, f"diagram '{diagram_id}' has no version {version}")
        return json.loads(Path(row.graph_path).read_text(encoding="utf-8"))

    def read_drawio(self, diagram_id: str, version: int) -> Tuple[bytes, str]:
        row = self.db.get_version(diagram_id, version)
        if row is None:
            raise ApiException(ErrorCode.VERSION_NOT_FOUND, f"diagram '{diagram_id}' has no version {version}")
        return Path(row.drawio_path).read_bytes(), row.sha256

    def read_manifest(self, diagram_id: str, version: int) -> Dict[str, Any]:
        row = self.db.get_version(diagram_id, version)
        if row is None:
            raise ApiException(ErrorCode.VERSION_NOT_FOUND, f"diagram '{diagram_id}' has no version {version}")
        return json.loads(Path(row.manifest_path).read_text(encoding="utf-8"))
