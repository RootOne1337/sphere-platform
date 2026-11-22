const assert = require('node:assert/strict');
const { createHash, createHmac } = require('node:crypto');
const test = require('node:test');
const { SphereEventTrigger } = require('../dist/nodes/SphereEventTrigger/SphereEventTrigger.node.js');

const receiver = new SphereEventTrigger();
const secret = 'local-webhook-contract-fixture';
const deliveryId = 'b17839db-805b-434a-b4da-a4031276f6ce';
const signed = Buffer.from(`{ "event": "task.completed", "data": {"label":"Проверка"}, "delivery_id":"${deliveryId}" }`);
const signature = 'sha256=' + createHmac('sha256', createHash('sha256').update(secret).digest('hex')).update(signed).digest('hex');

function receive({ raw = signed, header = deliveryId, hmac = signature, readRawBody } = {}) {
    const rejected = [];
    const request = { rawBody: raw, readRawBody };
    const context = {
        getNodeParameter: name => ({ validateHmac: true, webhookSecret: secret })[name],
        getBodyData: () => ({ event: 'not the signed value' }),
        getHeaderData: () => ({ 'x-sphere-signature': hmac, 'x-sphere-delivery': header }),
        getRequestObject: () => request,
        getResponseObject: () => ({ status: code => ({ send: () => rejected.push(code) }) }),
    };
    return { result: receiver.webhook.call(context), rejected };
}

test('authenticates exact bytes and forwards the signed delivery ID', async () => {
    const { result, rejected } = receive();
    assert.deepEqual((await result).workflowData, [[{ json: JSON.parse(signed.toString('utf8')) }]]);
    assert.deepEqual(rejected, []);
});

test('rejects a changed delivery ID or a body reserialized after signing', async () => {
    for (const options of [
        { header: 'b845eb09-7841-45df-8bc6-94f6ea07fd26' },
        { raw: Buffer.from(JSON.stringify(JSON.parse(signed.toString('utf8')))) },
        { raw: null },
    ]) {
        const { result, rejected } = receive(options);
        assert.deepEqual(await result, { noWebhookResponse: true });
        assert.deepEqual(rejected, [401]);
    }
});

test('registers and rereads through the tenant-authorized API and retires confirmed deletions', async () => {
    const state = {};
    const requests = [];
    const context = {
        getNodeParameter: name => ({ eventTypes: ['task_completed', 'task.failed'], tagsFilter: 'canary', validateHmac: true, webhookSecret: secret })[name],
        getNodeWebhookUrl: () => 'http://receiver.example/webhook',
        getNode: () => ({ name: 'Canary receiver' }),
        getWorkflowStaticData: () => state,
        getCredentials: async () => ({ serverUrl: 'https://sphere.example', accessToken: 'fixture' }),
        helpers: { request: async options => { requests.push(options); return { id: deliveryId }; } },
    };
    const methods = receiver.webhookMethods.default;
    assert.equal(await methods.checkExists.call(context), false);
    assert.equal(await methods.create.call(context), true);
    assert.deepEqual(requests[0].body, {
        name: 'Canary receiver', url: 'http://receiver.example/webhook', events: ['task.completed', 'task.failed'],
        tags: ['canary'], secret,
    });
    assert.equal(await methods.checkExists.call(context), true);
    assert.equal(await methods.delete.call(context), true);
    assert.deepEqual(requests.map(({ method, url, headers }) => [method, url, headers.Authorization]), [
        ['POST', 'https://sphere.example/api/v1/n8n/webhooks', 'Bearer fixture'],
        ['GET', `https://sphere.example/api/v1/n8n/webhooks/${deliveryId}`, 'Bearer fixture'],
        ['DELETE', `https://sphere.example/api/v1/n8n/webhooks/${deliveryId}`, 'Bearer fixture'],
    ]);
    assert.equal(state.webhookId, undefined);
});
