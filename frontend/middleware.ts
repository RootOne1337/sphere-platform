import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Auth redirect убран из middleware — переведён на client-side guard (providers.tsx).
// Причина: middleware redirect кэшируется в Next.js Router Cache и вызывает
// бесконечный цикл redirect после login через tunnel (Serveo/Cloudflare).
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
