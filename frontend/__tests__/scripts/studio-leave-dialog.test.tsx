import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StudioLeaveDialog } from '@/src/features/scripts/studio/StudioLeaveDialog';

const state = { documentChanged: true, nodePending: true, workbenchState: true };
it('explains the independent losses and exposes staying before the destructive action', async () => {
  const decide = jest.fn(); render(<StudioLeaveDialog state={state} onDecision={decide} onExport={jest.fn()} />);
  expect(screen.getByRole('dialog', { name: 'Сохранить работу перед выходом?' })).toBeInTheDocument();
  expect(screen.getByText('Несохранённый сценарий')).toBeInTheDocument();
  expect(screen.getByText('Неприменённые поля не входят в экспорт JSON.')).toBeInTheDocument();
  expect(screen.getByText(/Созданное задание продолжит работу/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Остаться в редакторе' })).toHaveFocus();
  await userEvent.keyboard('{Escape}'); expect(decide).toHaveBeenCalledWith(false);
});

it('exports before canceling exit, and only the explicit exit allows navigation', () => {
  const decide = jest.fn(), exportJson = jest.fn();
  render(<StudioLeaveDialog state={state} onDecision={decide} onExport={exportJson} />);
  fireEvent.click(screen.getByRole('button', { name: 'Скачать JSON и остаться' }));
  expect(exportJson).toHaveBeenCalledTimes(1); expect(decide).toHaveBeenLastCalledWith(false);
  expect(exportJson.mock.invocationCallOrder[0]).toBeLessThan(decide.mock.invocationCallOrder[0]);
  fireEvent.click(screen.getByRole('button', { name: 'Выйти без сохранения' })); expect(decide).toHaveBeenLastCalledWith(true);
});

it('does not render an inactive dialog or claim nonexistent node/workbench changes', () => {
  const view = render(<StudioLeaveDialog state={null} onDecision={jest.fn()} onExport={jest.fn()} />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  view.rerender(<StudioLeaveDialog state={{ documentChanged: true, nodePending: false, workbenchState: false }} onDecision={jest.fn()} onExport={jest.fn()} />);
  expect(screen.queryByText('Параметры выбранного шага')).not.toBeInTheDocument();
  expect(screen.queryByText('Лаборатория устройства')).not.toBeInTheDocument();
});
