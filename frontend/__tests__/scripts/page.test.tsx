import { act, fireEvent, render, screen } from '@testing-library/react';
import ScriptsPage from '@/app/(dashboard)/scripts/page';
import { useScript, useScripts } from '@/lib/hooks/useScripts';
import { useAuthStore } from '@/lib/store';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';

jest.mock('@/lib/hooks/useScripts', () => ({ useScript: jest.fn(), useScripts: jest.fn() }));
jest.mock('@/components/sphere/RunScriptModal', () => ({ RunScriptModal: jest.fn(({ open }: { open: boolean }) => open ? <div role="dialog">Запуск текущей версии</div> : null) }));

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
  localStorage.clear();
  useAuthStore.setState({ user: null, sessionVersion: 0 });
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

const actor = { id: 'operator-1', org_id: 'org-1', role: 'org_admin', email: 'operator@example.org' };
const preferenceKey = 'sphere:scripts:catalog:v1:org-1:operator-1';

it('retains catalog view and field preferences after remount for the same operator', () => {
  useAuthStore.setState({ user: actor });
  const first = render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Карточки сценариев' }));
  fireEvent.click(screen.getByRole('button', { name: 'Настроить каталог' }));
  fireEvent.click(screen.getByRole('button', { name: 'Компактная' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Идентификаторы сценария и версии' }));
  fireEvent.click(screen.getByRole('button', { name: 'Готово' }));
  expect(screen.getByText('ID: script-1')).toBeInTheDocument();
  const saved = JSON.parse(localStorage.getItem(preferenceKey)!);
  expect(saved).toMatchObject({ schema: 1, view: 'cards', density: 'compact', identifiers: true });
  expect(JSON.stringify(saved)).not.toContain('Canary DAG');
  first.unmount();
  render(<ScriptsPage />);
  expect(screen.getByRole('button', { name: 'Карточки сценариев' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByText('ID: script-1')).toBeInTheDocument();
});

it('does not inherit a different operator or organisation preferences', () => {
  localStorage.setItem(preferenceKey, JSON.stringify({ schema: 1, view: 'cards', identifiers: true }));
  useAuthStore.setState({ user: actor });
  render(<ScriptsPage />);
  expect(screen.getByText('ID: script-1')).toBeInTheDocument();
  act(() => useAuthStore.setState({ user: { ...actor, org_id: 'org-2' }, sessionVersion: 1 }));
  expect(screen.getByRole('button', { name: 'Подробный список' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.queryByText('ID: script-1')).not.toBeInTheDocument();
  expect(localStorage.getItem('sphere:scripts:catalog:v1:org-2:operator-1')).toBeNull();
});

it.each(['{bad JSON', JSON.stringify({ schema: 1, view: 'cards', perPage: 5000 }), ' '.repeat(4097)])('bounds and validates saved page size (%#)', raw => {
  useAuthStore.setState({ user: actor });
  localStorage.setItem(preferenceKey, raw);
  render(<ScriptsPage />);
  expect(useScripts).toHaveBeenLastCalledWith({ query: undefined, page: 1, per_page: 50 });
});

it('opens an explicit device-selection run tied to the published version', () => {
  useAuthStore.setState({ user: actor });
  render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить' }));
  expect(jest.mocked(RunScriptModal).mock.calls.at(-1)?.[0]).toMatchObject({
    scriptId: script.id, expectedVersion: script.current_version, requireVersion: true, initialTargetMode: 'select',
  });
  act(() => useAuthStore.setState({ sessionVersion: 1 }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('does not allow a run without a published API version', () => {
  useAuthStore.setState({ user: actor });
  jest.mocked(useScripts).mockReturnValue({
    data: { items: [{ ...script, current_version: null }], total: 1, page: 1, per_page: 50 },
    isLoading: false, isError: false, isFetching: false, refetch: jest.fn(),
  } as never);
  render(<ScriptsPage />);
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeDisabled();
  expect(useScript).not.toHaveBeenCalled();
});

it('keeps a selected source panel scoped to its originating session', () => {
  useAuthStore.setState({ user: actor });
  render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть DAG' }));
  expect(screen.getByText('DAG сценария · только чтение')).toBeInTheDocument();
  act(() => useAuthStore.setState({ sessionVersion: 1 }));
  expect(screen.queryByText('DAG сценария · только чтение')).not.toBeInTheDocument();
});

it('changes backend page size and resets page selection rather than sorting a partial catalog', () => {
  useAuthStore.setState({ user: actor });
  jest.mocked(useScripts).mockReturnValue({
    data: { items: [script], total: 101, page: 1, per_page: 50 }, isLoading: false, isError: false, isFetching: false, refetch: jest.fn(),
  } as never);
  render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: сценарии' }));
  expect(useScripts).toHaveBeenLastCalledWith({ query: undefined, page: 2, per_page: 50 });
  fireEvent.click(screen.getByRole('button', { name: 'Настроить каталог' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Сценариев на странице' }), { target: { value: '100' } });
  expect(useScripts).toHaveBeenLastCalledWith({ query: undefined, page: 1, per_page: 100 });
});
