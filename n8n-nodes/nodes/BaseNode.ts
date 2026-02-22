import {
    ICredentialDataDecryptedObject,
    INode,
    IRequestOptions,
    IHttpRequestMethods,
    NodeApiError,
} from 'n8n-workflow';

/**
 * Minimal structural type shared by IExecuteFunctions and IHookFunctions.
 * Allows sphereApiRequest to be called from both execute() and webhookMethods.
 */
export interface SphereFunctionContext {
    getCredentials<T extends object = ICredentialDataDecryptedObject>(
        type: string,
        itemIndex?: number,
    ): Promise<T>;
    getNode(): INode;
    helpers: {
        request(options: IRequestOptions): Promise<unknown>;
    };
}

/**
 * Shared HTTP helper for all Sphere Platform nodes.
 * Accepts both IExecuteFunctions and IHookFunctions (structural duck-typing).
 */
export async function sphereApiRequest(
    this: SphereFunctionContext,
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
