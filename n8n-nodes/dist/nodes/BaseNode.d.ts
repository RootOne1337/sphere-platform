import { IExecuteFunctions, IHttpRequestMethods } from 'n8n-workflow';
/**
 * Shared HTTP helper for all Sphere Platform nodes.
 * Reads credentials (serverUrl, apiKey, orgId) from SpherePlatformApi
 * and attaches the required X-API-Key / X-Org-ID headers automatically.
 */
export declare function sphereApiRequest(this: IExecuteFunctions, method: IHttpRequestMethods, path: string, body?: object, qs?: Record<string, string>): Promise<unknown>;
//# sourceMappingURL=BaseNode.d.ts.map