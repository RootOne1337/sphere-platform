import type { ReactNode } from 'react';
import { cn } from '@/src/shared/lib/utils';

interface PageFrameProps {
  children: ReactNode;
  className?: string;
}

/** Shared responsive content width and rhythm for administrative pages. */
export function PageFrame({ children, className }: PageFrameProps) {
  return (
    <div className={cn('mx-auto flex min-h-full w-full max-w-[1720px] flex-col gap-6 px-4 py-5 sm:px-6 sm:py-6 xl:px-8', className)}>
      {children}
    </div>
  );
}

interface PageHeadingProps {
  title: string;
  description?: string;
  eyebrow?: string;
  actions?: ReactNode;
  className?: string;
}

/** Consistent page hierarchy with action placement that wraps on narrow screens. */
export function PageHeading({ title, description, eyebrow, actions, className }: PageHeadingProps) {
  return (
    <header className={cn('flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-2 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-primary">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
            {eyebrow}
          </p>
        )}
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{title}</h1>
        {description && <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
