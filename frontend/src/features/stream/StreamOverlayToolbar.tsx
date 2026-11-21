'use client';
import { useEffect, useState, type ReactNode, type RefObject } from 'react';
import { Ellipsis, X } from 'lucide-react';

/** One small touch target reveals tools; observing movement never consumes input. */
export function StreamOverlayToolbar({ viewport, children }: { viewport: RefObject<HTMLDivElement | null>; children: ReactNode }) {
  const [pinned, setPinned] = useState(false), [hovered, setHovered] = useState(false), [focused, setFocused] = useState(false);
  const shown = pinned || hovered || focused;
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const move = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return;
      const r = element.getBoundingClientRect();
      setHovered(event.clientY >= r.top && event.clientY < r.top + 84 && event.clientX > r.right - 240);
    };
    const leave = () => setHovered(false);
    element.addEventListener('pointermove', move, { passive: true }); element.addEventListener('pointerleave', leave);
    return () => { element.removeEventListener('pointermove', move); element.removeEventListener('pointerleave', leave); };
  }, [viewport]);
  return <div className="stream-overlay-tools pointer-events-none absolute right-[max(.375rem,env(safe-area-inset-right))] top-[max(.375rem,env(safe-area-inset-top))] z-30 flex max-w-[calc(100%-0.75rem)] items-start gap-1">
    <div aria-hidden={!shown} inert={!shown} onFocusCapture={() => setFocused(true)}
      onBlurCapture={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false); }}
      className={`flex min-w-0 flex-wrap justify-end gap-1 rounded-2xl border border-white/15 bg-zinc-950/65 p-1 text-white shadow-lg backdrop-blur-md transition-opacity duration-150 motion-reduce:transition-none ${shown ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0'}`}>
      {children}
    </div>
    <button type="button" aria-label={pinned ? 'Скрыть инструменты стрима' : 'Показать инструменты стрима'} aria-expanded={shown} aria-pressed={pinned}
      onClick={() => { setPinned(v => !v); setHovered(false); setFocused(false); }} className="pointer-events-auto flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
      <span className="flex h-8 w-8 items-center justify-center rounded-full border border-white/20 bg-zinc-950/55 shadow-sm backdrop-blur-md">{pinned ? <X className="h-4 w-4" aria-hidden /> : <Ellipsis className="h-4 w-4" aria-hidden />}</span>
    </button>
  </div>;
}
