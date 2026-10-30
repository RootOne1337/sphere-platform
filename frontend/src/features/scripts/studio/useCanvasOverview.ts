'use client';

import { useCallback, useEffect, useRef, type RefObject } from 'react';

/** Follow container geometry only while showing the overview, never during manual navigation. */
export function useCanvasOverview(pane: RefObject<HTMLDivElement | null>, enabled: boolean, fit: () => unknown) {
  const following = useRef(true);
  const fitRef = useRef(fit); fitRef.current = fit;
  const frame = useRef<number | null>(null);
  const cancel = useCallback(() => {
    if (frame.current !== null) window.cancelAnimationFrame(frame.current);
    frame.current = null;
  }, []);
  const manual = useCallback(() => { following.current = false; cancel(); }, [cancel]);
  const follow = useCallback(() => { following.current = true; cancel(); }, [cancel]);
  const overview = useCallback(() => { follow(); void fitRef.current(); }, [follow]);

  useEffect(() => {
    const element = pane.current;
    if (!enabled || !element || typeof ResizeObserver === 'undefined') return;
    following.current = true;
    let first = true;
    let size = { width: 0, height: 0 };
    let active = true;
    const observer = new ResizeObserver(entries => {
      const entry = entries.find(item => item.target === element);
      if (!entry || !active) return;
      const next = { width: Math.round(entry.contentRect.width), height: Math.round(entry.contentRect.height) };
      if (first) { first = false; size = next; return; } // React Flow owns its initial fit.
      if (next.width === size.width && next.height === size.height) return;
      size = next;
      cancel();
      if (!following.current || next.width <= 0 || next.height <= 0) return;
      // React Flow also measures this pane. Fit after its measurement, and
      // coalesce a burst of observer notifications into one final viewport update.
      frame.current = window.requestAnimationFrame(() => {
        frame.current = window.requestAnimationFrame(() => {
          frame.current = null;
          if (active && following.current) void fitRef.current();
        });
      });
    });
    observer.observe(element);
    return () => { active = false; observer.disconnect(); cancel(); };
  }, [pane, enabled, cancel]);

  return { overview, manual, follow };
}
