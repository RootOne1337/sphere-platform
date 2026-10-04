import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SingleDeviceStream } from '@/src/features/stream/SingleDeviceStream';
import { api } from '@/lib/api';

let mockPermission = true;
let mockToken = 'fixture-token';
let mockStreamProps: Record<string, any>;
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ can: () => mockPermission }), PermissionNotice: () => null,
}));
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: mockToken }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('@/components/sphere/DeviceStream', () => ({ DeviceStream: (props: Record<string, any>) => {
  mockStreamProps = props;
  return <button onClick={() => props.onFrameDimensions({ width: 960, height: 540 })}>Fixture frame</button>;
} }));
const snapshot = (deviceId = 'remote') => ({ device_id: deviceId, snapshot_id: 'a'.repeat(32), source: 'android_uiautomator_root',
  requested_at: '2026-10-03T21:00:00Z', completed_at: '2026-10-03T21:00:02Z', width: 960, height: 540, rotation: 1, temporary_file_cleanup_confirmed: true,
  nodes: [{ id: 0, parent_id: null, depth: 0, xpath: '/hierarchy/node[1]',
    bounds: { left: 100, top: 100, right: 200, bottom: 150 }, attributes: { text: '<script>safe plain text</script>', 'resource-id': 'pkg:id/ok', clickable: 'true', enabled: 'true', custom: 'retained' } }] });
beforeEach(() => { jest.clearAllMocks(); mockPermission = true; mockToken = 'fixture-token'; });
function open() {
  const view = render(<SingleDeviceStream deviceId="remote" />);
  fireEvent.click(screen.getByText('Fixture frame'));
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  return view;
}
async function loaded() {
  jest.mocked(api.post).mockResolvedValue({ data: snapshot() });
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Обновить дерево' }));
  await screen.findByText(/1 элементов/);
  return view;
}
it('reads only on explicit request, reveals all attributes and scales highlight after a pick', async () => {
  await loaded();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/devices/remote/ui-hierarchy', undefined, expect.objectContaining({ timeout: 50_000 }));
  act(() => mockStreamProps.inspection.onPick(120, 120, { width: 960, height: 540 }));
  expect(screen.getByText('/hierarchy/node[1]')).toBeInTheDocument();
  expect(screen.getByText('<script>safe plain text</script>')).toBeInTheDocument();
  expect(screen.getByText('custom')).toBeInTheDocument();
  expect(mockStreamProps.inspection.bounds).toEqual(snapshot().nodes[0].bounds);
  fireEvent.click(screen.getByRole('button', { name: 'Управление' }));
  expect(mockStreamProps.inspection).toBeUndefined();
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('geometry mismatch prevents picking/highlighting and retains the explicit warning', async () => {
  await loaded();
  act(() => mockStreamProps.onFrameDimensions({ width: 540, height: 960 }));
  act(() => mockStreamProps.inspection.onPick(120, 120, { width: 540, height: 960 }));
  expect(screen.getByText(/Геометрия дерева не совпадает/)).toBeInTheDocument();
  expect(mockStreamProps.inspection.bounds).toBeNull();
  expect(screen.queryByText('/hierarchy/node[1]')).not.toBeInTheDocument();
});
it.each(['device', 'token', 'permission', 'socket'])('retires an in-flight tree on %s change', async reason => {
  let resolve: (value: unknown) => void = () => {};
  jest.mocked(api.post).mockImplementation(() => new Promise(r => { resolve = r; }) as never);
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Обновить дерево' }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal;
  if (reason === 'device') view.rerender(<SingleDeviceStream deviceId="other" />);
  else if (reason === 'socket') act(() => mockStreamProps.onInspectionInvalidated());
  else { if (reason === 'token') mockToken = 'new-token'; else mockPermission = false; view.rerender(<SingleDeviceStream deviceId="remote" />); }
  await act(async () => { resolve({ data: snapshot() }); });
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText(/1 элементов/)).not.toBeInTheDocument();
});
it('failure and wrong-device receipt stay errors, with an explicit operator retry', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: snapshot('other') });
  open(); fireEvent.click(screen.getByRole('button', { name: 'Обновить дерево' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(/Дерево не принадлежит/);
  expect(api.post).toHaveBeenCalledTimes(1);
  jest.mocked(api.post).mockResolvedValue({ data: snapshot() });
  fireEvent.click(screen.getByRole('button', { name: 'Обновить дерево' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('received permission withdrawal disables inspection even after restoring the same device', async () => {
  const view = await loaded(); mockPermission = false;
  view.rerender(<SingleDeviceStream deviceId="remote" />);
  expect(screen.getByRole('button', { name: 'XPath-инспектор' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Обновить дерево' })).toBeDisabled();
  expect(screen.queryByText(/1 элементов/)).not.toBeInTheDocument();
});

it('expires the tree after 30 seconds without polling Android or retaining a clickable selection', async () => {
  jest.useFakeTimers();
  try {
    await loaded();
    act(() => mockStreamProps.inspection.onPick(120, 120, { width: 960, height: 540 }));
    expect(mockStreamProps.inspection.bounds).not.toBeNull();
    act(() => jest.advanceTimersByTime(31_000));
    expect(screen.getByText('Снимок устарел. Обновите дерево.')).toBeInTheDocument();
    expect(mockStreamProps.inspection.bounds).toBeNull();
    expect(screen.queryByText('/hierarchy/node[1]')).not.toBeInTheDocument();
    expect(api.post).toHaveBeenCalledTimes(1);
  } finally { jest.useRealTimers(); }
});

it('shows a valid tree with a distinct warning when Android cleanup is unconfirmed', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { ...snapshot(), temporary_file_cleanup_confirmed: false } });
  open(); fireEvent.click(screen.getByRole('button', { name: 'Обновить дерево' }));
  await screen.findByText(/1 элементов/);
  expect(screen.getByText(/Удаление временного файла дерева не подтверждено/)).toBeInTheDocument();
});
