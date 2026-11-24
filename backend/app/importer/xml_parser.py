"""Safe draw.io XML parsing (docs/03 sections 5 and 7).

Security:
  - hard size limit before any parsing;
  - DOCTYPE/ENTITY declarations are rejected outright (no external entities);
  - compressed pages are decoded with the verified drawio pipeline
    (encodeURIComponent(xml) -> deflateRaw -> base64; confirmed in
    drawio v24.7.17 Graph.compress/decompress);
  - multi-page files are rejected explicitly (kept unmodified server-side);
  - cell/geometry limits bound memory use.
"""
from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

from app.schemas.api import ApiException, ErrorCode

_DOCTYPE_PATTERN = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


def compress_diagram_content(xml: str) -> str:
    """drawio-compatible page compression (Graph.compress, verified)."""
    data = quote(xml, safe="!~*'()").encode("utf-8")  # encodeURIComponent form
    compressor = zlib.compressobj(level=9, wbits=-15)  # raw DEFLATE
    raw = compressor.compress(data) + compressor.flush()
    return base64.b64encode(raw).decode("ascii")


def decompress_diagram_content(content: str, max_decompressed_bytes: int = 6 * 1024 * 1024) -> str:
    """Inverse of compress_diagram_content; supports the URL-encoded variant.

    Decompression is capped (docs/04 section 6): a small compressed upload that
    expands beyond the limit is rejected instead of allocating unbounded memory
    (decompression-bomb protection).
    """
    text = content.strip()
    # drawio writes plain base64 into files; URL-encoding may appear when the
    # content passed through URI contexts.
    if "%" in text:
        try:
            text = unquote(text)
        except Exception as exc:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"URL-encoded diagram content is malformed: {exc}") from exc
    padding = "=" * (-len(text) % 4)
    try:
        raw = base64.b64decode(text + padding, validate=False)
        dobj = zlib.decompressobj(-15)
        chunks = []
        total = 0
        data = raw
        while data:
            out = dobj.decompress(data, 256 * 1024)
            total += len(out)
            if total > max_decompressed_bytes:
                raise ApiException(
                    ErrorCode.DRAWIO_UPLOAD_TOO_LARGE,
                    f"decompressed diagram content exceeds the {max_decompressed_bytes}-byte limit",
                )
            chunks.append(out)
            if dobj.eof:
                break
            data = dobj.unconsumed_tail
        if not dobj.eof:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "compressed diagram content is truncated")
        xml_bytes = b"".join(chunks)
    except ApiException:
        raise
    except Exception as exc:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"compressed diagram content could not be decoded: {exc}") from exc
    try:
        xml = unquote(xml_bytes.decode("utf-8"), errors="strict")
        guard_no_dtd(xml.encode("utf-8"), max_decompressed_bytes)
        return xml
    except UnicodeDecodeError as exc:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "decompressed diagram content is not valid UTF-8") from exc


@dataclass
class ParsedGeometry:
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    relative: bool = False
    points: List[Dict[str, float]] = field(default_factory=list)


@dataclass
class ParsedCell:
    id: str
    value: Optional[str] = None
    style: Optional[str] = None
    vertex: bool = False
    edge: bool = False
    parent: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None
    geometry: Optional[ParsedGeometry] = None
    wrapped: bool = False  # inside UserObject/object
    raw_xml: str = ""


@dataclass
class ParsedDrawio:
    page_name: Optional[str]
    page_width: Optional[float]
    page_height: Optional[float]
    compressed: bool
    cells: List[ParsedCell]
    cell_by_id: Dict[str, ParsedCell]
    unknown_cells: List[ParsedCell]

    def absolute_geometry(self, cell: ParsedCell) -> Dict[str, Optional[float]]:
        """Walk the parent chain converting relative mxGeometry to absolute."""
        x = cell.geometry.x if cell.geometry and cell.geometry.x is not None else None
        y = cell.geometry.y if cell.geometry and cell.geometry.y is not None else None
        if x is None or y is None:
            return {"x": x, "y": y}
        parent = self.cell_by_id.get(cell.parent) if cell.parent else None
        while parent is not None and parent.id not in ("0", "1") and parent.geometry is not None:
            if parent.geometry.x is not None and parent.geometry.y is not None:
                x += parent.geometry.x
                y += parent.geometry.y
            parent = self.cell_by_id.get(parent.parent) if parent.parent else None
        return {"x": x, "y": y}


def _num(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_geometry(geo_el: Optional[ET.Element]) -> Optional[ParsedGeometry]:
    if geo_el is None:
        return None
    points: List[Dict[str, float]] = []
    for array in geo_el.findall("Array"):
        if array.get("as") != "points":
            continue
        for pt in array.findall("mxPoint"):
            px, py = _num(pt.get("x")), _num(pt.get("y"))
            if px is not None and py is not None:
                points.append({"x": px, "y": py})
    return ParsedGeometry(
        x=_num(geo_el.get("x")),
        y=_num(geo_el.get("y")),
        width=_num(geo_el.get("width")),
        height=_num(geo_el.get("height")),
        relative=geo_el.get("relative") == "1",
        points=points,
    )


def guard_no_dtd(data: bytes, max_bytes: int) -> None:
    """Reject oversized buffers and any DOCTYPE/ENTITY declaration anywhere in
    the document. ElementTree does not fetch external entities, but declared
    payloads have no business in user uploads at all (docs/04 section 6)."""
    if len(data) > max_bytes:
        raise ApiException(
            ErrorCode.DRAWIO_UPLOAD_TOO_LARGE,
            f"file is {len(data)} bytes, exceeds the {max_bytes}-byte limit",
        )
    if b"\x00" in data or _DOCTYPE_PATTERN.search(data):
        raise ApiException(
            ErrorCode.DRAWIO_PARSE_FAILED,
            "XML encoding or DOCTYPE/ENTITY declaration is unsupported",
        )


def normalize_to_uncompressed(data: bytes, max_cells: int = 5000, max_bytes: int = 10 * 1024 * 1024) -> Tuple[bytes, bool]:
    """Rewrite a single-page mxfile so its diagram content is uncompressed.

    Import commit stores the uploaded XML verbatim as the graphical source of
    truth; without this normalization a Desktop-saved compressed page would be
    stored compressed and every subsequent Patch application would be refused
    (xml_edit rejects compressed pages). Returns (normalized_bytes,
    was_normalized). The semantic content is unchanged — only the encoding.
    """
    if len(data) > max_bytes:
        raise ApiException(
            ErrorCode.DRAWIO_UPLOAD_TOO_LARGE,
            f"file is {len(data)} bytes, exceeds the {max_bytes}-byte limit",
        )
    guard_no_dtd(data, max_bytes)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"XML is not well-formed: {exc}") from exc
    if root.tag == "mxGraphModel":
        return data, False  # bare model: already uncompressed
    if root.tag != "mxfile":
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"root element must be mxfile, got '{root.tag}'")
    diagrams = root.findall("diagram")
    if len(diagrams) != 1:
        raise ApiException(
            ErrorCode.DRAWIO_UNSUPPORTED_CONTENT,
            f"multi-page files are not supported ({len(diagrams)} pages found)",
        )
    diagram = diagrams[0]
    model = diagram.find("mxGraphModel")
    if model is not None and not (diagram.text or "").strip():
        return data, False  # plain single-page content: nothing to do
    text = (diagram.text or "").strip()
    if not text:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "diagram has neither mxGraphModel nor compressed content")
    xml = decompress_diagram_content(text)
    try:
        model = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"decompressed diagram is not well-formed: {exc}") from exc
    if model.tag != "mxGraphModel":
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "decompressed content must be an mxGraphModel")

    root.set("compressed", "false")
    if "compressed" in diagram.attrib:
        diagram.set("compressed", "false")
    diagram.text = None
    diagram.append(model)
    out = root
    serialized = ET.tostring(out, encoding="unicode")
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n{serialized}\n').encode("utf-8"), True


def parse_drawio_bytes(data: bytes, max_cells: int = 5000, max_bytes: int = 10 * 1024 * 1024) -> ParsedDrawio:
    """Parse uncompressed or compressed single-page draw.io XML safely."""
    if len(data) > max_bytes:
        raise ApiException(
            ErrorCode.DRAWIO_UPLOAD_TOO_LARGE,
            f"upload is {len(data)} bytes, exceeds the {max_bytes}-byte limit",
        )
    guard_no_dtd(data, max_bytes)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"XML is not well-formed: {exc}") from exc
    if root.tag != "mxfile":
        # drawio Desktop may also save a bare <mxGraphModel>; accept it.
        if root.tag != "mxGraphModel":
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"root element must be mxfile, got '{root.tag}'")
        diagrams = [root]
        root_el: Optional[ET.Element] = None
    else:
        root_el = root
        diagrams = [d for d in root.findall("diagram")]
    if len(diagrams) == 0:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "mxfile contains no diagram")
    if len(diagrams) > 1:
        raise ApiException(
            ErrorCode.DRAWIO_UNSUPPORTED_CONTENT,
            f"multi-page files are not supported for import ({len(diagrams)} pages); the file was not modified",
        )
    diagram = diagrams[0]

    compressed = False
    model_el: Optional[ET.Element] = diagram if diagram.tag == "mxGraphModel" else diagram.find("mxGraphModel")
    if model_el is None:
        # Compressed pages store the payload as element text.
        text = (diagram.text or "").strip()
        if not text:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "diagram has neither mxGraphModel nor compressed content")
        xml = decompress_diagram_content(text)
        compressed = True
        try:
            model_el = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"decompressed diagram is not well-formed: {exc}") from exc
        if model_el.tag != "mxGraphModel":
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "decompressed content must be an mxGraphModel")

    cells: List[ParsedCell] = []
    cell_by_id: Dict[str, ParsedCell] = {}
    unknown_cells: List[ParsedCell] = []
    root_el_children = list(model_el.find("root")) if model_el.find("root") is not None else []
    if len(root_el_children) > max_cells:
        raise ApiException(
            ErrorCode.DRAWIO_UNSUPPORTED_CONTENT,
            f"file contains {len(root_el_children)} elements, exceeds the {max_cells}-cell limit",
        )
    for el in root_el_children:
        wrapper_attrs: Dict[str, Optional[str]] = {}
        wrapped = False
        if el.tag in ("object", "UserObject"):
            wrapped = True
            wrapper_attrs = {k: el.get(k) for k in ("id", "label")}
            inner = el.find("mxCell")
            if inner is None:
                continue
            cell_el = inner
        elif el.tag == "mxCell":
            cell_el = el
        else:
            continue  # mxPoint/MxRectangleModel etc. at root level: ignored safely
        cid = cell_el.get("id") or wrapper_attrs.get("id")
        if not cid:
            continue
        value = cell_el.get("value")
        if wrapped and wrapper_attrs.get("label") is not None:
            value = wrapper_attrs["label"]
        cell = ParsedCell(
            id=cid,
            value=value,
            style=cell_el.get("style"),
            vertex=cell_el.get("vertex") == "1",
            edge=cell_el.get("edge") == "1",
            parent=cell_el.get("parent"),
            source=cell_el.get("source"),
            target=cell_el.get("target"),
            geometry=_parse_geometry(cell_el.find("mxGeometry")),
            wrapped=wrapped,
            raw_xml=ET.tostring(el, encoding="unicode"),
        )
        if cid in cell_by_id:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "duplicate cell ID", [cid])
        cells.append(cell)
        cell_by_id[cid] = cell
        # Unknown objects: cells outside the stable n_/g_/e_ mapping (plus the
        # infrastructure cells 0/1 which are never graph objects).
        if cid in ("0", "1"):
            continue
        if not (cid.startswith(("n_", "g_", "e_")) or "aiKind=" in (cell.style or "")):
            unknown_cells.append(cell)

    visit_state: Dict[str, int] = {}
    for cell in cells:
        trail = []
        parent = cell.id
        while parent in cell_by_id and parent not in visit_state:
            visit_state[parent] = 1
            trail.append(parent)
            parent = cell_by_id[parent].parent
        if visit_state.get(parent) == 1:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "XML cell parent cycle", [cell.id])
        visit_state.update((id_, 2) for id_ in trail)

    # Reference integrity inside the uploaded file itself.
    for cell in cells:
        if cell.parent and cell.parent not in cell_by_id:
            raise ApiException(
                ErrorCode.DRAWIO_PARSE_FAILED,
                f"cell '{cell.id}' references unknown parent '{cell.parent}'",
            )
        if cell.edge:
            if not cell.source or cell.source not in cell_by_id:
                raise ApiException(
                    ErrorCode.DRAWIO_PARSE_FAILED,
                    f"edge '{cell.id}' references unknown source '{cell.source or ''}'",
                )
            if not cell.target or cell.target not in cell_by_id:
                raise ApiException(
                    ErrorCode.DRAWIO_PARSE_FAILED,
                    f"edge '{cell.id}' references unknown target '{cell.target or ''}'",
                )

    return ParsedDrawio(
        page_name=diagram.get("name") if root_el is not None else None,
        page_width=_num(model_el.get("pageWidth")),
        page_height=_num(model_el.get("pageHeight")),
        compressed=compressed,
        cells=cells,
        cell_by_id=cell_by_id,
        unknown_cells=unknown_cells,
    )
