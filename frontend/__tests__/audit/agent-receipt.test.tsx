import { render, screen, within } from '@testing-library/react';
import { AuditDrawer } from '@/src/features/audit/AuditDrawer';
import { normalizeAuditEvent } from '@/src/features/audit/types';

const task = '11111111-1111-4111-8111-111111111111';
const device = '22222222-2222-4222-8222-222222222222';
const operator = '33333333-3333-4333-8333-333333333333';
const record = {
  id: '44444444-4444-4444-8444-444444444444',
  created_at: '2026-11-14T00:40:00Z',
  resource_type: 'task',
  resource_id: task,
  action: 'task.agent_result',
  meta: {
    status: 'success',
    agent_outcome: 'completed',
    device_id: device,
    receipt_id: task,
    requested_by: operator,
    request_id: 'audit-receipt-test',
    ignored_secret: 'private-agent-output',
  },
};

describe('Audit Android receipt', () => {
  it('links the authenticated agent report to its task, device and initiating request', () => {
    render(<AuditDrawer event={normalizeAuditEvent(record)} onClose={() => {}} />);
    const dialog = screen.getByRole('dialog', { name: 'task.agent_result' });
    expect(within(dialog).getByText('Результат Android-агента')).toBeInTheDocument();
    expect(within(dialog).getByText('Выполнено')).toBeInTheDocument();
    expect(within(dialog).getByText('Android-агент')).toBeInTheDocument();
    expect(within(dialog).getByText(operator)).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: task })).toHaveAttribute('href', '/tasks/' + task);
    expect(within(dialog).getByRole('link', { name: device })).toHaveAttribute('href', '/devices/' + device);
    expect(within(dialog).getByRole('link', { name: 'Открыть события этого запроса' }))
      .toHaveAttribute('href', '/audit?request_id=audit-receipt-test');
    expect(within(dialog).queryByText('private-agent-output')).not.toBeInTheDocument();
  });

  it('does not present an HTTP response or mismatched ID as an Android receipt', () => {
    const http = normalizeAuditEvent({ ...record, meta: { ...record.meta, http_status: 201 } });
    const unrelated = normalizeAuditEvent({ ...record, meta: { ...record.meta, receipt_id: device } });
    expect(http.outcomeSource).toBe('http');
    expect(http.taskReceipt).toBeNull();
    expect(unrelated.outcomeSource).toBeNull();
    expect(unrelated.taskReceipt).toBeNull();
  });

  it('shows an unknown command outcome even when the task itself failed', () => {
    const unknown = normalizeAuditEvent({
      ...record, meta: { ...record.meta, status: 'unknown', agent_outcome: 'unknown' },
    });
    render(<AuditDrawer event={unknown} onClose={() => {}} />);
    expect(screen.getByText('Исход неизвестен')).toBeInTheDocument();
    expect(screen.queryByText('Ошибка выполнения')).not.toBeInTheDocument();
  });
});
