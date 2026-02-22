import {
    IDataObject,
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
} from 'n8n-workflow';
import { sphereApiRequest } from '../BaseNode';

export class SphereExecuteScript implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Sphere Execute Script',
        name: 'sphereExecuteScript',
        group: ['transform'],
        version: 1,
        subtitle: '={{$parameter["scriptId"]}}',
        description: 'Execute a Sphere Platform script on one or more devices',
        defaults: {
            name: 'Sphere Execute Script',
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
                displayName: 'Script ID',
                name: 'scriptId',
                type: 'string',
                default: '',
                required: true,
                description: 'ID of the Sphere script to execute',
            },
            {
                displayName: 'Device IDs',
                name: 'deviceIds',
                type: 'string',
                default: '',
                required: true,
                description: 'Comma-separated list of device IDs to run the script on',
            },
            {
                displayName: 'Parameters',
                name: 'parameters',
                type: 'json',
                default: '{}',
                description: 'JSON object with script parameters',
            },
            {
                displayName: 'Wait for Completion',
                name: 'waitForCompletion',
                type: 'boolean',
                default: true,
                description: 'Whether to wait for the script execution to complete before proceeding',
            },
        ],
    };

    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];

        for (let i = 0; i < items.length; i++) {
            const scriptId = this.getNodeParameter('scriptId', i) as string;
            const deviceIdsRaw = this.getNodeParameter('deviceIds', i) as string;
            const parametersRaw = this.getNodeParameter('parameters', i, '{}') as string;
            const waitForCompletion = this.getNodeParameter('waitForCompletion', i) as boolean;

            const deviceIds = deviceIdsRaw.split(',').map((d) => d.trim()).filter(Boolean);
            let parameters: Record<string, unknown> = {};
            try {
                parameters = JSON.parse(parametersRaw) as Record<string, unknown>;
            } catch {
                parameters = {};
            }

            const body = {
                script_id: scriptId,
                device_ids: deviceIds,
                parameters,
                wait: waitForCompletion,
            };

            const responseData = await sphereApiRequest.call(this, 'POST', '/scripts/execute', body);

            const executionData = this.helpers.constructExecutionMetaData(
                this.helpers.returnJsonArray(responseData as IDataObject),
                { itemData: { item: i } },
            );
            returnData.push(...executionData);
        }

        return [returnData];
    }
}
