import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAuthStore } from '@/lib/store';
import { VpnControlDialog, vpnActorScope } from '@/src/features/vpn/VpnControlDialog';
import { controlFailure, controlReceipt } from '@/src/features/vpn/controlReceipt';
import { useVpnKillSwitch, useVpnRotate } from '@/lib/hooks/useVpn';
import { useBulkAction } from '@/lib/hooks/useDevices';

jest.mock('@/lib/hooks/useVpn', () => ({ useVpnKillSwitch: jest.fn(), useVpnRotate: jest.fn() }));
jest.mock('@/lib/hooks/useDevices', () => ({ useBulkAction: jest.fn() }));
const id = 'de5a6e7f-2222-4444-aaaa-000000000001';
const second = 'de5a6e7f-2222-4444-aaaa-000000000002';
const send = jest.fn(); const close = jest.fn(); const observed = jest.fn(); const reload = jest.fn();
const ks = (outcomes: Record<string, string>) => ({ action: 'disable', total: Object.keys(outcomes).length,
  success: Object.values(outcomes).filter(v => v === 'submitted').length, execution_confirmed: false,
  results: Object.fromEntries(Object.entries(outcomes).map(([key, v]) => [key, v === 'submitted'])), outcomes });
beforeEach(() => {
  jest.clearAllMocks(); reload.mockResolvedValue(true);
  useAuthStore.setState({ user: { id: 'actor', org_id: 'org', role: 'org_admin', email: 'audit@example.org' }, sessionVersion: 5 });
  jest.mocked(useVpnKillSwitch).mockReturnValue({ mutateAsync: send } as never);
  jest.mocked(useVpnRotate).mockReturnValue({ mutateAsync: send } as never);
  jest.mocked(useBulkAction).mockReturnValue({ mutateAsync: send } as never);
});
function show(props = {}) {
  render(<VpnControlDialog kind="disable" ids={[id]} scope={vpnActorScope()} fresh reload={reload} onOutcomes={observed} onClose={close} {...props} />);
}
async function confirm() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('checkbox')); await user.click(screen.getByRole('button', { name: 'Подтвердить операцию' }));
}
it('requires confirmation and retains unsupported results without claiming completion', async () => {
  send.mockResolvedValue({ data: ks({ [id]: 'unsupported' }) }); show();
  expect(screen.getByRole('button', { name: 'Подтвердить операцию' })).toBeDisabled();
  await confirm(); await screen.findByText('unsupported');
  expect(send).toHaveBeenCalledWith({ device_ids: [id], enabled: false });
  expect(close).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Подтвердить операцию' })).not.toBeInTheDocument();
});
it('does not dispatch with an unavailable fresh snapshot', async () => {
  reload.mockResolvedValue(false); show(); await confirm();
  await screen.findByRole('alert'); expect(send).not.toHaveBeenCalled();
});
it('ignores a late preflight after the actor changes', async () => {
  let resolve!: (v: boolean) => void;
  reload.mockReturnValue(new Promise<boolean>(r => { resolve = r; })); show(); await confirm();
  act(() => useAuthStore.setState({ sessionVersion: 6 }));
  await act(async () => resolve(true)); expect(send).not.toHaveBeenCalled();
});
it('blocks dismissal and duplicate commands while pending', async () => {
  let resolve!: (v: unknown) => void;
  send.mockReturnValue(new Promise(r => { resolve = r; })); show(); await confirm();
  expect(screen.getByRole('button', { name: 'Закрыть результаты' })).toBeDisabled();
  await userEvent.setup().click(screen.getByRole('button', { name: /^Закрыть$/ }));
  expect(close).not.toHaveBeenCalled();
  await userEvent.setup().keyboard('{Escape}'); expect(close).not.toHaveBeenCalled();
  await act(async () => resolve({ data: ks({ [id]: 'submitted' }) }));
  expect(send).toHaveBeenCalledTimes(1); await screen.findByText('submitted');
});
it('marks a timeout unknown and offers no replay', async () => {
  send.mockRejectedValue({ response: { status: 504 } }); show(); await confirm();
  await screen.findByText('unknown'); expect(observed).toHaveBeenCalled();
  expect(screen.queryByText('Подготовить повтор только неотправленных')).not.toBeInTheDocument();
});
it('rejects malformed success counts as unknown', async () => {
  send.mockResolvedValue({ data: { ...ks({ [id]: 'submitted' }), success: 99 } }); show(); await confirm();
  await screen.findByText('unknown'); expect(screen.queryByText('submitted')).not.toBeInTheDocument();
});
it('retries only explicit not_sent targets with a new confirmation', async () => {
  send.mockResolvedValueOnce({ data: ks({ [id]: 'submitted', [second]: 'not_sent' }) })
    .mockResolvedValueOnce({ data: ks({ [second]: 'submitted' }) });
  show({ ids: [id, second] }); await confirm();
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Подготовить повтор только неотправленных' }));
  expect(screen.getByRole('button', { name: 'Подтвердить операцию' })).toBeDisabled();
  await confirm(); await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
  expect(send.mock.calls[1][0]).toEqual({ device_ids: [second], enabled: false });
});
it('does not present reboot acknowledgement as a completed boot', () => {
  const receipt = controlReceipt('reboot', { total: 1, succeeded: 1, failed: 0, results: [{ device_id: id, success: true, error: null }] }, [id]);
  expect(receipt[0].outcome).toBe('acknowledged'); expect(receipt[0].detail).toContain('heartbeat');
});
it.each([{}, { ...ks({ [id]: 'submitted' }), execution_confirmed: true }, ks({ [second]: 'submitted' }),
  { ...ks({ [id]: 'submitted' }), results: { [id]: false } }])('rejects incomplete, applied or foreign receipts', value => {
  expect(() => controlReceipt('disable', value, [id])).toThrow();
});
it('does not infer a safe rotation retry from a router exception', () => {
  const receipt = controlReceipt('rotate', { total: 1, success: 0, failed: 1, execution_confirmed: false,
    details: [{ device_id: id, old_ip: '10.200.0.2', new_ip: null, error: 'Unavailable', outcome: 'unknown', revoke_confirmed: true }] }, [id]);
  expect(receipt[0].retryable).toBe(false); expect(receipt[0].detail).toContain('подтверждён');
});
it.each([undefined, 500, 503, 504])('treats server/transport failure %s as unknown', status => {
  expect(controlFailure({ response: { status } }).unknown).toBe(true);
});
it.each([401, 403, 404, 422])('recognizes pre-dispatch rejection %s', status => {
  expect(controlFailure({ response: { status } }).unknown).toBe(false);
});
