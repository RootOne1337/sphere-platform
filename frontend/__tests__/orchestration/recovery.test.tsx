import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { PipelineResumeControl } from '@/components/orchestration/PipelineResumeControl';

describe('Pipeline resume follows persisted recovery state', () => {
  test.each([
    [{ execution_phase: 'unknown' }, 'Результат шага неизвестен'],
    [{ execution_phase: 'in_flight', execution_lease_until: '2000-01-01T00:00:00Z' }, 'восстановление исполнителя'],
    [{ execution_phase: 'ready', cancel_requested_at: '2026-09-20T00:00:00Z' }, 'подтверждение отмены'],
  ])('blocks replay when backend has not established a safe boundary: %s', (run, message) => {
    const resume = jest.fn();
    render(<PipelineResumeControl run={run} onResume={resume} />);
    expect(screen.getByRole('status')).toHaveTextContent(message);
    const button = screen.getByRole('button', { name: 'Возобновить pipeline' });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(resume).not.toHaveBeenCalled();
  });

  test('permits resume after recovery cleared ownership, retaining an existing child', () => {
    const resume = jest.fn();
    const { rerender } = render(<PipelineResumeControl
      run={{ execution_phase: 'in_flight', execution_lease_until: '2000-01-01T00:00:00Z' }} onResume={resume} />);
    expect(screen.getByRole('button')).toBeDisabled();
    rerender(<PipelineResumeControl run={{ execution_phase: 'in_flight', execution_lease_until: null }} onResume={resume} />);
    fireEvent.click(screen.getByRole('button'));
    expect(resume).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  test('does not resubmit while the request is pending', () => {
    const resume = jest.fn();
    render(<PipelineResumeControl run={{ execution_phase: 'ready' }} onResume={resume} pending />);
    fireEvent.click(screen.getByRole('button'));
    expect(resume).not.toHaveBeenCalled();
  });
});
