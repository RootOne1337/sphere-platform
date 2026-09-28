import { act, fireEvent, render, screen } from '@testing-library/react';
import { ContextInspector } from '@/src/features/inspector/ContextInspector';
import { useInspectorStore } from '@/src/features/inspector/inspectorStore';

jest.mock('@/src/features/devices/DeviceInspectorDetail', () => ({ DeviceInspectorDetail: () => null }));

describe('ContextInspector', () => {
  beforeEach(() => useInspectorStore.getState().closeInspector());

  it('is hidden from keyboard and assistive navigation until opened, then closes accessibly', () => {
    const { container } = render(<ContextInspector />);
    expect(container.querySelector('aside')).toHaveAttribute('aria-hidden', 'true');

    act(() => useInspectorStore.getState().openInspector('vpn', 'global'));
    expect(screen.getByRole('complementary', { name: 'Инспектор Sphere' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть инспектор' }));
    expect(container.querySelector('aside')).toHaveAttribute('aria-hidden', 'true');
  });
});
