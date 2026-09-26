import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { DeviceBulkDeleteButton } from '@/src/features/devices/DeviceBulkDeleteButton';
import { MAX_BULK_DEVICE_OPERATION_COUNT } from '@/src/features/devices/constants';

jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    warning: jest.fn(),
    error: jest.fn(),
  },
}));

describe('DeviceBulkDeleteButton', () => {
  const deviceIds = ['device-1', 'device-2'];
  let onDelete: jest.Mock<Promise<{ deleted: number }>, [string[]]>;
  let onDeleted: jest.Mock<void, []>;

  beforeEach(() => {
    jest.clearAllMocks();
    onDelete = jest.fn();
    onDeleted = jest.fn();
  });

  it('requires explicit in-app confirmation, preserves selection while pending, and clears on full success', async () => {
    let resolveDelete!: (value: { deleted: number }) => void;
    onDelete.mockReturnValue(new Promise((resolve) => { resolveDelete = resolve; }));

    render(
      <DeviceBulkDeleteButton
        deviceIds={deviceIds}
        isPending={false}
        onDelete={onDelete}
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Обновления и приложения на Android не затрагиваются');
    expect(screen.getByRole('dialog')).toHaveTextContent('история задач и событий сохранится');
    expect(screen.getByRole('dialog')).toHaveTextContent('refresh-доступ отзывается');
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Убрать из каталога (2)' }));
    expect(onDelete).toHaveBeenCalledWith(deviceIds);
    expect(onDeleted).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Удаление…' })).toBeDisabled();

    resolveDelete({ deleted: 2 });

    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith('Убрано из активного каталога: 2');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('preserves selection and shows the server reason when deletion fails', async () => {
    onDelete.mockRejectedValue({ response: { data: { detail: 'Forbidden' } } });

    render(
      <DeviceBulkDeleteButton
        deviceIds={deviceIds}
        isPending={false}
        onDelete={onDelete}
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Убрать из каталога (2)' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      'Не удалось удалить устройства',
      { description: 'Forbidden' },
    ));
    expect(screen.getByRole('alert')).toHaveTextContent('Forbidden');
    expect(screen.getByRole('button', { name: 'Убрать из каталога (2)' })).toBeEnabled();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it('does not issue a request when the destructive confirmation is cancelled', () => {
    render(
      <DeviceBulkDeleteButton
        deviceIds={deviceIds}
        isPending={false}
        onDelete={onDelete}
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('blocks requests larger than the backend batch limit before opening confirmation', () => {
    const tooManyIds = Array.from({ length: MAX_BULK_DEVICE_OPERATION_COUNT + 1 }, (_, index) => `device-${index}`);
    render(
      <DeviceBulkDeleteButton
        deviceIds={tooManyIds}
        isPending={false}
        onDelete={onDelete}
        onDeleted={onDeleted}
      />,
    );

    expect(screen.getByRole('button', { name: `Удалить выбранные устройства (${tooManyIds.length})` })).toBeDisabled();
    expect(screen.getByRole('button', { name: `Удалить выбранные устройства (${tooManyIds.length})` })).toHaveAttribute(
      'title',
      `За один раз можно удалить не более ${MAX_BULK_DEVICE_OPERATION_COUNT} устройств`,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('keeps unresolved devices selected after a partial server result', async () => {
    onDelete.mockResolvedValue({ deleted: 1 });
    render(
      <DeviceBulkDeleteButton
        deviceIds={deviceIds}
        isPending={false}
        onDelete={onDelete}
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Убрать из каталога (2)' }));

    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(
      'Каталог обновлён частично',
      expect.objectContaining({ description: expect.stringContaining('Убрано 1 из 2') }),
    ));
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does not issue duplicate requests while the first deletion is in flight', async () => {
    let resolveDelete!: (value: { deleted: number }) => void;
    onDelete.mockReturnValue(new Promise((resolve) => { resolveDelete = resolve; }));
    render(
      <DeviceBulkDeleteButton
        deviceIds={deviceIds}
        isPending={false}
        onDelete={onDelete}
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' }));
    const confirmButton = screen.getByRole('button', { name: 'Убрать из каталога (2)' });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    expect(onDelete).toHaveBeenCalledTimes(1);
    resolveDelete({ deleted: 2 });
    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
  });
});
