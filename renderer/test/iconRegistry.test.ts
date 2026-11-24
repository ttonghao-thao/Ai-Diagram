/**
 * Phase 0.5 Icon Registry tests: kind -> stencil mapping integrity, custom
 * SVG embedding (no online loading), generic fallback with original device
 * type preservation, and layout accommodation of icon size + label band.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  CISCO_ALIAS_REGISTRY,
  CISCO_ICON_REGISTRY,
  ICON_REGISTRY,
  dataUriToSvg,
  loadCustomIcons,
  resolveNodeIcon,
  sanitizeStyleToken,
  svgImageStyle,
  svgToDataUri,
} from '../src/shapes/iconRegistry.js';
import { layoutGraph } from '../src/layout/elkLayout.js';
import { serializeDrawio } from '../src/drawio/xmlWriter.js';
import { parseDrawioXml } from '../src/drawio/xmlReader.js';
import { GraphDocument, GraphNode, NodeKind } from '../src/types.js';
import { composeEdgeStyle } from '../src/shapes/styles.js';
import { resolveDrawing } from '../src/shapes/resolve.js';

const ALL_KINDS: NodeKind[] = [
  'switch', 'router', 'firewall', 'server', 'vm', 'cloud', 'service', 'database', 'client', 'generic',
];

const SAMPLE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="12" fill="#2d6a4f"/><text x="50" y="58" font-size="34" text-anchor="middle" fill="#fff">XT</text></svg>`;

test('registry covers every GraphDocument NodeKind with positive default sizes', () => {
  for (const kind of ALL_KINDS) {
    const desc = ICON_REGISTRY[kind];
    assert.ok(desc, `missing registry entry for kind ${kind}`);
    assert.ok(desc.width > 0 && desc.height > 0);
    assert.ok(desc.stencilStyle.length > 0 && desc.fallbackStyle.length > 0);
    assert.ok(desc.stencilStyle.includes('verticalLabelPosition=bottom'), `${kind} label must sit below the icon`);
  }
});

test('professional stencil ids match the verified mxgraph.networks shape names', () => {
  // drawio v24.7.17 stencils/networks.xml + parseStencilSet conversion:
  // packageName + '.' + name.toLowerCase().replace(/ /g, '_')
  const expected: Partial<Record<NodeKind, string>> = {
    switch: 'shape=mxgraph.networks.switch;',
    router: 'shape=mxgraph.networks.router;',
    firewall: 'shape=mxgraph.networks.firewall;',
    server: 'shape=mxgraph.networks.server;',
    vm: 'shape=mxgraph.networks.virtual_server;',
    database: 'shape=mxgraph.networks.storage;',
    cloud: 'shape=mxgraph.networks.cloud;',
    client: 'shape=mxgraph.networks.terminal;',
    service: 'shape=process;',
  };
  for (const [kind, style] of Object.entries(expected)) {
    assert.ok(
      (ICON_REGISTRY[kind as NodeKind].stencilStyle ?? '').startsWith(style),
      `${kind} must map to ${style}, got ${ICON_REGISTRY[kind as NodeKind].stencilStyle}`,
    );
  }
});

test('sanitizeStyleToken strips style-breaking characters, keeps device names', () => {
  assert.equal(sanitizeStyleToken('printer;fillColor=#000'), 'printer-fillColor-#000');
  assert.equal(sanitizeStyleToken('a=b c'), 'a-b-c');
  // Non-ASCII device types are legal style values and must survive.
  assert.equal(sanitizeStyleToken('打印机'), '打印机');
});

test('unknown deviceType on a generic node keeps the original type in the style', () => {
  const node: GraphNode = { id: 'printer1', label: '打印服务器', kind: 'generic', properties: { deviceType: 'printer' } };
  const icon = resolveNodeIcon(node);
  // kind='generic' resolves through its registry entry (the generic icon).
  assert.equal(icon.resolvedBy, 'kind-stencil');
  assert.ok(icon.style.startsWith(ICON_REGISTRY.generic.stencilStyle));
  assert.ok(icon.style.includes('aiKind=generic'));
  assert.ok(icon.style.includes('aiDeviceType=printer'));
});

test('a kind missing from the registry falls back to the generic icon (defensive)', () => {
  const node = { id: 'x1', label: '神秘设备', kind: 'alien_device' } as unknown as GraphNode;
  const icon = resolveNodeIcon(node);
  assert.equal(icon.resolvedBy, 'generic');
  assert.ok(icon.style.startsWith(ICON_REGISTRY.generic.stencilStyle));
  assert.ok(icon.style.includes('aiKind=alien_device'));
});

test('deviceType alias upgrades a generic node to the matching professional stencil', () => {
  const node: GraphNode = { id: 'fw2', label: '备用防火墙', kind: 'generic', properties: { deviceType: 'firewall' } };
  const icon = resolveNodeIcon(node);
  assert.equal(icon.resolvedBy, 'alias-stencil');
  assert.ok(icon.style.startsWith('shape=mxgraph.networks.firewall;'));
  assert.ok(icon.style.includes('aiKind=generic'));
  assert.ok(icon.style.includes('aiDeviceType=firewall'));
  assert.equal(icon.width, ICON_REGISTRY.firewall.width);
});

test('kind-stencil resolution includes aiKind and honors node style overrides', () => {
  const node: GraphNode = { id: 'sw1', label: '核心交换机', kind: 'switch', style: { rotation: 0 } };
  const icon = resolveNodeIcon(node);
  assert.equal(icon.resolvedBy, 'kind-stencil');
  assert.ok(icon.style.includes('aiKind=switch'));
  assert.ok(icon.style.includes('rotation=0;'));
  assert.ok(!icon.style.includes('undefined'));
});

test('custom SVG icons load from a local dir and embed as percent-encoded data URIs', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ai-icons-'));
  try {
    writeFileSync(path.join(dir, 'switch.svg'), SAMPLE_SVG, 'utf8');
    const icons = loadCustomIcons(dir);
    assert.equal(icons.size, 1);
    const uri = icons.get('switch')!;
    // drawio style values are split on ';', so the URI must not contain any.
    assert.ok(uri.startsWith('data:image/svg+xml,'));
    assert.ok(!uri.includes(';'));
    assert.ok(!uri.includes('base64'));
    assert.ok(dataUriToSvg(uri).includes('<svg'));
    // No online resources: style contains only the embedded data URI.
    const icon = resolveNodeIcon({ id: 's1', label: 'SW', kind: 'switch' }, icons);
    assert.equal(icon.resolvedBy, 'custom-svg');
    assert.ok(icon.style.startsWith('shape=image;'));
    assert.ok(icon.style.includes(uri));
    assert.ok(!icon.style.includes('http://') && !icon.style.includes('https://'));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('custom SVG alias by deviceType works (printer on a generic node)', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ai-icons-'));
  try {
    writeFileSync(path.join(dir, 'printer.svg'), SAMPLE_SVG, 'utf8');
    const icons = loadCustomIcons(dir);
    const icon = resolveNodeIcon(
      { id: 'p1', label: '打印服务器', kind: 'generic', properties: { deviceType: 'Printer' } },
      icons,
    );
    assert.equal(icon.resolvedBy, 'custom-svg');
    assert.ok(icon.style.includes('image=data:image/svg+xml,'));
    assert.ok(!icon.style.includes(';base64,'));
    assert.ok(icon.style.includes('aiDeviceType=Printer'));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('SVG files with scripts, javascript: URIs, non-SVG or oversized content are rejected', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ai-icons-bad-'));
  try {
    writeFileSync(path.join(dir, 'evil.svg'), '<svg><script>alert(1)</script></svg>', 'utf8');
    assert.throws(() => loadCustomIcons(dir), /executable content/);
    rmSync(path.join(dir, 'evil.svg'));
    writeFileSync(path.join(dir, 'js.svg'), '<svg><a href="javascript:alert(1)">x</a></svg>', 'utf8');
    assert.throws(() => loadCustomIcons(dir), /executable content/);
    rmSync(path.join(dir, 'js.svg'));
    writeFileSync(path.join(dir, 'txt.svg'), 'not an svg', 'utf8');
    assert.throws(() => loadCustomIcons(dir), /not an SVG/);
    rmSync(path.join(dir, 'txt.svg'));
    writeFileSync(path.join(dir, 'big.svg'), '<svg>' + 'x'.repeat(70 * 1024) + '</svg>', 'utf8');
    assert.throws(() => loadCustomIcons(dir), /byte limit/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('svgImageStyle rejects base64 and non-SVG image values', () => {
  assert.throws(() => svgImageStyle('data:image/svg+xml;base64,AAAA'), /percent-encoded SVG data URI/);
  assert.throws(() => svgImageStyle('data:image/png;base64,AAAA'), /percent-encoded SVG data URI/);
  assert.throws(() => svgImageStyle('https://example.com/icon.svg'), /percent-encoded SVG data URI/);
  // The canonical form is accepted and keeps the URI intact.
  const style = svgImageStyle(svgToDataUri(SAMPLE_SVG));
  assert.ok(style.includes(svgToDataUri(SAMPLE_SVG)));
  assert.equal(dataUriToSvg(svgToDataUri(SAMPLE_SVG)), SAMPLE_SVG);
});

test('resolved icon dimensions preserve defaults and explicit geometry', () => {
  const doc: GraphDocument = {
    schemaVersion: '1.0', diagramId: 'sizes', name: '尺寸', diagramType: 'business_architecture', groups: [], edges: [],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
    nodes: [
      { id: 'r1', label: 'R1', kind: 'router' },
      { id: 'r2', label: '核心出口路由器集群设备A区', kind: 'router' },
      { id: 'r3', label: 'R3', kind: 'router', geometry: { x: 0, y: 0, width: 200, height: 70 } },
    ],
  };
  const { nodes } = resolveDrawing(doc);
  assert.equal(nodes.r1.iconSize.width, ICON_REGISTRY.router.width);
  assert.equal(nodes.r1.iconSize.height, ICON_REGISTRY.router.height);
  assert.deepEqual(nodes.r2.iconSize, nodes.r1.iconSize);
  assert.ok(nodes.r2.labelSize.width > nodes.r1.labelSize.width);
  assert.deepEqual(nodes.r3.iconSize, { width: 200, height: 70 });
});

test('layout reserves the label band below icons (icon box kept in geometry)', async () => {
  const doc: GraphDocument = {
    schemaVersion: '1.0',
    diagramId: 'icon_layout',
    name: '图标布局',
    diagramType: 'network_topology',
    nodes: [{ id: 'sw', label: '核心交换机', kind: 'switch' }],
    groups: [],
    edges: [],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const layout = await layoutGraph(doc);
  const geo = layout.geometries.get('n_sw')!;
  // network_topology defaults to the cisco theme (Route Switch Processor icon)
  assert.equal(geo.height, CISCO_ICON_REGISTRY.switch!.height);
  assert.ok(geo.width >= CISCO_ICON_REGISTRY.switch!.width);
});

test('generated XML embeds stencil icons, aiKind, anchors and labels (roundtrip parse)', async () => {
  const doc: GraphDocument = {
    schemaVersion: '1.0',
    diagramId: 'icon_xml',
    name: '图标 XML',
    diagramType: 'network_topology',
    nodes: [
      { id: 'sw', label: '核心交换机', kind: 'switch' },
      { id: 'srv', label: '业务服务器', kind: 'server' },
      { id: 'prn', label: '打印机', kind: 'generic', properties: { deviceType: 'printer' } },
    ],
    groups: [],
    edges: [{ id: 'l1', source: 'sw', target: 'srv', kind: 'physical', direction: 'undirected' }],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const layout = await layoutGraph(doc);
  const xml = serializeDrawio(doc, layout);
  const parsed = parseDrawioXml(xml);
  const sw = parsed.cellById.get('n_sw')!;
  assert.ok(sw.style?.includes('shape=mxgraph.cisco.misc.route_switch_processor'));
  assert.ok(sw.style?.includes('fillColor=#036897'));
  assert.ok(sw.style?.includes('aiKind=switch'));
  assert.equal(sw.value, '核心交换机');
  const prn = parsed.cellById.get('n_prn')!;
  assert.ok(prn.style?.includes('aiKind=generic'));
  assert.ok(prn.style?.includes('aiDeviceType=printer'));
  const l1 = parsed.cellById.get('e_l1')!;
  // cisco theme: straight thin line, no arrows, no fixed anchors
  assert.ok(l1.style?.includes('endArrow=none'));
  assert.ok(l1.style?.includes('aiKind=physical;aiDirection=undirected'));
  assert.ok(!l1.style?.includes('edgeStyle=orthogonalEdgeStyle'));
  assert.ok(!l1.style?.includes('exitX='));
});

test('orthogonal routing writes directional anchors for horizontal and vertical neighbors', async () => {
  const doc: GraphDocument = {
    schemaVersion: '1.1', diagramId: 'anchors', name: '连接锚点', diagramType: 'network_topology',
    appearance: { edgeRouting: 'orthogonal' }, groups: [],
    layout: { algorithm: 'manual', direction: 'DOWN', preserveManualPositions: true },
    nodes: [['a', 0, 0], ['b', 400, 0], ['c', 0, 400]].map(([id, x, y]) =>
      ({ id: String(id), label: String(id), kind: 'router', geometry: { x: Number(x), y: Number(y), width: 100, height: 50 } })),
    edges: ['b', 'c'].map((target) =>
      ({ id: 'edge_' + target, source: 'a', target, kind: 'physical', direction: 'undirected' })),
  };
  const layout = await layoutGraph(doc);
  assert.match(layout.drawing!.edges.edge_b.style, /exitX=1;exitY=0.5;entryX=0;entryY=0.5;/);
  assert.match(layout.drawing!.edges.edge_c.style, /exitX=0.5;exitY=1;/);
  doc.nodes = [doc.nodes[0], { ...doc.nodes[0], id: 'd' }];
  doc.edges = [{ ...doc.edges[0], target: 'd' }];
  const coincident = await layoutGraph(doc);
  assert.doesNotMatch(coincident.drawing!.edges.edge_b.style, /exitX=/);
});

test('deviceType extended aliases resolve to mxgraph.networks stencils', () => {
  const lb = resolveNodeIcon({ id: 'lb1', label: '负载均衡', kind: 'generic', properties: { deviceType: 'load_balancer' } });
  assert.equal(lb.resolvedBy, 'alias-stencil');
  assert.ok(lb.style.startsWith('shape=mxgraph.networks.load_balancer;'));
  assert.ok(lb.style.includes('aiDeviceType=load_balancer'));
  assert.ok(lb.style.includes('aiKind=generic'));
  const ap = resolveNodeIcon({ id: 'ap1', label: 'AP', kind: 'generic', properties: { deviceType: 'access_point' } });
  assert.ok(ap.style.startsWith('shape=mxgraph.networks.wireless_hub;'));
});

test('custom SVG file for an alias overrides its stencil (assets/icons)', () => {
  // Simulate the shipped default material without touching the real dir.
  const icons = new Map([['access_point', 'data:image/svg+xml,%3Csvg%3Etest%3C/svg%3E']]);
  const icon = resolveNodeIcon(
    { id: 'ap2', label: '无线AP', kind: 'generic', properties: { deviceType: 'access_point' } },
    icons,
  );
  assert.equal(icon.resolvedBy, 'custom-svg');
  assert.ok(icon.style.startsWith('shape=image;'));
  assert.ok(!icon.style.includes('base64'));
});

test('alias kinds survive a render->import roundtrip', async () => {
  const doc: GraphDocument = {
    schemaVersion: '1.0',
    diagramId: 'alias_rt',
    name: '别名往返',
    diagramType: 'network_topology',
    nodes: [
      { id: 'lb', label: '负载均衡', kind: 'generic', properties: { deviceType: 'load_balancer' } },
      { id: 'sw', label: '交换机', kind: 'switch' },
    ],
    groups: [],
    edges: [],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const layout = await layoutGraph(doc);
  const xml = serializeDrawio(doc, layout);
  const parsed = parseDrawioXml(xml);
  const lbStyle = parsed.cellById.get('n_lb')!.style ?? '';
  assert.ok(lbStyle.includes('shape=mxgraph.cisco.directors.localdirector'));
  assert.ok(lbStyle.includes('aiDeviceType=load_balancer'));
});

// ---------------------------------------------------------------------------
// Icon themes: cisco (default for network topology) vs networks
// ---------------------------------------------------------------------------

test('network topology resolves through the cisco theme by default', () => {
  const cases: Array<[NodeKind, string]> = [
    ['cloud', 'storage.cloud'],
    ['router', 'routers.router'],
    ['firewall', 'security.ios_firewall'],
    ['switch', 'misc.route_switch_processor'],
    ['server', 'servers.server_with_router'],
    ['database', 'storage.relational_database'],
    ['client', 'computers_and_peripherals.pc'],
  ];
  for (const [kind, id] of cases) {
    const icon = resolveNodeIcon({ id: 'x', label: 'x', kind }, { theme: 'cisco' });
    assert.ok(icon.style.includes(`shape=mxgraph.cisco.${id};`), `${kind} -> ${id}`);
    if (kind !== 'cloud') {
      assert.ok(icon.style.includes('fillColor=#036897'), `${kind} cisco blue`);
    }
  }
});

test('cisco cloud is an outline cloud with the label inside', () => {
  const icon = resolveNodeIcon({ id: 'c', label: '公网', kind: 'cloud' }, { theme: 'cisco' });
  assert.ok(icon.style.includes('fillColor=#FFFFFF'));
  assert.ok(icon.style.includes('verticalAlign=middle'));
  assert.ok(!icon.style.includes('verticalLabelPosition=bottom'));
});

test('cisco aliases fall back to the networks alias registry when unmapped', () => {
  const vpn = resolveNodeIcon({ id: 'v', label: 'VPN', kind: 'generic', properties: { deviceType: 'vpn_gateway' } }, { theme: 'cisco' });
  assert.ok(vpn.style.includes('shape=mxgraph.cisco.hubs_and_gateways.vpn_gateway'));
  const proxy = resolveNodeIcon({ id: 'p', label: '代理', kind: 'generic', properties: { deviceType: 'proxy' } }, { theme: 'cisco' });
  assert.ok(proxy.style.includes('shape=mxgraph.networks.proxy_server'));
  // kinds without a cisco entry keep their flat/networks icon
  const generic = resolveNodeIcon({ id: 'g', label: '未知', kind: 'generic' }, { theme: 'cisco' });
  assert.ok(generic.style.includes('fillColor=#FFF2CC'));
});

test('document theme: network_topology -> cisco, metadata and node overrides win', async () => {
  const base: GraphDocument = {
    schemaVersion: '1.0', diagramId: 't', name: 't', diagramType: 'network_topology',
    nodes: [{ id: 'fw', label: '防火墙', kind: 'firewall' }], groups: [], edges: [],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const shapeOf = async (doc: GraphDocument) =>
    parseDrawioXml(serializeDrawio(doc, await layoutGraph(doc))).cellById.get('n_fw')!.style ?? '';

  assert.ok((await shapeOf(base)).includes('shape=mxgraph.cisco.security.ios_firewall'));
  // metadata.iconTheme opts the whole diagram out
  const optedOut: GraphDocument = { ...base, metadata: { iconTheme: 'networks' } };
  assert.ok((await shapeOf(optedOut)).includes('shape=mxgraph.networks.firewall'));
  // node.style.iconTheme overrides one node (and is not emitted as a style key)
  const perNode: GraphDocument = {
    ...base,
    nodes: [{ id: 'fw', label: '防火墙', kind: 'firewall', style: { iconTheme: 'networks' } }],
  };
  const style = await shapeOf(perNode);
  assert.ok(style.includes('shape=mxgraph.networks.firewall'));
  assert.ok(!style.includes('iconTheme'));
});

test('business architecture keeps the networks/flat theme and orthogonal edges', async () => {
  const doc: GraphDocument = {
    schemaVersion: '1.0', diagramId: 'b', name: 'b', diagramType: 'business_architecture',
    nodes: [
      { id: 'svc', label: '内容服务', kind: 'service' },
      { id: 'db', label: '内容库', kind: 'database' },
    ],
    groups: [],
    edges: [{ id: 'e1', source: 'svc', target: 'db', kind: 'dataflow', direction: 'bidirectional', label: '读写' }],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const parsed = parseDrawioXml(serializeDrawio(doc, await layoutGraph(doc)));
  assert.ok(parsed.cellById.get('n_svc')!.style?.includes('shape=process'));
  assert.ok(parsed.cellById.get('n_db')!.style?.includes('shape=mxgraph.networks.storage'));
  const edge = parsed.cellById.get('e_e1')!.style ?? '';
  assert.ok(edge.includes('edgeStyle=orthogonalEdgeStyle'));
  assert.ok(edge.includes('startArrow=block') && edge.includes('endArrow=block'));
});

test('cisco non-physical edges keep arrows and labels on straight lines', () => {
  const style = composeEdgeStyle('dataflow', 'forward', undefined, 'cisco');
  assert.ok(style.includes('endArrow=block') && style.includes('startArrow=none'));
  assert.ok(!style.includes('edgeStyle=orthogonalEdgeStyle'));
  assert.ok(composeEdgeStyle('logical', 'forward', undefined, 'cisco').includes('dashed=1'));
});
