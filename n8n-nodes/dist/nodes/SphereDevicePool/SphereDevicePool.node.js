"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SphereDevicePool = void 0;
const n8n_workflow_1 = require("n8n-workflow");
const BaseNode_1 = require("../BaseNode");
class SphereDevicePool {
    constructor() {
        this.description = {
            displayName: 'Sphere Platform Device Pool',
            name: 'sphereDevicePool',
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
                    description: 'Whether to output each device as a separate item or bundle all into one item',
                },
            ],
        };
    }
    async execute() {
        var _a;
        const operation = this.getNodeParameter('operation', 0);
        const limit = this.getNodeParameter('limit', 0);
        const qs = {
            limit: String(limit),
        };
        if (operation === 'getByTags') {
            const tags = this.getNodeParameter('tags', 0);
            if (!tags) {
                throw new n8n_workflow_1.NodeOperationError(this.getNode(), 'Tags are required for "Get by Tags" operation');
            }
            qs.tags = tags;
        }
        if (operation === 'getByGroup') {
            const groupId = this.getNodeParameter('groupId', 0);
            if (!groupId) {
                throw new n8n_workflow_1.NodeOperationError(this.getNode(), 'Group ID is required for "Get by Group" operation');
            }
            qs.group_id = groupId;
        }
        if (operation === 'getOnline') {
            qs.status = 'online';
        }
        const response = await BaseNode_1.sphereApiRequest.call(this, 'GET', '/devices', undefined, qs);
        const devices = ((_a = response.items) !== null && _a !== void 0 ? _a : (Array.isArray(response) ? response : []));
        const outputMode = this.getNodeParameter('outputMode', 0);
        if (outputMode === 'all') {
            return [[{ json: { devices, count: devices.length } }]];
        }
        // each: один item на устройство; пустой список → пустой output (не ошибка)
        return [devices.map((device) => ({ json: device }))];
    }
}
exports.SphereDevicePool = SphereDevicePool;
//# sourceMappingURL=SphereDevicePool.node.js.map