/**
 * Structural (schema-shaped) and semantic validation for GraphDocument v1.
 * Mirrors backend/app/graph/validate.py; error codes match docs/04 section 3.
 */
import { ErrorCodes, GraphValidationError, issue, type ValidationIssue } from './errors.js';
import type {
  EdgeDirection,
  EdgeKind,
  Geometry,
  GraphDocument,
  GraphEdge,
  GraphGroup,
  GraphNode,
  LayoutAlgorithm,
  LayoutDirection,
  MetadataValue,
  NodeKind,
  StyleMap,
  StyleValue,
} from './types.js';

const ID_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;

const NODE_KINDS: readonly NodeKind[] = [
  'switch', 'router', 'firewall', 'server', 'vm', 'cloud', 'service', 'database', 'client', 'generic',
];
const EDGE_KINDS: readonly EdgeKind[] = ['physical', 'logical', 'dataflow', 'control', 'dependency'];
const EDGE_DIRECTIONS: readonly EdgeDirection[] = ['undirected', 'forward', 'bidirectional'];
const LAYOUT_ALGORITHMS: readonly LayoutAlgorithm[] = ['layered', 'manual'];
const LAYOUT_DIRECTIONS: readonly LayoutDirection[] = ['DOWN', 'RIGHT', 'UP', 'LEFT'];
const NODE_ORIGINS = ['explicit', 'ai', 'imported'] as const;

const MAX_NODES = 1000;
const MAX_GROUPS = 200;
const MAX_EDGES = 3000;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isMetadataValue(value: unknown): value is MetadataValue {
  return value === null || typeof value === 'string' || typeof value === 'number' ||
    typeof value === 'boolean';
}

function isStyleValue(value: unknown): value is StyleValue {
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
}

function isStyleMap(value: unknown): value is StyleMap {
  return isPlainObject(value) && Object.values(value).every(isStyleValue);
}

export class Validator {
  private readonly errors: ValidationIssue[] = [];
  private readonly warnings: ValidationIssue[] = [];

  private error(code: string, message: string, relatedIds: string[] = []): void {
    this.errors.push(issue(code, message, relatedIds, 'error'));
  }

  private warn(code: string, message: string, relatedIds: string[] = []): void {
    this.warnings.push(issue(code, message, relatedIds, 'warning'));
  }

  // ---- structural checks -------------------------------------------------

  private checkGeometry(value: unknown, where: string, ids: string[]): Geometry | null {
    if (value === undefined || value === null) {
      return null;
    }
    if (!isPlainObject(value)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.geometry must be an object`, ids);
      return null;
    }
    const g = value as Record<string, unknown>;
    const keys = Object.keys(g);
    if (keys.some((k) => !['x', 'y', 'width', 'height'].includes(k))) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.geometry has unknown keys (allowed: x, y, width, height)`, ids);
      return null;
    }
    for (const k of ['x', 'y', 'width', 'height'] as const) {
      if (typeof g[k] !== 'number' || !Number.isFinite(g[k] as number)) {
        this.error(ErrorCodes.SCHEMA_INVALID, `${where}.geometry.${k} must be a finite number`, ids);
        return null;
      }
    }
    if ((g.width as number) <= 0 || (g.height as number) <= 0) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.geometry width/height must be > 0`, ids);
      return null;
    }
    return g as unknown as Geometry;
  }

  private checkStyleMap(value: unknown, where: string, ids: string[]): void {
    if (value === undefined) {
      return;
    }
    if (!isStyleMap(value)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.style must map to string/number/boolean values`, ids);
    }
  }

  private checkNode(raw: unknown, index: number): GraphNode | null {
    const where = `nodes[${index}]`;
    if (!isPlainObject(raw)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where} must be an object`);
      return null;
    }
    const n = raw as Record<string, unknown>;
    const allowed = ['id', 'label', 'kind', 'groupId', 'properties', 'geometry', 'manualLocked', 'style', 'origin'];
    const unknownKeys = Object.keys(n).filter((k) => !allowed.includes(k));
    if (unknownKeys.length) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where} has unknown fields: ${unknownKeys.join(', ')}`);
    }
    const ids: string[] = [];
    if (typeof n.id !== 'string' || !ID_PATTERN.test(n.id)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.id must match ^[A-Za-z][A-Za-z0-9_-]{0,63}$`);
    } else {
      ids.push(n.id);
    }
    if (typeof n.label !== 'string' || n.label.length < 1 || n.label.length > 500) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.label must be a string of length 1..500`, ids);
    }
    if (typeof n.kind !== 'string' || !NODE_KINDS.includes(n.kind as NodeKind)) {
      this.error(
        ErrorCodes.SCHEMA_INVALID,
        `${where}.kind must be one of: ${NODE_KINDS.join(', ')}`,
        ids,
      );
    }
    if (n.groupId !== undefined && n.groupId !== null) {
      if (typeof n.groupId !== 'string' || !ID_PATTERN.test(n.groupId)) {
        this.error(ErrorCodes.SCHEMA_INVALID, `${where}.groupId must be a valid id or null`, ids);
      }
    }
    if (n.properties !== undefined) {
      if (!isPlainObject(n.properties) || !Object.values(n.properties).every(isMetadataValue)) {
        this.error(ErrorCodes.SCHEMA_INVALID, `${where}.properties values must be string/number/boolean/null`, ids);
      }
    }
    this.checkGeometry(n.geometry, where, ids);
    if (n.manualLocked !== undefined && typeof n.manualLocked !== 'boolean') {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.manualLocked must be a boolean`, ids);
    }
    this.checkStyleMap(n.style, where, ids);
    if (n.origin !== undefined && !(NODE_ORIGINS as readonly string[]).includes(n.origin as string)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.origin must be one of: ${NODE_ORIGINS.join(', ')}`, ids);
    }
    if (ids.length === 0) {
      return null;
    }
    return n as unknown as GraphNode;
  }

  private checkGroup(raw: unknown, index: number): GraphGroup | null {
    const where = `groups[${index}]`;
    if (!isPlainObject(raw)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where} must be an object`);
      return null;
    }
    const g = raw as Record<string, unknown>;
    const allowed = ['id', 'label', 'parentId', 'geometry', 'manualLocked', 'style'];
    const unknownKeys = Object.keys(g).filter((k) => !allowed.includes(k));
    if (unknownKeys.length) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where} has unknown fields: ${unknownKeys.join(', ')}`);
    }
    const ids: string[] = [];
    if (typeof g.id !== 'string' || !ID_PATTERN.test(g.id)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.id must match ^[A-Za-z][A-Za-z0-9_-]{0,63}$`);
    } else {
      ids.push(g.id);
    }
    if (typeof g.label !== 'string' || g.label.length < 1 || g.label.length > 500) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.label must be a string of length 1..500`, ids);
    }
    if (g.parentId !== undefined && g.parentId !== null) {
      if (typeof g.parentId !== 'string' || !ID_PATTERN.test(g.parentId)) {
        this.error(ErrorCodes.SCHEMA_INVALID, `${where}.parentId must be a valid id or null`, ids);
      }
    }
    this.checkGeometry(g.geometry, where, ids);
    if (g.manualLocked !== undefined && typeof g.manualLocked !== 'boolean') {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.manualLocked must be a boolean`, ids);
    }
    this.checkStyleMap(g.style, where, ids);
    if (ids.length === 0) {
      return null;
    }
    return g as unknown as GraphGroup;
  }

  private checkEdge(raw: unknown, index: number): GraphEdge | null {
    const where = `edges[${index}]`;
    if (!isPlainObject(raw)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where} must be an object`);
      return null;
    }
    const e = raw as Record<string, unknown>;
    const allowed = ['id', 'source', 'target', 'kind', 'direction', 'label', 'sourcePort', 'targetPort', 'waypoints', 'style'];
    const unknownKeys = Object.keys(e).filter((k) => !allowed.includes(k));
    if (unknownKeys.length) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where} has unknown fields: ${unknownKeys.join(', ')}`);
    }
    const ids: string[] = [];
    if (typeof e.id !== 'string' || !ID_PATTERN.test(e.id)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.id must match ^[A-Za-z][A-Za-z0-9_-]{0,63}$`);
    } else {
      ids.push(e.id);
    }
    for (const k of ['source', 'target'] as const) {
      if (typeof e[k] !== 'string' || !ID_PATTERN.test(e[k] as string)) {
        this.error(ErrorCodes.SCHEMA_INVALID, `${where}.${k} must be a valid node id`, ids);
      }
    }
    if (typeof e.kind !== 'string' || !EDGE_KINDS.includes(e.kind as EdgeKind)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.kind must be one of: ${EDGE_KINDS.join(', ')}`, ids);
    }
    if (typeof e.direction !== 'string' || !EDGE_DIRECTIONS.includes(e.direction as EdgeDirection)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.direction must be one of: ${EDGE_DIRECTIONS.join(', ')}`, ids);
    }
    if (e.label !== undefined && (typeof e.label !== 'string' || e.label.length > 500)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `${where}.label must be a string of length <= 500`, ids);
    }
    for (const k of ['sourcePort', 'targetPort'] as const) {
      if (e[k] !== undefined && (typeof e[k] !== 'string' || (e[k] as string).length > 100)) {
        this.error(ErrorCodes.SCHEMA_INVALID, `${where}.${k} must be a string of length <= 100`, ids);
      }
    }
    if (e.waypoints !== undefined) {
      if (!Array.isArray(e.waypoints) || !e.waypoints.every((p) => isPlainObject(p) && typeof p.x === 'number' && typeof p.y === 'number')) {
        this.error(ErrorCodes.SCHEMA_INVALID, `${where}.waypoints must be an array of {x, y} points`, ids);
      }
    }
    this.checkStyleMap(e.style, where, ids);
    if (ids.length === 0) {
      return null;
    }
    return e as unknown as GraphEdge;
  }

  private checkLayout(raw: unknown): void {
    if (!isPlainObject(raw)) {
      this.error(ErrorCodes.SCHEMA_INVALID, 'layout must be an object');
      return;
    }
    const l = raw as Record<string, unknown>;
    const allowed = ['algorithm', 'direction', 'preserveManualPositions'];
    const unknownKeys = Object.keys(l).filter((k) => !allowed.includes(k));
    if (unknownKeys.length) {
      this.error(ErrorCodes.SCHEMA_INVALID, `layout has unknown fields: ${unknownKeys.join(', ')}`);
    }
    if (typeof l.algorithm !== 'string' || !LAYOUT_ALGORITHMS.includes(l.algorithm as LayoutAlgorithm)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `layout.algorithm must be one of: ${LAYOUT_ALGORITHMS.join(', ')}`);
    }
    if (typeof l.direction !== 'string' || !LAYOUT_DIRECTIONS.includes(l.direction as LayoutDirection)) {
      this.error(ErrorCodes.SCHEMA_INVALID, `layout.direction must be one of: ${LAYOUT_DIRECTIONS.join(', ')}`);
    }
    if (typeof l.preserveManualPositions !== 'boolean') {
      this.error(ErrorCodes.SCHEMA_INVALID, 'layout.preserveManualPositions must be a boolean');
    }
  }

  // ---- semantic checks ---------------------------------------------------

  private checkSemantics(doc: GraphDocument): void {
    const seen = new Map<string, string>();
    const duplicates = new Map<string, string[]>();
    const register = (id: string, kind: string): void => {
      const prev = seen.get(id);
      if (prev) {
        const list = duplicates.get(id) ?? [prev];
        list.push(kind);
        duplicates.set(id, list);
      } else {
        seen.set(id, kind);
      }
    };
    doc.nodes.forEach((n) => register(n.id, 'node'));
    doc.groups.forEach((g) => register(g.id, 'group'));
    doc.edges.forEach((e) => register(e.id, 'edge'));
    for (const [id, kinds] of duplicates) {
      this.error(
        ErrorCodes.GRAPH_DUPLICATE_ID,
        `id "${id}" is used by multiple objects (${kinds.join(', ')}); ids must be globally unique across nodes, groups and edges`,
        [id],
      );
    }

    const nodeIds = new Set(doc.nodes.map((n) => n.id));
    const groupIds = new Set(doc.groups.map((g) => g.id));

    for (const e of doc.edges) {
      const missing: string[] = [];
      if (!nodeIds.has(e.source)) missing.push(e.source);
      if (!nodeIds.has(e.target)) missing.push(e.target);
      if (missing.length) {
        this.error(
          ErrorCodes.GRAPH_INVALID_REFERENCE,
          `edge "${e.id}" references missing node(s): ${missing.join(', ')}`,
          [e.id, ...missing],
        );
      }
    }
    for (const n of doc.nodes) {
      if (n.groupId && !groupIds.has(n.groupId)) {
        this.error(
          ErrorCodes.GRAPH_INVALID_REFERENCE,
          `node "${n.id}" references missing group "${n.groupId}"`,
          [n.id, n.groupId],
        );
      }
    }
    for (const g of doc.groups) {
      if (g.parentId && !groupIds.has(g.parentId)) {
        this.error(
          ErrorCodes.GRAPH_INVALID_REFERENCE,
          `group "${g.id}" references missing parent group "${g.parentId}"`,
          [g.id, g.parentId],
        );
      }
    }

    // Group nesting cycle detection (parentId chains), including self-parent.
    const state = new Map<string, 'visiting' | 'done'>();
    const stack: string[] = [];
    const visit = (groupId: string): void => {
      if (state.get(groupId) === 'done') return;
      if (state.get(groupId) === 'visiting') {
        const cycleStart = stack.indexOf(groupId);
        const cycle = cycleStart >= 0 ? stack.slice(cycleStart).concat(groupId) : [groupId, groupId];
        this.error(
          ErrorCodes.GRAPH_GROUP_CYCLE,
          `group nesting forms a cycle: ${cycle.join(' -> ')}`,
          cycle,
        );
        state.set(groupId, 'done');
        return;
      }
      state.set(groupId, 'visiting');
      stack.push(groupId);
      const g = doc.groups.find((x) => x.id === groupId);
      if (g?.parentId) visit(g.parentId);
      stack.pop();
      state.set(groupId, 'done');
    };
    for (const g of doc.groups) visit(g.id);

    // Physical links carry no data direction (docs/02 section 1, docs/05 0.2).
    for (const e of doc.edges) {
      if (e.kind === 'physical' && e.direction !== 'undirected') {
        this.warn(
          ErrorCodes.GRAPH_PHYSICAL_EDGE_DIRECTION,
          `physical edge "${e.id}" declares direction "${e.direction}"; physical links do not imply a data direction, so it is rendered undirected`,
          [e.id],
        );
      }
    }
  }

  // ---- entry point -------------------------------------------------------

  public validate(raw: unknown): { doc: GraphDocument; warnings: ValidationIssue[] } {
    if (!isPlainObject(raw)) {
      throw new GraphValidationError([issue(ErrorCodes.SCHEMA_INVALID, 'graph document must be a JSON object')]);
    }
    const root = raw as Record<string, unknown>;
    const required = ['schemaVersion', 'diagramId', 'name', 'diagramType', 'nodes', 'groups', 'edges', 'layout'];
    for (const key of required) {
      if (root[key] === undefined) {
        this.error(ErrorCodes.SCHEMA_INVALID, `missing required field: ${key}`);
      }
    }
    if (root.schemaVersion !== '1.0') {
      this.error(ErrorCodes.SCHEMA_INVALID, `schemaVersion must be "1.0", got ${JSON.stringify(root.schemaVersion)}`);
    }
    if (typeof root.diagramId !== 'string' || !ID_PATTERN.test(root.diagramId)) {
      this.error(ErrorCodes.SCHEMA_INVALID, 'diagramId must match ^[A-Za-z][A-Za-z0-9_-]{0,63}$');
    }
    if (typeof root.name !== 'string' || root.name.length < 1 || root.name.length > 200) {
      this.error(ErrorCodes.SCHEMA_INVALID, 'name must be a string of length 1..200');
    }
    if (root.diagramType !== 'network_topology' && root.diagramType !== 'business_architecture') {
      this.error(ErrorCodes.SCHEMA_INVALID, 'diagramType must be "network_topology" or "business_architecture"');
    }
    if (Array.isArray(root.nodes) && root.nodes.length > MAX_NODES) {
      this.error(ErrorCodes.SCHEMA_INVALID, `nodes exceeds maxItems ${MAX_NODES}`);
    }
    if (Array.isArray(root.groups) && root.groups.length > MAX_GROUPS) {
      this.error(ErrorCodes.SCHEMA_INVALID, `groups exceeds maxItems ${MAX_GROUPS}`);
    }
    if (Array.isArray(root.edges) && root.edges.length > MAX_EDGES) {
      this.error(ErrorCodes.SCHEMA_INVALID, `edges exceeds maxItems ${MAX_EDGES}`);
    }

    const nodes: GraphNode[] = [];
    const groups: GraphGroup[] = [];
    const edges: GraphEdge[] = [];
    if (Array.isArray(root.nodes)) {
      root.nodes.forEach((n, i) => {
        const node = this.checkNode(n, i);
        if (node) nodes.push(node);
      });
    } else if (root.nodes !== undefined) {
      this.error(ErrorCodes.SCHEMA_INVALID, 'nodes must be an array');
    }
    if (Array.isArray(root.groups)) {
      root.groups.forEach((g, i) => {
        const group = this.checkGroup(g, i);
        if (group) groups.push(group);
      });
    } else if (root.groups !== undefined) {
      this.error(ErrorCodes.SCHEMA_INVALID, 'groups must be an array');
    }
    if (Array.isArray(root.edges)) {
      root.edges.forEach((e, i) => {
        const edge = this.checkEdge(e, i);
        if (edge) edges.push(edge);
      });
    } else if (root.edges !== undefined) {
      this.error(ErrorCodes.SCHEMA_INVALID, 'edges must be an array');
    }
    if (root.layout !== undefined) {
      this.checkLayout(root.layout);
    }
    if (root.metadata !== undefined) {
      if (!isPlainObject(root.metadata) || !Object.values(root.metadata).every(isMetadataValue)) {
        this.error(ErrorCodes.SCHEMA_INVALID, 'metadata values must be string/number/boolean/null');
      }
    }
    if (root.warnings !== undefined) {
      if (!Array.isArray(root.warnings)) {
        this.error(ErrorCodes.SCHEMA_INVALID, 'warnings must be an array');
      } else {
        root.warnings.forEach((w, i) => {
          if (!isPlainObject(w) || typeof w.code !== 'string' || typeof w.message !== 'string' || typeof w.requiresConfirmation !== 'boolean') {
            this.error(ErrorCodes.SCHEMA_INVALID, `warnings[${i}] must contain code (string), message (string), requiresConfirmation (boolean)`);
          }
        });
      }
    }

    // Semantic checks need a best-effort document even if some structural
    // errors exist; only run it when the basic arrays are usable.
    const doc: GraphDocument = {
      schemaVersion: '1.0',
      diagramId: typeof root.diagramId === 'string' ? root.diagramId : '',
      name: typeof root.name === 'string' ? root.name : '',
      diagramType: root.diagramType === 'business_architecture' ? 'business_architecture' : 'network_topology',
      nodes,
      groups,
      edges,
      layout: {
        algorithm: 'layered',
        direction: 'DOWN',
        preserveManualPositions: true,
      },
    };
    // Metadata is validated above and must reach the renderer: it carries
    // document-level options such as `iconTheme`.
    if (isPlainObject(root.metadata) && Object.values(root.metadata).every(isMetadataValue)) {
      doc.metadata = root.metadata as Record<string, MetadataValue>;
    }
    if (isPlainObject(root.layout)) {
      // Carry the caller's layout spec through (shape validated above).
      // Before this, direction/algorithm were silently replaced by DOWN/layered.
      const l = root.layout;
      if (typeof l.algorithm === 'string' && LAYOUT_ALGORITHMS.includes(l.algorithm as LayoutAlgorithm)) {
        doc.layout.algorithm = l.algorithm as LayoutAlgorithm;
      }
      if (typeof l.direction === 'string' && LAYOUT_DIRECTIONS.includes(l.direction as LayoutDirection)) {
        doc.layout.direction = l.direction as LayoutDirection;
      }
      if (typeof l.preserveManualPositions === 'boolean') {
        doc.layout.preserveManualPositions = l.preserveManualPositions;
      }
    }
    this.checkSemantics(doc);

    if (this.errors.length) {
      throw new GraphValidationError(this.errors);
    }
    return { doc, warnings: this.warnings };
  }
}

export interface ValidationResult {
  doc: GraphDocument;
  warnings: ValidationIssue[];
}

/** Validate a raw parsed JSON graph document. Throws GraphValidationError on errors. */
export function validateGraph(raw: unknown): ValidationResult {
  return new Validator().validate(raw);
}
