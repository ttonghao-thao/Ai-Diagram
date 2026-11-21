/**
 * First-time layout via ELK.js layered algorithm, and a manual mode that
 * honors provided absolute geometry. All output geometry is in absolute
 * canvas coordinates (docs/03 section 2). Conversion to draw.io relative
 * coordinates happens only in the XML serializer.
 */
import ELK from 'elkjs/lib/elk.bundled.js';
import { ErrorCodes, RenderError } from '../errors.js';
import { LABEL_BAND_HEIGHT, resolveNodeSize } from '../shapes/iconRegistry.js';
import { groupCellId, nodeCellId, edgeCellId } from '../types.js';
import type { Geometry, GraphDocument, GraphGroup, GraphNode, Point } from '../types.js';

export interface LayoutOutput {
  /** Absolute geometry per cell id (nodes with `n_`, groups with `g_` prefixes). */
  geometries: Map<string, Geometry>;
  /** Absolute bend points per edge cell id (`e_` prefix), root coordinate frame. */
  edgeWaypoints: Map<string, Point[]>;
  pageWidth: number;
  pageHeight: number;
}

const CANVAS_MARGIN = 40;
const MIN_PAGE_WIDTH = 900;
const MIN_PAGE_HEIGHT = 600;

const GROUP_PADDING = '[top=48,left=20,bottom=20,right=20]';

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

/** ELK box = icon box + label band (labels render below icons; docs Phase 0.5). */
function leafElkSize(node: GraphNode): { width: number; height: number } {
  const size = resolveNodeSize(node);
  return { width: size.width, height: size.height + LABEL_BAND_HEIGHT };
}

function buildElkTree(index: GraphIndex, doc: GraphDocument): ElkNode {
  const buildGroup = (group: GraphGroup): ElkNode => ({
    id: groupCellId(group.id),
    layoutOptions: { 'elk.padding': GROUP_PADDING },
    children: [
      ...(index.groupsByParent.get(group.id) ?? []).map(buildGroup),
      ...(index.nodesByGroup.get(group.id) ?? []).map(buildLeaf),
    ],
  });
  const buildLeaf = (node: GraphNode): ElkNode => {
    const size = leafElkSize(node);
    return { id: nodeCellId(node.id), width: size.width, height: size.height };
  };
  return {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': doc.layout.direction,
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      'elk.spacing.nodeNode': '48',
      'elk.layered.spacing.nodeNodeBetweenLayers': '80',
      'elk.layered.spacing.edgeNodeBetweenLayers': '36',
      'elk.nodeSize.constraints': 'NODES',
    },
    children: [
      ...(index.groupsByParent.get(undefined) ?? []).map(buildGroup),
      ...(index.nodesByGroup.get(undefined) ?? []).map(buildLeaf),
    ],
    edges: doc.edges.map((e) => ({
      id: edgeCellId(e.id),
      sources: [nodeCellId(e.source)],
      targets: [nodeCellId(e.target)],
    })),
  };
}

/** Collect ELK results into absolute geometry. ELK child coords are parent-relative. */
function collectElkResults(result: ElkNode): {
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
      // Leaf node boxes were inflated by the label band for layout; the
      // recorded geometry is the icon box (labels live outside the shape).
      const isLeaf = child.id.startsWith('n_');
      const height = isLeaf
        ? Math.max((child.height ?? 0) - LABEL_BAND_HEIGHT, 1)
        : (child.height ?? 0);
      geometries.set(child.id, {
        x: round2(ax),
        y: round2(ay),
        width: round2(child.width ?? 0),
        height: round2(height),
      });
      walk(child, ax, ay);
      for (const e of child.edges ?? []) collectEdge(e, ax, ay);
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
function layoutManual(doc: GraphDocument, index: GraphIndex): Map<string, Geometry> {
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
      const size = resolveNodeSize(n);
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

/**
 * Compute the first layout. For `layered`, ELK.js decides every position and
 * group size (provided node width/height are kept as fixed sizes). For
 * `manual`, provided absolute geometry is used as-is.
 */
export async function layoutGraph(doc: GraphDocument): Promise<LayoutOutput> {
  const index = indexGraph(doc);
  let geometries: Map<string, Geometry>;
  let edgeWaypoints = new Map<string, Point[]>();

  if (doc.layout.algorithm === 'manual') {
    geometries = layoutManual(doc, index);
    for (const e of doc.edges) {
      if (e.waypoints?.length) {
        edgeWaypoints.set(edgeCellId(e.id), e.waypoints.map((p) => ({ ...p })));
      }
    }
  } else {
    const elk = new ELK();
    const tree = buildElkTree(index, doc);
    let result: ElkNode;
    try {
      result = (await elk.layout(tree as never)) as unknown as ElkNode;
    } catch (err) {
      throw new RenderError(
        ErrorCodes.GRAPH_LAYOUT_FAILED,
        `ELK.js layout failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    const collected = collectElkResults(result);
    geometries = collected.geometries;
    edgeWaypoints = collected.edgeWaypoints;
    // Edges may declare explicit waypoints (manual positions to keep); ELK
    // recomputes first layouts, so declared waypoints win only in manual mode.
  }

  const page = normalize(geometries, edgeWaypoints, doc.layout.algorithm === 'layered');
  return { geometries, edgeWaypoints, pageWidth: page.pageWidth, pageHeight: page.pageHeight };
}
