#!/usr/bin/env python3
"""Offline check of file hashes and local Markdown links within the documentation kit."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
expected = {item["path"]: item["sha256"] for item in MANIFEST["files"]}
actual = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and p.name != "PACKAGE_MANIFEST.json"}
assert actual == set(expected), f"File list mismatch: missing={sorted(set(expected) - actual)} unexpected={sorted(actual - set(expected))}"

for path_str, digest in expected.items():
    file_path = ROOT / path_str
    actual_digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    assert digest == actual_digest, f"SHA256 mismatch: {path_str}"

# Links in Markdown; skip HTTP(s), fragment-only, and mailto.
for md in ROOT.rglob("*.md"):
    content = md.read_text(encoding="utf-8")
    for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", content):
        target = target.strip().split("#", 1)[0]
        if not target or target.startswith(("https://", "http://", "mailto:")):
            continue
        assert (md.parent / target).exists(), f"Broken local link: {md.relative_to(ROOT)} -> {target}"

print(f"PASS: {len(expected)} files verified by SHA-256; local Markdown links resolved")
