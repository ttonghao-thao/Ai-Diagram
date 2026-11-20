/**
 * Semantic validation tests (docs/06 section 2: G-02 ~ G-05) on the renderer
 * side validator. The same rules are implemented in backend pytest.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateGraph } from '../src/validate.js';
import { ErrorCodes, GraphValidationError } from '../src/errors.js';
import type { GraphDocument } from '../src/types.js';

function baseDoc(): GraphDocument {
  return {
    schemaVersion: '1.0',
    diagramId: 'test_doc',
    name: '测试图',
    diagramType: 'network_topology',
    nodes: [
      { id: 'a', label: '节点A', kind: 'server' },
      { id: 'b', label: '节点B', kind: 'switch' },
    ],
    groups: [],
    edges: [{ id: 'e1', source: 'a', target: 'b', kind: 'physical', direction: 'undirected' }],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
}

function expectError(raw: unknown, code: string): GraphValidationError {
  try {
    validateGraph(raw);
  } catch (err) {
    assert.ok(err instanceof GraphValidationError, `expected GraphValidationError, got: ${err}`);
    const found = err.issues.some((i) => i.code === code);
    assert.ok(found, `expected issue ${code} in:\n${err.issues.map((i) => i.code).join('\n')}`);
    return err;
  }
  throw new Error(`expected validation error ${code}, but validation passed`);
}

test('valid base document passes with no errors or warnings', () => {
  const result = validateGraph(baseDoc());
  assert.equal(result.doc.nodes.length, 2);
  assert.equal(result.warnings.length, 0);
});

test('G-02 duplicate node id is rejected with GRAPH_DUPLICATE_ID', () => {
  const doc = baseDoc();
  doc.nodes.push({ id: 'a', label: '重复节点', kind: 'server' });
  expectError(doc, ErrorCodes.GRAPH_DUPLICATE_ID);
});

test('G-02 duplicate id across entity types (node id == edge id) is rejected', () => {
  const doc = baseDoc();
  (doc.nodes[1] as { id: string }).id = 'e1';
  expectError(doc, ErrorCodes.GRAPH_DUPLICATE_ID);
});

test('G-03 edge referencing missing node is rejected', () => {
  const doc = baseDoc();
  doc.edges[0].target = 'ghost';
  expectError(doc, ErrorCodes.GRAPH_INVALID_REFERENCE);
});

test('G-03 edge with missing source is rejected', () => {
  const doc = baseDoc();
  doc.edges[0].source = 'ghost';
  expectError(doc, ErrorCodes.GRAPH_INVALID_REFERENCE);
});

test('G-04 node groupId referencing missing group is rejected', () => {
  const doc = baseDoc();
  doc.nodes[0].groupId = 'no_such_group';
  expectError(doc, ErrorCodes.GRAPH_INVALID_REFERENCE);
});

test('G-04 group parentId referencing missing group is rejected', () => {
  const doc = baseDoc();
  doc.groups.push({ id: 'g1', label: '组', parentId: 'missing' });
  expectError(doc, ErrorCodes.GRAPH_INVALID_REFERENCE);
});

test('G-05 nested group cycle is rejected with GRAPH_GROUP_CYCLE', () => {
  const doc = baseDoc();
  doc.groups.push(
    { id: 'g1', label: '组1', parentId: 'g2' },
    { id: 'g2', label: '组2', parentId: 'g1' },
  );
  expectError(doc, ErrorCodes.GRAPH_GROUP_CYCLE);
});

test('G-05 self-parenting group is rejected with GRAPH_GROUP_CYCLE', () => {
  const doc = baseDoc();
  doc.groups.push({ id: 'g1', label: '组1', parentId: 'g1' });
  expectError(doc, ErrorCodes.GRAPH_GROUP_CYCLE);
});

test('physical edge with a direction produces a warning, not an error', () => {
  const doc = baseDoc();
  doc.edges[0].direction = 'forward';
  const result = validateGraph(doc);
  assert.equal(result.warnings.length, 1);
  assert.equal(result.warnings[0].code, ErrorCodes.GRAPH_PHYSICAL_EDGE_DIRECTION);
  assert.deepEqual(result.warnings[0].relatedIds, ['e1']);
});

test('non-physical undirected edges produce no warnings', () => {
  const doc = baseDoc();
  doc.edges[0] = { id: 'e1', source: 'a', target: 'b', kind: 'dataflow', direction: 'forward' };
  const result = validateGraph(doc);
  assert.equal(result.warnings.length, 0);
});

test('schema violations are reported with SCHEMA_INVALID', () => {
  const raw = { ...baseDoc(), schemaVersion: '2.0' };
  expectError(raw, ErrorCodes.SCHEMA_INVALID);
});

test('bad id pattern is rejected', () => {
  const doc = baseDoc();
  (doc.nodes[0] as { id: string }).id = '9bad id';
  expectError(doc, ErrorCodes.SCHEMA_INVALID);
});

test('empty label is rejected', () => {
  const doc = baseDoc();
  doc.nodes[0].label = '';
  expectError(doc, ErrorCodes.SCHEMA_INVALID);
});

test('unknown node kind is rejected', () => {
  const doc = baseDoc();
  (doc.nodes[0] as { kind: string }).kind = 'spaceship';
  expectError(doc, ErrorCodes.SCHEMA_INVALID);
});

test('non-positive geometry is rejected', () => {
  const doc = baseDoc();
  doc.nodes[0].geometry = { x: 0, y: 0, width: 0, height: 40 };
  expectError(doc, ErrorCodes.SCHEMA_INVALID);
});

test('all errors are collected in a single validation pass', () => {
  const doc = baseDoc();
  doc.nodes.push({ id: 'a', label: '重复', kind: 'server' });
  doc.edges.push({ id: 'bad_ref', source: 'a', target: 'ghost', kind: 'logical', direction: 'forward' });
  try {
    validateGraph(doc);
    assert.fail('expected GraphValidationError');
  } catch (err) {
    assert.ok(err instanceof GraphValidationError);
    const codes = new Set(err.issues.map((i) => i.code));
    assert.ok(codes.has(ErrorCodes.GRAPH_DUPLICATE_ID));
    assert.ok(codes.has(ErrorCodes.GRAPH_INVALID_REFERENCE));
  }
});
