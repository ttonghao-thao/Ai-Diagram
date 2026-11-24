import { applyConstraints, fixedCells, layoutConflict } from './constraints.js';
import { finishLayout, fitGroups, type LayoutOutput } from './elkLayout.js';
import { deviceTypeOf } from '../shapes/catalog.js';
import { overlaps, labelBox } from '../routing/edgeRouter.js';
import type { ResolvedDrawing } from '../shapes/resolve.js';
import { groupCellId, nodeCellId, type Geometry, type GraphDocument } from '../types.js';

export interface LocalLayoutOptions {
  movable?: string[];
  unknownBoxes?: Geometry[];
  affectedGroups?: string[];
  reposition?: string[];
}

export function layoutLocal(doc: GraphDocument, drawing: ResolvedDrawing, options: LocalLayoutOptions): LayoutOutput {
  const movable = new Set(options.movable ?? []);
  const reposition = new Set(options.reposition ?? []);
  const fixed = fixedCells(doc);
  const boxes = new Map<string, Geometry>();
  const nodes = new Map(doc.nodes.map((node) => [node.id, node]));
  const groups = new Map(doc.groups.map((group) => [group.id, group]));
  for (const node of doc.nodes) {
    const cellId = nodeCellId(node.id);
    if (node.geometry && (!reposition.has(node.id) || fixed.has(cellId))) {
      boxes.set(cellId, { ...node.geometry, ...drawing.nodes[node.id].iconSize });
    }
    if (!movable.has(node.id) && node.geometry) fixed.add(nodeCellId(node.id));
  }
  for (const group of doc.groups) {
    if (group.geometry) boxes.set(groupCellId(group.id), { ...group.geometry });
  }
  const affectedGroups = new Set(options.affectedGroups ?? []);
  function ancestors(id?: string | null): Set<string> {
    const chain = new Set<string>();
    while (id) {
      chain.add(id);
      id = groups.get(id)?.parentId;
    }
    return chain;
  }
  function footprint(id: string, box: Geometry): Geometry {
    const label = labelBox(box, drawing.nodes[id].labelSize);
    return label ? { ...label, y: box.y, height: box.height + label.height } : box;
  }
  const connections = new Map<string, string[]>();
  for (const { source, target } of doc.edges) {
    for (const [id, other] of [[source, target], [target, source]]) {
      const list = connections.get(id) ?? [];
      list.push(other);
      connections.set(id, list);
    }
  }
  const unknown = options.unknownBoxes ?? [];
  const added = new Set<string>();
  const gap = drawing.theme.layout.nodeSpacing;
  for (const node of doc.nodes) {
    const key = nodeCellId(node.id);
    if (boxes.has(key)) continue;
    const hierarchy = ancestors(node.groupId);
    hierarchy.forEach((id) => affectedGroups.add(id));
    const peers = doc.nodes.filter((other) => other.id !== node.id && other.groupId === node.groupId &&
      deviceTypeOf(other) === deviceTypeOf(node) && boxes.has(nodeCellId(other.id)));
    const relative = (doc.layout.constraints ?? []).find((rule) => rule.type === 'relativePosition' &&
      (rule.source === node.id || rule.target === node.id) &&
      boxes.has(nodeCellId(rule.source === node.id ? rule.target : rule.source)));
    const neighbors = (connections.get(node.id) ?? []).filter((id) => nodes.has(id))
      .map((id) => boxes.get(nodeCellId(id))).filter((box): box is Geometry => !!box);
    const parent = node.groupId ? boxes.get(groupCellId(node.groupId)) : undefined;
    const size = drawing.nodes[node.id].iconSize;
    let x = parent ? parent.x + gap : 40;
    let y = parent ? parent.y + gap + 32 : 40;
    if (relative?.type === 'relativePosition') {
      const first = relative.source === node.id;
      const anchor = boxes.get(nodeCellId(first ? relative.target : relative.source))!;
      const second = (first ? relative.position : { above: 'below', below: 'above', left: 'right', right: 'left' }[relative.position]);
      x = second === 'left' ? anchor.x - size.width - gap : second === 'right' ? anchor.x + anchor.width + gap : anchor.x;
      y = second === 'above' ? anchor.y - size.height - gap : second === 'below' ? anchor.y + anchor.height + gap : anchor.y;
    } else if (peers.length) {
      const last = peers.map(({ id }) => footprint(id, boxes.get(nodeCellId(id))!)).sort((a, b) => b.x + b.width - a.x - a.width)[0];
      x = last.x + last.width + gap + Math.max(0, (drawing.nodes[node.id].layoutSize.width - size.width) / 2);
      y = last.y;
    } else if (neighbors.length && !parent) {
      const anchor = neighbors[0];
      if (['RIGHT', 'LEFT'].includes(doc.layout.direction)) {
        x = anchor.x + anchor.width + gap;
        y = anchor.y;
      } else {
        x = anchor.x;
        y = anchor.y + anchor.height + gap;
      }
    }
    const obstacles = [
      ...doc.nodes.flatMap((other) => {
        const box = boxes.get(nodeCellId(other.id));
        return box ? [footprint(other.id, box)] : [];
      }),
      ...doc.groups.flatMap((group) => {
        const box = boxes.get(groupCellId(group.id));
        return box && !hierarchy.has(group.id) ? [box] : [];
      }),
      ...unknown,
    ];
    let candidate = { x, y, ...size };
    const axis = relative?.type === 'relativePosition' && ['above', 'below'].includes(relative.position) ? 'y' : 'x';
    const backwards = relative?.type === 'relativePosition' &&
      (['above', 'left'].includes(relative.position) === (relative.source === node.id));
    const dimension = axis === 'x' ? 'width' : 'height';
    for (let attempts = 0; attempts <= obstacles.length; attempts++) {
      const collision = obstacles.find((other) => overlaps(footprint(node.id, candidate), other, 16));
      if (!collision) break;
      const candidateFootprint = footprint(node.id, candidate);
      candidate[axis] += backwards ? collision[axis] - candidateFootprint[axis] - candidateFootprint[dimension] - gap :
        collision[axis] + collision[dimension] - candidateFootprint[axis] + gap;
      if (attempts === obstacles.length) layoutConflict(`无法在锁定对象之外放置 ${node.id}`);
    }
    boxes.set(key, candidate);
    added.add(node.id);
  }
  applyConstraints(doc, drawing, boxes, fixed);
  for (const node of doc.nodes) {
    if (!added.has(node.id) && !movable.has(node.id)) continue;
    const box = footprint(node.id, boxes.get(nodeCellId(node.id))!);
    if (unknown.some((other) => overlaps(box, other))) layoutConflict(`设备 ${node.id} 与未知图形重叠`);
    if (node.groupId && groups.get(node.groupId)?.geometry) {
      const parent = groups.get(node.groupId)!.geometry!;
      if (box.x < parent.x || box.y < parent.y + 32 || (fixed.has(groupCellId(node.groupId)) &&
        (box.x + box.width > parent.x + parent.width || box.y + box.height > parent.y + parent.height))) {
        layoutConflict(`设备 ${node.id} 超出受保护的分组范围（manualLocked）`);
      }
    }
  }
  const fixedGroups = new Set([...fixed, ...doc.groups.filter((group) => group.geometry && !affectedGroups.has(group.id))
    .map((group) => groupCellId(group.id))]);
  fitGroups(doc, drawing, boxes, fixedGroups, true);
  return finishLayout(doc, drawing, boxes, new Map(), unknown);
}
