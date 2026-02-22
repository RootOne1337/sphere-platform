import { ICredentialDataDecryptedObject, INode, IRequestOptions, IHttpRequestMethods } from 'n8n-workflow';
/**
 * Minimal structural type shared by IExecuteFunctions and IHookFunctions.
 * Allows sphereApiRequest to be called from both execute() and webhookMethods.
 */
export interface SphereFunctionContext {
    getCredentials<T extends object = ICredentialDataDecryptedObject>(type: string, itemIndex?: number): Promise<T>;
    getNode(): INode;
    helpers: {
        request(options: IRequestOptions): Promise<unknown>;
    };
}
/**
 * Shared HTTP helper for all Sphere Platform nodes.
 * Accepts both IExecuteFunctions and IHookFunctions (structural duck-typing).
 */
export declare function sphereApiRequest(this: SphereFunctionContext, method: IHttpRequestMethods, path: string, body?: object, qs?: Record<string, string>): Promise<unknown>;
//# sourceMappingURL=BaseNode.d.ts.map