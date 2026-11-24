/**
 * TypeScript mirror of contracts/graph.schema.json (GraphDocument v1).
 * The JSON Schema in contracts/ remains the authoritative contract; these
 * types are used by the renderer and must stay in sync.
 */

export type DiagramType = 'network_topology' | 'business_architecture';

export type NodeKind =
  | 'switch'
  | 'router'
  | 'firewall'
  | 'server'
  | 'vm'
  | 'cloud'
  | 'service'
  | 'database'
  | 'client'
  | 'generic';

export type EdgeKind = 'physical' | 'logical' | 'dataflow' | 'control' | 'dependency';

export type EdgeDirection = 'undirected' | 'forward' | 'bidirectional';

export type NodeOrigin = 'explicit' | 'ai' | 'imported';

export type LayoutAlgorithm = 'layered' | 'manual' | 'star' | 'grouped';

export type LayoutDirection = 'DOWN' | 'RIGHT' | 'UP' | 'LEFT';

export type Axis = 'x' | 'y';
export type LayoutConstraint =
  | { type: 'sameRank'; nodes: string[] }
  | { type: 'order'; axis: Axis; nodes: string[] }
  | { type: 'align'; axis: Axis; mode: 'start' | 'center' | 'end'; nodes: string[] }
  | { type: 'relativePosition'; source: string; target: string; position: 'above' | 'below' | 'left' | 'right' }
  | { type: 'rank'; rank: number; nodes: string[] }
  | { type: 'preservePosition'; nodes: string[] };

export interface Appearance {
  themeId?: string;
  edgeRouting?: 'auto' | 'straight' | 'orthogonal';
  edgeLabelPolicy?: 'hidden' | 'explicit_only' | 'all';
  edgeArrowPolicy?: 'semantic' | 'hidden';
  showGroups?: boolean;
}

/** Style entries as allowed by graph.schema.json ($defs/style). */
export type StyleValue = string | number | boolean;
export type StyleMap = Record<string, StyleValue>;

/** metadata/properties values as allowed by graph.schema.json. */
export type MetadataValue = string | number | boolean | null;

export interface Geometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: NodeKind;
  groupId?: string | null;
  properties?: Record<string, MetadataValue>;
  geometry?: Geometry;
  manualLocked?: boolean;
  style?: StyleMap;
  origin?: NodeOrigin;
}

export interface GraphGroup {
  id: string;
  label: string;
  parentId?: string | null;
  geometry?: Geometry;
  manualLocked?: boolean;
  style?: StyleMap;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  direction: EdgeDirection;
  label?: string;
  sourcePort?: string;
  targetPort?: string;
  waypoints?: Point[];
  style?: StyleMap;
}

export interface LayoutSpec {
  algorithm: LayoutAlgorithm;
  direction: LayoutDirection;
  preserveManualPositions: boolean;
  constraints?: LayoutConstraint[];
  centerNodeId?: string;
}

export interface GraphWarning {
  code: string;
  message: string;
  relatedIds?: string[];
  requiresConfirmation: boolean;
}

export interface GraphDocument {
  schemaVersion: '1.0' | '1.1';
  diagramId: string;
  name: string;
  diagramType: DiagramType;
  nodes: GraphNode[];
  groups: GraphGroup[];
  edges: GraphEdge[];
  layout: LayoutSpec;
  appearance?: Appearance;
  metadata?: Record<string, MetadataValue>;
  warnings?: GraphWarning[];
}

/**
 * Stable cell id mapping between graph objects and mxCell ids (docs/02 section 7).
 */
export const CELL_PREFIX = {
  node: 'n_',
  group: 'g_',
  edge: 'e_',
} as const;

export function nodeCellId(id: string): string {
  return CELL_PREFIX.node + id;
}

export function groupCellId(id: string): string {
  return CELL_PREFIX.group + id;
}

export function edgeCellId(id: string): string {
  return CELL_PREFIX.edge + id;
}
