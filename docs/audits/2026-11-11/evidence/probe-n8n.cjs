// Exercise the shipped CommonJS node artifacts with synthetic n8n and HTTP contexts.
// No HTTP connection, credential, workflow execution or external module is used.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../../../../n8n-nodes/dist/nodes');
const modules = new Map();
let now = 0;

function load(filename) {
    if (modules.has(filename)) return modules.get(filename);
    const module = { exports: {} };
    const fakeN8n = { NodeOperationError: Error, NodeApiError: Error };
    vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
        exports: module.exports,
        module,
        require(specifier) {
            if (specifier === 'n8n-workflow') return fakeN8n;
            if (specifier === '../BaseNode') return load(path.join(root, 'BaseNode.js'));
            throw new Error(`Unexpected module: ${specifier}`);
        },
        Date: { now: () => now },
        setTimeout(callback, ms) {
            now += ms;
            callback();
        },
    }, { filename });
    modules.set(filename, module.exports);
    return module.exports;
}

function instance(name) {
    const filename = path.join(root, name, `${name}.node.js`);
    return new (load(filename)[name])();
}

function context(parameters, request) {
    return {
        getNodeParameter: (name, index, fallback) => parameters[name] ?? fallback,
        getCredentials: async () => ({ serverUrl: 'https://sphere.example.test', apiKey: 'fixture', orgId: 'fixture' }),
        getInputData: () => [{ json: {} }],
        getNode: () => ({}),
        helpers: { request },
    };
}

async function executeCase(terminal) {
    now = 0;
    const calls = [];
    const params = { deviceId: 'device-fixture', scriptId: 'script-fixture', priority: 5,
        waitForResult: true, pollTimeoutSec: 1 };
    const node = instance('SphereExecuteScript');
    const result = await node.execute.call(context(params, async options => {
        calls.push(options.method);
        if (options.method === 'POST') return { id: 'task-fixture', status: 'queued' };
        return { id: 'task-fixture', status: terminal, error_message: 'Recorded backend reason' };
    }));
    return { backend_terminal: terminal, call_sequence: calls, elapsed_simulated_ms: now, result };
}

async function poolCase() {
    let captured;
    const node = instance('SphereDevicePool');
    const result = await node.execute.call(context({
        operation: 'getByTags', limit: 100, tags: 'fixture-tag', outputMode: 'all',
    }, async options => {
        captured = {
            url: options.url,
            header_names: Object.keys(options.headers).sort(),
            query: options.qs,
        };
        return { items: [{ id: 'untagged-fixture', tags: [] }], total: 140, page: 1, per_page: 50, pages: 3 };
    }));
    return { request: captured, response_to_workflow: result };
}

async function main() {
    const cancelled = await executeCase('cancelled');
    const failed = await executeCase('failed');
    const pool = await poolCase();
    process.stdout.write(JSON.stringify({ cancelled, failed, pool }, null, 2) + '\n');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
