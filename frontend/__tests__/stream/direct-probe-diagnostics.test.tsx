import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { DirectProbeDiagnostics } from '@/src/features/stream/DirectProbeDiagnostics';
import type { DirectProbeResult } from '@/src/features/stream/directProbe';

let mockReport: (value: DirectProbeResult) => void;
const mockStop = jest.fn();
const mockStart = jest.fn((_url: string, _token: string, report: typeof mockReport) => { mockReport = report; return mockStop; });
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ accessToken: 'fixture' }) }));
jest.mock('@/src/features/stream/directProbe', () => ({ startDirectProbe: (...args: Parameters<typeof mockStart>) => mockStart(...args) }));

beforeEach(() => { mockStart.mockClear(); mockStop.mockClear(); });

test('failed ICE exposes measured zero replies and unknown RTT/path/DTLS without implying Android execution', () => {
  render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  act(() => mockReport({ state: 'failed', samples: [], path: 'unknown', protocol: null, reason: 'connection_deadline',
    iceState: 'checking', networkAgeAtStopMs: 99, network: { localCandidates: 1, remoteCandidates: 2,
      pairs: 2, checkingPairs: 2, failedPairs: 0, succeededPairs: 0, requestsSent: 4, responsesReceived: 0, dtlsState: null } }));
  expect(screen.getByRole('status')).toHaveTextContent('Соединение не подтверждено');
  expect(screen.getByText('Не измерен')).toBeInTheDocument();
  expect(screen.getByText('Не подтверждён')).toBeInTheDocument();
  expect(screen.getByText('checking / Не измерен')).toBeInTheDocument();
  expect(screen.getByText('4 / 0')).toBeInTheDocument();
  expect(screen.getByText('99 мс')).toBeInTheDocument();
  expect(screen.getByText(/Успешная пара не означает выбранный путь/)).toBeInTheDocument();
});

test('changing device retires the old probe and clears its diagnostic snapshot', () => {
  const { rerender } = render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  act(() => mockReport({ state: 'connecting', samples: [], path: 'unknown', protocol: null, reason: null }));
  expect(screen.getByRole('status')).toHaveTextContent('APK ответил');
  rerender(<DirectProbeDiagnostics deviceId="two" />);
  expect(mockStop).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(mockStart).toHaveBeenCalledTimes(1);
});
