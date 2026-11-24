/**
 * Network hierarchy tiers — the POSITION template from docs/03 section 1
 * ("云/出口 → 防火墙 → 核心/接入 → 服务器"). A position template decides
 * where devices are drawn; it is never used to invent or alter edges.
 */
import type { GraphDocument, GraphEdge, GraphNode } from '../types.js';

const KIND_TIER: Partial<Record<string, number>> = {
  cloud: 0,
  router: 1,
  firewall: 2,
  switch: 3,
  server: 4,
  vm: 4,
  database: 4,
  client: 4,
};

/** Tiers for extended deviceType aliases on kind="generic" nodes. */
const ALIAS_TIER: Record<string, number> = {
  modem: 1,
  vpn_gateway: 2,
  load_balancer: 3,
  proxy: 3,
  hub: 3,
  access_point: 4,
  mainframe: 4,
  rack: 4,
};

/** Lower tier = closer to the internet = drawn higher. undefined = unknown. */
export function networkTierOf(node: Pick<GraphNode, 'kind' | 'properties'>): number | undefined {
  if (node.kind === 'generic') {
    const deviceType = node.properties?.deviceType;
    if (typeof deviceType === 'string') {
      return ALIAS_TIER[deviceType.toLowerCase()];
    }
    return undefined;
  }
  return KIND_TIER[node.kind];
}

export interface OrientedEdge {
  edge: GraphEdge;
  source: string;
  target: string;
}

/**
 * Layout-only orientation of undirected edges in network topologies.
 *
 * LLM/user output follows sentence order ("核心交换机 上联 防火墙" becomes
 * switch -> firewall), but ELK places a source above its target in a DOWN
 * layout, which put servers and firewalls on one row below the switch. For
 * `undirected` edges the source/target order carries no meaning, so the
 * higher-tier device is handed to ELK as the "flow origin". The semantic
 * graph and the stored XML keep the declared source/target untouched.
 */
export function orientEdgesForLayout(doc: GraphDocument): OrientedEdge[] {
  const nodes = new Map(doc.nodes.map((n) => [n.id, n]));
  const isNetwork = doc.diagramType === 'network_topology';
  // DOWN/RIGHT layouts put the source first (top/left); UP/LEFT put it last.
  const sourceFirst = doc.layout.direction === 'DOWN' || doc.layout.direction === 'RIGHT';
  return doc.edges.map((edge) => {
    let source = edge.source;
    let target = edge.target;
    const sourceNode = nodes.get(edge.source);
    const targetNode = nodes.get(edge.target);
    if (isNetwork && edge.direction === 'undirected' && sourceNode && targetNode) {
      const sourceTier = networkTierOf(sourceNode);
      const targetTier = networkTierOf(targetNode);
      if (sourceTier !== undefined && targetTier !== undefined && sourceTier !== targetTier) {
        const higher = sourceTier < targetTier ? edge.source : edge.target;
        const lower = higher === edge.source ? edge.target : edge.source;
        source = sourceFirst ? higher : lower;
        target = sourceFirst ? lower : higher;
      }
    }
    return { edge, source, target };
  });
}
