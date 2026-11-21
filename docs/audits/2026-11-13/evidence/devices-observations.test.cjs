// Audit fixtures with the real FleetMatrix and inspector. Network and AG Grid layout are mocked.
const React = require('react');
const { fireEvent, render, screen, waitFor } = require('@testing-library/react');

jest.mock('ag-grid-react', () => jest.requireActual('@/__tests__/mocks/agGridReact'));
jest.mock('next/dynamic', () => () => props => require('react').createElement(jest.requireActual('@/src/features/devices/FleetDataGrid').FleetDataGrid, props));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: () => ({ can: () => true }) }));
jest.mock('@/src/features/devices/DeviceViewerPresence', () => ({ DeviceViewerPresence: () => null }));
jest.mock('@/components/sphere/DeviceStream', () => ({ DeviceStream: () => null }));
jest.mock('@/src/features/devices/WebTerminal', () => ({ WebTerminal: () => null }));
jest.mock('@/src/features/devices/LogcatViewer', () => ({ LogcatViewer: () => null }));

const { FleetMatrix } = require('@/src/features/devices/FleetMatrix');
const { DeviceInspectorDetail } = require('@/src/features/devices/DeviceInspectorDetail');
const { createWrapper } = require('@/__tests__/helpers');
const { api } = require('@/lib/api');
const payload = require('./devices-contract-result.json');

beforeEach(() => { jest.resetAllMocks(); window.localStorage.clear(); });

it('shows the API default as negative access while the inspector shows fresh active VPN', async () => {
  const { list, detail } = payload.fresh_presence;
  api.get.mockResolvedValue({ data: detail });
  render(React.createElement(React.Fragment, null,
    React.createElement(FleetMatrix, { data: [list], isLoading: false, rowSelection: {}, onRowSelectionChange: jest.fn() }),
    React.createElement(DeviceInspectorDetail, { deviceId: detail.id }),
  ), { wrapper: createWrapper() });
  await screen.findByText('VPN, активность по APK');
  expect(screen.queryByText('VPN —')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Настроить видимые колонки' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Доступ' }));
  expect(screen.getByTitle('VPN not assigned')).toHaveTextContent('VPN —');
  expect(screen.getByTitle('ADB not linked')).toHaveTextContent('ADB —');
  expect(screen.getByText('ADB (дополнительный канал)').nextSibling).toHaveTextContent('Не подключён');
  expect(screen.getByText('VPN, активность по APK').nextSibling).toHaveTextContent('Активен');
  expect(api.post).not.toHaveBeenCalled();
});

it('enables live commands for an online catalogue fallback with no heartbeat', async () => {
  const detail = payload.fresh_presence.detail;
  const fallback = payload.redis_client_absent;
  api.get.mockResolvedValue({ data: { ...detail, status: fallback.detail_status, last_heartbeat: fallback.detail_heartbeat,
    connected_since: null, vpn_active: null, vpn_observation_state: 'unknown' } });
  render(React.createElement(DeviceInspectorDetail, { deviceId: detail.id }), { wrapper: createWrapper() });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Перезагрузка' })).toBeEnabled());
  expect(screen.getByRole('button', { name: 'Терминал' })).toBeEnabled();
  expect(screen.getByText('Последний heartbeat APK').nextSibling).toHaveTextContent('Не сообщено');
  expect(api.post).not.toHaveBeenCalled();
});
