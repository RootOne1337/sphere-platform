# SPLIT-2 — SphereDevicePool Node

**ТЗ-родитель:** TZ-09-n8n-Integration  
**Ветка:** `stage/9-n8n`  
**Задача:** `SPHERE-047`  
**Исполнитель:** Backend/Node.js  
**Оценка:** 1 день  
**Блокирует:** TZ-09 SPLIT-3

---

## Цель Сплита

Node для получения списка устройств с фильтрацией — входная точка для любого n8n workflow, работающего с парком устройств.

---

## Шаг 1 — SphereDevicePool.node.ts

```typescript
// nodes/SphereDevicePool/SphereDevicePool.node.ts
import {
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    NodeOperationError,
} from 'n8n-workflow';
import { sphereApiRequest } from '../BaseNode';

export class SphereDevicePool implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Sphere Platform Device Pool',
        name: 'sphereDevicePool',
        icon: 'file:SphereDevicePool.node.json',
        group: ['transform'],
        version: 1,
        subtitle: '={{$parameter["operation"]}}',
        description: 'Query devices from Sphere Platform fleet',
        defaults: { name: 'Device Pool' },
        inputs: ['main'],
        outputs: ['main'],
        credentials: [{ name: 'spherePlatformApi', required: true }],
        
        properties: [
            {
                displayName: 'Operation',
                name: 'operation',
                type: 'options',
                noDataExpression: true,
                options: [
                    { name: 'Get All Devices', value: 'getAll' },
                    { name: 'Get by Tags', value: 'getByTags' },
                    { name: 'Get Online Only', value: 'getOnline' },
                    { name: 'Get by Group', value: 'getByGroup' },
                ],
                default: 'getAll',
            },
            {
                displayName: 'Tags',
                name: 'tags',
                type: 'string',
                default: '',
                placeholder: 'farm1,automation',
                description: 'Comma-separated tags filter',
                displayOptions: { show: { operation: ['getByTags'] } },
            },
            {
                displayName: 'Group ID',
                name: 'groupId',
                type: 'string',
                default: '',
                displayOptions: { show: { operation: ['getByGroup'] } },
            },
            {
                displayName: 'Limit',
                name: 'limit',
                type: 'number',
                default: 100,
                description: 'Max devices to return',
            },
            {
                displayName: 'Output Mode',
                name: 'outputMode',
                type: 'options',
                options: [
                    { name: 'One Item per Device', value: 'each' },
                    { name: 'All Devices in One Item', value: 'all' },
                ],
                default: 'each',
            },
        ],
    };
    
    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const operation = this.getNodeParameter('operation', 0) as string;
        const limit = this.getNodeParameter('limit', 0) as number;
        
        const qs: Record<string, string> = {
            limit: String(limit),
        };
        
        if (operation === 'getByTags') {
            const tags = this.getNodeParameter('tags', 0) as string;
            if (!tags) throw new NodeOperationError(this.getNode(), 'Tags are required');
            qs.tags = tags;
        }
        
        if (operation === 'getByGroup') {
            const groupId = this.getNodeParameter('groupId', 0) as string;
            if (!groupId) throw new NodeOperationError(this.getNode(), 'Group ID is required');
            qs.group_id = groupId;
        }
        
        if (operation === 'getOnline') {
            qs.status = 'online';
        }
        
        const response = await sphereApiRequest.call(this, 'GET', '/devices', undefined, qs);
        const devices: object[] = response.items ?? response ?? [];
        
        const outputMode = this.getNodeParameter('outputMode', 0) as string;
        
        if (outputMode === 'all') {
            return [[{ json: { devices, count: devices.length } }]];
        }
        
        // each: один item на устройство
        return [devices.map((device) => ({ json: device as Record<string, unknown> }))];
    }
}
```

---

## Шаг 2 — Icon файл (placeholder)

```json
// nodes/SphereDevicePool/SphereDevicePool.node.json
{
  "node": "n8n-nodes-sphereplatform.sphereDevicePool",
  "nodeVersion": "1",
  "codexVersion": "1.0",
  "categories": ["Productivity"],
  "resources": {
    "primaryDocumentation": [
      { "url": "https://docs.sphere.local/n8n" }
    ]
  }
}
```

---

## Шаг 3 — Пример Workflow JSON

```json
{
  "name": "Sphere Platform — Ежедневная задача",
  "nodes": [
    {
      "parameters": {
        "rule": { "interval": [{ "field": "cronExpression", "expression": "0 9 * * 1-5" }] }
      },
      "type": "n8n-nodes-base.scheduleTrigger",
      "name": "Расписание",
      "position": [240, 300]
    },
    {
      "parameters": {
        "operation": "getByTags",
        "tags": "production",
        "limit": 50,
        "outputMode": "each"
      },
      "type": "n8n-nodes-sphereplatform.sphereDevicePool",
      "name": "Получить устройства",
      "credentials": { "spherePlatformApi": { "id": "1" } },
      "position": [440, 300]
    }
  ],
  "connections": {
    "Расписание": { "main": [[{ "node": "Получить устройства", "type": "main", "index": 0 }]] }
  }
}
```

---

## Критерии готовности

- [ ] `getAll` возвращает все устройства без фильтра
- [ ] `getByTags` передаёт `?tags=tag1,tag2` в запрос
- [ ] `getOnline` передаёт `?status=online`
- [ ] `outputMode=each` → каждое устройство отдельным item (downstream SplitInBatches работает)
- [ ] `outputMode=all` → один item с массивом devices и count
- [ ] Пустой список → пустой output (не ошибка)
