'use client';

import { useRef, useState } from 'react';
import { type Group, useDeleteGroup } from '@/lib/hooks/useGroups';
import { getApiErrorMessage } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { PermissionNotice } from '@/src/features/access/Capabilities';

export function GroupDeleteDialog({ group, available, canDelete, onClose, onDeleted }: {
  group: Group; available: boolean; canDelete: boolean; onClose: () => void; onDeleted: () => void;
}) {
  const deletion = useDeleteGroup();
  const lock = useRef(false);
  const [error, setError] = useState<string | null>(null);
  async function remove() {
    if (!canDelete || !available || deletion.isPending || lock.current) return;
    lock.current = true; setError(null);
    try { await deletion.mutateAsync(group.id); onDeleted(); }
    catch (failure) { setError(getApiErrorMessage(failure, failure instanceof Error ? failure.message : 'Результат удаления не подтверждён. Обновите каталог и проверьте права доступа.')); }
    finally { lock.current = false; }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !lock.current) onClose(); }}>
    <DialogContent>
      <DialogHeader><DialogTitle>Удалить группу «{group.name}»?</DialogTitle>
        <DialogDescription>Членство в этой группе будет удалено. Устройства, их приложения и членство в других группах сохраняются.</DialogDescription>
      </DialogHeader>
      <PermissionNotice permission="device:delete" action="удаление группы" />
      <div className="space-y-2 rounded-lg border border-border p-3 text-sm">
        <p>{group.total_devices} устройств · {group.online_devices} онлайн по последнему ответу каталога.</p>
        <p className="break-all font-mono text-xs text-muted-foreground">ID: {group.id}</p>
        <p className="text-muted-foreground">Если группа используется в сценариях или расписаниях, проверьте их назначения после удаления.</p>
      </div>
      {!available && <p role="alert" className="text-sm text-destructive">Каталог сейчас недоступен или группа уже удалена.</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <DialogFooter className="gap-2">
        <Button type="button" variant="outline" disabled={deletion.isPending} onClick={onClose}>Отмена</Button>
        <Button type="button" variant="destructive" disabled={!canDelete || !available || deletion.isPending} onClick={() => { void remove(); }}>{deletion.isPending ? 'Удаляем…' : 'Удалить группу'}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
