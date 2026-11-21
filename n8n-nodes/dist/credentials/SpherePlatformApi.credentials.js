"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SpherePlatformApi = void 0;
class SpherePlatformApi {
    constructor() {
        this.name = 'spherePlatformApi';
        this.displayName = 'Sphere Platform API';
        this.documentationUrl = 'https://docs.sphere.local';
        this.properties = [
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
                description: 'Legacy API key for routes that support it',
            },
            {
                displayName: 'Organization ID',
                name: 'orgId',
                type: 'string',
                default: '',
            },
            {
                displayName: 'Access Token',
                name: 'accessToken',
                type: 'string',
                typeOptions: { password: true },
                default: '',
                description: 'Sphere user access token for routes requiring Bearer authentication',
            },
        ];
    }
}
exports.SpherePlatformApi = SpherePlatformApi;
//# sourceMappingURL=SpherePlatformApi.credentials.js.map