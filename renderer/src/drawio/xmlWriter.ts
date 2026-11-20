/**
 * GraphDocument + LayoutOutput -> uncompressed single-page .drawio XML.
 * docs/03 section 3: stable cell ids, real vertex/edge/group cells, correct
 * parent-child and source/target references, XML escaping for all text.
 */
import { composeEdgeStyle, composeStyle, GROUP_STYLE, NODE_STYLES } from '../shapes/styles.js';
import { edgeCellId, groupCellId, nodeCellId } from '../types.js';
import type { Geometry, GraphDocument, GraphGroup, GraphNode, StyleMap } from '../types.js';
import type { LayoutOutput } from '../layout/elkLayout.js';

/**
 * Escape a string for XML attribute values. All attributes are written with
 * double quotes, so a literal `'` is safe (draw.io does not escape it either);
 * `& < >` must be escaped in all contexts.
 */
export function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmt(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100);
}

function attr(name: string, value: string | number | undefined): string {
  return value === undefined ? '' : ` ${name}="${escapeXml(String(value))}"`;
}

interface CellTree {
  groups: Array<{ group: GraphGroup; depth: number; parentCellId: string }>;
  nodes: Array<{ node: GraphNode; parentCellId: string }>;
}

/** Compute parent cell ids and emit groups ordered so parents come first. */
function buildTree(doc: GraphDocument): CellTree {
  const groupById = new Map(doc.groups.map((g) => [g.id, g]));
  const depthCache = new Map<string, number>();
  const depthOf = (g: GraphGroup): number => {
    const cached = depthCache.get(g.id);
    if (cached !== undefined) return cached;
    let depth = 0;
    let cur: GraphGroup | undefined = g;
    while (cur?.parentId) {
      depth += 1;
      cur = groupById.get(cur.parentId);
    }
    depthCache.set(g.id, depth);
    return depth;
  };
  const parentCellOfGroup = (g: GraphGroup): string => (g.parentId ? groupCellId(g.parentId) : '1');
  const groups = doc.groups
    .map((g) => ({ group: g, depth: depthOf(g), parentCellId: parentCellOfGroup(g) }))
    .sort((a, b) => a.depth - b.depth);
  const nodes = doc.nodes.map((n) => ({
    node: n,
    parentCellId: n.groupId ? groupCellId(n.groupId) : '1',
  }));
  return { groups, nodes };
}

function geometryLines(cellId: string, geo: Geometry | undefined, parentAbs: Geometry | undefined, indent: string): string {
  if (!geo) return '';
  const relX = geo.x - (parentAbs?.x ?? 0);
  const relY = geo.y - (parentAbs?.y ?? 0);
  return (
    `${indent}<mxGeometry x="${fmt(relX)}" y="${fmt(relY)}" width="${fmt(geo.width)}" height="${fmt(geo.height)}" as="geometry" />`
  );
}

/**
 * Serialize the laid-out graph into draw.io XML. `layout.geometries` holds
 * absolute coordinates; cells nested in a group are converted to coordinates
 * relative to their parent group (docs/03 section 2).
 */
export function serializeDrawio(doc: GraphDocument, layout: LayoutOutput): string {
  const tree = buildTree(doc);
  const lines: string[] = [];

  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  lines.push('<mxfile host="ai-diagram-studio" compressed="false">');
  lines.push(`  <diagram id="page-1" name="${escapeXml(doc.name)}">`);
  lines.push(
    `    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="${layout.pageWidth}" pageHeight="${layout.pageHeight}" math="0" shadow="0">`,
  );
  lines.push('      <root>');
  lines.push('        <mxCell id="0" />');
  lines.push('        <mxCell id="1" parent="0" />');

  // Groups: parents before children, absolute geometry (swimlane cells on the
  // layer where they live: root groups sit on "1", nested groups on their parent).
  for (const { group, parentCellId } of tree.groups) {
    const geo = layout.geometries.get(groupCellId(group.id));
    if (!geo) continue;
    const parentAbs = group.parentId ? layout.geometries.get(groupCellId(group.parentId)) : undefined;
    const style = composeStyle(GROUP_STYLE, group.style as StyleMap | undefined);
    lines.push(`        <mxCell id="${groupCellId(group.id)}"${attr('value', group.label)} style="${escapeXml(style)}" vertex="1" parent="${parentCellId}">`);
    lines.push(geometryLines(groupCellId(group.id), geo, parentAbs, '          '));
    lines.push('        </mxCell>');
  }

  // Nodes: geometry converted from absolute to parent-group-relative.
  for (const { node, parentCellId } of tree.nodes) {
    const geo = layout.geometries.get(nodeCellId(node.id));
    if (!geo) continue;
    const parentAbs = node.groupId ? layout.geometries.get(groupCellId(node.groupId)) : undefined;
    const style = composeStyle(NODE_STYLES[node.kind], node.style as StyleMap | undefined);
    lines.push(`        <mxCell id="${nodeCellId(node.id)}"${attr('value', node.label)} style="${escapeXml(style)}" vertex="1" parent="${parentCellId}">`);
    lines.push(geometryLines(nodeCellId(node.id), geo, parentAbs, '          '));
    lines.push('        </mxCell>');
  }

  // Edges: always parented to the root layer; waypoints are absolute points.
  for (const edge of doc.edges) {
    const style = composeEdgeStyle(edge.kind, edge.direction, edge.style as StyleMap | undefined);
    const waypoints = layout.edgeWaypoints.get(edgeCellId(edge.id)) ?? [];
    lines.push(
      `        <mxCell id="${edgeCellId(edge.id)}"${attr('value', edge.label ?? '')} style="${escapeXml(style)}" edge="1" parent="1" source="${nodeCellId(edge.source)}" target="${nodeCellId(edge.target)}">`,
    );
    if (waypoints.length) {
      lines.push('          <mxGeometry relative="1" as="geometry">');
      lines.push('            <Array as="points">');
      for (const p of waypoints) {
        lines.push(`              <mxPoint x="${fmt(p.x)}" y="${fmt(p.y)}" />`);
      }
      lines.push('            </Array>');
      lines.push('          </mxGeometry>');
    } else {
      lines.push('          <mxGeometry relative="1" as="geometry" />');
    }
    lines.push('        </mxCell>');
  }

  lines.push('      </root>');
  lines.push('    </mxGraphModel>');
  lines.push('  </diagram>');
  lines.push('</mxfile>');
  return lines.join('\n') + '\n';
}
