'use client';

import { useEffect, useState, type ReactNode, type RefObject } from 'react';
import { ChevronDown, Ellipsis } from 'lucide-react';

/** Pointer observation never consumes a remote gesture; touch has an explicit toggle. */
export function StreamControlsTray({ viewport, overlay, children }: {
  viewport: RefObject<HTMLDivElement | null>; overlay: boolean; children: ReactNode;
}) {
  const [pinned, setPinned] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const shown = !overlay || pinned || hovered || focused;
  useEffect(() => {
    if (!overlay) { setPinned(false); setHovered(false); return; }
    const element = viewport.current;
    if (!element) return;
    const move = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return;
      const rect = element.getBoundingClientRect();
      setHovered(event.clientY >= rect.bottom - 72 && event.clientY <= rect.bottom);
    };
    const leave = () => setHovered(false);
    const down = (event: PointerEvent) => { if (event.pointerType !== 'mouse') leave(); };
    element.addEventListener('pointermove', move, { passive: true });
    element.addEventListener('pointerleave', leave);
    element.addEventListener('pointerdown', down, { passive: true });
    return () => {
      element.removeEventListener('pointermove', move);
      element.removeEventListener('pointerleave', leave);
      element.removeEventListener('pointerdown', down);
    };
  }, [overlay, viewport]);
  return <div className={overlay
    ? 'pointer-events-none absolute inset-x-2 bottom-[max(0.5rem,env(safe-area-inset-bottom))] z-30 flex justify-center pr-12'
    : 'contents'}>
    <div aria-hidden={overlay && !shown} inert={overlay && !shown}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false); }}
      className={overlay ? `max-w-full transition-opacity duration-150 motion-reduce:transition-none ${shown
        ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0'}` : 'contents'}>
      {children}
    </div>
    {overlay && <button type="button" aria-label={pinned ? 'Скрыть панель Android' : 'Показать панель Android'}
      aria-expanded={shown} aria-pressed={pinned} onClick={() => setPinned(value => !value)}
      className="pointer-events-auto absolute bottom-0 right-0 flex h-11 w-11 items-center justify-center rounded-xl border border-white/20 bg-zinc-950/70 text-white shadow-lg backdrop-blur hover:bg-zinc-800/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
      {pinned ? <ChevronDown className="h-5 w-5" aria-hidden /> : <Ellipsis className="h-5 w-5" aria-hidden />}
    </button>}
  </div>;
}
