import {
    IDataObject,
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
} from 'n8n-workflow';
import { sphereApiRequest } from '../BaseNode';

export class SphereDevicePool implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Sphere Device Pool',
        name: 'sphereDevicePool',
        group: ['transform'],
        version: 1,
        subtitle: '={{$parameter["operation"]}}',
        description: 'Manage Sphere Platform device pools and acquire/release devices',
        defaults: {
            name: 'Sphere Device Pool',
        },
        inputs: ['main'],
        outputs: ['main'],
        credentials: [
            {
                name: 'spherePlatformApi',
                required: true,
            },
        ],
        properties: [
            {
                displayName: 'Operation',
                name: 'operation',
                type: 'options',
                noDataExpression: true,
                options: [
                    {
                        name: 'Acquire Device',
                        value: 'acquire',
                        description: 'Acquire a device from the pool',
                        action: 'Acquire a device from the pool',
                    },
                    {
                        name: 'Release Device',
                        value: 'release',
                        description: 'Release a previously acquired device back to the pool',
                        action: 'Release a device back to the pool',
                    },
                    {
                        name: 'List Devices',
                        value: 'list',
                        description: 'List all devices in the pool',
                        action: 'List all devices in the pool',
                    },
                ],
                default: 'list',
            },
            {
                displayName: 'Group ID',
                name: 'groupId',
                type: 'string',
                default: '',
                description: 'Device group ID to filter by',
                displayOptions: {
                    show: {
                        operation: ['acquire', 'list'],
                    },
                },
            },
            {
                displayName: 'Device ID',
                name: 'deviceId',
                type: 'string',
                default: '',
                required: true,
                description: 'Device ID to release',
                displayOptions: {
                    show: {
                        operation: ['release'],
                    },
                },
            },
        ],
    };

    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];
        const operation = this.getNodeParameter('operation', 0) as string;

        for (let i = 0; i < items.length; i++) {
            let responseData: unknown;

            if (operation === 'list') {
                const groupId = this.getNodeParameter('groupId', i, '') as string;
                const qs: Record<string, string> = {};
                if (groupId) qs.group_id = groupId;
                responseData = await sphereApiRequest.call(this, 'GET', '/devices', undefined, qs);
            } else if (operation === 'acquire') {
                const groupId = this.getNodeParameter('groupId', i, '') as string;
                const body: Record<string, string> = {};
                if (groupId) body.group_id = groupId;
                responseData = await sphereApiRequest.call(this, 'POST', '/devices/acquire', body);
            } else if (operation === 'release') {
                const deviceId = this.getNodeParameter('deviceId', i) as string;
                responseData = await sphereApiRequest.call(this, 'POST', `/devices/${deviceId}/release`, undefined);
            }

            const executionData = this.helpers.constructExecutionMetaData(
                this.helpers.returnJsonArray(responseData as IDataObject),
                { itemData: { item: i } },
            );
            returnData.push(...executionData);
        }

        return [returnData];
    }
}
