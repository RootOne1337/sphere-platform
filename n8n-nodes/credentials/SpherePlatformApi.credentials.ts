import { ICredentialType, INodeProperties } from 'n8n-workflow';

export class SpherePlatformApi implements ICredentialType {
    name = 'spherePlatformApi';
    displayName = 'Sphere Platform API';
    documentationUrl = 'https://docs.sphere.local';

    properties: INodeProperties[] = [
        {
            displayName: 'Server URL',
            name: 'serverUrl',
            type: 'string',
            default: 'http://backend:8000',
            required: true,
            placeholder: 'https://api.sphere.local',
        },
        {
            displayName: 'API Key',
            name: 'apiKey',
            type: 'string',
            typeOptions: { password: true },
            default: '',
            required: true,
            description: 'API key в формате sphr_prod_<hex32>',
        },
        {
            displayName: 'Organization ID',
            name: 'orgId',
            type: 'string',
            default: '',
            required: true,
        },
    ];
}
