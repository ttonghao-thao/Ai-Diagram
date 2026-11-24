import { RenderError } from '../errors.js';
import { groupCellId, nodeCellId, type Axis, type Geometry, type GraphDocument } from '../types.js';
import type { ResolvedDrawing } from '../shapes/resolve.js';

interface MinimumGap { before: string; after: string; gap: number }
const TOLERANCE = 0.02;
const extent = { x: 'width', y: 'height' } as const;

export function layoutConflict(message: string): never {
  throw new RenderError('LAYOUT_CONFLICT', message);
}

export function rankAxis(doc: GraphDocument): Axis {
  return ['DOWN', 'UP'].includes(doc.layout.direction) ? 'y' : 'x';
}

export function fixedCells(doc: GraphDocument): Set<string> {
  const pinned = new Set((doc.layout.constraints ?? []).flatMap((constraint) =>
    constraint.type === 'preservePosition' ? constraint.nodes : []));
  const locked = (obj: GraphDocument['nodes'][number] | GraphDocument['groups'][number]) =>
    pinned.has(obj.id) || doc.layout.preserveManualPositions && obj.manualLocked;
  for (const id of pinned) {
    const obj = doc.nodes.find((node) => node.id === id) ?? doc.groups.find((group) => group.id === id);
    if (!obj?.geometry) layoutConflict(`preservePosition 缺少原位置：${id}`);
  }
  return new Set([
    ...doc.nodes.filter((node) => node.geometry && locked(node)).map((node) => nodeCellId(node.id)),
    ...doc.groups.filter((group) => group.geometry && locked(group)).map((group) => groupCellId(group.id)),
  ]);
}

function solve(edges: MinimumGap[], preferred: Map<string, number>, pins: Map<string, number>): Map<string, number> {
  const ids = new Set(edges.flatMap(({ before, after }) => [before, after]));
  const upper = new Map(pins);
  const value = new Map(preferred);
  for (let pass = 0; pass < ids.size; pass++) {
    let changed = false;
    for (const { before, after, gap } of edges) {
      const limit = (upper.get(after) ?? Infinity) - gap;
      if (limit < (upper.get(before) ?? Infinity) - TOLERANCE) {
        upper.set(before, limit);
        changed = true;
      }
    }
    if (!changed) break;
  }
  for (const id of ids) value.set(id, Math.min(preferred.get(id)!, upper.get(id) ?? Infinity));
  for (const [id, required] of pins) {
    if ((upper.get(id) ?? Infinity) < required - TOLERANCE) layoutConflict(`锁定对象与布局约束冲突：${id}`);
    value.set(id, required);
  }
  for (let pass = 0; pass < ids.size; pass++) {
    let changed = false;
    for (const { before, after, gap } of edges) {
      const required = value.get(before)! + gap;
      if (value.get(after)! >= required - TOLERANCE) continue;
      if (pins.has(after)) layoutConflict(`锁定对象与相对位置冲突：${after}`);
      value.set(after, required);
      changed = true;
    }
    if (!changed) return value;
  }
  if (edges.length) layoutConflict('布局约束相互冲突');
  return value;
}

export function applyConstraints(
  doc: GraphDocument, drawing: ResolvedDrawing, geometries: Map<string, Geometry>, fixed: Set<string>,
): boolean {
  const constraints = doc.layout.constraints ?? [];
  const primary = rankAxis(doc);
  let moved = false;
  for (const axis of ['x', 'y'] as const) {
    const gaps: MinimumGap[] = [];
    const base = new Map(doc.nodes.map(({ id }) => [id, geometries.get(nodeCellId(id))![axis]]));
    const pins = new Map([...base].filter(([id]) => fixed.has(nodeCellId(id))));
    const boxes = (id: string) => drawing.nodes[id].layoutSize[extent[axis]];
    const size = (id: string) => geometries.get(nodeCellId(id))![extent[axis]];
    const before = (a: string, b: string, gap = boxes(a) + drawing.theme.layout.nodeSpacing) => {
      gaps.push({ before: a, after: b, gap });
    };
    const align = (nodes: string[], fraction: number) => {
      for (const id of nodes.slice(1)) {
        const first = nodes[0];
        const offset = (size(first) - size(id)) * fraction;
        before(first, id, offset); before(id, first, -offset);
      }
    };
    for (const constraint of constraints) {
      if (constraint.type === 'sameRank' && axis === primary) align(constraint.nodes, 0.5);
      if (constraint.type === 'align' && constraint.axis === axis) {
        align(constraint.nodes, { start: 0, center: 0.5, end: 1 }[constraint.mode]);
      }
      if (constraint.type === 'order' && constraint.axis === axis) {
        for (let i = 1; i < constraint.nodes.length; i++) before(constraint.nodes[i - 1], constraint.nodes[i]);
      }
      if (constraint.type === 'relativePosition') {
        const { source, target, position } = constraint;
        if (axis === 'x' && position === 'left' || axis === 'y' && position === 'above') before(source, target);
        if (axis === 'x' && position === 'right' || axis === 'y' && position === 'below') before(target, source);
      }
    }
    if (axis === primary) {
      const ranks = new Map<string, number>();
      for (const node of doc.nodes) {
        const tier = node.properties?.tier;
        if (typeof tier === 'number' && Number.isInteger(tier) && tier >= 0 && tier <= 999) ranks.set(node.id, tier);
      }
      const explicitlyRanked = new Map<string, number>();
      for (const constraint of constraints) {
        if (constraint.type !== 'rank') continue;
        for (const id of constraint.nodes) {
          if (explicitlyRanked.has(id) && explicitlyRanked.get(id) !== constraint.rank) {
            layoutConflict(`设备被指定到两个不同层级：${id}`);
          }
          explicitlyRanked.set(id, constraint.rank);
          ranks.set(id, constraint.rank);
        }
      }
      const rows = new Map<number, string[]>();
      for (const [id, rank] of ranks) rows.set(rank, [...(rows.get(rank) ?? []), id]);
      const ordered = [...rows.keys()].sort((a, b) => (['UP', 'LEFT'].includes(doc.layout.direction) ? b - a : a - b));
      ordered.forEach((rank, i) => {
        const ids = rows.get(rank)!;
        align(ids, 0.5);
        if (i) {
          const above = rows.get(ordered[i - 1])!;
          const a = above[0];
          const b = ids[0];
          const gap = (Math.max(...above.map(boxes)) + Math.max(...ids.map(boxes))) / 2 +
            (size(a) - size(b)) / 2 + drawing.theme.layout.layerSpacing;
          before(a, b, gap);
        }
      });
    }
    if (!gaps.length) continue;
    for (const [id, coordinate] of solve(gaps, base, pins)) {
      const box = geometries.get(nodeCellId(id))!;
      if (Math.abs(box[axis] - coordinate) > TOLERANCE) moved = true;
      box[axis] = coordinate;
    }
  }
  return moved;
}
