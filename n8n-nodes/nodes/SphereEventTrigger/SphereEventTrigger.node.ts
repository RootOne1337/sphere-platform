import {
    IDataObject,
    IHookFunctions,
    INodeType,
    INodeTypeDescription,
    IWebhookFunctions,
    IWebhookResponseData,
} from 'n8n-workflow';

export class SphereEventTrigger implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Sphere Event Trigger',
        name: 'sphereEventTrigger',
        group: ['trigger'],
        version: 1,
        subtitle: '={{$parameter["eventType"]}}',
        description: 'Triggers when a Sphere Platform event occurs (device status change, script completion, etc.)',
        defaults: {
            name: 'Sphere Event Trigger',
        },
        inputs: [],
        outputs: ['main'],
        credentials: [
            {
                name: 'spherePlatformApi',
                required: true,
            },
        ],
        webhooks: [
            {
                name: 'default',
                httpMethod: 'POST',
                responseMode: 'onReceived',
                path: 'sphere-event',
            },
        ],
        properties: [
            {
                displayName: 'Event Type',
                name: 'eventType',
                type: 'options',
                options: [
                    {
                        name: 'Device Status Changed',
                        value: 'device.status_changed',
                        description: 'Triggers when a device comes online or goes offline',
                    },
                    {
                        name: 'Script Completed',
                        value: 'script.completed',
                        description: 'Triggers when a script finishes execution',
                    },
                    {
                        name: 'Script Failed',
                        value: 'script.failed',
                        description: 'Triggers when a script execution fails',
                    },
                    {
                        name: 'Device Discovered',
                        value: 'device.discovered',
                        description: 'Triggers when a new device is discovered',
                    },
                ],
                default: 'device.status_changed',
                required: true,
            },
            {
                displayName: 'Device Group ID',
                name: 'groupId',
                type: 'string',
                default: '',
                description: 'Filter events to a specific device group (leave empty for all groups)',
            },
        ],
    };

    webhookMethods = {
        default: {
            async checkExists(this: IHookFunctions): Promise<boolean> {
                // TODO (SPLIT-3): implement webhook registration check via Sphere API
                return false;
            },
            async create(this: IHookFunctions): Promise<boolean> {
                // TODO (SPLIT-3): register webhook with Sphere Platform
                // POST /api/v1/webhooks { url: webhookUrl, events: [eventType] }
                return true;
            },
            async delete(this: IHookFunctions): Promise<boolean> {
                // TODO (SPLIT-3): deregister webhook from Sphere Platform
                // DELETE /api/v1/webhooks/{webhookId}
                return true;
            },
        },
    };

    async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
        const bodyData = this.getBodyData() as IDataObject;
        return {
            workflowData: [
                [
                    {
                        json: bodyData,
                    },
                ],
            ],
        };
    }
}
