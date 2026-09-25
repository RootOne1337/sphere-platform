import { fireEvent, render, screen } from '@testing-library/react';
import { DeviceDeleteConfirmationDialog } from '@/src/features/devices/DeviceDeleteConfirmationDialog';

describe('DeviceDeleteConfirmationDialog', () => {
  it('shows scope and invokes the confirmed operation', () => {
    const onConfirm = jest.fn();
    const onOpenChange = jest.fn();

    render(
      <DeviceDeleteConfirmationDialog
        open
        title="Удалить PH006 из каталога?"
        description="APK останется установленным."
        confirmLabel="Удалить запись"
        pendingLabel="Удаление…"
        isPending={false}
        errorMessage={null}
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByRole('dialog')).toHaveTextContent('APK останется установленным');
    fireEvent.click(screen.getByRole('button', { name: 'Удалить запись' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('keeps the dialog open and blocks cancellation while an operation is pending', () => {
    const onConfirm = jest.fn();
    const onOpenChange = jest.fn();

    render(
      <DeviceDeleteConfirmationDialog
        open
        title="Удалить устройства?"
        description="Удаляются записи из каталога."
        confirmLabel="Удалить записи"
        pendingLabel="Удаление…"
        isPending
        errorMessage={null}
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByRole('button', { name: 'Отмена' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Удаление…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('renders backend failure details as an accessible alert', () => {
    render(
      <DeviceDeleteConfirmationDialog
        open
        title="Удалить устройства?"
        description="Удаляются записи из каталога."
        confirmLabel="Удалить записи"
        pendingLabel="Удаление…"
        isPending={false}
        errorMessage="Недостаточно прав."
        onOpenChange={jest.fn()}
        onConfirm={jest.fn()}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Недостаточно прав.');
  });
});
