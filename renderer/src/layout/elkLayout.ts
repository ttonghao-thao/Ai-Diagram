/**
 * First-time layout via ELK.js layered algorithm, and a manual mode that
 * honors provided absolute geometry. All output geometry is in absolute
 * canvas coordinates (docs/03 section 2). Conversion to draw.io relative
 * coordinates happens only in the XML serializer.
 */
import ELK from 'elkjs/lib/elk.bundled.js';
import { ErrorCodes, RenderError } from '../errors.js';
import { resolveDrawing, type ResolvedDrawing } from '../shapes/resolve.js';
import { deviceTypeOf } from '../shapes/catalog.js';
import { applyConstraints, fixedCells, rankAxis } from './constraints.js';
import { labelBox, overlaps, routeDrawing } from '../routing/edgeRouter.js';
import { orientEdgesForLayout } from './networkTier.js';
import { groupCellId, nodeCellId, edgeCellId } from '../types.js';
import type { Geometry, GraphDocument, GraphGroup, GraphNode, Point } from '../types.js';

export interface LayoutOutput {
  /** Absolute geometry per cell id (nodes with `n_`, groups with `g_` prefixes). */
  geometries: Map<string, Geometry>;
  /** Absolute bend points per edge cell id (`e_` prefix), root coordinate frame. */
  edgeWaypoints: Map<string, Point[]>;
  drawing?: ResolvedDrawing;
  pageWidth: number;
  pageHeight: number;
}

const CANVAS_MARGIN = 40;
const MIN_PAGE_WIDTH = 900;
const MIN_PAGE_HEIGHT = 600;

interface ElkNode {
  id: string;
  width?: number;
  height?: number;
  x?: number;
  y?: number;
  children?: ElkNode[];
  edges?: ElkEdge[];
  layoutOptions?: Record<string, string>;
}

interface ElkEdge {
  id: string;
  sources: string[];
  targets: string[];
  sections?: Array<{
    id?: string;
    startPoint?: Point;
    endPoint?: Point;
    bendPoints?: Point[];
  }>;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

interface GraphIndex {
  nodesById: Map<string, GraphNode>;
  groupsById: Map<string, GraphGroup>;
  nodesByGroup: Map<string | undefined, GraphNode[]>;
  groupsByParent: Map<string | undefined, GraphGroup[]>;
}

function indexGraph(doc: GraphDocument): GraphIndex {
  const nodesById = new Map(doc.nodes.map((n) => [n.id, n]));
  const groupsById = new Map(doc.groups.map((g) => [g.id, g]));
  const nodesByGroup = new Map<string | undefined, GraphNode[]>();
  const groupsByParent = new Map<string | undefined, GraphGroup[]>();
  for (const n of doc.nodes) {
    const key = n.groupId ?? undefined;
    const list = nodesByGroup.get(key) ?? [];
    list.push(n);
    nodesByGroup.set(key, list);
  }
  for (const g of doc.groups) {
    const key = g.parentId ?? undefined;
    const list = groupsByParent.get(key) ?? [];
    list.push(g);
    groupsByParent.set(key, list);
  }
  return { nodesById, groupsById, nodesByGroup, groupsByParent };
}

function buildElkTree(index: GraphIndex, doc: GraphDocument, drawing: ResolvedDrawing): ElkNode {
  const { nodeSpacing, layerSpacing, groupPadding } = drawing.theme.layout;
  const ordering: Record<string, string> = doc.diagramType === 'network_topology' && doc.schemaVersion === '1.0'
    ? { 'elk.layered.crossingMinimization.forceNodeModelOrder': 'true' } : {};
  const spacing: Record<string, string> = {
    'elk.spacing.nodeNode': String(nodeSpacing),
    'elk.layered.spacing.nodeNodeBetweenLayers': String(layerSpacing),
    'elk.layered.spacing.edgeNodeBetweenLayers': '36',
  };
  const buildGroup = (group: GraphGroup): ElkNode => ({
    id: groupCellId(group.id),
    layoutOptions: { 'elk.padding': `[top=${32 + groupPadding},left=${groupPadding},bottom=${groupPadding},right=${groupPadding}]`, ...spacing },
    children: [
      ...(index.groupsByParent.get(group.id) ?? []).map(buildGroup),
      ...(index.nodesByGroup.get(group.id) ?? []).map(buildLeaf),
    ],
  });
  const buildLeaf = (node: GraphNode): ElkNode => {
    const size = drawing.nodes[node.id].layoutSize;
    return { id: nodeCellId(node.id), width: size.width, height: size.height };
  };
  return {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': doc.layout.direction,
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      ...spacing,
      ...ordering,
      'elk.nodeSize.constraints': 'NODES',
    },
    children: [
      ...(index.groupsByParent.get(undefined) ?? []).map(buildGroup),
      ...(index.nodesByGroup.get(undefined) ?? []).map(buildLeaf),
    ],
    // Layout-only orientation: undirected edges flow from the higher network
    // tier so "公网 → 防火墙 → 核心交换机 → 服务器" comes out top-down even
    // when the sentence listed them from the switch outward. The semantic
    // source/target in the document and XML are not modified.
    edges: orientEdgesForLayout(doc).map(({ edge, source, target }) => ({
      id: edgeCellId(edge.id),
      sources: [nodeCellId(source)],
      targets: [nodeCellId(target)],
    })),
  };
}

/** Collect ELK results into absolute geometry. ELK child coords are parent-relative. */
function collectElkResults(result: ElkNode, drawing: ResolvedDrawing): {
  geometries: Map<string, Geometry>;
  edgeWaypoints: Map<string, Point[]>;
} {
  const geometries = new Map<string, Geometry>();
  const edgeWaypoints = new Map<string, Point[]>();

  const collectEdge = (edge: ElkEdge, ox: number, oy: number): void => {
    const points: Point[] = [];
    for (const section of edge.sections ?? []) {
      for (const bend of section.bendPoints ?? []) {
        points.push({ x: ox + bend.x, y: oy + bend.y });
      }
    }
    if (points.length) {
      edgeWaypoints.set(edge.id, points);
    }
  };

  const walk = (container: ElkNode, ox: number, oy: number): void => {
    for (const child of container.children ?? []) {
      const ax = ox + (child.x ?? 0);
      const ay = oy + (child.y ?? 0);
      const icon = child.id.startsWith('n_') ? drawing.nodes[child.id.slice(2)]?.iconSize : undefined;
      geometries.set(child.id, {
        x: round2(ax + (icon ? ((child.width ?? 0) - icon.width) / 2 : 0)),
        y: round2(ay),
        width: icon?.width ?? (child.width ?? 0),
        height: icon?.height ?? (child.height ?? 0),
      });
      walk(child, ax, ay);
    }
    for (const e of container.edges ?? []) collectEdge(e, ox, oy);
  };
  walk(result, 0, 0);
  return { geometries, edgeWaypoints };
}

/**
 * Manual mode: honor provided absolute geometry; compute bounding boxes for
 * groups without geometry; grid-place nodes without geometry below content.
 */
function layoutManual(doc: GraphDocument, index: GraphIndex, drawing: ResolvedDrawing): Map<string, Geometry> {
  const geometries = new Map<string, Geometry>();
  const placedNodes = new Set<string>();

  // 1. Nodes with explicit geometry.
  for (const n of doc.nodes) {
    if (n.geometry) {
      geometries.set(nodeCellId(n.id), { ...n.geometry });
      placedNodes.add(n.id);
    }
  }
  // 2. Groups deepest-first: explicit geometry wins, otherwise wrap members.
  const depthOf = (g: GraphGroup): number => {
    let depth = 0;
    let cur: GraphGroup | undefined = g;
    while (cur?.parentId) {
      cur = index.groupsById.get(cur.parentId);
      depth += 1;
    }
    return depth;
  };
  const sortedGroups = [...doc.groups].sort((a, b) => depthOf(b) - depthOf(a));
  for (const g of sortedGroups) {
    if (g.geometry) {
      geometries.set(groupCellId(g.id), { ...g.geometry });
      continue;
    }
    const members: Geometry[] = [];
    for (const child of index.nodesByGroup.get(g.id) ?? []) {
      const geo = geometries.get(nodeCellId(child.id));
      if (geo) members.push(geo);
    }
    for (const child of index.groupsByParent.get(g.id) ?? []) {
      const geo = geometries.get(groupCellId(child.id));
      if (geo) members.push(geo);
    }
    if (members.length) {
      const minX = Math.min(...members.map((m) => m.x));
      const minY = Math.min(...members.map((m) => m.y));
      const maxX = Math.max(...members.map((m) => m.x + m.width));
      const maxY = Math.max(...members.map((m) => m.y + m.height));
      geometries.set(groupCellId(g.id), {
        x: round2(minX - 24),
        y: round2(minY - 48),
        width: round2(maxX - minX + 48),
        height: round2(maxY - minY + 72),
      });
    } else {
      // Empty group: place a default box below current content.
      const maxY = Math.max(0, ...[...geometries.values()].map((m) => m.y + m.height));
      geometries.set(groupCellId(g.id), { x: CANVAS_MARGIN, y: round2(maxY + 80), width: 300, height: 160 });
    }
  }
  // 3. Nodes without geometry: deterministic grid below existing content.
  const missing = doc.nodes.filter((n) => !placedNodes.has(n.id));
  if (missing.length) {
    const maxY = Math.max(0, ...[...geometries.values()].map((m) => m.y + m.height));
    const perRow = 4;
    missing.forEach((n, i) => {
      const size = drawing.nodes[n.id].iconSize;
      const row = Math.floor(i / perRow);
      const col = i % perRow;
      geometries.set(nodeCellId(n.id), {
        x: round2(CANVAS_MARGIN + col * 240),
        y: round2(maxY + 80 + row * (size.height + 60)),
        width: size.width,
        height: size.height,
      });
    });
  }
  return geometries;
}

/**
 * Compute page size; for `layered` output also shift coordinates so content
 * starts at CANVAS_MARGIN. Manual mode never shifts: user-provided absolute
 * geometry must be preserved exactly (docs/03 section 6).
 */
function normalize(geometries: Map<string, Geometry>, edgeWaypoints: Map<string, Point[]>, shiftToMargin: boolean): {
  pageWidth: number;
  pageHeight: number;
} {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const consider = (x: number, y: number, w: number, h: number): void => {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + w);
    maxY = Math.max(maxY, y + h);
  };
  for (const g of geometries.values()) consider(g.x, g.y, g.width, g.height);
  for (const pts of edgeWaypoints.values()) {
    for (const p of pts) consider(p.x, p.y, 0, 0);
  }
  if (minX === Infinity) {
    return { pageWidth: MIN_PAGE_WIDTH, pageHeight: MIN_PAGE_HEIGHT };
  }
  let dx = 0;
  let dy = 0;
  if (shiftToMargin) {
    dx = round2(CANVAS_MARGIN - minX);
    dy = round2(CANVAS_MARGIN - minY);
    if (dx !== 0 || dy !== 0) {
      for (const g of geometries.values()) {
        g.x = round2(g.x + dx);
        g.y = round2(g.y + dy);
      }
      for (const pts of edgeWaypoints.values()) {
        for (const p of pts) {
          p.x = round2(p.x + dx);
          p.y = round2(p.y + dy);
        }
      }
    }
  }
  return {
    pageWidth: Math.max(MIN_PAGE_WIDTH, Math.ceil(maxX + dx + CANVAS_MARGIN)),
    pageHeight: Math.max(MIN_PAGE_HEIGHT, Math.ceil(maxY + dy + CANVAS_MARGIN)),
  };
}

function reorderNumbered(doc: GraphDocument, geometries: Map<string, Geometry>, fixed: Set<string>): boolean {
  if (doc.diagramType !== 'network_topology') return false;
  const rank = rankAxis(doc);
  const axis = rank === 'x' ? 'y' : 'x';
  const collections = new Map<string, { number: number; box: Geometry }[]>();
  const explicit = new Set((doc.layout.constraints ?? []).flatMap((rule) => rule.type === 'order' ? rule.nodes : []));
  for (const node of doc.nodes) {
    const id = nodeCellId(node.id);
    const match = /^(.*?)\s*([0-9]+)$/u.exec(node.label.normalize('NFKC'));
    if (!match || fixed.has(id) || explicit.has(node.id)) continue;
    const box = geometries.get(id)!;
    const key = JSON.stringify([node.groupId, deviceTypeOf(node), match[1].trim(), Math.round(box[rank] / 2)]);
    const group = collections.get(key) ?? [];
    group.push({ number: Number(match[2]), box });
    collections.set(key, group);
  }
  let moved = false;
  for (const devices of collections.values()) {
    const positions = devices.map(({ box }) => box[axis]).sort((a, b) => a - b);
    devices.sort((a, b) => a.number - b.number).forEach(({ box }, i) => {
      if (box[axis] !== positions[i]) moved = true;
      box[axis] = positions[i];
    });
  }
  return moved;
}

function layoutStar(doc: GraphDocument, drawing: ResolvedDrawing): Map<string, Geometry> {
  const boxes = new Map<string, Geometry>();
  if (!doc.nodes.length) return boxes;
  const degrees = new Map<string, number>();
  for (const { source, target } of doc.edges) {
    degrees.set(source, (degrees.get(source) ?? 0) + 1);
    degrees.set(target, (degrees.get(target) ?? 0) + 1);
  }
  const center = doc.layout.centerNodeId ?? [...doc.nodes].sort((a, b) => (degrees.get(b.id) ?? 0) - (degrees.get(a.id) ?? 0))[0].id;
  const others = doc.nodes.filter(({ id }) => id !== center);
  const maxSpan = Math.max(...Object.values(drawing.nodes).map(({ layoutSize }) => Math.hypot(layoutSize.width, layoutSize.height)));
  const radius = Math.max(maxSpan + 48, (maxSpan + 30) / (2 * Math.sin(Math.PI / Math.max(2, others.length))));
  const start = { DOWN: Math.PI / 2, UP: -Math.PI / 2, LEFT: Math.PI, RIGHT: 0 }[doc.layout.direction];
  const assign = (id: string, x: number, y: number) => {
    const size = drawing.nodes[id].iconSize;
    boxes.set(nodeCellId(id), { ...size, x: x - size.width / 2, y: y - size.height / 2 });
  };
  assign(center, 0, 0);
  others.forEach(({ id }, i) => {
    const angle = start + 2 * Math.PI * i / others.length;
    assign(id, radius * Math.cos(angle), radius * Math.sin(angle));
  });
  return boxes;
}

/** Refit group containers after constraints or local insertion, inside-out. */
export function fitGroups(
  doc: GraphDocument, drawing: ResolvedDrawing, geometries: Map<string, Geometry>, fixed: Set<string>, expandOnly = false,
): void {
  const index = indexGraph(doc);
  const pad = drawing.theme.layout.groupPadding;
  function fit(group: GraphGroup): Geometry {
    const id = groupCellId(group.id);
    const old = geometries.get(id);
    const members = (index.groupsByParent.get(group.id) ?? []).map(fit);
    for (const node of index.nodesByGroup.get(group.id) ?? []) {
      const box = geometries.get(nodeCellId(node.id));
      if (box) {
        members.push(box);
        const label = labelBox(box, drawing.nodes[node.id].labelSize);
        if (label) members.push(label);
      }
    }
    if (old && (fixed.has(id) || !members.length)) return old;
    const left = members.length ? Math.min(...members.map((g) => g.x)) - pad : 40;
    const top = members.length ? Math.min(...members.map((g) => g.y)) - pad - 32 : 40;
    const x = expandOnly && old ? old.x : left;
    const y = expandOnly && old ? old.y : top;
    const minimumRight = x + Math.max(180, old && expandOnly ? old.width : 180);
    const minimumBottom = y + Math.max(100, old && expandOnly ? old.height : 100);
    const right = Math.max(minimumRight, ...members.map((g) => g.x + g.width + pad));
    const bottom = Math.max(minimumBottom, ...members.map((g) => g.y + g.height + pad));
    const result = { x, y, width: right - x, height: bottom - y };
    geometries.set(id, result);
    return result;
  }
  for (const root of index.groupsByParent.get(undefined) ?? []) fit(root);
}

function addLabelBoxes(doc: GraphDocument, drawing: ResolvedDrawing, geometries: Map<string, Geometry>, extent: Map<string, Geometry>): void {
  for (const node of doc.nodes) {
    const box = geometries.get(nodeCellId(node.id))!;
    const label = labelBox(box, drawing.nodes[node.id].labelSize);
    if (label) extent.set('label_' + node.id, label);
  }
}

function repairOverlaps(
  doc: GraphDocument, drawing: ResolvedDrawing, geometries: Map<string, Geometry>, fixed: Set<string>,
  extra: Geometry[],
): boolean {
  const constrained = new Set((doc.layout.constraints ?? []).flatMap((rule) =>
    rule.type === 'relativePosition' ? [rule.source, rule.target] : rule.nodes));
  const axis = rankAxis(doc) === 'x' ? 'y' : 'x';
  const dimension = axis === 'x' ? 'width' : 'height';
  const footprint = (node: GraphNode) => {
    const geometry = geometries.get(nodeCellId(node.id))!;
    const label = labelBox(geometry, drawing.nodes[node.id].labelSize);
    return label ? { ...label, y: geometry.y, height: geometry.height + label.height } : { ...geometry };
  };
  const obstacles = [...extra];
  const free: GraphNode[] = [];
  for (const node of doc.nodes) {
    if (fixed.has(nodeCellId(node.id)) || constrained.has(node.id) || node.properties?.tier !== undefined || node.groupId) {
      obstacles.push(footprint(node));
    } else {
      free.push(node);
    }
  }
  let changed = false;
  for (const node of free) {
    const box = footprint(node);
    const geometry = geometries.get(nodeCellId(node.id))!;
    for (let step = 0; step < obstacles.length; step++) {
      const collision = obstacles.find((other) => overlaps(box, other));
      if (!collision) break;
      const distance = collision[axis] + collision[dimension] + drawing.theme.layout.nodeSpacing - box[axis];
      box[axis] += distance;
      geometry[axis] += distance;
      changed = true;
    }
    obstacles.push(box);
  }
  return changed;
}

export function finishLayout(
  doc: GraphDocument, drawing: ResolvedDrawing, geometries: Map<string, Geometry>,
  hints = new Map<string, Point[]>(), obstacles: Geometry[] = [],
): LayoutOutput {
  const edgeWaypoints = routeDrawing(doc, drawing, geometries, hints, obstacles);
  const extent = new Map(geometries);
  addLabelBoxes(doc, drawing, geometries, extent);
  const page = normalize(extent, edgeWaypoints, false);
  for (const node of doc.nodes) drawing.nodes[node.id].geometry = geometries.get(nodeCellId(node.id));
  for (const group of doc.groups) drawing.groups[group.id].geometry = geometries.get(groupCellId(group.id));
  return { geometries, edgeWaypoints, ...page, drawing };
}

export async function layoutGraph(
  doc: GraphDocument, drawing = resolveDrawing(doc), obstacles: Geometry[] = [],
): Promise<LayoutOutput> {
  const index = indexGraph(doc);
  const fixed = fixedCells(doc);
  let geometries: Map<string, Geometry>;
  let hints = new Map<string, Point[]>();
  if (doc.layout.algorithm === 'manual') {
    geometries = layoutManual(doc, index, drawing);
    const manual = new Set([
      ...fixed,
      ...doc.nodes.filter((node) => node.geometry).map(({ id }) => nodeCellId(id)),
      ...doc.groups.filter((group) => group.geometry).map(({ id }) => groupCellId(id)),
    ]);
    applyConstraints(doc, drawing, geometries, manual);
    fitGroups(doc, drawing, geometries, manual);
  } else {
    if (doc.layout.algorithm === 'star') {
      geometries = layoutStar(doc, drawing);
    } else {
      const tree = buildElkTree(index, doc, drawing);
      try {
        const result = await new ELK().layout(tree as never) as unknown as ElkNode;
        ({ geometries, edgeWaypoints: hints } = collectElkResults(result, drawing));
      } catch (err) {
        throw new RenderError(ErrorCodes.GRAPH_LAYOUT_FAILED, `ELK.js layout failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    for (const node of doc.nodes) if (fixed.has(nodeCellId(node.id))) geometries.set(nodeCellId(node.id), { ...node.geometry! });
    for (const group of doc.groups) if (fixed.has(groupCellId(group.id))) geometries.set(groupCellId(group.id), { ...group.geometry! });
    const reordered = reorderNumbered(doc, geometries, fixed);
    const constrained = applyConstraints(doc, drawing, geometries, fixed);
    const repaired = repairOverlaps(doc, drawing, geometries, fixed, obstacles);
    if (reordered || constrained || repaired || fixed.size || doc.layout.algorithm === 'star') {
      fitGroups(doc, drawing, geometries, fixed);
      hints.clear();
    }
    if (!fixed.size && !obstacles.length && !doc.edges.some((edge) => edge.waypoints?.length)) {
      const footprints = new Map(geometries);
      addLabelBoxes(doc, drawing, geometries, footprints);
      normalize(footprints, hints, true);
    }
  }
  return finishLayout(doc, drawing, geometries, hints, obstacles);
}
