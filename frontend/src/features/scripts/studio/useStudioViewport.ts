'use client';

import { useEffect, useState } from 'react';

/** Match the CSS workspace breakpoint, including rotation and window resizing. */
export function useStudioViewport() {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') { setWide(true); return; }
    const media = window.matchMedia('(min-width: 1280px)');
    const changed = () => setWide(media.matches);
    changed();
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);
  return wide;
}
