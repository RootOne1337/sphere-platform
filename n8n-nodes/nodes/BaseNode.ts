import { IExecuteFunctions, IHttpRequestMethods, NodeApiError } from 'n8n-workflow';

/**
 * Shared HTTP helper for all Sphere Platform nodes.
 * Reads credentials (serverUrl, apiKey, orgId) from SpherePlatformApi
 * and attaches the required X-API-Key / X-Org-ID headers automatically.
 */
export async function sphereApiRequest(
    this: IExecuteFunctions,
    method: IHttpRequestMethods,
    path: string,
    body?: object,
    qs?: Record<string, string>,
): Promise<unknown> {
    const creds = await this.getCredentials('spherePlatformApi');

    const options = {
        method,
        url: `${creds.serverUrl as string}/api/v1${path}`,
        headers: {
            'X-API-Key': creds.apiKey as string,
            'X-Org-ID': creds.orgId as string,
            'Content-Type': 'application/json',
        },
        body,
        qs,
        json: true,
    };

    try {
        return await this.helpers.request(options);
    } catch (error) {
        throw new NodeApiError(this.getNode(), error as never);
    }
}
