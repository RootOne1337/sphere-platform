"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.sphereApiRequest = sphereApiRequest;
const n8n_workflow_1 = require("n8n-workflow");
/**
 * Shared HTTP helper for all Sphere Platform nodes.
 * Accepts both IExecuteFunctions and IHookFunctions (structural duck-typing).
 */
async function sphereApiRequest(method, path, body, qs) {
    const creds = await this.getCredentials('spherePlatformApi');
    const options = {
        method,
        url: `${creds.serverUrl}/api/v1${path}`,
        headers: {
            'X-API-Key': creds.apiKey,
            'X-Org-ID': creds.orgId,
            'Content-Type': 'application/json',
        },
        body,
        qs,
        json: true,
    };
    try {
        return await this.helpers.request(options);
    }
    catch (error) {
        throw new n8n_workflow_1.NodeApiError(this.getNode(), error);
    }
}
//# sourceMappingURL=BaseNode.js.map