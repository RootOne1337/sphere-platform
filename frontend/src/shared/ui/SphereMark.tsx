import type { SVGProps } from 'react';

/** A single-color mark remains legible in every palette and at navigation size. */
export function SphereMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" {...props}>
      <circle cx="16" cy="16" r="11.5" stroke="currentColor" strokeWidth="1.8" />
      <ellipse cx="16" cy="16" rx="5.5" ry="11.5" stroke="currentColor" strokeWidth="1.6" transform="rotate(35 16 16)" />
      <path d="M5 13.5c6.5 5 15.5 5 22 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="25.5" cy="9" r="3" fill="currentColor" stroke="var(--mark-background, hsl(var(--card)))" strokeWidth="1.5" />
    </svg>
  );
}
