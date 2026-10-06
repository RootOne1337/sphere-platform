import { act, fireEvent, render, screen } from '@testing-library/react';
import ScriptsPage from '@/app/(dashboard)/scripts/page';
import { ScriptCatalogContractError, useScriptCatalog, useScriptCatalogSource } from '@/lib/hooks/useScriptCatalog';
import { catalogActor, catalogScript, catalogSource, catalogEnvelope } from './catalog-fixtures';
import { useAuthStore } from '@/lib/store';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';
import { useCapabilities } from '@/src/features/access/Capabilities';

jest.mock('@/lib/hooks/useScriptCatalog', () => ({ ...jest.requireActual('@/lib/hooks/useScriptCatalog'), useScriptCatalog: jest.fn(), useScriptCatalogSource: jest.fn() }));
jest.mock('@/components/sphere/RunScriptModal', () => ({ RunScriptModal: jest.fn(({ open }: { open: boolean }) => open ? <div role="dialog">Запуск текущей версии</div> : null) }));
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: jest.fn() }));
const grantedAccess = {
  verified: true, pending: false, failed: false, role: 'org_admin',
  can: (permission: string) => ['script:read', 'script:write', 'script:execute'].includes(permission),
  canAccessRoute: () => true, retry: jest.fn(),
};

const script = catalogScript;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  useAuthStore.setState({ user: catalogActor, sessionVersion: 0 });
  jest.mocked(useCapabilities).mockReturnValue(grantedAccess);
  jest.mocked(useScriptCatalog).mockReturnValue({
    data: catalogEnvelope(),
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  } as never);
  jest.mocked(useScriptCatalogSource).mockReturnValue({
    data: catalogSource,
    isLoading: false,
    isError: false,
    isFetching: false,
    refetch: jest.fn(),
  } as never);
});

it('shows authoritative metadata step count and does not fetch source until requested', () => {
  render(<ScriptsPage />);

  expect(screen.getByText('2 шага')).toBeInTheDocument();
  expect(useScriptCatalogSource).not.toHaveBeenCalled();
});

it('opens a read-only, redacted DAG inspector on explicit request', () => {
  jest.mocked(useScriptCatalogSource).mockReturnValue({
    data: { ...catalogSource, dag: { nodes: [{ id: 'login', type: 'input', password: 'do-not-render' }, { id: 'end' }], edges: [] } },
    isLoading: false, isError: false, isFetching: false, refetch: jest.fn(),
  } as never);
  render(<ScriptsPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть DAG' }));

  expect(screen.getByText('DAG сценария · только чтение')).toBeInTheDocument();
  expect(screen.getByText(/"password": "\[скрыто\]"/)).toBeInTheDocument();
  expect(screen.queryByText('do-not-render')).not.toBeInTheDocument();
  expect(useScriptCatalogSource).toHaveBeenCalledWith(script);
});

const actor = catalogActor;
const preferenceKey = `sphere:scripts:catalog:v1:${actor.org_id}:${actor.id}`;

it('retains catalog view and field preferences after remount for the same operator', () => {
  useAuthStore.setState({ user: actor });
  const first = render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Карточки сценариев' }));
  fireEvent.click(screen.getByRole('button', { name: 'Настроить каталог' }));
  fireEvent.click(screen.getByRole('button', { name: 'Компактная' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Идентификаторы сценария и версии' }));
  fireEvent.click(screen.getByRole('button', { name: 'Готово' }));
  expect(screen.getByText(`ID: ${script.id}`)).toBeInTheDocument();
  const saved = JSON.parse(localStorage.getItem(preferenceKey)!);
  expect(saved).toMatchObject({ schema: 1, view: 'cards', density: 'compact', identifiers: true });
  expect(JSON.stringify(saved)).not.toContain('Canary DAG');
  first.unmount();
  render(<ScriptsPage />);
  expect(screen.getByRole('button', { name: 'Карточки сценариев' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByText(`ID: ${script.id}`)).toBeInTheDocument();
});

it('does not inherit a different operator or organisation preferences', () => {
  localStorage.setItem(preferenceKey, JSON.stringify({ schema: 1, view: 'cards', identifiers: true }));
  useAuthStore.setState({ user: actor });
  render(<ScriptsPage />);
  expect(screen.getByText(`ID: ${script.id}`)).toBeInTheDocument();
  act(() => useAuthStore.setState({ user: { ...actor, org_id: 'org-2' }, sessionVersion: 1 }));
  expect(screen.getByRole('button', { name: 'Подробный список' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.queryByText(`ID: ${script.id}`)).not.toBeInTheDocument();
  expect(localStorage.getItem(`sphere:scripts:catalog:v1:org-2:${actor.id}`)).toBeNull();
});

it.each(['{bad JSON', JSON.stringify({ schema: 1, view: 'cards', perPage: 5000 }), ' '.repeat(4097)])('bounds and validates saved page size (%#)', raw => {
  useAuthStore.setState({ user: actor });
  localStorage.setItem(preferenceKey, raw);
  render(<ScriptsPage />);
  expect(useScriptCatalog).toHaveBeenLastCalledWith({ query: undefined, page: 1, per_page: 50 });
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
  jest.mocked(useScriptCatalog).mockReturnValue({
    data: catalogEnvelope([{ ...script, current_version_id: null, current_version: null, node_count: null }]),
    isLoading: false, isError: false, isFetching: false, refetch: jest.fn(),
  } as never);
  render(<ScriptsPage />);
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Нет опубликованного DAG' })).toBeDisabled();
  expect(screen.getByText('Нет опубликованной версии')).toBeInTheDocument();
  expect(useScriptCatalogSource).not.toHaveBeenCalled();
});

it('pins an open source to the clicked receipt while the catalog publishes a new current version', () => {
  const view = render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть DAG' }));
  const published = { ...script, current_version_id: '55555555-5555-4555-8555-555555555555', current_version: {
    ...script.current_version!, id: '55555555-5555-4555-8555-555555555555', version: 5, dag_hash: 'b'.repeat(64),
  } };
  jest.mocked(useScriptCatalog).mockReturnValue({ data: catalogEnvelope([published]), isError: false, isLoading: false, refetch: jest.fn() } as never);
  view.rerender(<ScriptsPage />);
  expect(screen.getByText('v5')).toBeInTheDocument();
  expect(useScriptCatalogSource).toHaveBeenLastCalledWith(script);
  expect(screen.getByText(catalogSource.dag_hash)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Скрыть DAG' }));
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть DAG' }));
  expect(useScriptCatalogSource).toHaveBeenLastCalledWith(published);
});

it('hides cached catalog rows after an invalid refresh and offers an explicit retry', () => {
  const refetch = jest.fn();
  jest.mocked(useScriptCatalog).mockReturnValue({ data: catalogEnvelope(), isError: true, error: new ScriptCatalogContractError(), isLoading: false, refetch } as never);
  render(<ScriptsPage />);
  expect(screen.getByText(/неполные или несогласованные метаданные/)).toBeInTheDocument();
  expect(screen.queryByText(script.name)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(refetch).toHaveBeenCalledTimes(1);
  expect(useScriptCatalogSource).not.toHaveBeenCalled();
});

it('reports incomplete server metadata without inventing a zero count or source', () => {
  jest.mocked(useScriptCatalog).mockReturnValue({ isError: true, error: { response: { status: 503, data: { detail: { code: 'script_catalog_metadata_unavailable' } } } }, isLoading: false, refetch: jest.fn() } as never);
  render(<ScriptsPage />);
  expect(screen.getByText(/Метаданные опубликованных версий пока недоступны/)).toBeInTheDocument();
  expect(screen.queryByText('0 шагов')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Посмотреть DAG' })).not.toBeInTheDocument();
});

it('hides a previously cached source when its fresh receipt cannot be confirmed', () => {
  jest.mocked(useScriptCatalogSource).mockReturnValue({ data: catalogSource, isError: true, isLoading: false, isFetching: false, refetch: jest.fn() } as never);
  render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть DAG' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось подтвердить исходник выбранной версии');
  expect(screen.queryByText(/"nodes":/)).not.toBeInTheDocument();
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
  jest.mocked(useScriptCatalog).mockReturnValue({
    data: catalogEnvelope([script], 101), isLoading: false, isError: false, isFetching: false, refetch: jest.fn(),
  } as never);
  render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: сценарии' }));
  expect(useScriptCatalog).toHaveBeenLastCalledWith({ query: undefined, page: 2, per_page: 50 });
  fireEvent.click(screen.getByRole('button', { name: 'Настроить каталог' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Сценариев на странице' }), { target: { value: '100' } });
  expect(useScriptCatalog).toHaveBeenLastCalledWith({ query: undefined, page: 1, per_page: 100 });
});

it.each([
  { pending: true, failed: false, role: null },
  { pending: false, failed: true, role: 'org_admin' },
  { pending: false, failed: false, role: 'viewer' },
])('keeps catalog mutations disabled until write/execute capabilities are verified (%j)', denied => {
  useAuthStore.setState({ user: actor });
  jest.mocked(useCapabilities).mockReturnValue({ ...grantedAccess, ...denied, verified: false, can: permission => permission === 'script:read' });
  render(<ScriptsPage />);
  expect(screen.getByRole('button', { name: 'Новый сценарий' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeDisabled();
  expect(screen.getByRole('link', { name: 'Открыть' })).toHaveAttribute('href', `/scripts/builder?id=${script.id}`);
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть DAG' }));
  expect(screen.getByText('DAG сценария · только чтение')).toBeInTheDocument();
  expect(RunScriptModal).not.toHaveBeenCalled();
});

it('allows an execution-only operator to launch while withholding creation', () => {
  useAuthStore.setState({ user: { ...actor, role: 'script_runner' } });
  jest.mocked(useCapabilities).mockReturnValue({ ...grantedAccess, role: 'script_runner', can: permission => permission !== 'script:write' });
  render(<ScriptsPage />);
  expect(screen.getByRole('button', { name: 'Новый сценарий' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Запустить' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});

it('retires an open run when verified execution permission expires without changing identity', () => {
  useAuthStore.setState({ user: actor });
  const view = render(<ScriptsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  jest.mocked(useCapabilities).mockReturnValue({ ...grantedAccess, verified: false, failed: true, can: () => false });
  view.rerender(<ScriptsPage />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  jest.mocked(useCapabilities).mockReturnValue(grantedAccess);
  view.rerender(<ScriptsPage />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
