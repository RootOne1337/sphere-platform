import {
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    NodeOperationError,
} from 'n8n-workflow';
import { sphereApiRequest } from '../BaseNode';

interface TaskStatusResponse {
    id: string;
    status: string;
    error?: string;
    [key: string]: unknown;
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

export class SphereExecuteScript implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Sphere Platform Execute Script',
        name: 'sphereExecuteScript',
        group: ['transform'],
        version: 1,
        description: 'Execute a DAG script on a Sphere Platform device',
        defaults: { name: 'Execute Script' },
        inputs: ['main'],
        outputs: ['main', 'main'],
        outputNames: ['success', 'failed'],
        credentials: [{ name: 'spherePlatformApi', required: true }],

        properties: [
            {
                displayName: 'Device ID',
                name: 'deviceId',
                type: 'string',
                default: '={{ $json.id }}',
                required: true,
                description: 'Device UUID from Device Pool node',
            },
            {
                displayName: 'Script ID',
                name: 'scriptId',
                type: 'string',
                default: '',
                required: true,
                description: 'UUID of the script to execute',
            },
            {
                displayName: 'Priority',
                name: 'priority',
                type: 'options',
                options: [
                    { name: 'Low', value: 1 },
                    { name: 'Normal', value: 5 },
                    { name: 'High', value: 10 },
                ],
                default: 5,
            },
            {
                displayName: 'Wait for Result',
                name: 'waitForResult',
                type: 'boolean',
                default: true,
                description: 'Whether to poll until task completes (max timeout applies)',
            },
            {
                displayName: 'Poll Timeout (seconds)',
                name: 'pollTimeoutSec',
                type: 'number',
                default: 120,
                displayOptions: { show: { waitForResult: [true] } },
            },
            {
                displayName: 'Webhook URL',
                name: 'webhookUrl',
                type: 'string',
                default: '',
                description: 'Optional: server calls this URL when task completes (use $execution.resumeUrl for Wait node pattern)',
                displayOptions: { show: { waitForResult: [false] } },
            },
        ],
    };

    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const successOutput: INodeExecutionData[] = [];
        const failedOutput: INodeExecutionData[] = [];

        for (let i = 0; i < items.length; i++) {
            const deviceId = this.getNodeParameter('deviceId', i) as string;
            const scriptId = this.getNodeParameter('scriptId', i) as string;
            const priority = this.getNodeParameter('priority', i) as number;
            const waitForResult = this.getNodeParameter('waitForResult', i) as boolean;
            const webhookUrl = this.getNodeParameter('webhookUrl', i, '') as string;

            if (!deviceId) {
                throw new NodeOperationError(this.getNode(), 'Device ID is required', { itemIndex: i });
            }
            if (!scriptId) {
                throw new NodeOperationError(this.getNode(), 'Script ID is required', { itemIndex: i });
            }

            // Create task
            const createBody: Record<string, unknown> = {
                device_id: deviceId,
                script_id: scriptId,
                priority,
            };
            if (webhookUrl) createBody.webhook_url = webhookUrl;

            const task = await sphereApiRequest.call(this, 'POST', '/tasks', createBody) as TaskStatusResponse;
            const taskId = task.id;

            if (!waitForResult) {
                successOutput.push({ json: { task_id: taskId, status: 'queued', device_id: deviceId } });
                continue;
            }

            // Poll until completed/failed or deadline
            const pollTimeoutSec = this.getNodeParameter('pollTimeoutSec', i) as number;
            const deadline = Date.now() + pollTimeoutSec * 1000;
            let resolved = false;

            while (Date.now() < deadline) {
                await sleep(2000);
                const status = await sphereApiRequest.call(this, 'GET', `/tasks/${taskId}`) as TaskStatusResponse;

                if (status.status === 'completed') {
                    successOutput.push({
                        json: {
                            task_id: taskId,
                            device_id: deviceId,
                            ...status,
                        },
                    });
                    resolved = true;
                    break;
                }

                if (status.status === 'failed') {
                    failedOutput.push({
                        json: {
                            task_id: taskId,
                            status: 'failed',
                            error: status.error ?? 'Unknown error',
                            device_id: deviceId,
                        },
                    });
                    resolved = true;
                    break;
                }
            }

            if (!resolved) {
                failedOutput.push({
                    json: {
                        task_id: taskId,
                        status: 'timeout',
                        device_id: deviceId,
                        error: `Timed out after ${pollTimeoutSec}s`,
                    },
                });
            }
        }

        return [successOutput, failedOutput];
    }
}
