'use client';

import * as Dialog from '@radix-ui/react-dialog';
import { Download, FileWarning, Monitor } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';

export interface StudioLeaveState { documentChanged: boolean; nodePending: boolean; workbenchState: boolean }
export function StudioLeaveDialog({ state, onDecision, onExport }: {
  state: StudioLeaveState | null; onDecision: (allow: boolean) => void; onExport: () => void;
}) {
  return <Dialog.Root open={Boolean(state)} onOpenChange={open => { if (!open) onDecision(false); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-[160] bg-slate-950/50 backdrop-blur-sm" />
      <Dialog.Content className="fixed left-1/2 top-1/2 z-[170] max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border bg-card p-5 text-card-foreground shadow-2xl sm:p-6">
        <div className="mb-4 flex items-center gap-3"><span className="rounded-xl bg-amber-500/10 p-2.5 text-amber-600 dark:text-amber-400"><FileWarning className="size-5" aria-hidden="true" /></span>
          <div><p className="mb-1 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">Script Studio</p><Dialog.Title className="text-lg font-semibold">Сохранить работу перед выходом?</Dialog.Title></div></div>
        <Dialog.Description className="text-sm leading-6 text-muted-foreground">Переход закроет текущий редактор. Проверьте изменения, прежде чем продолжить.</Dialog.Description>
        <ul className="my-4 space-y-3 rounded-xl border bg-muted/30 p-4 text-sm">
          {state?.documentChanged && <li><strong>Несохранённый сценарий</strong><p className="mt-1 text-xs leading-5 text-muted-foreground">Название и исходник ещё не сохранены в версии на сервере.</p></li>}
          {state?.nodePending && <li><strong>Параметры выбранного шага</strong><p className="mt-1 text-xs leading-5 text-muted-foreground">Неприменённые поля не входят в экспорт JSON.</p></li>}
          {state?.workbenchState && <li><strong className="flex items-center gap-2"><Monitor className="size-4" aria-hidden="true" />Лаборатория устройства</strong><p className="mt-1 text-xs leading-5 text-muted-foreground">Невставленная запись будет потеряна. Созданное задание продолжит работу; его можно проверить в журнале.</p></li>}
        </ul>
        <p className="mb-4 text-xs leading-5 text-muted-foreground">JSON содержит текущий исходник графа. Запись устройства и неприменённые поля сохраняются только после вставки или применения.</p>
        <div className="flex flex-wrap justify-end gap-2"><Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={() => onDecision(false)}>Остаться в редакторе</Button>
          <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={() => { onExport(); onDecision(false); }}><Download className="mr-2 size-4 shrink-0" />Скачать JSON и остаться</Button>
          <Button variant="destructive" className="h-auto min-h-9 whitespace-normal" onClick={() => onDecision(true)}>Выйти без сохранения</Button></div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
