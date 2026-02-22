"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SphereEventTrigger = void 0;
const crypto_1 = require("crypto");
const BaseNode_1 = require("../BaseNode");
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
                        { name: 'All Events', value: 'all' },
                        { name: 'Task Completed', value: 'task_completed' },
                        { name: 'Task Failed', value: 'task_failed' },
                        { name: 'Device Offline', value: 'device_offline' },
                        { name: 'Device Online', value: 'device_online' },
                        { name: 'VPN Connected', value: 'vpn_connected' },
                        { name: 'VPN Disconnected', value: 'vpn_disconnected' },
                        { name: 'OTA Update Complete', value: 'ota_complete' },
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
                    description: 'Secret provided by Sphere Platform when webhook was registered',
                },
            ],
        };
        this.webhookMethods = {
            default: {
                async checkExists() {
                    const webhookData = this.getWorkflowStaticData('node');
                    return !!webhookData.webhookId;
                },
                async create() {
                    const webhookUrl = this.getNodeWebhookUrl('default');
                    const eventTypes = this.getNodeParameter('eventTypes');
                    const tagsFilter = this.getNodeParameter('tagsFilter');
                    const body = {
                        url: webhookUrl,
                        events: eventTypes.includes('all') ? ['*'] : eventTypes,
                    };
                    if (tagsFilter) {
                        body.tags = tagsFilter.split(',').map((t) => t.trim()).filter(Boolean);
                    }
                    const result = await BaseNode_1.sphereApiRequest.call(this, 'POST', '/webhooks', body);
                    const webhookData = this.getWorkflowStaticData('node');
                    webhookData.webhookId = result.id;
                    return true;
                },
                async delete() {
                    const webhookData = this.getWorkflowStaticData('node');
                    if (webhookData.webhookId) {
                        try {
                            await BaseNode_1.sphereApiRequest.call(this, 'DELETE', `/webhooks/${webhookData.webhookId}`);
                        }
                        catch {
                            // Webhook may already be gone; proceed with cleanup
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
        const body = this.getBodyData();
        const headers = this.getHeaderData();
        if (validateHmac) {
            const secret = this.getNodeParameter('webhookSecret');
            const signature = headers['x-sphere-signature'];
            if (!signature) {
                return {
                    webhookResponse: { status: 401, body: 'Missing X-Sphere-Signature header' },
                };
            }
            const rawBody = JSON.stringify(body);
            const expected = (0, crypto_1.createHmac)('sha256', secret).update(rawBody).digest('hex');
            const provided = signature.replace('sha256=', '');
            // FIX 9.3: constant-time comparison via crypto.timingSafeEqual
            // Prevents timing side-channel attacks on HMAC verification
            const expectedBuf = Buffer.from(expected, 'utf-8');
            const providedBuf = Buffer.from(provided, 'utf-8');
            const valid = expectedBuf.length === providedBuf.length &&
                (0, crypto_1.timingSafeEqual)(expectedBuf, providedBuf);
            if (!valid) {
                return {
                    webhookResponse: { status: 401, body: 'Invalid signature' },
                };
            }
        }
        return {
            workflowData: [[{ json: body }]],
        };
    }
}
exports.SphereEventTrigger = SphereEventTrigger;
//# sourceMappingURL=SphereEventTrigger.node.js.map