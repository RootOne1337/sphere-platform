'use client';

import { useRef, useState } from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/src/shared/ui/button';
import { getApiErrorMessage } from '@/lib/apiError';
import { DeviceDeleteConfirmationDialog } from './DeviceDeleteConfirmationDialog';
import { MAX_BULK_DEVICE_OPERATION_COUNT } from './constants';

interface DeviceBulkDeleteButtonProps {
  deviceIds: string[];
  isPending: boolean;
  onDelete: (deviceIds: string[]) => Promise<{ deleted: number }>;
  onDeleted: () => void;
}

export function DeviceBulkDeleteButton({
  deviceIds,
  isPending,
  onDelete,
  onDeleted,
}: DeviceBulkDeleteButtonProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const submissionLock = useRef(false);
  const busy = isPending || isSubmitting;
  const exceedsLimit = deviceIds.length > MAX_BULK_DEVICE_OPERATION_COUNT;

  const openConfirmation = () => {
    if (busy || deviceIds.length === 0 || exceedsLimit) return;
    setErrorMessage(null);
    setConfirmationOpen(true);
  };

  const handleDelete = async () => {
    const ids = [...deviceIds];
    if (busy || submissionLock.current || ids.length === 0 || ids.length > MAX_BULK_DEVICE_OPERATION_COUNT) return;

    submissionLock.current = true;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const result = await onDelete(ids);
      if (result.deleted === ids.length) {
        onDeleted();
        setConfirmationOpen(false);
        toast.success(`Убрано из активного каталога: ${result.deleted}`);
      } else {
        setConfirmationOpen(false);
        toast.warning('Каталог обновлён частично', {
          description: `Убрано ${result.deleted} из ${ids.length}. Оставшиеся записи сохранятся выделенными, если они ещё существуют.`,
        });
      }
    } catch (error) {
      const message = getApiErrorMessage(
        error,
        'Проверьте права доступа и соединение с сервером. Выделение сохранено.',
      );
      setErrorMessage(message);
      toast.error('Не удалось удалить устройства', {
        description: message,
      });
    } finally {
      submissionLock.current = false;
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <Button
        variant="destructive"
        size="sm"
        onClick={openConfirmation}
        disabled={busy || deviceIds.length === 0 || exceedsLimit}
        aria-busy={busy}
        aria-label={busy ? 'Удаление устройств' : `Удалить выбранные устройства (${deviceIds.length})`}
        title={exceedsLimit ? `За один раз можно удалить не более ${MAX_BULK_DEVICE_OPERATION_COUNT} устройств` : 'Удалить выбранные записи из каталога'}
        className="h-9"
      >
        {busy ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        ) : (
          <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
        )}
        {busy ? 'Удаление…' : 'Удалить'}
      </Button>
      <DeviceDeleteConfirmationDialog
        open={confirmationOpen}
        title="Удалить устройства из каталога?"
        description="Устройства будут убраны из активного каталога, а история задач и событий сохранится. Обновления и приложения на Android не затрагиваются; refresh-доступ отзывается."
        confirmLabel={`Убрать из каталога (${deviceIds.length})`}
        pendingLabel="Удаление…"
        isPending={busy}
        errorMessage={errorMessage ? `${errorMessage} Выделение сохранено.` : null}
        onOpenChange={setConfirmationOpen}
        onConfirm={() => { void handleDelete(); }}
      />
    </>
  );
}
