'use client';

import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import { createRouteScrollRestoration } from './routeScrollRestoration';

export function RouteScrollRestoration({ main }: { main: RefObject<HTMLElement | null> }) {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const user = useAuthStore(state => state.user);
  const session = useAuthStore(state => state.sessionVersion);
  const scope = `${session}:${user?.org_id ?? ''}:${user?.id ?? ''}:${user?.role ?? ''}`;
  const key = pathname + (search ? '?' + search : '');
  const keyRef = useRef(key); keyRef.current = key;
  const controller = useRef<ReturnType<typeof createRouteScrollRestoration> | null>(null);
  useEffect(() => {
    // Next installs its own history integration in the parent effect. Compose
    // after that effect and preserve all framework-owned history state fields.
    const frame = window.requestAnimationFrame(() => {
      if (!main.current) return;
      controller.current = createRouteScrollRestoration(main.current);
      controller.current.routeRendered(keyRef.current);
    });
    return () => { window.cancelAnimationFrame(frame); controller.current?.dispose(); controller.current = null; };
  }, [main, scope]);
  useLayoutEffect(() => {
    // App Router can commit a POP before later popstate listeners run. Wait
    // until those listeners and the framework's own scroll reset have settled.
    const frame = window.requestAnimationFrame(() => controller.current?.routeRendered(key));
    return () => window.cancelAnimationFrame(frame);
  }, [key]);
  return null;
}
