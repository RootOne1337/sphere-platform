import { fireEvent, render, screen, within } from '@testing-library/react';
import TaskEnginePage from '@/app/(dashboard)/tasks/page';

const mockPush = jest.fn();
const mockQueries = jest.fn();
let mockError = false;
let mockLoading = false;
let mockRows: any[];
let mockPipelines: any;
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('@/lib/hooks/useDebounce', () => ({ useDebounce: (value: unknown) => value }));
jest.mock('@/lib/hooks/useTasks', () => ({
  useTasks: (params: any) => {
    mockQueries(params);
    let rows = mockRows.filter(t => (!params.status || t.status === params.status)
      && (!params.active_only || ['queued', 'assigned', 'running'].includes(t.status))
      && (!params.search || `${t.id} ${t.script_name}`.toLowerCase().includes(params.search.toLowerCase())));
    if (params.sort_dir === 'asc') rows = [...rows].reverse();
    const counts = Object.fromEntries(['queued','assigned','running','completed','failed','timeout','cancelled'].map(s => [s,rows.filter(t => t.status===s).length]));
    const page = params.page ?? 1, size = params.per_page ?? 50;
    return { data: mockError || mockLoading ? undefined : {
      items: rows.slice((page-1)*size,page*size), total: rows.length,
      page, per_page: size, pages: Math.ceil(rows.length/size), status_counts: counts,
    }, isLoading: mockLoading, isError: mockError, isFetching: false, dataUpdatedAt: 1, refetch: jest.fn() };
  },
  useRetryTask: () => ({ mutate: jest.fn(), isPending: false }),
}));
jest.mock('@/lib/hooks/usePipelineRuns', () => ({
  useActivePipelineRuns: () => mockPipelines,
}));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: () => ({ data: { items: [], total: 0 } }) }));
jest.mock('@/lib/hooks/useBatches', () => ({ useBroadcastBatch: () => ({ mutate: jest.fn() }) }));

beforeEach(() => {
  jest.clearAllMocks(); mockError=false; mockLoading=false;
  mockRows = Array.from({ length: 190 }, (_, i) => ({
    id:`task-${i}`, script_id:'script', device_id:'agent', priority:5,
    script_name:i===189?'Old failure':'Safe system scenario',
    status:i===189?'failed':'completed', created_at:new Date(2026,0,1,0,190-i).toISOString(),
    started_at:null,finished_at:null,device_name:'Android',
  }));
  mockPipelines = { data: { items: [], total: 0 }, isLoading:false,isError:false };
});

it('uses the full server total and can reach the eighth page', () => {
  render(<TaskEnginePage />);
  expect(screen.getAllByText('190').length).toBeGreaterThan(0);
  expect(screen.getByText('99.5%')).toBeInTheDocument();
  for (let i=0;i<7;i++) fireEvent.click(screen.getByRole('button',{name:'Следующая страница'}));
  expect(screen.getByText('Old failure')).toBeInTheDocument();
  expect(mockQueries).toHaveBeenCalledWith(expect.objectContaining({page:8,per_page:25,include_counts:true}));
  expect(screen.getByRole('button',{name:'Следующая страница'})).toBeDisabled();
});

it('searches older history and resets pagination before displaying it', () => {
  render(<TaskEnginePage />);
  fireEvent.click(screen.getByRole('button',{name:'Следующая страница'}));
  fireEvent.change(screen.getByPlaceholderText('Filter tasks...'),{target:{value:'Old failure'}});
  expect(screen.getByText('Old failure')).toBeInTheDocument();
  expect(mockQueries).toHaveBeenCalledWith(expect.objectContaining({page:1,search:'Old failure'}));
});

it('filters older failed rows on the server and sends sort direction', () => {
  render(<TaskEnginePage />);
  fireEvent.change(screen.getByRole('combobox'),{target:{value:'FAILED'}});
  expect(screen.getByText('Old failure')).toBeInTheDocument();
  expect(mockQueries).toHaveBeenCalledWith(expect.objectContaining({status:'failed'}));
  fireEvent.click(screen.getByRole('button',{name:/Создана/}));
  expect(mockQueries).toHaveBeenCalledWith(expect.objectContaining({sort_by:'created_at',sort_dir:'asc'}));
});

it('uses script names and priority without inventing CRON or a future forecast', () => {
  render(<TaskEnginePage />);
  expect(screen.getAllByText('Safe system scenario').length).toBeGreaterThan(0);
  expect(screen.queryByText('CRON')).not.toBeInTheDocument();
  expect(screen.queryByText(/Next 60s/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Новый сценарий'}));
  expect(mockPush).toHaveBeenCalledWith('/scripts/builder');
});

it('reports request failure instead of zero tasks or a fabricated empty queue', () => {
  mockError=true; mockPipelines={data:undefined,isLoading:false,isError:true};
  render(<TaskEnginePage />);
  expect(screen.getByText('Не удалось загрузить историю задач')).toBeInTheDocument();
  expect(screen.queryByText('Нет активных pipeline')).not.toBeInTheDocument();
  expect(screen.queryByText('Нет активных задач')).not.toBeInTheDocument();
});

it('shows old active work and a real waiting pipeline independently of the history page', () => {
  mockRows[189].status='running';
  mockPipelines={data:{total:1,items:[{id:'run-old',pipeline_id:'pipe',device_id:'agent',status:'waiting',current_task_id:'task-189'}]},isLoading:false,isError:false};
  render(<TaskEnginePage />);
  expect(screen.getByText('run-old')).toBeInTheDocument();
  expect(screen.getByText('waiting')).toBeInTheDocument();
  expect(screen.getByText('Old failure')).toBeInTheDocument();
  expect(mockQueries).toHaveBeenCalledWith(expect.objectContaining({active_only:true}));
  fireEvent.click(screen.getByRole('button',{name:'Текущая задача pipeline run-old'}));
  expect(mockPush).toHaveBeenCalledWith('/tasks/task-189');
});

it('marks loading metrics as unavailable rather than zero', () => {
  mockLoading=true;
  render(<TaskEnginePage />);
  const card = screen.getByText('Total Tasks').parentElement!;
  expect(within(card).queryByText('0')).not.toBeInTheDocument();
});

it('returns to a valid server page when polling shrinks the result set', () => {
  const view = render(<TaskEnginePage />);
  for (let i=0;i<7;i++) fireEvent.click(screen.getByRole('button',{name:'Следующая страница'}));
  mockRows = mockRows.slice(0,20);
  view.rerender(<TaskEnginePage />);
  expect(screen.getByText('1 / 1')).toBeInTheDocument();
  expect(mockQueries).toHaveBeenLastCalledWith(expect.objectContaining({ active_only:true }));
  expect(screen.queryByText('Задачи не найдены')).not.toBeInTheDocument();
});
