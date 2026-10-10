// Audit-only source probe. No API, browser, database or Android operations.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const ts = require(path.join(root, 'frontend/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'frontend/lib/dag/export.ts'), 'utf8');
const moduleExports = {};
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
vm.runInNewContext(compiled, { exports: moduleExports, Set, Object, Error }, { timeout: 1000 });
const nodes = [
  { id: 'start', type: 'Start', data: { action: { type: 'start' } } },
  { id: 'tap', type: 'Tap', data: { action: { type: 'tap', x: 20, y: 30 } } },
  { id: 'end', type: 'End', data: { action: { type: 'end' } } },
];
const edges = [{ source: 'start', target: 'tap' }, { source: 'tap', target: 'end' }];
const payload = moduleExports.exportDag(nodes, edges);
const canonical = JSON.parse(fs.readFileSync(path.join(root, 'frontend/__tests__/fixtures/builder-canonical-dag.json'), 'utf8'));
const graph = moduleExports.importDag(canonical);
process.stdout.write(JSON.stringify({ payload, frontendErrors: moduleExports.validateDag(payload),
  canonicalFixture: canonical, roundtrip: moduleExports.exportDag(graph.nodes, graph.edges, graph.metadata),
  actionTypes: moduleExports.ACTION_TYPES,
}));
