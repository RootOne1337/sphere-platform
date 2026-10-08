/** Tab-local geometry only. No API data, tokens, pixels or drafts are retained. */
const ENTRY_FIELD = '__sphereScrollEntry';
const LIMIT = 80;
const AREA_LIMIT = 12;
type Position = { top: number; left: number };
type Entry = { id: string; url: string; parent: string | null; areas: Record<string, Position> };
let sequence = 0;
let activeBack: ((fallback: string, push: (url: string) => void, preferredPath?: string) => void) | null = null;
let previousAvailable: (() => boolean) | null = null;
let activeDeparture: (() => void) | null = null;
export function rememberRouteDeparture() { activeDeparture?.(); }

export function hasPreviousRoute() { return previousAvailable?.() ?? false; }

export function returnToPreviousRoute(fallback: string, push: (url: string) => void, preferredPath?: string) {
  if (activeBack) activeBack(fallback, push, preferredPath);
  else push(fallback);
}

export function createRouteScrollRestoration(main: HTMLElement) {
  const history = window.history;
  const originalPush = history.pushState;
  const originalReplace = history.replaceState;
  const entries = new Map<string, Entry>();
  const prefix = `sphere-${Date.now().toString(36)}-`;
  let live = true;
  let frame: number | null = null;
  let observer: ResizeObserver | null = null;
  let timer: number | null = null;
  let pending: Entry | null = null;
  let departure: { id: string; areas: Entry['areas'] } | null = null;
  let departureTimer: number | null = null;
  const route = () => {
    const search = new URLSearchParams(window.location.search).toString();
    return window.location.pathname + (search ? '?' + search : '');
  };
  const stamp = (state: unknown, id: string) => state === null || state === undefined || typeof state === 'object' && !Array.isArray(state)
    ? { ...state as Record<string, unknown>, [ENTRY_FIELD]: id } : state;
  const newId = () => prefix + (++sequence).toString(36);
  const put = (entry: Entry) => {
    entries.delete(entry.id); entries.set(entry.id, entry);
    while (entries.size > LIMIT) entries.delete(entries.keys().next().value!);
    return entry;
  };
  let current = put({ id: newId(), url: route(), parent: null, areas: {} });
  originalReplace.call(history, stamp(history.state, current.id), '', window.location.href);

  function areas() {
    const result = new Map<string, HTMLElement>([['main', main]]);
    for (const element of main.querySelectorAll<HTMLElement>('[data-route-scroll]')) {
      const key = element.dataset.routeScroll;
      if (key && key.length <= 64 && !result.has(key)) result.set(key, element);
      if (result.size >= AREA_LIMIT) break;
    }
    return result;
  }
  function save() {
    if (!live || pending) return;
    current.areas = Object.fromEntries([...areas()].map(([key, element]) => [key, {
      top: Math.max(0, element.scrollTop), left: Math.max(0, element.scrollLeft),
    }]));
    put(current);
  }
  function cancelRestore() {
    pending = null; observer?.disconnect(); observer = null;
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
  }
  function clearDeparture() {
    departure = null;
    if (departureTimer !== null) window.clearTimeout(departureTimer);
    departureTimer = null;
  }
  function rememberDeparture() {
    clearDeparture(); save();
    departure = { id: current.id, areas: { ...current.areas } };
    departureTimer = window.setTimeout(clearDeparture, 10000);
  }
  function saveBeforeNavigation() {
    // App Router may render a shorter destination (clamping the old main)
    // before it writes history. Use geometry captured at the accepted click.
    if (departure?.id === current.id) current.areas = { ...departure.areas };
    else save();
  }
  function linkDeparture(event: MouseEvent) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;
    if (!(anchor instanceof HTMLAnchorElement) || anchor.hasAttribute('download') || anchor.target && anchor.target !== '_self') return;
    const target = new URL(anchor.href);
    if (target.origin === window.location.origin && destination(target) !== route()) rememberDeparture();
  }
  function restore() {
    if (!live || !pending || pending !== current) return;
    let complete = true;
    for (const [key, wanted] of Object.entries(pending.areas)) {
      const element = areas().get(key);
      if (!element) { complete = false; continue; }
      element.scrollTop = wanted.top; element.scrollLeft = wanted.left;
      if (Math.abs(element.scrollTop - wanted.top) > 1 || Math.abs(element.scrollLeft - wanted.left) > 1) complete = false;
    }
    if (complete) cancelRestore();
  }
  function scheduleSave() {
    if (frame !== null || !live || pending) return;
    frame = window.requestAnimationFrame(() => { frame = null; save(); });
  }
  function interrupt(event: Event) {
    if (event instanceof KeyboardEvent && !['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) return;
    cancelRestore(); clearDeparture();
  }
  function begin(entry: Entry) {
    cancelRestore(); clearDeparture(); current = put(entry); pending = entry;
  }
  function destination(url?: string | URL | null) {
    const value = new URL(url ?? window.location.href, window.location.href);
    const search = value.searchParams.toString();
    return value.pathname + (search ? '?' + search : '');
  }
  const push: History['pushState'] = function(state, unused, url) {
    if (!live) return originalPush.call(history, state, unused, url);
    saveBeforeNavigation();
    const next: Entry = { id: newId(), url: destination(url), parent: current.id, areas: {} };
    // Preserve native in-page anchor scrolling instead of resetting its geometry.
    if (next.url === current.url) next.areas = { ...current.areas };
    originalPush.call(history, stamp(state, next.id), unused, url);
    begin(next);
  };
  const replace: History['replaceState'] = function(state, unused, url) {
    if (!live) return originalReplace.call(history, state, unused, url);
    const nextUrl = destination(url);
    if (nextUrl === current.url) return originalReplace.call(history, stamp(state, current.id), unused, url);
    saveBeforeNavigation();
    const next: Entry = { id: newId(), url: nextUrl, parent: current.parent, areas: {} };
    originalReplace.call(history, stamp(state, next.id), unused, url);
    begin(next);
  };
  function pop(event: PopStateEvent) {
    saveBeforeNavigation();
    const id = event.state?.[ENTRY_FIELD];
    const known = typeof id === 'string' ? entries.get(id) : undefined;
    const next = known?.url === route() ? known : { id: newId(), url: route(), parent: null, areas: {} };
    if (!known) originalReplace.call(history, stamp(history.state, next.id), '', window.location.href);
    begin(next);
  }
  history.pushState = push; history.replaceState = replace;
  window.addEventListener('popstate', pop);
  document.addEventListener('click', linkDeparture, true);
  main.addEventListener('scroll', scheduleSave, { capture: true, passive: true });
  main.addEventListener('wheel', interrupt, { passive: true });
  main.addEventListener('touchstart', interrupt, { passive: true });
  main.addEventListener('keydown', interrupt);

  const back = (fallback: string, navigate: (url: string) => void, preferredPath?: string) => {
    const previous = current.parent ? entries.get(current.parent) : undefined;
    if (previous && (!preferredPath || new URL(previous.url, window.location.origin).pathname === preferredPath)) { rememberDeparture(); history.back(); }
    else if (destination(fallback) !== route()) navigate(fallback);
  };
  activeBack = back;
  const available = () => Boolean(current.parent && entries.has(current.parent));
  previousAvailable = available;
  activeDeparture = rememberDeparture;
  return {
    routeRendered(key: string) {
      if (!live || key !== current.url) return;
      // A new app route starts at the top. POP restores the exact history entry,
      // not a single shared position for every visit to that URL.
      if (!Object.keys(current.areas).length) current.areas = { main: { top: 0, left: 0 } };
      pending = current; restore();
      if (!pending) return;
      // Data can arrive after the route commit. Retry boundedly as it grows;
      // the operator's own scrolling always takes precedence.
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(restore);
        observer.observe(main);
        if (main.firstElementChild) observer.observe(main.firstElementChild);
        for (const element of areas().values()) observer.observe(element);
      }
      timer = window.setTimeout(cancelRestore, 10000);
    },
    retainedEntries: () => entries.size,
    dispose() {
      save(); live = false; cancelRestore(); clearDeparture();
      if (frame !== null) window.cancelAnimationFrame(frame);
      window.removeEventListener('popstate', pop);
      document.removeEventListener('click', linkDeparture, true);
      main.removeEventListener('scroll', scheduleSave, true);
      main.removeEventListener('wheel', interrupt);
      main.removeEventListener('touchstart', interrupt);
      main.removeEventListener('keydown', interrupt);
      if (history.pushState === push) history.pushState = originalPush;
      if (history.replaceState === replace) history.replaceState = originalReplace;
      if (activeBack === back) activeBack = null;
      if (previousAvailable === available) previousAvailable = null;
      if (activeDeparture === rememberDeparture) activeDeparture = null;
      entries.clear();
    },
  };
}
