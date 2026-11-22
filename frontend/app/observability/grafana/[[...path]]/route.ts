import { proxyGrafana } from '@/lib/server/observability';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
async function handler(request: Request, context: { params: Promise<{ path?: string[] }> }) {
    return proxyGrafana(request, (await context.params).path ?? []);
}
export { handler as GET, handler as HEAD, handler as POST, handler as PUT, handler as PATCH, handler as DELETE };
