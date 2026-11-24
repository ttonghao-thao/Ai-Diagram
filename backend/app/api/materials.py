"""Catalog, themes, and material preferences for the single-instance workbench."""
from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.api.envelope import ok
from app.api.imports import _read_upload_limited
from app.schemas.api import ApiException, ErrorCode
from app.services.materials import ASSETS, LIBRARY_MAX_BYTES, SVG_MAX_BYTES, device_aliases, theme_catalog

router = APIRouter(prefix="/api/v1")


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mappings: Optional[Dict[str, str]] = Field(default=None, max_length=100)
    favorites: Optional[List[str]] = Field(default=None, max_length=300)


class ExportRequest(BaseModel):
    ids: List[str] = Field(min_length=1, max_length=100)


class ExtractRequest(BaseModel):
    diagramId: str
    version: int = Field(ge=1)
    cellId: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)


@router.get("/shapes/search")
def search(
    request: Request, q: str = Query(default="", max_length=160), library: str = Query(default="", max_length=32),
    favorite: bool = False, offset: int = Query(default=0, ge=0), limit: int = Query(default=40, ge=1, le=100),
):
    return ok(request, request.app.state.materials.search(q, library, favorite, offset, limit))


@router.post("/shapes/import")
async def import_material(
    request: Request, file: UploadFile = File(...), kind: Literal["svg", "library", "drawio"] = Form(...),
    name: Optional[str] = Form(default=None, max_length=200), cellId: str = Form(default="", max_length=120),
):
    data = await _read_upload_limited(file, SVG_MAX_BYTES if kind == "svg" else LIBRARY_MAX_BYTES)
    material_name = name or (file.filename or "素材").rsplit(".", 1)[0]
    items = await run_in_threadpool(request.app.state.materials.import_file, data, material_name, kind, cellId)
    return ok(request, {"items": items})


@router.post("/shapes/extract")
def extract(request: Request, body: ExtractRequest):
    state = request.app.state
    xml, _ = state.version_store.read_drawio(body.diagramId, body.version)
    items = state.materials.import_file(xml, body.name, "drawio", body.cellId)
    return ok(request, {"items": items})


def _shape_xml(item: dict) -> str:
    if item.get("xml"):
        return item["xml"]
    model = ET.Element("mxGraphModel")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    node = ET.SubElement(root, "mxCell", {"id": "2", "parent": "1", "vertex": "1", "style": item["style"]})
    ET.SubElement(node, "mxGeometry", {
        "x": "40", "y": "40", "width": str(item["defaultWidth"]), "height": str(item["defaultHeight"]),
        "as": "geometry",
    })
    return ET.tostring(model, encoding="unicode")


@router.post("/shapes/export")
def export_materials(request: Request, body: ExportRequest):
    entries = []
    for id_ in dict.fromkeys(body.ids):
        item = request.app.state.materials.get(id_)
        record = {"title": item.get("nameZh", item["name"]), "w": item["defaultWidth"], "h": item["defaultHeight"]}
        if item.get("svg"):
            encoded = base64.b64encode(item["svg"].encode()).decode("ascii")
            record["data"] = "data:image/svg+xml;base64," + encoded
        else:
            record["xml"] = _shape_xml(item)
        entries.append(record)
    library = ET.Element("mxlibrary")
    library.text = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    data = ET.tostring(library, encoding="utf-8")
    if len(data) > LIBRARY_MAX_BYTES:
        raise ApiException(ErrorCode.DRAWIO_UPLOAD_TOO_LARGE, "导出的素材库超过 2 MiB")
    return Response(data, media_type="application/xml", headers={
        "Content-Disposition": 'attachment; filename="materials.xml"', "X-Content-Type-Options": "nosniff",
    })


@router.get("/shapes/{shape_id}/preview")
def preview_material(request: Request, shape_id: str):
    item = request.app.state.materials.get(shape_id)
    if item.get("svg"):
        return Response(item["svg"], media_type="image/svg+xml", headers={
            "Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff",
        })
    mxfile = ET.Element("mxfile", {"compressed": "false"})
    page = ET.SubElement(mxfile, "diagram", {"id": "preview", "name": "Preview"})
    page.append(ET.fromstring(_shape_xml(item)))
    return Response(ET.tostring(mxfile, encoding="utf-8"), media_type="application/xml", headers={
        "Content-Disposition": 'attachment; filename="preview.drawio"', "X-Content-Type-Options": "nosniff",
    })


@router.get("/shapes/{shape_id}/thumbnail")
def thumbnail(request: Request, shape_id: str):
    item = request.app.state.materials.get(shape_id)
    file = ASSETS / "previews" / f"{item['id']}.png"
    if not file.is_file():
        raise ApiException(ErrorCode.MATERIAL_NOT_FOUND, "此素材提供原生图纸预览")
    return FileResponse(file, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/shapes/{shape_id}")
def get_shape(request: Request, shape_id: str):
    item = request.app.state.materials.get(shape_id)
    return ok(request, item | {"thumbnail": (ASSETS / "previews" / f"{item['id']}.png").is_file()})


@router.get("/themes")
def themes(request: Request):
    return ok(request, {"themes": list(theme_catalog().values())})


@router.get("/themes/{theme_id}")
def get_theme(request: Request, theme_id: str):
    theme = theme_catalog().get(theme_id)
    if theme is None:
        raise ApiException(ErrorCode.MATERIAL_NOT_FOUND, "主题不存在")
    return ok(request, theme)


@router.get("/preferences/shapes")
def preferences(request: Request):
    prefs = request.app.state.materials.preferences()
    return ok(request, {"mappings": {}, "favorites": [], **prefs, "deviceTypes": list(device_aliases())})


@router.put("/preferences/shapes")
def update_preferences(request: Request, body: Preferences):
    prefs = request.app.state.materials.set_preferences(body.model_dump(exclude_none=True))
    return ok(request, {"mappings": {}, "favorites": [], **prefs, "deviceTypes": list(device_aliases())})
