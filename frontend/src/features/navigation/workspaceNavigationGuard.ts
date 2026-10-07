'use client';

import { useEffect, useRef } from 'react';

type LeaveGuard = () => boolean;
const guards = new Map<symbol, LeaveGuard>();

/** Only mounted workspaces participate. No document, token or draft is stored. */
export function registerWorkspaceLeaveGuard(guard: LeaveGuard): () => void {
  const owner = Symbol('workspace');
  guards.set(owner, guard);
  if (guards.size === 1) document.addEventListener('click', captureNavigation, true);
  return () => {
    guards.delete(owner);
    if (!guards.size) document.removeEventListener('click', captureNavigation, true);
  };
}

/** For programmatic navigation and sign-out, before their side effects start. */
export function workspaceNavigationAllowed(): boolean {
  for (const guard of guards.values()) {
    try { if (!guard()) return false; }
    catch { return false; }
  }
  return true;
}

function captureNavigation(event: MouseEvent) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;
  if (!(anchor instanceof HTMLAnchorElement) || anchor.hasAttribute('download')
    || (anchor.target && anchor.target.toLowerCase() !== '_self')) return;
  let destination: URL;
  try { destination = new URL(anchor.href, window.location.href); }
  catch { return; }
  if (!['http:', 'https:'].includes(destination.protocol)) return;
  // In-page navigation keeps the editor mounted; a different query can own a
  // different script, even when pathname is unchanged.
  if (destination.origin === window.location.origin && destination.pathname === window.location.pathname
    && destination.search === window.location.search) return;
  if (workspaceNavigationAllowed()) return;
  event.preventDefault();
  event.stopImmediatePropagation();
}

/** Protect ordinary links, including sidebar/breadcrumbs and portal content. */
export function useWorkspaceNavigationGuard(guard: LeaveGuard): void {
  const current = useRef(guard); current.current = guard;
  useEffect(() => {
    const unregister = registerWorkspaceLeaveGuard(() => current.current());
    return unregister;
  }, []);
}
