# SPLIT-4 — SphereEventTrigger Node (Webhook Receiver)

**ТЗ-родитель:** TZ-09-n8n-Integration  
**Ветка:** `stage/9-n8n`  
**Задача:** `SPHERE-049`  
**Исполнитель:** Backend/Node.js  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-09 SPLIT-5

---

## Цель Сплита

Trigger-нода для запуска n8n workflow при событиях от Sphere Platform (task_completed, device_offline, vpn_status_changed и т.д.).

---

## Шаг 1 — SphereEventTrigger.node.ts

```typescript
// nodes/SphereEventTrigger/SphereEventTrigger.node.ts
import {
    IHookFunctions,
    IWebhookFunctions,
    INodeType,
    INodeTypeDescription,
    IWebhookResponseData,
    NodeOperationError,
} from 'n8n-workflow';
import { sphereApiRequest } from '../BaseNode';
import { createHmac, timingSafeEqual } from 'crypto';

export class SphereEventTrigger implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Sphere Platform Event Trigger',
        name: 'sphereEventTrigger',
        icon: 'file:SphereEventTrigger.node.json',
        group: ['trigger'],
        version: 1,
        description: 'Triggers when Sphere Platform events occur',
        defaults: { name: 'Sphere Event' },
        inputs: [],
        outputs: ['main'],
        credentials: [{ name: 'spherePlatformApi', required: true }],
        webhooks: [{ name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: 'webhook' }],
        
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
                description: 'Only receive events for devices with these tags (comma-separated)',
            },
            {
                displayName: 'Validate HMAC Signature',
                name: 'validateHmac',
                type: 'boolean',
                default: true,
                description: 'Verify X-Sphere-Signature header',
            },
            {
                displayName: 'Webhook Secret',
                name: 'webhookSecret',
                type: 'string',
                typeOptions: { password: true },
                default: '',
                displayOptions: { show: { validateHmac: [true] } },
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
                if (tagsFilter) body.tags = tagsFilter.split(',').map(t => t.trim());
                
                const result = await sphereApiRequest.call(
                    this as unknown as IHookFunctions & Parameters<typeof sphereApiRequest>[0],
                    'POST',
                    '/webhooks',
                    body,
                );
                
                const webhookData = this.getWorkflowStaticData('node');
                webhookData.webhookId = result.id;
                return true;
            },
            
            async delete(this: IHookFunctions): Promise<boolean> {
                const webhookData = this.getWorkflowStaticData('node');
                if (webhookData.webhookId) {
                    await sphereApiRequest.call(
                        this as unknown as any,
                        'DELETE',
                        `/webhooks/${webhookData.webhookId}`,
                    );
                    delete webhookData.webhookId;
                }
                return true;
            },
        },
    };
    
    async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
        const validateHmac = this.getNodeParameter('validateHmac') as boolean;
        const body = this.getBodyData() as Record<string, unknown>;
        const headers = this.getHeaderData();
        
        // Валидация HMAC
        if (validateHmac) {
            const secret = this.getNodeParameter('webhookSecret') as string;
            const signature = headers['x-sphere-signature'] as string;
            
            if (!signature) {
                return { webhookResponse: { status: 401, body: 'Missing signature' } };
            }
            
            const rawBody = JSON.stringify(body);
            const expected = createHmac('sha256', secret)
                .update(rawBody)
                .digest('hex');
            
            const provided = signature.replace('sha256=', '');
            // FIX 9.3: БЫЛО — самописная timingSafeEqual (уязвима к timing-атаке)
            // СТАЛО — crypto.timingSafeEqual (native C-реализация, constant-time)
            const expectedBuf = Buffer.from(expected, 'utf-8');
            const providedBuf = Buffer.from(provided, 'utf-8');
            if (expectedBuf.length !== providedBuf.length || !timingSafeEqual(expectedBuf, providedBuf)) {
                return { webhookResponse: { status: 401, body: 'Invalid signature' } };
            }
        }
        
        return {
            workflowData: [[{ json: body }]],
        };
    }
}

// FIX 9.3: Самописная timingSafeEqual УДАЛЕНА.
// Вместо неё используется crypto.timingSafeEqual из Node.js stdlib:
//  - Реализована на native C-уровне (constant-time)
//  - Не подвержена timing side-channel атакам
//  - Проверка длины ПЕРЕД вызовом — предотвращает length-oracle
```

---

## Критерии готовности

- [ ] `checkExists` возвращает true если webhookId уже сохранён в StaticData
- [ ] `create` регистрирует webhook на сервере, сохраняет ID
- [ ] `delete` удаляет webhook при деактивации workflow
- [ ] HMAC validation: timing-safe compare (не `===`)
- [ ] Отсутствие signature при validateHmac=true → 401 (не 500)
- [ ] `all` в eventTypes → передаёт `["*"]` серверу
