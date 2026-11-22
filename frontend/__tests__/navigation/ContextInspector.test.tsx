import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ContextInspector } from '@/src/features/inspector/ContextInspector';
import { useUIStore } from '@/src/shared/store/useUIStore';
import { useInspectorStore } from '@/src/features/inspector/inspectorStore';

jest.mock('@/src/features/devices/DeviceInspectorDetail', () => ({ DeviceInspectorDetail: () => <input aria-label="Черновик детали" defaultValue="" /> }));
jest.mock('@/src/features/access/Capabilities', () => ({ RouteAccessBoundary: ({ children }: { children: React.ReactNode }) => children }));
let mockPath = '/devices';
jest.mock('next/navigation', () => ({ usePathname: () => mockPath }));

describe('ContextInspector', () => {
  beforeEach(() => { mockPath = '/devices'; useUIStore.setState({ inspectorMode: 'modal' }); useInspectorStore.getState().closeInspector(); });

  it('is hidden from keyboard and assistive navigation until opened, then closes accessibly', () => {
    render(<ContextInspector />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    act(() => useInspectorStore.getState().openInspector('vpn', 'global'));
    expect(screen.getByRole('dialog', { name: 'Инспектор Sphere' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть инспектор' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('supports Escape and restores focus to the device button', async () => {
    render(<><button onClick={() => useInspectorStore.getState().openInspector('device', 'id-1')}>Открыть</button><ContextInspector /></>);
    const opener = screen.getByRole('button', { name: 'Открыть' });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it('closes the inspector when the operator navigates to another page', () => {
    const { rerender } = render(<ContextInspector />);
    act(() => useInspectorStore.getState().openInspector('device', 'id-1'));
    mockPath = '/devices/id-1';
    rerender(<ContextInspector />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('restores focus after a live table refresh replaces the original device button', async () => {
    const ui = (version: number) => <><button key={version} data-inspector-device="id-1" onClick={() => useInspectorStore.getState().openInspector('device', 'id-1')}>Открыть устройство</button><ContextInspector /></>;
    const { rerender } = render(ui(1));
    const first = screen.getByRole('button', { name: 'Открыть устройство' });
    first.focus(); fireEvent.click(first);
    rerender(ui(2));
    expect(first.isConnected).toBe(false);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Открыть устройство' })).toHaveFocus());
  });
});

it('defaults to a modal and changes presentation without discarding the open detail state', () => {
  render(<ContextInspector />);
  act(() => useInspectorStore.getState().openInspector('device', 'id-1'));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toHaveAttribute('data-placement', 'center');
  fireEvent.change(screen.getByLabelText('Черновик детали'), { target: { value: 'unsaved local state' } });
  fireEvent.click(screen.getByRole('button', { name: 'Открывать карточку сбоку' }));
  expect(dialog).toHaveAttribute('data-placement', 'right');
  expect(screen.getByLabelText('Черновик детали')).toHaveValue('unsaved local state');
  fireEvent.click(screen.getByRole('button', { name: 'Открывать карточку в окне' }));
  expect(dialog).toHaveAttribute('data-placement', 'center');
  expect(screen.getByLabelText('Черновик детали')).toHaveValue('unsaved local state');
});
