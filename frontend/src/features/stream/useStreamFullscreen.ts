'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/** Fullscreen changes presentation only; the stream and its input peer stay mounted. */
export function useStreamFullscreen() {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);
  const [available, setAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const alive = useRef(false);
  useEffect(() => {
    alive.current = true;
    const element = ref.current;
    const sync = () => setActive(document.fullscreenElement === element && !!element);
    setAvailable(!!document.fullscreenEnabled && typeof element?.requestFullscreen === 'function');
    document.addEventListener('fullscreenchange', sync);
    sync();
    return () => {
      alive.current = false;
      document.removeEventListener('fullscreenchange', sync);
      if (element && document.fullscreenElement === element) void document.exitFullscreen().catch(() => {});
    };
  }, []);
  const toggle = useCallback(async () => {
    const element = ref.current;
    if (!element || !available || pending.current) return;
    pending.current = true;
    setError(null);
    try {
      if (document.fullscreenElement === element) await document.exitFullscreen();
      else if (document.fullscreenElement) throw Error('another_fullscreen_owner');
      else await element.requestFullscreen({ navigationUI: 'hide' });
      if (!alive.current && document.fullscreenElement === element) await document.exitFullscreen();
    } catch {
      if (alive.current) setError('Браузер не разрешил полноэкранный режим. Видеопоток продолжает работать.');
    } finally { pending.current = false; }
  }, [available]);
  return { ref, active, available, error, toggle };
}
