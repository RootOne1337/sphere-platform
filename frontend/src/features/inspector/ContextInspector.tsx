'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import * as Dialog from '@radix-ui/react-dialog';
import { Maximize2, PanelRight, X } from 'lucide-react';
import { useUIStore } from '@/src/shared/store/useUIStore';
import { useInspectorStore } from './inspectorStore';
import { DeviceInspectorDetail } from '@/src/features/devices/DeviceInspectorDetail';
import { RouteAccessBoundary } from '@/src/features/access/Capabilities';

export function ContextInspector() {
  const { isOpen, contentType, contentId, closeInspector } = useInspectorStore();
  const { inspectorMode, setInspectorMode } = useUIStore();
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
    <Dialog.Portal><Dialog.Overlay className="sphere-dialog-overlay fixed inset-0 z-50 bg-black/30 backdrop-blur-sm" />
      <Dialog.Content aria-label="Инспектор Sphere" aria-labelledby={undefined} data-placement={inspectorMode === 'drawer' ? 'right' : 'center'} className="sphere-dialog sphere-material sphere-inspector fixed z-50 flex min-h-0 flex-col overflow-hidden border border-border shadow-2xl outline-none"
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
        <header className="flex items-start justify-between gap-4 border-b border-border p-4 sm:px-6"><div className="min-w-0"><Dialog.Title className="font-semibold">{contentType === 'device' ? 'Карточка устройства' : contentType === 'task' ? 'Задание' : contentType === 'script' ? 'Скрипт' : 'Инспектор'}</Dialog.Title><Dialog.Description title={contentId ?? undefined} className="mt-1 truncate font-mono text-xs text-muted-foreground">{contentId || 'Выберите запись'}</Dialog.Description></div><div className="flex shrink-0 items-center gap-1"><button type="button" data-ui="button" onClick={() => setInspectorMode(inspectorMode === 'modal' ? 'drawer' : 'modal')} aria-label={inspectorMode === 'modal' ? 'Открывать карточку сбоку' : 'Открывать карточку в окне'} title={inspectorMode === 'modal' ? 'Панель справа' : 'Просторное окно'} className="hidden h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex">{inspectorMode === 'modal' ? <PanelRight className="h-4 w-4" aria-hidden /> : <Maximize2 className="h-4 w-4" aria-hidden />}</button><Dialog.Close data-ui="button" aria-label="Закрыть инспектор" className="shrink-0 rounded-lg p-2 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><X className="h-4 w-4" aria-hidden /></Dialog.Close></div></header>
        <div className="sphere-inspector-body min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-6">
          {contentType === 'device' && contentId ? <RouteAccessBoundary pathname="/devices"><DeviceInspectorDetail key={contentId} deviceId={contentId} /></RouteAccessBoundary> : <p className="text-sm text-muted-foreground">Данные этой панели пока недоступны.</p>}
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
