'use client';
import { useRef, type PointerEvent } from 'react';
import { GripVertical } from 'lucide-react';

/** Dedicated swipe handle avoids taking gestures from Android canvas or page scrolling. */
export function MobileMenuHandle({ onOpen }: { onOpen: () => void }) {
  const start = useRef<{ id: number; x: number; y: number } | null>(null);
  const down = (event: PointerEvent<HTMLButtonElement>) => {
    if (!event.isPrimary || event.pointerType === 'mouse') return;
    start.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  return <button type="button" aria-label="Открыть меню: потяните вправо" title="Потяните вправо или нажмите"
    className="mobile-menu-handle fixed left-0 top-1/2 z-40 flex h-16 w-5 -translate-y-1/2 touch-pan-y items-center justify-center rounded-r-xl border border-l-0 border-primary/20 bg-card/75 text-muted-foreground shadow-sm backdrop-blur-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
    onPointerDown={down} onPointerCancel={() => { start.current = null; }}
    onPointerMove={event => {
      const origin = start.current;
      if (!origin || event.pointerId !== origin.id) return;
      const dx = event.clientX - origin.x, dy = Math.abs(event.clientY - origin.y);
      if (dy > 28 && dy > Math.abs(dx)) { start.current = null; return; }
      if (dx > 56 && dx > dy * 1.8) { start.current = null; onOpen(); }
    }} onPointerUp={() => { start.current = null; }} onClick={onOpen}>
    <GripVertical className="h-4 w-4" aria-hidden />
  </button>;
}
