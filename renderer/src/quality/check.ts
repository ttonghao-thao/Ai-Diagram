import { absoluteGeometry, type ParsedDrawio } from '../drawio/xmlReader.js';
import { rankAxis } from '../layout/constraints.js';
import { center, labelBox, overlaps, pathCrosses, pathForEdge } from '../routing/edgeRouter.js';
import type { ResolvedDrawing } from '../shapes/resolve.js';
import { edgeCellId, groupCellId, nodeCellId, type Geometry, type GraphDocument, type Point } from '../types.js';

export interface QualityIssue { code: string; message: string; relatedIds: string[]; severity: 'warning' | 'error' }
export interface QualityReport {
  ok: boolean;
  counts: { nodes: number; edges: number; matchedShapes: number; warnings: number; errors: number };
  issues: QualityIssue[];
  truncated: boolean;
}
export interface QualityContext {
  cellMapping?: Record<string, string>;
  unknownIds?: string[];
  protectedGeometry?: Record<string, Geometry>;
  manualStyleIds?: string[];
}
const TOLERANCE = 0.06;

export function checkQuality(doc: GraphDocument, drawing: ResolvedDrawing, parsed: ParsedDrawio, context: QualityContext = {}): QualityReport {
  const issues: QualityIssue[] = [];
  const count = { nodes: doc.nodes.length, edges: doc.edges.length,
    matchedShapes: Object.values(drawing.nodes).filter((shape) => shape.resolvedBy !== 'fallback').length, warnings: 0, errors: 0 };
  const add = (code: string, message: string, relatedIds: string[], severity: QualityIssue['severity'] = 'warning') => {
    count[severity === 'error' ? 'errors' : 'warnings']++;
    if (issues.length < 300) issues.push({ code, message, relatedIds, severity });
    else if (severity === 'error' && issues.some((item) => item.severity !== 'error')) {
      issues.splice(issues.findIndex((item) => item.severity !== 'error'), 1, { code, message, relatedIds, severity });
    }
  };
  for (const warning of drawing.warnings) add(warning.code, warning.message, warning.relatedIds ?? []);
  const mapped = (id: string, fallback: string) => context.cellMapping?.[id] ?? fallback;
  const geometries = new Map<string, Geometry>();
  const visual = new Map<string, Geometry>();
  const parents = new Map(doc.groups.map((item) => [item.id, item.parentId]));
  const groupAncestors = new Map(doc.nodes.map((node) => {
    const set = new Set<string>();
    let parent = node.groupId;
    while (parent) { set.add(parent); parent = parents.get(parent); }
    return [node.id, set];
  }));
  const inspect = (id: string, stable: string, expectedParent: string | undefined) => {
    const cell = parsed.cellById.get(mapped(id, stable));
    let parent = cell?.parent;
    while (parent && parent !== expectedParent && parent !== '1' && parent !== '0') {
      parent = parsed.cellById.get(parent)?.parent;
    }
    if (!cell?.vertex || (expectedParent !== undefined && parent !== expectedParent)) {
      add('TOPOLOGY_MISMATCH', '图形或分组归属与 GraphDocument 不一致', [id], 'error');
    }
    if (!cell?.geometry) return undefined;
    const box = absoluteGeometry(cell, parsed.cellById);
    geometries.set(stable, box);
    const old = context.protectedGeometry?.[id];
    if (old && ['x', 'y', 'width', 'height'].some((key) => Math.abs(old[key as keyof Geometry] - box[key as keyof Geometry]) > TOLERANCE)) {
      add('LOCKED_POSITION_CHANGED', '受保护的几何位置已改变', [id], 'error');
    }
    return box;
  };
  for (const group of doc.groups) {
    inspect(group.id, groupCellId(group.id), group.parentId ? mapped(group.parentId, groupCellId(group.parentId)) : undefined);
  }
  const manual = new Set(context.manualStyleIds ?? []);
  const styleGroups = new Map<string, { id: string; style: string }>();
  for (const node of doc.nodes) {
    const box = inspect(node.id, nodeCellId(node.id), node.groupId ? mapped(node.groupId, groupCellId(node.groupId)) : undefined);
    if (!box) continue;
    const shape = drawing.nodes[node.id];
    const actual = parsed.cellById.get(mapped(node.id, nodeCellId(node.id)))?.style ?? '';
    const style = shape.style;
    const label = labelBox(box, actual.includes('verticalLabelPosition=bottom') ? shape.labelSize : undefined);
    if (label) visual.set(node.id, label);
    const manuallySized = node.geometry || manual.has(node.id) || node.origin === 'imported';
    if (!manuallySized && Math.abs(box.width / box.height - shape.iconSize.width / shape.iconSize.height) > TOLERANCE) {
      add('ASPECT_RATIO_VIOLATION', '自动图形的宽高比有偏差', [node.id]);
    }
    for (const group of groupAncestors.get(node.id) ?? []) {
      const g = geometries.get(groupCellId(group));
      const candidate = label ? { x: label.x, y: box.y, width: label.width, height: box.height + label.height } : box;
      if (g && (candidate.x < g.x - TOLERANCE || candidate.y < g.y - TOLERANCE ||
         candidate.x + candidate.width > g.x + g.width + TOLERANCE || candidate.y + candidate.height > g.y + g.height + TOLERANCE)) {
        add('GROUP_OVERFLOW', '设备或文字超出分组', [node.id, group]);
      }
    }
    if (!manual.has(node.id) && !Object.keys(node.style ?? {}).length && node.origin !== 'imported') {
      const key = JSON.stringify([shape.themeId, node.kind, node.properties?.deviceType ?? '', shape.shapeId]);
      const signature = actual.split(';').filter((part) => /^(shape|image|strokeColor|fillColor|fontColor)=/.test(part)).join(';');
      const peer = styleGroups.get(key);
      if (peer && peer.style !== signature) add('STYLE_INCONSISTENCY', '同类自动设备的样式不同', [peer.id, node.id]);
      if (!peer && style) styleGroups.set(key, { id: node.id, style: signature });
    }
  }
  for (const id of context.unknownIds ?? []) {
    if (!parsed.cellById.has(id)) add('UNKNOWN_CELL_LOSS', '原始 XML 未知对象丢失', [id], 'error');
  }
  for (let i = 0; i < doc.nodes.length; i++) {
    const a = doc.nodes[i].id;
    const first = geometries.get(nodeCellId(a));
    if (!first) continue;
    for (const { id: b } of doc.nodes.slice(i + 1)) {
      const second = geometries.get(nodeCellId(b));
      if (!second) continue;
      if (overlaps(first, second)) add('NODE_OVERLAP', '设备图形重叠', [a, b]);
      const leftLabel = visual.get(a);
      const rightLabel = visual.get(b);
      if (leftLabel && overlaps(leftLabel, second) || rightLabel && overlaps(rightLabel, first) ||
          leftLabel && rightLabel && overlaps(leftLabel, rightLabel)) add('LABEL_OVERLAP', '设备与文字区域重叠', [a, b]);
    }
  }
  const edgeLabels: Array<{ id: string; box: Geometry }> = [];
  for (const edge of doc.edges) {
    const cell = parsed.cellById.get(mapped(edge.id, edgeCellId(edge.id)));
    if (!cell?.edge || cell.source !== mapped(edge.source, nodeCellId(edge.source)) ||
        cell.target !== mapped(edge.target, nodeCellId(edge.target))) {
      add('TOPOLOGY_MISMATCH', 'XML 中的线路或端点与 GraphDocument 不一致', [edge.id], 'error');
      continue;
    }
    const p = cell.parent ? parsed.cellById.get(cell.parent) : undefined;
    const offset = p?.geometry ? absoluteGeometry(p, parsed.cellById) : { x: 0, y: 0 };
    const points = pathForEdge(edge, (cell.geometry?.points ?? []).map(({ x, y }) => ({ x: x + offset.x, y: y + offset.y })), geometries);
    for (const { id } of doc.nodes) {
      if (edge.source === id || edge.target === id) continue;
      const box = geometries.get(nodeCellId(id));
      const label = visual.get(id);
      if (box && pathCrosses(points, box) || label && pathCrosses(points, label)) {
        add('EDGE_NODE_COLLISION', '连线经过无关设备或文字', [edge.id, id]);
      }
    }
    if (cell.value && points.length >= 2) {
      const midpoint = pathMidpoint(points);
      const width = Math.min(240, 12 * cell.value.length + 8);
      const box = { x: midpoint.x - width / 2, y: midpoint.y - 9, width, height: 18 };
      for (const other of edgeLabels) {
        if (overlaps(box, other.box)) add('EDGE_LABEL_COLLISION', '连线标签重叠', [edge.id, other.id]);
      }
      edgeLabels.push({ id: edge.id, box });
    }
  }
  for (const rule of doc.layout.constraints ?? []) {
    if (rule.type !== 'order' && rule.type !== 'sameRank') continue;
    const axis = rule.type === 'order' ? rule.axis : rankAxis(doc);
    const coords = rule.nodes.map((id) => geometries.get(nodeCellId(id))).filter((g): g is Geometry => !!g)
      .map((g) => center(g)[axis]);
    if (rule.type === 'order' && coords.some((c, i) => i > 0 && c <= coords[i - 1] + TOLERANCE)) {
      add('ORDER_VIOLATION', '设备顺序约束未满足', rule.nodes);
    }
    if (rule.type === 'sameRank' && coords.some((c) => Math.abs(c - coords[0]) > TOLERANCE)) {
      add('RANK_VIOLATION', '同层约束未满足', rule.nodes);
    }
  }
  return { ok: count.errors === 0, counts: count, issues, truncated: issues.length < count.errors + count.warnings };
}

function pathMidpoint(points: Point[]): Point {
  const lengths = points.slice(1).map((p, i) => Math.hypot(p.x - points[i].x, p.y - points[i].y));
  let remaining = lengths.reduce((a, b) => a + b, 0) / 2;
  for (const [i, length] of lengths.entries()) {
    if (length > 0 && remaining <= length) {
      const a = points[i];
      const b = points[i + 1];
      return { x: a.x + (b.x - a.x) * remaining / length, y: a.y + (b.y - a.y) * remaining / length };
    }
    remaining -= length;
  }
  return points[0];
}
