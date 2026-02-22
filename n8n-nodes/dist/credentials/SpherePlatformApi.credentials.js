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
}
exports.SpherePlatformApi = SpherePlatformApi;
//# sourceMappingURL=SpherePlatformApi.credentials.js.map