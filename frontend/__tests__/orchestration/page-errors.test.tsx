import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
jest.mock('@/components/orchestration/PipelineResumeControl', () => ({ PipelineResumeControl: () => null }));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={client}>
      <OrchestrationPage />
    </QueryClientProvider>,
  );
  return { ...result, client };
}

afterEach(() => jest.clearAllMocks());

it('keeps failed sources unknown, offers an isolated retry, and only confirms an empty list after success', async () => {
  let pipelineAttempts = 0;
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (url === '/pipelines?per_page=100') {
      pipelineAttempts += 1;
      if (pipelineAttempts === 1) throw new Error('network timeout');
      return { data: { items: [], total: 0, page: 1, per_page: 100, pages: 0 } } as never;
    }
    if (url === '/pipelines/runs?per_page=100' || url === '/schedules?per_page=100') throw new Error('service unavailable');
    throw new Error(`Unexpected GET ${url}`);
  });

  const { client } = renderPage();
  expect(await screen.findByText('Не удалось обновить Конвейеры.')).toBeInTheDocument();
  expect(screen.getByText('Не удалось обновить Запуски.')).toBeInTheDocument();
  expect(screen.getByText('Не удалось обновить Расписания.')).toBeInTheDocument();
  expect(screen.getAllByText('Данные не получены; пустой список не подтверждён.')).toHaveLength(3);
  expect(screen.getByText('Список pipelines не загружен; пустой каталог не подтверждён.')).toBeInTheDocument();
  expect(screen.queryByText('Нет pipelines. Создайте первый!')).not.toBeInTheDocument();
  expect(within(screen.getByText('Schedules Active').parentElement!).getByText('—')).toBeInTheDocument();
  expect(screen.queryByText('0/—')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку: Конвейеры' }));
  await waitFor(() => expect(screen.getByText('Нет pipelines. Создайте первый!')).toBeInTheDocument());
  expect(screen.getAllByRole('alert')).toHaveLength(2);
  expect(screen.queryByText('Последний снимок пуст; обновить список не удалось.')).not.toBeInTheDocument();

  fireEvent.click(screen.getByText('Pipeline Runs'));
  expect(screen.getByText('Список запусков не загружен; пустой результат не подтверждён.')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Schedules'));
  expect(screen.getByText('Список расписаний не загружен; пустой каталог не подтверждён.')).toBeInTheDocument();
  client.clear();
});
