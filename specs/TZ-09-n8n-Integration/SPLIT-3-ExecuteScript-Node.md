# SPLIT-3 — SphereExecuteScript Node

**ТЗ-родитель:** TZ-09-n8n-Integration  
**Ветка:** `stage/9-n8n`  
**Задача:** `SPHERE-048`  
**Исполнитель:** Backend/Node.js  
**Оценка:** 1 день  
**Блокирует:** TZ-09 SPLIT-5

---

## Цель Сплита

Node для запуска DAG-скрипта на конкретном устройстве. Поддерживает wait (опрос) и webhook (callback) режимы получения результата.

---

## Шаг 1 — SphereExecuteScript.node.ts

```typescript
// nodes/SphereExecuteScript/SphereExecuteScript.node.ts
import {
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    NodeOperationError,
} from 'n8n-workflow';
import { sphereApiRequest } from '../BaseNode';

export class SphereExecuteScript implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Sphere Platform Execute Script',
        name: 'sphereExecuteScript',
        icon: 'file:SphereExecuteScript.node.json',
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
                description: 'Poll until task completes (max timeout applies)',
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
                description: 'Optional: server calls this URL when task completes',
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
            
            // Создать задачу
            const createBody: Record<string, unknown> = {
                device_id: deviceId,
                script_id: scriptId,
                priority,
            };
            if (webhookUrl) createBody.webhook_url = webhookUrl;
            
            const task = await sphereApiRequest.call(this, 'POST', '/tasks', createBody);
            const taskId = task.id as string;
            
            if (!waitForResult) {
                successOutput.push({ json: { task_id: taskId, status: 'queued' } });
                continue;
            }
            
            // Poll
            const pollTimeoutSec = this.getNodeParameter('pollTimeoutSec', i) as number;
            const deadline = Date.now() + pollTimeoutSec * 1000;
            let taskResult: Record<string, unknown> | null = null;
            
            while (Date.now() < deadline) {
                await sleep(2000);
                const status = await sphereApiRequest.call(this, 'GET', `/tasks/${taskId}`);
                
                if (status.status === 'completed') {
                    taskResult = status;
                    break;
                }
                if (status.status === 'failed') {
                    failedOutput.push({
                        json: {
                            task_id: taskId,
                            status: 'failed',
                            error: status.error,
                            device_id: deviceId,
                        },
                    });
                    taskResult = null;
                    break;
                }
            }
            
            if (taskResult) {
                successOutput.push({
                    json: {
                        task_id: taskId,
                        device_id: deviceId,
                        ...taskResult,
                    },
                });
            } else if (!failedOutput.find(f => (f.json as any).task_id === taskId)) {
                // Timeout
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

function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
}
```

---

## Шаг 2 — Типичный workflow

```
[Schedule] → [Device Pool: getByTags "automation"] → [Execute Script: farm_task_001]
                                                              ↓ success        ↓ failed
                                                       [Set: status=ok]  [Slack alert]
```

---

## Критерии готовности

- [ ] Два output: `success` и `failed` (не исключение)
- [ ] Poll 2 секунды интервал, deadline = Date.now() + timeout
- [ ] Timeout → failed output с `status: "timeout"`
- [ ] `webhookUrl` передаётся в тело запроса только если не пустой
- [ ] `waitForResult=false` → немедленный return с task_id
- [ ] Работает в SplitInBatches loop (items.length > 1)
