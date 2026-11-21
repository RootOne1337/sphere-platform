"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SphereEventTrigger = void 0;
const crypto_1 = require("crypto");
const BaseNode_1 = require("../BaseNode");
const SUBSCRIPTIONS = '/n8n/webhooks';
const SUPPORTED_EVENTS = new Set(['task.completed', 'task.failed']);
function eventNames(selected) {
    if (selected.includes('all') || selected.includes('*'))
        return ['*'];
    const events = selected.map(event => event.replace(/^task_/, 'task.'));
    if (!events.length || events.some(event => !SUPPORTED_EVENTS.has(event))) {
        throw new Error('Sphere publishes task.completed and task.failed to this node. Select supported events.');
    }
    return [...new Set(events)];
}
function isMissing(error) {
    return String(error === null || error === void 0 ? void 0 : error.httpCode) === '404';
}
class SphereEventTrigger {
    constructor() {
        this.description = {
            displayName: 'Sphere Platform Event Trigger',
            name: 'sphereEventTrigger',
            group: ['trigger'],
            version: 1,
            description: 'Triggers when Sphere Platform events occur',
            defaults: { name: 'Sphere Event' },
            inputs: [],
            outputs: ['main'],
            credentials: [{ name: 'spherePlatformApi', required: true }],
            webhooks: [
                {
                    name: 'default',
                    httpMethod: 'POST',
                    responseMode: 'onReceived',
                    path: 'webhook',
                },
            ],
            properties: [
                {
                    displayName: 'Event Types',
                    name: 'eventTypes',
                    type: 'multiOptions',
                    options: [
                        { name: 'All Supported Events', value: 'all' },
                        { name: 'Task Completed', value: 'task_completed' },
                        { name: 'Task Failed', value: 'task_failed' },
                    ],
                    default: ['task_completed'],
                },
                {
                    displayName: 'Device Tags Filter',
                    name: 'tagsFilter',
                    type: 'string',
                    default: '',
                    description: 'Only receive events for devices with these tags (comma-separated, leave empty for all)',
                },
                {
                    displayName: 'Validate HMAC Signature',
                    name: 'validateHmac',
                    type: 'boolean',
                    default: true,
                    description: 'Whether to verify X-Sphere-Signature header (recommended)',
                },
                {
                    displayName: 'Webhook Secret',
                    name: 'webhookSecret',
                    type: 'string',
                    typeOptions: { password: true },
                    default: '',
                    displayOptions: { show: { validateHmac: [true] } },
                    description: 'Original secret shared with Sphere when this subscription is created',
                },
            ],
        };
        this.webhookMethods = {
            default: {
                async checkExists() {
                    const webhookData = this.getWorkflowStaticData('node');
                    if (typeof webhookData.webhookId !== 'string')
                        return false;
                    try {
                        const result = await BaseNode_1.sphereApiRequest.call(this, 'GET', `${SUBSCRIPTIONS}/${encodeURIComponent(webhookData.webhookId)}`);
                        if ((result === null || result === void 0 ? void 0 : result.id) !== webhookData.webhookId)
                            throw new Error('Sphere did not confirm the subscription ID.');
                        return true;
                    }
                    catch (error) {
                        if (isMissing(error))
                            return false;
                        throw error;
                    }
                },
                async create() {
                    const webhookUrl = this.getNodeWebhookUrl('default');
                    const eventTypes = this.getNodeParameter('eventTypes');
                    const tagsFilter = this.getNodeParameter('tagsFilter');
                    const validateHmac = this.getNodeParameter('validateHmac');
                    const secret = validateHmac ? this.getNodeParameter('webhookSecret') : '';
                    if (validateHmac && !secret)
                        throw new Error('Set the Sphere webhook secret before activating this trigger.');
                    const body = {
                        name: this.getNode().name,
                        url: webhookUrl,
                        events: eventNames(eventTypes),
                        ...(secret ? { secret } : {}),
                    };
                    if (tagsFilter) {
                        body.tags = tagsFilter.split(',').map((t) => t.trim()).filter(Boolean);
                    }
                    const result = await BaseNode_1.sphereApiRequest.call(this, 'POST', SUBSCRIPTIONS, body);
                    if (typeof (result === null || result === void 0 ? void 0 : result.id) !== 'string' || !result.id)
                        throw new Error('Sphere did not confirm the new subscription ID.');
                    const webhookData = this.getWorkflowStaticData('node');
                    webhookData.webhookId = result.id;
                    return true;
                },
                async delete() {
                    const webhookData = this.getWorkflowStaticData('node');
                    if (typeof webhookData.webhookId === 'string') {
                        try {
                            await BaseNode_1.sphereApiRequest.call(this, 'DELETE', `${SUBSCRIPTIONS}/${encodeURIComponent(webhookData.webhookId)}`);
                        }
                        catch (error) {
                            if (!isMissing(error))
                                throw error;
                        }
                        delete webhookData.webhookId;
                    }
                    return true;
                },
            },
        };
    }
    async webhook() {
        const validateHmac = this.getNodeParameter('validateHmac');
        let body = this.getBodyData();
        const headers = this.getHeaderData();
        if (validateHmac) {
            const secret = this.getNodeParameter('webhookSecret');
            const signature = headers['x-sphere-signature'];
            const request = this.getRequestObject();
            if (!Buffer.isBuffer(request.rawBody) && typeof request.readRawBody === 'function') {
                await request.readRawBody();
            }
            const provided = typeof signature === 'string' && /^sha256=[0-9a-f]{64}$/.test(signature)
                ? Buffer.from(signature.slice(7), 'hex') : null;
            const raw = request.rawBody;
            const expected = secret && Buffer.isBuffer(raw)
                ? (0, crypto_1.createHmac)('sha256', (0, crypto_1.createHash)('sha256').update(secret).digest('hex')).update(raw).digest()
                : null;
            if (!provided || !expected || !(0, crypto_1.timingSafeEqual)(expected, provided)) {
                this.getResponseObject().status(401).send('Invalid Sphere webhook signature');
                return { noWebhookResponse: true };
            }
            try {
                body = JSON.parse(raw.toString('utf8'));
            }
            catch {
                this.getResponseObject().status(400).send('Invalid Sphere webhook payload');
                return { noWebhookResponse: true };
            }
        }
        const deliveryId = headers['x-sphere-delivery'];
        if (validateHmac && deliveryId !== undefined && (typeof deliveryId !== 'string' || (body === null || body === void 0 ? void 0 : body.delivery_id) !== deliveryId)) {
            this.getResponseObject().status(401).send('Invalid Sphere webhook delivery ID');
            return { noWebhookResponse: true };
        }
        const json = !validateHmac && typeof deliveryId === 'string' ? { ...body, delivery_id: deliveryId } : body;
        return {
            workflowData: [[{ json }]],
        };
    }
}
exports.SphereEventTrigger = SphereEventTrigger;
//# sourceMappingURL=SphereEventTrigger.node.js.map