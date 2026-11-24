/**
 * CLI integration: generate must work for any valid graph JSON (no fixture
 * special-casing) and reject invalid input with non-zero exit codes.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const CLI = path.join(__dirname, '..', 'src', 'cli.js');

function runCli(args: string[]): { status: number; stdout: string; stderr: string } {
  try {
    const stdout = execFileSync(process.execPath, [CLI, ...args], { encoding: 'utf8', cwd: REPO_ROOT });
    return { status: 0, stdout, stderr: '' };
  } catch (err) {
    const e = err as { status?: number; stdout?: string; stderr?: string };
    return { status: e.status ?? 1, stdout: e.stdout ?? '', stderr: e.stderr ?? '' };
  }
}

test('CLI generate renders the network fixture and validate accepts it', () => {
  const out = path.join(REPO_ROOT, 'out', 'cli-network.drawio');
  const res = runCli(['generate', '--input', 'fixtures/network.graph.json', '--output', out]);
  assert.equal(res.status, 0, `generate failed: ${res.stderr}`);
  assert.ok(existsSync(out));
  const val = runCli(['validate', '--input', out]);
  assert.equal(val.status, 0, `validate failed: ${val.stderr}`);
  assert.match(val.stdout, /OK/);
  rmSync(out);
});

test('CLI generate renders the business fixture', () => {
  const out = path.join(REPO_ROOT, 'out', 'cli-business.drawio');
  const res = runCli(['generate', '--input', 'fixtures/business.graph.json', '--output', out]);
  assert.equal(res.status, 0, `generate failed: ${res.stderr}`);
  assert.ok(existsSync(out));
  const xml = readFileSync(out, 'utf8');
  assert.ok(xml.includes('<mxfile host="ai-diagram-studio" compressed="false">'));
  rmSync(out);
});

test('CLI rejects an invalid graph with exit code 1 and a machine-readable code', () => {
  const bad = path.join(REPO_ROOT, 'out', 'bad-graph.json');
  rmSync(bad, { force: true });
  const doc = {
    schemaVersion: '1.0',
    diagramId: 'bad_graph',
    name: '坏图',
    diagramType: 'network_topology',
    nodes: [{ id: 'a', label: 'A', kind: 'server' }],
    groups: [],
    edges: [{ id: 'e1', source: 'a', target: 'ghost', kind: 'physical', direction: 'undirected' }],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const { writeFileSync, mkdirSync } = require('node:fs') as typeof import('node:fs');
  mkdirSync(path.dirname(bad), { recursive: true });
  writeFileSync(bad, JSON.stringify(doc), 'utf8');
  const res = runCli(['generate', '--input', bad, '--output', path.join(REPO_ROOT, 'out', 'bad.drawio')]);
  assert.equal(res.status, 1);
  assert.match(res.stderr, /GRAPH_INVALID_REFERENCE/);
  assert.ok(!existsSync(path.join(REPO_ROOT, 'out', 'bad.drawio')), 'no output file may be written for an invalid graph');
  rmSync(bad);
});

test('CLI usage error exits 2', () => {
  const res = runCli(['generate']);
  assert.equal(res.status, 2);
});

test('CLI honors the caller\'s layout.direction and metadata.iconTheme', () => {
  // Layout-only: previously the validator replaced direction/algorithm with
  // DOWN/layered and dropped metadata, so these options never reached the renderer.
  const dir = path.join(REPO_ROOT, 'out', 'cli-options');
  mkdirSync(dir, { recursive: true });
  const graph = {
    schemaVersion: '1.0',
    diagramId: 'cli_options',
    name: '方向与主题',
    diagramType: 'network_topology',
    nodes: [
      { id: 'fw', label: '防火墙', kind: 'firewall' },
      { id: 'sw', label: '交换机', kind: 'switch' },
    ],
    groups: [],
    edges: [{ id: 'l1', source: 'fw', target: 'sw', kind: 'physical', direction: 'undirected' }],
    layout: { algorithm: 'layered', direction: 'RIGHT', preserveManualPositions: true },
    metadata: { iconTheme: 'networks' },
  };
  const input = path.join(dir, 'graph.json');
  const output = path.join(dir, 'graph.drawio');
  writeFileSync(input, JSON.stringify(graph), 'utf8');
  const res = runCli(['generate', '--input', input, '--output', output]);
  assert.equal(res.status, 0, res.stderr);
  const { parseDrawioXml } = require('../src/drawio/xmlReader.js') as typeof import('../src/drawio/xmlReader.js');
  const parsed = parseDrawioXml(readFileSync(output, 'utf8'));
  const fw = parsed.cellById.get('n_fw')!.geometry!;
  const sw = parsed.cellById.get('n_sw')!.geometry!;
  // RIGHT layout: one row (vertically center-aligned), higher tier on the left.
  const fwCenter = (fw.y ?? 0) + (fw.height ?? 0) / 2;
  const swCenter = (sw.y ?? 0) + (sw.height ?? 0) / 2;
  assert.ok(Math.abs(fwCenter - swCenter) <= 1, `centers differ: ${fwCenter} vs ${swCenter}`);
  assert.ok((fw.x ?? 0) < (sw.x ?? 0), 'RIGHT layout must put the higher tier on the left');
  assert.ok(parsed.cellById.get('n_fw')!.style?.includes('shape=mxgraph.networks.firewall'));
  rmSync(dir, { recursive: true, force: true });
});
