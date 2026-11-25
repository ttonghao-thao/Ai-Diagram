"""Deployment regression guard (docs/09): the .dockerignore must never
exclude runtime code from the build context again.

History: the first real deployment crashed with ModuleNotFoundError because
bare `storage` excluded backend/app/storage/, and a leading-slash anchor did
NOT fix it (older Docker versions strip the slash before matching). The final
rule: .dockerignore may only contain pattern shapes that cannot hit code
paths (`**/<name>` for tool dirs, `*.ext` for file suffixes) — NO directory
name exclusions at all. This test enforces both the outcome and the rule.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _docker_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Simplified dockerignore matching for the rule shapes we allow:
    `**/<glob>` (any level) and `*.ext` (suffix at any level)."""
    rel_path = rel_path.lstrip("/")
    for raw in patterns:
        pattern = raw.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, "**/" + pattern):
            return True
    return False


def test_dockerignore_keeps_all_runtime_files() -> None:
    patterns = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()

    runtime_files = [
        # backend application package (the one the first deploy lost)
        "backend/app/storage/versions.py",
        "backend/app/storage/db.py",
        "backend/app/main.py",
        "backend/app/api/diagrams.py",
        "backend/app/api/imports.py",
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


def test_dockerignore_never_excludes_directories_by_name() -> None:
    """The root cause of the first deploy failure was a directory-name
    exclusion (bare or /-anchored). Such patterns are forbidden: only
    **/<glob> and *.ext shapes may appear."""
    for raw in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines():
        pattern = raw.strip()
        if not pattern or pattern.startswith("#"):
            continue
        # Allowed shapes: **/<glob>, *.ext, and dot-prefixed files/dirs
        # (.git, .env ...) — the repo has no dot-prefixed code paths, so they
        # can never collide with application packages. Bare names like
        # `storage`/`out`/`data` are FORBIDDEN (the original deploy failure).
        assert pattern.startswith("**/") or pattern.startswith("*.") or pattern.startswith("."), \
            f"unsafe .dockerignore pattern '{pattern}': bare directory-name exclusions " \
            "match at any level and can hit code packages; use **/<tool-dir> or *.ext shapes"
    assert "*.db" in (REPO / ".dockerignore").read_text(encoding="utf-8")


def test_dockerignore_keeps_every_runtime_tracked_file() -> None:
    """Strongest outcome check: sweep every git-tracked file under the
    runtime-critical prefixes (backend/renderer/frontend/contracts) through
    the matcher. Excluding non-runtime files (.gitignore, docs, ...) is fine."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert len(tracked) > 80, "git ls-files returned an implausible list"
    prefixes = ("backend/", "renderer/", "frontend/", "contracts/")
    runtime = [f for f in tracked if f.startswith(prefixes)]
    assert len(runtime) > 60, f"implausible runtime file list: {len(runtime)}"
    patterns = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    bad = [f for f in runtime if _docker_ignored(f, patterns)]
    assert not bad, f".dockerignore would exclude runtime files: {bad[:20]}"


def test_runtime_data_db_files_stay_out_of_context() -> None:
    """storage/studio.db is excluded from the build context via the *.db
    suffix rule; the storage DIRECTORY stays in the context harmlessly (the
    container reads/writes only STORAGE_ROOT, which points at the volume)."""
    patterns = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert _docker_ignored("storage/studio.db", patterns)
    assert not _docker_ignored("storage/diagrams/demo/v0001/graph.json", patterns)  # harmless
    # git still ignores runtime data (separate .gitignore responsibility).
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "storage/" in gitignore and "*.db" in gitignore


def test_git_tracks_all_runtime_packages() -> None:
    """Second deploy killer (docs/11 B-2): bare `storage/` in .gitignore
    silently excluded the backend/app/storage Python package from git, so
    servers cloned from GitHub never received it. Guard: every runtime
    package file must be git-tracked."""
    import subprocess

    must_be_tracked = [
        "backend/app/__init__.py",
        "backend/app/api/__init__.py",
        "backend/app/storage/__init__.py",
        "backend/app/storage/db.py",
        "backend/app/storage/versions.py",
        "backend/app/llm/__init__.py",
        "backend/app/services/__init__.py",
        "backend/app/importer/__init__.py",
    ]
    tracked = set(subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines())
    for rel in must_be_tracked:
        assert (REPO / rel).is_file(), f"missing on disk: {rel}"
        assert rel in tracked, (
            f"'{rel}' is NOT committed to git — check .gitignore for bare "
            "directory names (they match at any level in git too)!"
        )
    # gitignore must never again contain bare runtime-data dir names.
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    for line in gitignore.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.rstrip("/") in ("storage", "data", "out"):
            assert line.startswith("/"), f".gitignore has unanchored dir name: '{line}'"
