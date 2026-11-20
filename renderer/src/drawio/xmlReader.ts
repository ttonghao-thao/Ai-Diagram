/**
 * Minimal draw.io XML reader used by `validate` CLI and roundtrip tests.
 * Phase 0 scope: uncompressed single-page mxfile (our own output format).
 * Compressed pages and multi-page files are explicitly rejected (Phase 2).
 */
import { XMLParser } from 'fast-xml-parser';
import { ErrorCodes, RenderError } from '../errors.js';
import { issue, type ValidationIssue } from '../errors.js';
import type { Point } from '../types.js';

export interface ParsedGeometry {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  relative?: boolean;
  /** Waypoint list (`Array as="points"`), absolute in the edge parent frame. */
  points: Point[];
}

export interface ParsedCell {
  id: string;
  value?: string;
  style?: string;
  vertex?: boolean;
  edge?: boolean;
  parent?: string;
  source?: string;
  target?: string;
  geometry?: ParsedGeometry;
}

export interface ParsedDrawio {
  pageId: string | null;
  pageName: string | null;
  pageWidth: number | null;
  pageHeight: number | null;
  cells: ParsedCell[];
  cellById: Map<string, ParsedCell>;
}

function asArray(value: unknown): unknown[] {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

function toNumber(value: unknown, what: string): number | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  const n = Number(value);
  if (!Number.isFinite(n)) {
    throw new RenderError(ErrorCodes.DRAWIO_PARSE_FAILED, `${what} is not a finite number: ${String(value)}`);
  }
  return n;
}

function parseGeometry(raw: unknown): ParsedGeometry | undefined {
  if (raw === undefined || raw === null) return undefined;
  const geo = raw as Record<string, unknown>;
  const points: Point[] = [];
  const arrays = asArray(geo.Array);
  for (const arr of arrays) {
    const a = arr as Record<string, unknown>;
    if (a.as !== 'points') continue;
    for (const p of asArray(a.mxPoint)) {
      const pt = p as Record<string, unknown>;
      points.push({ x: toNumber(pt.x, 'mxPoint.x') ?? 0, y: toNumber(pt.y, 'mxPoint.y') ?? 0 });
    }
  }
  return {
    x: toNumber(geo.x, 'mxGeometry.x'),
    y: toNumber(geo.y, 'mxGeometry.y'),
    width: toNumber(geo.width, 'mxGeometry.width'),
    height: toNumber(geo.height, 'mxGeometry.height'),
    relative: geo.relative === '1' || geo.relative === true,
    points,
  };
}

/** Parse uncompressed single-page draw.io XML. Throws RenderError on unsupported content. */
export function parseDrawioXml(xml: string): ParsedDrawio {
  let parsed: Record<string, unknown>;
  try {
    const parser = new XMLParser({
      ignoreAttributes: false,
      attributeNamePrefix: '',
      parseTagValue: false,
      parseAttributeValue: false,
      // trimValues (default true) drops whitespace-only text nodes between
      // tags; a genuinely compressed diagram still yields non-empty #text.
      isArray: (name) => name === 'mxCell' || name === 'diagram' || name === 'mxPoint' || name === 'Array',
    });
    parsed = parser.parse(xml) as Record<string, unknown>;
  } catch (err) {
    throw new RenderError(
      ErrorCodes.DRAWIO_PARSE_FAILED,
      `XML is not well-formed: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
  const mxfile = parsed.mxfile as Record<string, unknown> | undefined;
  if (!mxfile) {
    throw new RenderError(ErrorCodes.DRAWIO_PARSE_FAILED, 'root element must be <mxfile>');
  }
  const diagrams = asArray(mxfile.diagram);
  if (diagrams.length === 0) {
    throw new RenderError(ErrorCodes.DRAWIO_PARSE_FAILED, 'mxfile contains no <diagram>');
  }
  if (diagrams.length > 1) {
    throw new RenderError(
      ErrorCodes.DRAWIO_UNSUPPORTED_CONTENT,
      `multi-page files are not supported in Phase 0 (${diagrams.length} pages found)`,
    );
  }
  const diagram = diagrams[0] as Record<string, unknown>;
  // Desktop saves compressed pages as text content inside <diagram>.
  if (typeof diagram === 'string' || typeof diagram['#text'] === 'string') {
    throw new RenderError(
      ErrorCodes.DRAWIO_UNSUPPORTED_CONTENT,
      'compressed diagram content is not supported in Phase 0',
    );
  }
  const model = diagram.mxGraphModel as Record<string, unknown> | undefined;
  if (!model || typeof model === 'string') {
    throw new RenderError(ErrorCodes.DRAWIO_PARSE_FAILED, '<diagram> must contain an <mxGraphModel>');
  }
  const root = model.root as Record<string, unknown> | undefined;
  if (!root) {
    throw new RenderError(ErrorCodes.DRAWIO_PARSE_FAILED, 'mxGraphModel must contain a <root>');
  }

  const cells: ParsedCell[] = [];
  const cellById = new Map<string, ParsedCell>();
  for (const rawCell of asArray(root.mxCell)) {
    const c = rawCell as Record<string, unknown>;
    const id = c.id;
    if (typeof id !== 'string' || id.length === 0) {
      throw new RenderError(ErrorCodes.DRAWIO_PARSE_FAILED, 'every mxCell must have an id');
    }
    if (cellById.has(id)) {
      throw new RenderError(ErrorCodes.DRAWIO_PARSE_FAILED, `duplicate cell id: ${id}`);
    }
    const cell: ParsedCell = {
      id,
      value: typeof c.value === 'string' ? c.value : undefined,
      style: typeof c.style === 'string' ? c.style : undefined,
      vertex: c.vertex === '1',
      edge: c.edge === '1',
      parent: typeof c.parent === 'string' ? c.parent : undefined,
      source: typeof c.source === 'string' ? c.source : undefined,
      target: typeof c.target === 'string' ? c.target : undefined,
      geometry: parseGeometry(c.mxGeometry),
    };
    cells.push(cell);
    cellById.set(id, cell);
  }

  return {
    pageId: typeof diagram.id === 'string' ? diagram.id : null,
    pageName: typeof diagram.name === 'string' ? diagram.name : null,
    pageWidth: toNumber(model.pageWidth, 'pageWidth') ?? null,
    pageHeight: toNumber(model.pageHeight, 'pageHeight') ?? null,
    cells,
    cellById,
  };
}

/** Structural reference checks: parent/source/target must reference known cells. */
export function validateStructure(parsed: ParsedDrawio): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  for (const cell of parsed.cells) {
    if (cell.parent && !parsed.cellById.has(cell.parent)) {
      issues.push(issue('DRAWIO_PARSE_FAILED', `cell "${cell.id}" references unknown parent "${cell.parent}"`, [cell.id]));
    }
    if (cell.edge === true) {
      if (!cell.source || !parsed.cellById.has(cell.source)) {
        issues.push(issue('DRAWIO_PARSE_FAILED', `edge "${cell.id}" references unknown source "${cell.source ?? ''}"`, [cell.id]));
      }
      if (!cell.target || !parsed.cellById.has(cell.target)) {
        issues.push(issue('DRAWIO_PARSE_FAILED', `edge "${cell.id}" references unknown target "${cell.target ?? ''}"`, [cell.id]));
      }
    }
  }
  return issues;
}

/**
 * Reconstruct absolute canvas coordinates from parent-relative mxGeometry
 * values (docs/03 section 2, inverse of serialization conversion).
 */
export function absoluteGeometry(cell: ParsedCell, cellById: Map<string, ParsedCell>): Point & { width: number; height: number } {
  if (!cell.geometry || cell.geometry.x === undefined || cell.geometry.y === undefined) {
    return { x: 0, y: 0, width: 0, height: 0 };
  }
  let x = cell.geometry.x;
  let y = cell.geometry.y;
  const parent = cell.parent ? cellById.get(cell.parent) : undefined;
  if (parent && parent.id !== '0' && parent.id !== '1') {
    const pAbs = absoluteGeometry(parent, cellById);
    x += pAbs.x;
    y += pAbs.y;
  }
  return { x, y, width: cell.geometry.width ?? 0, height: cell.geometry.height ?? 0 };
}
