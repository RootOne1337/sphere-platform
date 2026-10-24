import { act, render, screen } from '@testing-library/react';
import { api } from '@/lib/api';
import { DeviceViewerBadge } from '@/src/features/devices/DeviceViewerBadge';
import { DeviceViewerPresence } from '@/src/features/devices/DeviceViewerPresence';
jest.mock('@/lib/store', () => ({ useAuthStore: (s: (value: unknown) => unknown) => s({sessionVersion:1}) }));
jest.mock('@/lib/api', () => ({ api: {post:jest.fn()} }));
beforeEach(() => { jest.resetAllMocks(); jest.useFakeTimers(); jest.mocked(api.post).mockResolvedValue({data:{available:true,counts:{card:2,stream:10}}}); });
afterEach(() => jest.useRealTimers());
test('compact counts distinguish tabs viewing a card from stream connections without another column', () => {
  render(<DeviceViewerBadge card={2} stream={10} />);
  expect(screen.getByLabelText('Открытые карточки: 2. Видеопоток: 10.')).toBeInTheDocument();
  expect(screen.getByTitle(/несколькими вкладками/)).toBeInTheDocument();
});
test('unknown counts do not appear as zero viewers and empty list badges stay unobtrusive', () => {
  const v=render(<DeviceViewerBadge />); expect(v.container).toBeEmptyDOMElement();
  v.rerender(<DeviceViewerBadge showEmpty />); expect(screen.getByText('Зрители: —')).toBeInTheDocument();
});
test('each mounted card has a separate nonce even under one account and close removes only itself', async () => {
  const a=render(<DeviceViewerPresence deviceId="same" />);
  const b=render(<DeviceViewerPresence deviceId="same" />);
  await act(async () => {});
  const first=jest.mocked(api.post).mock.calls[0][1] as {session:string};
  const second=jest.mocked(api.post).mock.calls[1][1] as {session:string};
  expect(first.session).toMatch(/^[0-9a-f]{32}$/); expect(second.session).not.toBe(first.session);
  a.unmount(); await act(async () => {});
  expect(api.post).toHaveBeenCalledWith('/devices/same/viewers',{session:first.session,active:false},expect.any(Object));
  b.unmount();
});
test('a late old-device response cannot change the new device badge', async () => {
  let finish!:(v:unknown)=>void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => {finish=resolve;}));
  const v=render(<DeviceViewerPresence deviceId="old" />);
  v.rerender(<DeviceViewerPresence deviceId="new" />);
  await act(async()=>finish({data:{available:true,counts:{card:99,stream:99}}}));
  expect(screen.queryByText('99')).not.toBeInTheDocument();
});
