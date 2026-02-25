"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SphereExecuteScript = void 0;
const n8n_workflow_1 = require("n8n-workflow");
const BaseNode_1 = require("../BaseNode");
function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
class SphereExecuteScript {
    constructor() {
        this.description = {
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
    }
    async execute() {
        var _a;
        const items = this.getInputData();
        const successOutput = [];
        const failedOutput = [];
        for (let i = 0; i < items.length; i++) {
            const deviceId = this.getNodeParameter('deviceId', i);
            const scriptId = this.getNodeParameter('scriptId', i);
            const priority = this.getNodeParameter('priority', i);
            const waitForResult = this.getNodeParameter('waitForResult', i);
            const webhookUrl = this.getNodeParameter('webhookUrl', i, '');
            if (!deviceId) {
                throw new n8n_workflow_1.NodeOperationError(this.getNode(), 'Device ID is required', { itemIndex: i });
            }
            if (!scriptId) {
                throw new n8n_workflow_1.NodeOperationError(this.getNode(), 'Script ID is required', { itemIndex: i });
            }
            // Create task
            const createBody = {
                device_id: deviceId,
                script_id: scriptId,
                priority,
            };
            if (webhookUrl)
                createBody.webhook_url = webhookUrl;
            const task = await BaseNode_1.sphereApiRequest.call(this, 'POST', '/tasks', createBody);
            const taskId = task.id;
            if (!waitForResult) {
                successOutput.push({ json: { task_id: taskId, status: 'queued', device_id: deviceId } });
                continue;
            }
            // Poll until completed/failed or deadline
            const pollTimeoutSec = this.getNodeParameter('pollTimeoutSec', i);
            const deadline = Date.now() + pollTimeoutSec * 1000;
            let resolved = false;
            while (Date.now() < deadline) {
                await sleep(2000);
                const status = await BaseNode_1.sphereApiRequest.call(this, 'GET', `/tasks/${taskId}`);
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
                            error: (_a = status.error) !== null && _a !== void 0 ? _a : 'Unknown error',
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
exports.SphereExecuteScript = SphereExecuteScript;
//# sourceMappingURL=SphereExecuteScript.node.js.map