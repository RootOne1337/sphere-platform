import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ContextInspector } from '@/src/features/inspector/ContextInspector';
import { useInspectorStore } from '@/src/features/inspector/inspectorStore';

jest.mock('@/src/features/devices/DeviceInspectorDetail', () => ({ DeviceInspectorDetail: () => null }));
let mockPath = '/devices';
jest.mock('next/navigation', () => ({ usePathname: () => mockPath }));

describe('ContextInspector', () => {
  beforeEach(() => { mockPath = '/devices'; useInspectorStore.getState().closeInspector(); });

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
});
