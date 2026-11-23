"""Deployment regression guard (docs/09): the .dockerignore must never
exclude runtime code from the build context again.

Docker matches bare names (no leading slash) at ANY level; anchored names
(leading slash) match only from the context root. The first real container
deployment failed with ModuleNotFoundError because bare `storage` excluded
backend/app/storage/. This test implements the relevant matching rules and
asserts every runtime-critical file survives COPY."""
from __future__ import annotations

import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _docker_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Simplified dockerignore matching covering the rule shapes we use:
    bare names / globs match at any level; a leading slash anchors to the
    context root; ** matches any number of directories."""
    rel_path = rel_path.lstrip("/")
    ignored = False
    for raw in patterns:
        pattern = raw.strip()
        if not pattern or pattern.startswith("#"):
            continue
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        if not anchored and "/" not in pattern:
            # bare names match the file/dir itself anywhere, plus its subtree
            candidates = [pattern, pattern + "/**", "**/" + pattern, "**/" + pattern + "/**"]
        else:
            # anchored patterns exclude the whole subtree when it is a directory
            candidates = [pattern, pattern + "/**"]
        for cand in candidates:
            if fnmatch.fnmatch(rel_path, cand):
                ignored = True
                break
    return ignored


def test_dockerignore_keeps_all_runtime_files() -> None:
    patterns = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()

    runtime_files = [
        # backend application package (the one the first deploy lost)
        "backend/app/storage/versions.py",
        "backend/app/storage/db.py",
        "backend/app/main.py",
        "backend/app/api/diagrams.py",
        "backend/app/importer/xml_edit.py",
        "backend/app/llm/adapter.py",
        "backend/requirements.txt",
        # renderer + frontend build inputs and lockfiles
        "renderer/package.json",
        "renderer/package-lock.json",
        "renderer/src/cli.ts",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/src/App.tsx",
        # runtime assets and contracts (prompts read schemas at runtime)
        "renderer/assets/icons/README.md",
        "contracts/graph.schema.json",
        "contracts/patch.schema.json",
    ]
    for rel in runtime_files:
        assert (REPO / rel).is_file(), f"reference file missing in repo: {rel}"
        assert not _docker_ignored(rel, patterns), \
            f".dockerignore would exclude runtime file '{rel}' — the container " \
            "would crash with ModuleNotFoundError at startup"

    # The runtime-data directories themselves must STILL be excluded
    # (anchored to the context root).
    for rel in ["storage/studio.db", "out/network.drawio", "data/anything.txt"]:
        assert _docker_ignored(rel, patterns), f"'{rel}' should stay excluded"
