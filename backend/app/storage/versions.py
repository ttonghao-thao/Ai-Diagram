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

import errno
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
        visual_state: Optional[Dict[str, Any]] = None,
        quality: Optional[Dict[str, Any]] = None,
        source_drawio: Optional[bytes] = None,
    ) -> VersionRow:
        """Validate baseVersion, stage files, atomically publish a new version."""
        diagram = self.db.get_diagram(diagram_id)
        if diagram is None and origin != "initial":
            raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
        if diagram is not None and origin == "initial" and diagram.current_version:
            raise ApiException(ErrorCode.DIAGRAM_ALREADY_EXISTS, f"diagram '{diagram_id}' already exists")
        current = diagram.current_version if diagram is not None else 0
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
            for filename, data in (("visual-state.json", visual_state), ("quality.json", quality)):
                if data is not None:
                    target = staged / filename
                    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    manifest["sha256"][filename] = sha256_file(target)
            if source_drawio is not None:
                source_file = staged / "source.drawio"
                source_file.write_bytes(source_drawio)
                manifest["sha256"]["source.drawio"] = sha256_file(source_file)
            if manifest_extra:
                manifest.update(manifest_extra)
            manifest_path = staged / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            # Atomic publish: rename(2) within the same filesystem.
            try:
                staged.rename(published)
            except OSError as exc:
                if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
                    raise ApiException(ErrorCode.VERSION_CONFLICT, "another request is committing this version") from exc
                raise
        finally:
            shutil.rmtree(staged, ignore_errors=True)

        row = VersionRow(
            diagram_id=diagram_id,
            version=next_version,
            parent_version=parent_version,
            graph_path=str(published / "graph.json"),
            drawio_path=str(published / "diagram.drawio"),
            patch_path=str(published / "patch.json") if patch_path else None,
            manifest_path=str(published / "manifest.json"),
            sha256=drawio_sha,
            origin=origin,
            created_at=manifest["createdAt"],
        )
        try:
            if diagram is None:
                self.db.insert_version(row, new_diagram=(diagram_name, diagram_type))
            else:
                self.db.insert_version(row)
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

    def read_artifact(self, diagram_id: str, version: int, name: str) -> Optional[Dict[str, Any]]:
        if name not in {"visual-state", "quality"}:
            raise ValueError("unknown version artifact")
        manifest = self.read_manifest(diagram_id, version)
        filename = f"{name}.json"
        if filename not in manifest["sha256"]:
            return None
        path = self.version_dir(diagram_id, version) / filename
        return json.loads(path.read_text(encoding="utf-8"))
