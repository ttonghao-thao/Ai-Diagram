import type { Geometry, GraphDocument, GraphEdge, Point } from '../types.js';
import { edgeCellId, nodeCellId } from '../types.js';
import type { ResolvedDrawing, ResolvedEdge } from '../shapes/resolve.js';

const EPSILON = 0.001;
const CLEARANCE = 12;

export function center(box: Geometry): Point {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

export function overlaps(a: Geometry, b: Geometry, padding = 0): boolean {
  return a.x < b.x + b.width + padding - EPSILON && b.x < a.x + a.width + padding - EPSILON &&
    a.y < b.y + b.height + padding - EPSILON && b.y < a.y + a.height + padding - EPSILON;
}

/** Open-rectangle intersection, leaving tangent routes on reserved boundaries usable. */
export function crosses(a: Point, b: Point, box: Geometry): boolean {
  let tMin = 0;
  let tMax = 1;
  for (const [axis, size] of [['x', 'width'], ['y', 'height']] as const) {
    const low = box[axis] + EPSILON;
    const high = box[axis] + box[size] - EPSILON;
    const delta = b[axis] - a[axis];
    if (Math.abs(delta) < EPSILON) {
      if (a[axis] <= low || a[axis] >= high) return false;
      continue;
    }
    const t0 = (low - a[axis]) / delta;
    const t1 = (high - a[axis]) / delta;
    tMin = Math.max(tMin, Math.min(t0, t1));
    tMax = Math.min(tMax, Math.max(t0, t1));
    if (tMin >= tMax) return false;
  }
  return true;
}

export function pathCrosses(points: Point[], box: Geometry): boolean {
  return points.some((point, index) => index > 0 && crosses(points[index - 1], point, box));
}

export function labelBox(box: Geometry, size?: { width: number; height: number }): Geometry | undefined {
  if (!size?.height) return undefined;
  return { x: box.x + (box.width - size.width) / 2, y: box.y + box.height, ...size };
}

function clearPath(points: Point[], boxes: Geometry[]): boolean {
  return !boxes.some((box) => pathCrosses(points, box));
}

function compact(points: Point[]): Point[] {
  return points.filter((point, i) => i === 0 || point.x !== points[i - 1].x || point.y !== points[i - 1].y)
    .filter((point, i, all) => i === 0 || i === all.length - 1 ||
      !(['x', 'y'] as const).some((axis) => point[axis] === all[i - 1][axis] && point[axis] === all[i + 1][axis]));
}

function manhattan(a: Point, b: Point): number {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
}

function orthogonal(a: Point, b: Point, boxes: Geometry[], hints: Point[]): Point[] | undefined {
  const candidates = [[a, { x: b.x, y: a.y }, b], [a, { x: a.x, y: b.y }, b]];
  if (hints.length) {
    candidates.push([a, { x: a.x, y: hints[0].y }, ...hints, { x: b.x, y: hints.at(-1)!.y }, b]);
    candidates.push([a, { x: hints[0].x, y: a.y }, ...hints, { x: hints.at(-1)!.x, y: b.y }, b]);
  }
  // Test nearby corridors and the four outer corridors. Search remains
  // bounded for dense inputs, and the quality report retains any collision.
  const blockers = boxes.filter((box) => candidates.some((points) => pathCrosses(points, box))).slice(0, 16);
  const extents = boxes.length ? {
    minX: Math.min(...boxes.map((g) => g.x)), maxX: Math.max(...boxes.map((g) => g.x + g.width)),
    minY: Math.min(...boxes.map((g) => g.y)), maxY: Math.max(...boxes.map((g) => g.y + g.height)),
  } : undefined;
  const xs = new Set([(a.x + b.x) / 2, ...blockers.flatMap((g) => [g.x - CLEARANCE, g.x + g.width + CLEARANCE])]);
  const ys = new Set([(a.y + b.y) / 2, ...blockers.flatMap((g) => [g.y - CLEARANCE, g.y + g.height + CLEARANCE])]);
  if (extents) {
    xs.add(extents.minX - CLEARANCE); xs.add(extents.maxX + CLEARANCE);
    ys.add(extents.minY - CLEARANCE); ys.add(extents.maxY + CLEARANCE);
  }
  for (const x of xs) candidates.push([a, { x, y: a.y }, { x, y: b.y }, b]);
  for (const y of ys) candidates.push([a, { x: a.x, y }, { x: b.x, y }, b]);
  return candidates.map(compact).filter((path) => path.every((p, i) => !i || p.x === path[i - 1].x || p.y === path[i - 1].y))
    .sort((p, q) => length(p) - length(q) || p.length - q.length).find((path) => clearPath(path, boxes));
}

function length(points: Point[]): number {
  return points.reduce((sum, p, i) => sum + (i ? manhattan(p, points[i - 1]) : 0), 0);
}

function attachment(box: Geometry, next: Point): [number, number] {
  const p = center(box);
  const dx = next.x - p.x;
  const dy = next.y - p.y;
  return Math.abs(dx) > Math.abs(dy) ? [dx < 0 ? 0 : 1, 0.5] : [0.5, dy < 0 ? 0 : 1];
}

function routeStyle(edge: ResolvedEdge, source: Geometry, target: Geometry, points: Point[], useBends: boolean, legacy: boolean): string {
  const base = edge.style.endsWith(';') ? edge.style : edge.style + ';';
  if (!useBends) return base;
  const a = center(source);
  const b = center(target);
  if (!points.length && a.x === b.x && a.y === b.y) return 'edgeStyle=orthogonalEdgeStyle;' + base;
  const [exitX, exitY] = attachment(source, points[0] ?? center(target));
  const [entryX, entryY] = attachment(target, points.at(-1) ?? center(source));
  const routingStyle = points.length && !legacy ? 'edgeStyle=segmentEdgeStyle' : 'edgeStyle=orthogonalEdgeStyle';
  // Explicit endpoint anchors from the caller stay above automatic anchors.
  return `${routingStyle};exitX=${exitX};exitY=${exitY};entryX=${entryX};entryY=${entryY};${base}`;
}

export function routeDrawing(
  doc: GraphDocument, drawing: ResolvedDrawing, geometries: Map<string, Geometry>,
  hints = new Map<string, Point[]>(), extraObstacles: Geometry[] = [],
): Map<string, Point[]> {
  const obstacles = doc.nodes.flatMap((node) => {
    const box = geometries.get(nodeCellId(node.id));
    if (!box) return [];
    const label = labelBox(box, drawing.nodes[node.id].labelSize);
    return [{ id: node.id, box }, ...(label ? [{ id: node.id, box: label }] : [])];
  });
  const paths = new Map<string, Point[]>();
  for (const graphEdge of doc.edges) {
    const edge = drawing.edges[graphEdge.id];
    const source = geometries.get(nodeCellId(graphEdge.source));
    const target = geometries.get(nodeCellId(graphEdge.target));
    if (!source || !target) continue;
    const boxes = obstacles.filter((obstacle) => obstacle.id !== graphEdge.source && obstacle.id !== graphEdge.target)
      .map(({ box }) => box).concat(extraObstacles);
    const a = center(source);
    const b = center(target);
    const manual = graphEdge.waypoints;
    const useBends = !manual && (edge.routing === 'orthogonal' ||
      (edge.routing === 'auto' && (!clearPath([a, b], boxes) || graphEdge.source === graphEdge.target)));
    const waypoints = manual ?? (useBends ? orthogonal(a, b, boxes, hints.get(edgeCellId(graphEdge.id)) ?? [])?.slice(1, -1) : undefined) ?? [];
    edge.waypoints = waypoints;
    edge.style = routeStyle(edge, source, target, waypoints, useBends, doc.schemaVersion === '1.0');
    if (pathCrosses([a, ...waypoints, b], source) && graphEdge.source === graphEdge.target && !waypoints.length) {
      edge.style = 'orthogonalLoop=1;loopStyle=loopEdgeStyle;' + edge.style;
    }
    if (waypoints.length) paths.set(edgeCellId(graphEdge.id), waypoints);
  }
  return paths;
}

export function pathForEdge(edge: GraphEdge, points: Point[], geometries: Map<string, Geometry>): Point[] {
  const source = geometries.get(nodeCellId(edge.source));
  const target = geometries.get(nodeCellId(edge.target));
  return source && target ? [center(source), ...points, center(target)] : [];
}
