'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useInspectorStore } from './inspectorStore';
import { DeviceInspectorDetail } from '@/src/features/devices/DeviceInspectorDetail';
import { RouteAccessBoundary } from '@/src/features/access/Capabilities';

export function ContextInspector() {
  const { isOpen, contentType, contentId, closeInspector } = useInspectorStore();
  const pathname = usePathname();
  const previousPath = useRef(pathname);
  const opener = useRef<HTMLElement | null>(null);
  const openerPath = useRef(pathname);
  const openerDevice = useRef<string | null>(null);
  useEffect(() => {
    if (previousPath.current !== pathname) closeInspector();
    previousPath.current = pathname;
  }, [pathname, closeInspector]);

  return <Dialog.Root open={isOpen} onOpenChange={(open) => { if (!open) closeInspector(); }}>
    <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none" />
      <Dialog.Content aria-label="Инспектор Sphere" aria-labelledby={undefined} className="fixed inset-y-0 right-0 z-50 flex h-dvh w-full max-w-[640px] flex-col border-l border-border bg-card shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:slide-in-from-right data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right duration-200 motion-reduce:animate-none"
        onOpenAutoFocus={() => {
          opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          openerPath.current = pathname;
          openerDevice.current = opener.current?.dataset.inspectorDevice || null;
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          // Live table refreshes/virtualization may replace the original button
          // while the dialog is open. Resolve its current counterpart by ID.
          const samePage = openerPath.current === pathname;
          const replacement = samePage && openerDevice.current ? Array.from(document.querySelectorAll<HTMLElement>('[data-inspector-device]')).find((element) => element.dataset.inspectorDevice === openerDevice.current) : undefined;
          const target = samePage && opener.current?.isConnected ? opener.current : replacement || document.getElementById('main-content');
          target?.focus();
        }}>
        <header className="flex items-start justify-between gap-4 border-b border-border p-4 sm:px-6"><div className="min-w-0"><Dialog.Title className="font-semibold">{contentType === 'device' ? 'Устройство' : contentType === 'task' ? 'Задание' : contentType === 'script' ? 'Скрипт' : 'Инспектор'}</Dialog.Title><Dialog.Description className="mt-1 break-all font-mono text-xs text-muted-foreground">{contentId || 'Выберите запись'}</Dialog.Description></div><Dialog.Close aria-label="Закрыть инспектор" className="shrink-0 rounded-lg p-2 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><X className="h-4 w-4" aria-hidden /></Dialog.Close></header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-6">
          {contentType === 'device' && contentId ? <RouteAccessBoundary pathname="/devices"><DeviceInspectorDetail key={contentId} deviceId={contentId} /></RouteAccessBoundary> : <p className="text-sm text-muted-foreground">Данные этой панели пока недоступны.</p>}
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
