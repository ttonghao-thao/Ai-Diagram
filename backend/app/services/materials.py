"""Offline native catalog and a persistent material library for the workbench."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from app.config import REPO_ROOT
from app.importer.model_map import parse_style
from app.importer.xml_parser import decompress_diagram_content, guard_no_dtd, parse_drawio_bytes
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument

ASSETS = REPO_ROOT / "renderer" / "assets"
SVG_MAX_BYTES = 64 * 1024
LIBRARY_MAX_BYTES = 2 * 1024 * 1024
SVG_NS = "http://www.w3.org/2000/svg"
SVG_ELEMENTS = {
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "title", "desc", "clipPath", "mask", "linearGradient", "radialGradient",
    "stop", "pattern", "symbol", "use", "marker",
}
BUILTIN_SHAPES = {"", "rectangle", "ellipse", "rhombus", "process", "cylinder3", "hexagon", "cloud", "swimlane", "image"}
BAD_VALUE = re.compile(r"(?:https?:|data:|file:|javascript:|url\s*\((?!#[\w.-]+\s*\)))", re.I)
NUMBER = re.compile(r"(?:\d+(?:\.\d+)?|\.\d+)(?:px)?\Z")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def bundled_shapes() -> dict:
    catalog = ASSETS / "catalogs"
    index = {shape["id"]: shape for shape in _json(catalog / "drawio-search-index.json")}
    for item in _json(catalog / "network.json"):
        index[item["id"]].update(item)
    return index


@lru_cache(maxsize=1)
def theme_catalog() -> dict:
    return {path.stem: _json(path) for path in sorted((ASSETS / "themes").glob("*.json"))}


@lru_cache(maxsize=1)
def device_aliases() -> dict:
    return _json(ASSETS / "catalogs" / "device-aliases.json")


@lru_cache(maxsize=1)
def catalog_version() -> str:
    return _json(ASSETS / "catalogs" / "manifest.json")["version"]


def _key(value: str) -> str:
    return re.sub(r"[\s-]+", "_", unicodedata.normalize("NFKC", value).strip().lower())


@lru_cache(maxsize=1)
def alias_lookup() -> dict:
    return {_key(alias): name for name, entry in device_aliases().items() for alias in (name, *entry["aliases"])}


def normalize_devices(doc: GraphDocument) -> None:
    for node in doc.nodes:
        raw = node.properties.get("deviceType")
        if isinstance(raw, str) and raw.strip():
            device = alias_lookup().get(_key(raw))
            if raw != device:
                node.properties.setdefault("deviceTypeRaw", raw)
            if device:
                node.properties["deviceType"] = device
        else:
            device = alias_lookup().get(re.sub(r"_?\d+$", "", _key(node.label)))
            if device and device != node.kind:
                node.properties["deviceType"] = device
        if device and "networkRole" not in node.properties:
            role = device_aliases()[device].get("role")
            if role:
                node.properties["networkRole"] = role
        if node.properties.get("networkRole") is None:
            for pattern, role in (
                (r"^(公网|外网|internet|wan)(\s*\d+)?$", "internet"),
                (r"边界防火墙|出口防火墙|perimeter.*firewall", "perimeter_security"),
                (r"服务器区防火墙|内部防火墙|internal.*firewall|server.*firewall", "internal_security"),
            ):
                if re.search(pattern, node.label.strip(), re.I):
                    node.properties["networkRole"] = role
                    break


def _invalid(message: str):
    raise ApiException(ErrorCode.DRAWIO_UNSUPPORTED_CONTENT, message)


def _parse_xml(data: bytes, limit: int) -> ET.Element:
    guard_no_dtd(data, limit)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "素材 XML 解析失败") from exc


def svg_dimensions(data: bytes) -> tuple[float, float]:
    root = _parse_xml(data, SVG_MAX_BYTES)
    if root.tag not in ("svg", f"{{{SVG_NS}}}svg"):
        _invalid("上传文件必须是 SVG")
    for element in root.iter():
        if element.tag.removeprefix(f"{{{SVG_NS}}}") not in SVG_ELEMENTS:
            _invalid("SVG 含有不支持的元素")
        for attr, value in element.attrib.items():
            key = attr.rsplit("}", 1)[-1].lower()
            if key.startswith("on") or key in {"style", "base", "src"} or BAD_VALUE.search(value) or (
                key == "href" and not re.fullmatch(r"#[\w.-]+", value)
            ):
                _invalid("SVG 含有事件、可执行样式或外部引用")
    viewbox = re.split(r"[\s,]+", root.get("viewBox", "").strip())
    try:
        if len(viewbox) == 4:
            _, _, width, height = map(float, viewbox)
        else:
            width, height = (float(value.removesuffix("px")) if NUMBER.fullmatch(value) else 0
                             for value in (root.get("width", ""), root.get("height", "")))
    except ValueError:
        width = height = 0
    if not (0 < width < 1e6 and 0 < height < 1e6 and 1e-4 < width / height < 1e4):
        return 100, 80
    return width, height


def _record(data: bytes, name: str, width: float, height: float, asset_type: str, style="", **payload) -> dict:
    return {
        "id": "personal." + hashlib.sha256(data).hexdigest()[:32], "name": name[:200],
        "category": "personal", "library": "personal", "assetType": asset_type, "source": "user_upload",
        "style": style, "nativeWidth": width, "nativeHeight": height, "defaultWidth": width,
        "defaultHeight": height, "labelPosition": "bottom", "preserveAspectRatio": True,
        "verified": False, "usable": asset_type != "cell_template", **payload,
    }


def _svg_record(data: bytes, name: str) -> dict:
    width, height = svg_dimensions(data)
    try:
        svg = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiException(ErrorCode.DRAWIO_UNSUPPORTED_CONTENT, "SVG 需使用 UTF-8") from exc
    return _record(data, name, width, height, "svg", svg=svg)


def _safe_native_style(raw: str) -> None:
    styles = parse_style(raw)
    shape = styles.get("shape", "")
    base = shape.removeprefix("mxgraph.")
    native = base in bundled_shapes() or any(
        base + "--" + styles.get(key, "").removeprefix("mxgraph.") in bundled_shapes() for key in ("resIcon", "prIcon")
    )
    if shape not in BUILTIN_SHAPES and not native:
        _invalid("素材含有本地目录无法验证的 Shape")
    if any(BAD_VALUE.search(value) or "<" in value or ">" in value for value in styles.values()):
        _invalid("素材样式含有外部资源")
    if set(styles) & {"image", "indicatorImage", "backgroundImage", "link"} or any(
        key.startswith("on") for key in styles
    ):
        _invalid("素材 XML 含有活动内容，请单独导入 SVG")


def _model_record(xml: str, name: str, *, selected: str = "") -> dict:
    data = xml.encode()
    root = _parse_xml(data, LIBRARY_MAX_BYTES)
    parsed = parse_drawio_bytes(data, max_cells=200, max_bytes=LIBRARY_MAX_BYTES)
    cells = [cell for cell in parsed.cells if cell.id not in {"0", "1"}]
    if selected:
        cells = [cell for cell in cells if cell.id == selected and cell.vertex]
        if not cells or any(other.parent == selected for other in parsed.cells):
            _invalid("请选择可单独提取的节点，组合图形可通过素材库导入")
    if not cells:
        _invalid("素材不包含图形")
    if len(cells) == 1 and cells[0].vertex:
        cell = cells[0]
        style = cell.style or ""
        _safe_native_style(style)
        # Names are plain text. Image/HTML/URL fields are deliberately omitted
        # when extracting a reusable vertex from an existing diagram.
        return _record((cell.id + name + style).encode(), name, cell.geometry.width or 100 if cell.geometry else 100,
                       cell.geometry.height or 80 if cell.geometry else 80, "stencil", style=style)
    if selected:
        _invalid("组合素材无法作为单设备放置")
    model = root if root.tag == "mxGraphModel" else root.find("diagram/mxGraphModel")
    model_root = model.find("root") if model is not None else None
    if model_root is None or any(item.tag != "mxCell" for item in model_root):
        _invalid("组合素材仅支持原生 mxCell 模板")
    for item in model_root:
        if set(item.attrib) - {"id", "parent", "value", "style", "vertex", "edge", "source", "target", "visible", "collapsed", "connectable"}:
            _invalid("组合素材含有不支持的属性")
        if "<" in item.get("value", "") or ">" in item.get("value", ""):
            _invalid("组合素材标签必须为纯文本")
        _safe_native_style(item.get("style", ""))
        if any(child.tag not in {"mxGeometry", "Array", "mxPoint", "mxRectangle"} for child in item.iter() if child is not item):
            _invalid("组合素材含有不支持的几何内容")
    portable = ET.tostring(model, encoding="unicode")
    return _record(portable.encode(), name, parsed.page_width or 100, parsed.page_height or 80,
                   "cell_template", xml=portable)


def _decode_svg_uri(uri: str) -> bytes:
    prefix = "data:image/svg+xml;base64,"
    if uri.startswith(prefix):
        try:
            return base64.b64decode(uri[len(prefix):], validate=True)
        except ValueError as exc:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "素材 SVG 编码无效") from exc
    if uri.startswith("data:image/svg+xml,"):
        from urllib.parse import unquote_to_bytes

        return unquote_to_bytes(uri.partition(",")[2])
    _invalid("素材库图像必须为内嵌 SVG")


class MaterialService:
    def __init__(self, db) -> None:
        self.db = db
        with db.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS personal_materials (id TEXT PRIMARY KEY, material TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS material_preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _personal(self) -> dict:
        with self.db.transaction() as conn:
            return {row["id"]: json.loads(row["material"]) for row in conn.execute("SELECT id, material FROM personal_materials")}

    def preferences(self) -> dict:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT key, value FROM material_preferences").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def get(self, id_: str) -> dict:
        hit = bundled_shapes().get(id_) or self._personal().get(id_)
        if hit is None:
            raise ApiException(ErrorCode.MATERIAL_NOT_FOUND, "素材不存在")
        return hit

    def search(self, q: str, library: str, favorite: bool, offset: int, limit: int) -> dict:
        favorites = set(self.preferences().get("favorites", []))
        terms = unicodedata.normalize("NFKC", q).lower().split()
        rows = []
        for item in [*self._personal().values(), *bundled_shapes().values()]:
            if library and library not in {item["library"], item["category"]} or favorite and item["id"] not in favorites:
                continue
            tags = [item["id"], item["name"], item.get("nameZh", ""), item.get("searchTags", ""),
                    *item.get("aliases", []), *item.get("deviceTypes", [])]
            for device in item.get("deviceTypes", []):
                tags.extend(device_aliases().get(device, {}).get("aliases", []))
            searchable = unicodedata.normalize("NFKC", " ".join(tags)).lower()
            if all(term in searchable for term in terms):
                rows.append({key: item[key] for key in ("id", "name", "category", "library", "assetType",
                            "defaultWidth", "defaultHeight", "verified", "nameZh") if key in item} | {
                    "favorite": item["id"] in favorites, "usable": item.get("usable", True),
                })
        rows.sort(key=lambda row: (not row["favorite"], row["library"] != "personal", row["verified"] is False, row["id"]))
        return {"items": rows[offset:offset + limit], "total": len(rows), "catalogVersion": catalog_version()}

    def set_preferences(self, changes: dict) -> dict:
        for key, value in changes.items():
            if key == "mappings":
                for device, id_ in value.items():
                    if device not in device_aliases() or not self.get(id_).get("usable", True):
                        raise ApiException(ErrorCode.SCHEMA_INVALID, "设备类型或素材不支持默认映射")
            else:
                for id_ in value:
                    self.get(id_)
        with self.db.transaction() as conn:
            for key, value in changes.items():
                conn.execute("INSERT INTO material_preferences (key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
        return self.preferences()

    def import_file(self, data: bytes, name: str, kind: str, cell_id: str) -> list[dict]:
        if kind == "svg":
            records = [_svg_record(data, name)]
        elif kind == "drawio":
            if not cell_id:
                raise ApiException(ErrorCode.SCHEMA_INVALID, "历史图纸提取需要 cellId")
            from app.importer.xml_parser import normalize_to_uncompressed

            normalized, _ = normalize_to_uncompressed(data, max_cells=5000, max_bytes=LIBRARY_MAX_BYTES)
            records = [_model_record(normalized.decode("utf-8"), name, selected=cell_id)]
        else:
            root = _parse_xml(data, LIBRARY_MAX_BYTES)
            if root.tag != "mxlibrary":
                _invalid("请选择 draw.io 的 mxlibrary 文件")
            try:
                entries = json.loads(root.text or "")
            except ValueError as exc:
                raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "mxlibrary 内容不是有效 JSON") from exc
            if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
                _invalid("素材库应包含 1 到 100 项")
            records = []
            expanded = 0
            for item in entries:
                if not isinstance(item, dict):
                    _invalid("mxlibrary 素材项无效")
                title = str(item.get("title") or name)[:200]
                if isinstance(item.get("data"), str):
                    payload = _decode_svg_uri(item["data"])
                    expanded += len(payload)
                    records.append(_svg_record(payload, title))
                elif isinstance(item.get("xml"), str):
                    xml = item["xml"]
                    if not xml.lstrip().startswith("<"):
                        xml = decompress_diagram_content(xml, max_decompressed_bytes=LIBRARY_MAX_BYTES)
                    expanded += len(xml.encode())
                    records.append(_model_record(xml, title))
                else:
                    _invalid("素材项需要内嵌 SVG 或 mxGraphModel")
                if expanded > LIBRARY_MAX_BYTES:
                    _invalid("素材库展开后超过限制")
        with self.db.transaction() as conn:
            count = conn.execute("SELECT COUNT(*) FROM personal_materials").fetchone()[0]
            existing = {row["id"] for row in conn.execute("SELECT id FROM personal_materials")}
            if count + len({item["id"] for item in records} - existing) > 300:
                _invalid("个人库最多保存 300 项素材")
            for item in records:
                conn.execute("INSERT OR IGNORE INTO personal_materials (id, material) VALUES (?, ?)",
                             (item["id"], json.dumps(item, ensure_ascii=False)))
        return records

    def renderer_context(self, doc: GraphDocument) -> dict:
        preferences = self.preferences().get("mappings", {})
        personal_ids = {shape for shape in preferences.values() if shape.startswith("personal.")}
        personal_ids.update(value for node in doc.nodes for value in (node.style.get("shapeId"),)
                            if isinstance(value, str) and value.startswith("personal."))
        personal = {id_: item for id_, item in self._personal().items() if id_ in personal_ids} if personal_ids else {}
        return {"preferences": preferences, "personalShapes": personal}
