"""Build the offline subset of drawio-mcp's official shape search index."""
import argparse
import hashlib
import json
import re
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1] / "renderer" / "assets" / "catalogs"
FAMILIES = {
    "cisco": "network", "cisco19": "network", "networks": "network", "networks2": "network",
    "rack": "rack", "rackGeneral": "rack", "aws4": "cloud", "azure": "cloud",
    "gcp3": "cloud", "kubernetes": "cloud",
}
NATIVE = re.compile(r"mxgraph\.[a-zA-Z0-9_.-]+\Z")


def catalog_entries(source):
    shapes = {}
    for row in source:
        parts = row["style"].strip(";").split(";")
        style = dict(part.split("=", 1) for part in parts if "=" in part)
        shape = style.get("shape", "")
        library = shape.split(".")[1] if NATIVE.fullmatch(shape) else None
        if row["type"] != "vertex" or library not in FAMILIES or not (row["w"] > 0 and row["h"] > 0):
            continue
        if any(re.search(r"[<>]|://|javascript:|data:|url\(", value, re.I) for value in style.values()):
            continue
        shape_id = shape.removeprefix("mxgraph.")
        variant = style.get("prIcon") or style.get("resIcon")
        if variant:
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", variant):
                continue
            shape_id += "--" + variant.removeprefix("mxgraph.")
        # The index can have multiple palette variants of a shape. Keep the
        # upstream first variant, with a stable ID independent of the title.
        shapes.setdefault(shape_id, {
            "id": shape_id, "name": row["title"], "category": FAMILIES[library],
            "library": library, "assetType": "stencil", "source": "drawio_builtin",
            "style": ";".join(parts) + ";", "nativeWidth": row["w"], "nativeHeight": row["h"],
            "defaultWidth": row["w"], "defaultHeight": row["h"], "preserveAspectRatio": True,
            "labelPosition": "bottom", "verified": True, "searchTags": row["tags"] or "",
        })
    return [shapes[shape_id] for shape_id in sorted(shapes)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="local download of the pinned upstream search-index.json")
    args = parser.parse_args()
    manifest = json.loads((DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    data = args.source.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["upstream"]["sha256"]:
        parser.error("source SHA-256 differs from the pinned upstream index")
    entries = catalog_entries(json.loads(data))
    output = ",\n".join(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) for entry in entries)
    (DIRECTORY / "drawio-search-index.json").write_text("[\n" + output + "\n]\n", encoding="utf-8")
    print(f"{len(entries)} native shape references")


if __name__ == "__main__":
    main()
