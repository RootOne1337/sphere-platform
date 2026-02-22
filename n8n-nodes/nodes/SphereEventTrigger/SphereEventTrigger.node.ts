import { createHmac, timingSafeEqual } from 'crypto';
import {
    IDataObject,
    IHookFunctions,
    INodeType,
    INodeTypeDescription,
    IWebhookFunctions,
    IWebhookResponseData,
} from 'n8n-workflow';
import { sphereApiRequest, SphereFunctionContext } from '../BaseNode';

interface WebhookCreateResponse {
    id: string;
    [key: string]: unknown;
}

export class SphereEventTrigger implements INodeType {
    description: INodeTypeDescription = {
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

    webhookMethods = {
        default: {
            async checkExists(this: IHookFunctions): Promise<boolean> {
                const webhookData = this.getWorkflowStaticData('node');
                return !!webhookData.webhookId;
            },

            async create(this: IHookFunctions): Promise<boolean> {
                const webhookUrl = this.getNodeWebhookUrl('default');
                const eventTypes = this.getNodeParameter('eventTypes') as string[];
                const tagsFilter = this.getNodeParameter('tagsFilter') as string;

                const body: Record<string, unknown> = {
                    url: webhookUrl,
                    events: eventTypes.includes('all') ? ['*'] : eventTypes,
                };
                if (tagsFilter) {
                    body.tags = tagsFilter.split(',').map((t) => t.trim()).filter(Boolean);
                }

                const result = await sphereApiRequest.call(
                    this as unknown as SphereFunctionContext,
                    'POST',
                    '/webhooks',
                    body,
                ) as WebhookCreateResponse;

                const webhookData = this.getWorkflowStaticData('node');
                webhookData.webhookId = result.id;
                return true;
            },

            async delete(this: IHookFunctions): Promise<boolean> {
                const webhookData = this.getWorkflowStaticData('node');
                if (webhookData.webhookId) {
                    try {
                        await sphereApiRequest.call(
                            this as unknown as SphereFunctionContext,
                            'DELETE',
                            `/webhooks/${webhookData.webhookId as string}`,
                        );
                    } catch {
                        // Webhook may already be gone; proceed with cleanup
                    }
                    delete webhookData.webhookId;
                }
                return true;
            },
        },
    };

    async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
        const validateHmac = this.getNodeParameter('validateHmac') as boolean;
        const body = this.getBodyData() as IDataObject;
        const headers = this.getHeaderData();

        if (validateHmac) {
            const secret = this.getNodeParameter('webhookSecret') as string;
            const signature = headers['x-sphere-signature'] as string | undefined;

            if (!signature) {
                return {
                    webhookResponse: { status: 401, body: 'Missing X-Sphere-Signature header' },
                };
            }

            const rawBody = JSON.stringify(body);
            const expected = createHmac('sha256', secret).update(rawBody).digest('hex');
            const provided = signature.replace('sha256=', '');

            // FIX 9.3: constant-time comparison via crypto.timingSafeEqual
            // Prevents timing side-channel attacks on HMAC verification
            const expectedBuf = Buffer.from(expected, 'utf-8');
            const providedBuf = Buffer.from(provided, 'utf-8');
            const valid =
                expectedBuf.length === providedBuf.length &&
                timingSafeEqual(expectedBuf, providedBuf);

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
