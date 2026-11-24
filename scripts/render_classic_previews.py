"""Render catalog previews with the pinned offline draw.io viewer and Chrome."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "renderer/assets"
BASE = "http://127.0.0.1:21824"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drawing(entry: dict) -> str:
    mxfile = ET.Element("mxfile", {"compressed": "false"})
    diagram = ET.SubElement(mxfile, "diagram", {"id": "preview", "name": "Preview"})
    model = ET.SubElement(diagram, "mxGraphModel", {"page": "0"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    cell = ET.SubElement(root, "mxCell", {"id": "2", "parent": "1", "vertex": "1", "style": entry["style"]})
    scale = 80 / max(entry["nativeWidth"], entry["nativeHeight"])
    ET.SubElement(cell, "mxGeometry", {"x": "0", "y": "0", "width": str(entry["nativeWidth"] * scale),
                                      "height": str(entry["nativeHeight"] * scale), "as": "geometry"})
    return ET.tostring(mxfile, encoding="unicode")


def render(viewer: Path, stencils: Path, chrome: str):
    catalog = ASSETS / "catalogs"
    manifest = json.loads((catalog / "manifest.json").read_text())
    if sha256(viewer) != manifest["classicPreview"]["viewerSha256"]:
        raise SystemExit("viewer digest differs from the catalog manifest")
    files = {}
    for name, digest in manifest["classicStencilSha256"].items():
        file = stencils / name
        if sha256(file) != digest:
            raise SystemExit(f"stencil digest differs: {name}")
        files[f"/stencils/cisco/{name}"] = file

    entries = json.loads((catalog / "network.json").read_text())
    tiles = []
    for index, entry in enumerate(entries):
        config = {"xml": drawing(entry), "nav": False, "resize": True, "zoom": False, "toolbar": ""}
        tiles.append(f'<div class="mxgraph" id="tile-{index}" data-mxgraph="{html.escape(json.dumps(config), quote=True)}"></div>')
    page_html = (
        '<!doctype html><meta charset="utf-8"><style>body{margin:0;display:grid;grid-template-columns:repeat(4,116px);'
        'gap:16px;background:white;padding:8px}.mxgraph{min-width:94px;min-height:94px}</style>'
        + "".join(tiles) + '<script>window.STENCIL_PATH="/stencils";window.STYLE_PATH="/styles";</script>'
        '<script src="/viewer-static.min.js"></script>'
    )
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        page = browser.new_page(viewport={"width": 600, "height": 440})
        page.on("pageerror", lambda error: failures.append(str(error)))

        def route(request):
            url = request.request.url
            if url == BASE + "/":
                request.fulfill(status=200, content_type="text/html", body=page_html)
            elif url == BASE + "/viewer-static.min.js":
                request.fulfill(status=200, content_type="text/javascript", path=viewer)
            elif url.startswith(BASE) and url[len(BASE):] in files:
                request.fulfill(status=200, content_type="application/xml", path=files[url[len(BASE):]])
            else:
                request.abort()

        page.route("**/*", route)
        page.goto(BASE + "/", wait_until="networkidle")
        output = ASSETS / "previews"
        output.mkdir(exist_ok=True)
        for index, entry in enumerate(entries):
            tile = page.locator(f"#tile-{index}")
            if not tile.locator("svg path, svg ellipse, svg polygon").count():
                raise RuntimeError(f"native preview did not render: {entry['id']}")
            tile.screenshot(path=output / f"{entry['id']}.png", animations="disabled")
        if failures:
            raise RuntimeError(failures)
        browser.close()
    print(f"{len(entries)} native Cisco previews")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer", type=Path, required=True)
    parser.add_argument("--stencils", type=Path, required=True)
    parser.add_argument("--chrome", required=True)
    args = parser.parse_args()
    render(args.viewer, args.stencils, args.chrome)
