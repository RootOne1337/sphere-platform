import { fireEvent, render, screen } from '@testing-library/react';
import ScriptsPage from '@/app/(dashboard)/scripts/page';
import { useScript, useScripts } from '@/lib/hooks/useScripts';

jest.mock('@/lib/hooks/useScripts', () => ({ useScript: jest.fn(), useScripts: jest.fn() }));
jest.mock('@/components/sphere/RunScriptModal', () => ({ RunScriptModal: () => null }));

const script = {
  id: 'script-1',
  name: 'Canary DAG',
  description: 'Безопасный сценарий проверки',
  is_archived: false,
  created_at: '2026-09-29T00:00:00Z',
  updated_at: '2026-09-29T00:00:00Z',
  current_version: {
    id: 'version-1', script_id: 'script-1', version: 4,
    dag: { nodes: { start: { type: 'start' }, wait: { type: 'wait' } }, edges: [] },
    dag_hash: 'sha256:canary', notes: 'Current version', created_by_id: null, created_at: '2026-09-29T00:00:00Z',
  },
};

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(useScripts).mockReturnValue({
    data: { items: [script], total: 1, page: 1, per_page: 20 },
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  } as never);
  jest.mocked(useScript).mockReturnValue({
    data: { ...script, versions: [script.current_version] },
    isLoading: false,
    isError: false,
    isFetching: false,
    refetch: jest.fn(),
  } as never);
});

it('shows step count derived from the backend current version DAG and does not fetch source until requested', () => {
  render(<ScriptsPage />);

  expect(screen.getByText('2 шага')).toBeInTheDocument();
  expect(useScript).not.toHaveBeenCalled();
});

it('opens a read-only, redacted DAG inspector on explicit request', () => {
  const secretScript = {
    ...script,
    current_version: {
      ...script.current_version,
      dag: { nodes: { login: { type: 'input', password: 'do-not-render' } }, edges: [] },
    },
  };
  jest.mocked(useScripts).mockReturnValue({
    data: { items: [secretScript], total: 1, page: 1, per_page: 20 },
    isLoading: false, isError: false, refetch: jest.fn(),
  } as never);
  jest.mocked(useScript).mockReturnValue({
    data: { ...secretScript, versions: [] },
    isLoading: false, isError: false, isFetching: false, refetch: jest.fn(),
  } as never);
  render(<ScriptsPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть DAG' }));

  expect(screen.getByText('DAG сценария · только чтение')).toBeInTheDocument();
  expect(screen.getByText(/"password": "\[скрыто\]"/)).toBeInTheDocument();
  expect(screen.queryByText('do-not-render')).not.toBeInTheDocument();
  expect(useScript).toHaveBeenCalledWith('script-1', { includeDag: true });
});
