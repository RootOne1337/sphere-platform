import { createGrafanaSession } from '@/lib/server/observability';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const POST = createGrafanaSession;
