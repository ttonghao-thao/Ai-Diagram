/**
 * draw.io style templates per node kind / edge kind, plus label-based size
 * estimation. Only portable, Desktop-bundled shapes are used (no external
 * images); professional icon libraries are a later-phase enhancement (docs/07).
 */
import type { EdgeDirection, EdgeKind, GraphNode, NodeKind, StyleMap, StyleValue } from '../types.js';
import type { IconTheme } from './iconRegistry.js';

/**
 * Base vertex styles per node kind. Colors follow the fixture palette family.
 * `whiteSpace=wrap` + centered alignment so Chinese labels wrap correctly.
 */
export const NODE_STYLES: Record<NodeKind, string> = {
  switch: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#D8EBFC;strokeColor=#78A9CD;fontColor=#1B3A57;',
  router: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#FFE6CC;strokeColor=#D79B00;fontColor=#5C3A00;',
  firewall: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#F8CECC;strokeColor=#B85450;fontColor=#5F1F1D;',
  server: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#E4F2E4;strokeColor=#85AE88;fontColor=#28402A;',
  vm: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#E1D5E7;strokeColor=#9673A6;fontColor=#3E2650;',
  cloud: 'ellipse;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;fillColor=#E1F0FC;strokeColor=#8CAFD0;fontColor=#1B3A57;',
  service: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#D5E8D4;strokeColor=#82B366;fontColor=#2A4023;',
  database: 'shape=cylinder3;whiteSpace=wrap;html=1;boundedLabels=1;backgroundOutline=1;size=15;align=center;verticalAlign=middle;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontColor=#1F3B5C;',
  client: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#F5F5F5;strokeColor=#666666;fontColor=#333333;',
  generic: 'whiteSpace=wrap;html=1;align=center;verticalAlign=middle;rounded=1;fillColor=#FFF2CC;strokeColor=#D6B656;fontColor=#4A3B00;',
};

/** Base style for group containers (swimlane with a 32px title bar). */
export const GROUP_STYLE =
  'swimlane;html=1;startSize=32;horizontal=1;rounded=1;fillColor=#F4F7FA;strokeColor=#9DB4C8;fontColor=#33506B;swimlaneFillColor=#FBFDFE;';

/**
 * Base edge styles per edge kind. Arrows are added per direction in
 * composeEdgeStyle(); physical links never get arrows (docs/02: physical
 * connections do not imply a data direction).
 */
export const EDGE_STYLES: Record<EdgeKind, string> = {
  physical: 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#536D83;strokeWidth=1.5;',
  logical: 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;dashed=1;strokeColor=#6C8EBF;strokeWidth=1.2;',
  dataflow: 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#4A7E53;strokeWidth=1.2;',
  control: 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;dashed=1;strokeColor=#B85450;strokeWidth=1.2;',
  dependency: 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;dashed=1;dashPattern=1 3;strokeColor=#8A8A8A;strokeWidth=1;',
};

function stylePart(key: string, value: StyleValue): string | null {
  const k = key.replace(/[;=\s]/g, '');
  if (!k) return null;
  const v = String(value).replace(/[;\r\n]/g, ' ').trim();
  return `${k}=${v}`;
}

/**
 * Append user-provided style overrides after the base style. In draw.io style
 * strings later occurrences of a key win, so overrides take precedence.
 */
export function composeStyle(base: string, overrides?: StyleMap): string {
  const parts = [base.endsWith(';') ? base : base + ';'];
  if (overrides) {
    for (const [key, value] of Object.entries(overrides)) {
      const part = stylePart(key, value);
      if (part) parts.push(part + ';');
    }
  }
  return parts.join('');
}

function arrowFragment(kind: EdgeKind, direction: EdgeDirection): string {
  if (kind === 'physical') {
    return 'startArrow=none;startFill=0;endArrow=none;endFill=0;';
  }
  if (direction === 'bidirectional') {
    return 'startArrow=block;startFill=1;endArrow=block;endFill=1;';
  }
  if (direction === 'forward') {
    return 'startArrow=none;startFill=0;endArrow=block;endFill=1;';
  }
  return 'startArrow=none;startFill=0;endArrow=none;endFill=0;';
}

/**
 * Cisco theme edge: thin straight black line as in draw.io's Cisco templates
 * (no orthogonal routing, no fixed anchors, no waypoints). Physical links
 * carry no arrow; other kinds keep their arrows and a dashed stroke.
 */
function composeCiscoEdgeStyle(kind: EdgeKind, direction: EdgeDirection, overrides?: StyleMap): string {
  // labelBackgroundColor keeps link labels readable where lines or icons cross.
  const parts: string[] = ['sketch=0;html=1;strokeColor=#000000;strokeWidth=1;labelBackgroundColor=#FFFFFF;'];
  if (kind === 'logical' || kind === 'control' || kind === 'dependency') {
    parts.push('dashed=1;');
  }
  parts.push(arrowFragment(kind, direction));
  if (overrides) {
    for (const [key, value] of Object.entries(overrides)) {
      parts.push(`${key.replace(/[;=\s]/g, '')}=${String(value).replace(/[;\r\n]/g, ' ').trim()};`);
    }
  }
  parts.push(`aiKind=${kind};aiDirection=${direction};`);
  return parts.join('');
}

/**
 * Physical edges are rendered without any arrow regardless of the declared
 * direction; other kinds get arrows according to their direction. The
 * semantic markers `aiKind`/`aiDirection` are stamped onto every edge so the
 * Phase 2 importer can restore the exact edge type after a Desktop edit
 * round-trip (arrow-based heuristics cannot distinguish logical/control/
 * dependency edges).
 */
export function composeEdgeStyle(
  kind: EdgeKind,
  direction: EdgeDirection,
  overrides?: StyleMap,
  theme: IconTheme = 'networks',
): string {
  if (theme === 'cisco') {
    return composeCiscoEdgeStyle(kind, direction, overrides);
  }
  const parts: string[] = [composeStyle(EDGE_STYLES[kind], overrides), arrowFragment(kind, direction)];
  parts.push(`aiKind=${kind};aiDirection=${direction};`);
  return parts.join('');
}

/** Cisco-theme edges are straight lines: no ELK waypoints and no fixed anchors. */
export function isStraightEdge(theme: IconTheme): boolean {
  return theme === 'cisco';
}

export const DEFAULT_NODE_WIDTH = 120;
export const DEFAULT_NODE_HEIGHT = 56;
const MIN_NODE_WIDTH = 120;
const MAX_NODE_WIDTH = 340;

/**
 * Rough label-driven size estimate for nodes that carry no explicit geometry.
 * CJK characters are counted at full width, ASCII at ~0.55x; wrapped lines
 * increase the height. This only affects first layout, not manual geometry.
 */
export function estimateNodeSize(node: Pick<GraphNode, 'label' | 'kind'>): { width: number; height: number } {
  let cjk = 0;
  let ascii = 0;
  for (const ch of node.label) {
    if (/[\u2E80-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/.test(ch)) {
      cjk += 1;
    } else {
      ascii += 1;
    }
  }
  const textWidth = 13 * cjk + 7 * ascii;
  const width = Math.min(MAX_NODE_WIDTH, Math.max(MIN_NODE_WIDTH, Math.ceil(textWidth) + 44));
  const usableWidth = Math.max(width - 40, 60);
  const lines = Math.max(1, Math.ceil(textWidth / usableWidth));
  let height = DEFAULT_NODE_HEIGHT;
  if (node.kind === 'database') height = 74;
  if (node.kind === 'cloud') height = 62;
  height = Math.max(height, 40 + lines * 16);
  return { width, height };
}
