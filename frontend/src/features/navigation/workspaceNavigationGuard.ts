'use client';

import { useEffect, useRef } from 'react';

type LeaveGuard = () => boolean | Promise<boolean>;
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
export function workspaceNavigationAllowed(): boolean | Promise<boolean> {
  const owners = [...guards.entries()];
  const stillOwned = () => guards.size === owners.length && owners.every(([owner, guard]) => guards.get(owner) === guard);
  function check(index: number): boolean | Promise<boolean> {
    if (index === owners.length) return stillOwned();
    const [owner, guard] = owners[index];
    if (guards.get(owner) !== guard) return false;
    try {
      const result = guard();
      if (typeof result === 'boolean') return result && check(index + 1);
      return result.then(allowed => allowed && stillOwned() ? check(index + 1) : false, () => false);
    } catch { return false; }
  }
  return check(0);
}

export function navigateFromWorkspace(perform: () => void): void {
  const result = workspaceNavigationAllowed();
  if (typeof result === 'boolean') { if (result) perform(); }
  else void result.then(allowed => { if (allowed) perform(); });
}

const resumedLinks = new WeakSet<HTMLAnchorElement>();

function captureNavigation(event: MouseEvent) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;
  if (!(anchor instanceof HTMLAnchorElement) || anchor.hasAttribute('download')
    || (anchor.target && anchor.target.toLowerCase() !== '_self')) return;
  if (resumedLinks.has(anchor)) return;
  let destination: URL;
  try { destination = new URL(anchor.href, window.location.href); }
  catch { return; }
  if (!['http:', 'https:'].includes(destination.protocol)) return;
  // In-page navigation keeps the editor mounted; a different query can own a
  // different script, even when pathname is unchanged.
  if (destination.origin === window.location.origin && destination.pathname === window.location.pathname
    && destination.search === window.location.search) return;
  const allowed = workspaceNavigationAllowed();
  if (allowed === true) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const originalHref = anchor.href;
  if (allowed !== false) void allowed.then(confirmed => {
    if (!confirmed || !anchor.isConnected || anchor.href !== originalHref) return;
    resumedLinks.add(anchor);
    try { anchor.click(); } finally { resumedLinks.delete(anchor); }
  });
}

/** Protect ordinary links, including sidebar/breadcrumbs and portal content. */
export function useWorkspaceNavigationGuard(guard: LeaveGuard): void {
  const current = useRef(guard); current.current = guard;
  useEffect(() => {
    const unregister = registerWorkspaceLeaveGuard(() => current.current());
    return unregister;
  }, []);
}
