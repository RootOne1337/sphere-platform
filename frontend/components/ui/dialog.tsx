'use client';

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
function DialogPortal({ container, ...props }: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Portal>) {
  const [fullscreen, setFullscreen] = React.useState<HTMLElement | undefined>();
  React.useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement instanceof HTMLElement ? document.fullscreenElement : undefined);
    sync(); document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);
  return <DialogPrimitive.Portal container={container ?? fullscreen} {...props} />;
}
const DialogClose = DialogPrimitive.Close;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'sphere-dialog-overlay fixed inset-0 z-50 bg-slate-950/30 backdrop-blur-sm',
      className,
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { placement?: 'center' | 'right'; layout?: 'default' | 'workspace' }
>(({ className, children, placement = 'center', layout = 'default', style, ...props }, ref) => {
  const [content, setContent] = React.useState<HTMLElement | null>(null);
  const contentRef = React.useCallback((node: HTMLDivElement | null) => {
    setContent(node);
    if (typeof ref === 'function') ref(node);
    else if (ref) ref.current = node;
  }, [ref]);
  const viewportStyle = useDialogViewport(layout === 'workspace' && content !== null);
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        ref={contentRef}
        data-placement={placement}
        data-layout={layout}
        style={{ ...viewportStyle, ...style }}
        className={cn(
          'sphere-dialog sphere-material fixed z-50 gap-4 overflow-y-auto overscroll-contain border bg-background shadow-lg',
          placement === 'right'
            ? 'inset-y-0 right-0 flex h-dvh max-h-none w-[min(440px,100vw)] flex-col rounded-none border-l p-0'
            : 'left-[50%] top-[50%] grid max-h-[calc(100dvh_-_2rem)] w-[calc(100%_-_2rem)] max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-xl p-6',
          className,
        )}
        {...props}
      >
        {children}
        <DialogClose data-ui="button" className="absolute right-2 top-2 flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground ring-offset-background transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none">
          <X className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">Закрыть</span>
        </DialogClose>
      </DialogPrimitive.Content>
    </DialogPortal>
  );
});
DialogContent.displayName = DialogPrimitive.Content.displayName;

// Mobile browsers may pan/shrink only the visual viewport when the keyboard opens.
// Scope this to workspace dialogs; a viewport update never remounts the form.
function useDialogViewport(enabled: boolean) {
  const [style, setStyle] = React.useState<React.CSSProperties>();
  React.useEffect(() => {
    const viewport = window.visualViewport;
    if (!enabled || !viewport) return;
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!Number.isFinite(viewport.height) || viewport.height <= 0 || !Number.isFinite(viewport.offsetTop)) return;
        setStyle({ '--dialog-viewport-height': `${viewport.height}px`, '--dialog-viewport-top': `${viewport.offsetTop}px` } as React.CSSProperties);
      });
    };
    measure();
    viewport.addEventListener('resize', measure);
    viewport.addEventListener('scroll', measure);
    return () => {
      cancelAnimationFrame(frame);
      viewport.removeEventListener('resize', measure);
      viewport.removeEventListener('scroll', measure);
    };
  }, [enabled]);
  return enabled ? style : undefined;
}

const DialogBody = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} data-dialog-body className={cn('sphere-dialog-body', className)} {...props} />,
);
DialogBody.displayName = 'DialogBody';

const DialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div data-dialog-header className={cn('flex flex-col space-y-1.5 pr-6 text-left', className)} {...props} />
);
DialogHeader.displayName = 'DialogHeader';

const DialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    data-dialog-footer
    className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
    {...props}
  />
);
DialogFooter.displayName = 'DialogFooter';

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('text-lg font-semibold leading-none tracking-tight', className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('text-sm text-muted-foreground', className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogClose,
  DialogTrigger,
  DialogContent,
  DialogBody,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
};
