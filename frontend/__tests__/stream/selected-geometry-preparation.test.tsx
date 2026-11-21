import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {webcrypto} from 'node:crypto';
import {TextDecoder,TextEncoder} from 'node:util';
import {TeachingNavigation} from '@/src/features/stream/TeachingNavigation';
import {reconstructionRequest,ReconstructionResponseError,type NavigationState} from '@/src/features/stream/reconstructionClient';
import type {RouteSource} from '@/src/features/stream/routeSource';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
jest.mock('@/src/features/stream/RecordedRouteFrame',()=>({RecordedRouteFrame:()=> <div>original-source-frame</div>}));
jest.mock('@/src/features/stream/RouteGeometryMap',()=>({__esModule:true,default:()=> <div>actual-selected-geometry</div>}));

const job={id:'a'.repeat(32),key:'b'.repeat(64)},manifestSha='c'.repeat(64),clip='d'.repeat(32),scope='e'.repeat(32);
const source={clip,scope,manifestSha,folder:{},rows:[{relative_ticks_90k:0},{relative_ticks_90k:90000}]} as RouteSource;
const raw=new TextEncoder().encode(JSON.stringify({schema:'sphere-recovered-scene-v1',source_manifest_sha256:manifestSha,
  cameras:[{center:[0,0,0],ticks_90k:0},{center:[0,0,1],ticks_90k:90000}],points:[[0,0,3,1,1,1]]}));
let geometrySha:string;
beforeAll(async()=>{geometrySha=Buffer.from(await webcrypto.subtle.digest('SHA-256',raw)).toString('hex');});
beforeEach(()=>{
  sessionStorage.clear();jest.clearAllMocks();
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});Object.defineProperty(globalThis,'TextDecoder',{configurable:true,value:TextDecoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'ffffffff-ffff-ffff-ffff-ffffffffffff'});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:jest.fn(),drawImage:jest.fn()} as never);
});
afterEach(()=>jest.restoreAllMocks());

function fixture(navigation:NavigationState={phase:'not_prepared'},qualified=true,startRefusal?:403|409){
  let current=navigation;
  const bound={alternativeId:'retained-173',geometry_sha256:geometrySha,runtime_family:'reference_lk' as const};
  const preparationSource={...bound,cameras:2,points:1};
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/navigation/start'))throw new ReconstructionResponseError(startRefusal??409,'route_start_source_changed');
    if(path.endsWith('/navigation/stop'))return {json:async()=>({phase:'closed'})} as Response;
    if(path.endsWith('/navigation/prepare')){
      current={phase:'features',source:bound};
      return {json:async()=>current} as Response;
    }
    if(path.endsWith('/geometry-alternatives'))return {json:async()=>({preferredAlternativeId:'retained-173',alternatives:[
      {id:'retained-173',label:'Совместная геометрия · 20 556 точек',cameras:2},
      {id:'comparison',label:'Новая схема · осмотр',cameras:2}]})} as Response;
    if(path.endsWith('/geometry')||path.includes('/geometry-alternatives/'))return {arrayBuffer:async()=>Uint8Array.from(raw).buffer} as Response;
    if(init?.method==='POST')throw Error('unexpected_game_or_session_command');
    return {json:async()=>({phase:'failed',error:'resource_guard',source_manifest_sha256:manifestSha,geometry_available:true,
      sparse_available:false,dense_available:false,navigation:{...current,preparationSources:qualified?[preparationSource]:[]}})} as Response;
  });
  const view=render(<TeachingNavigation job={job} clip={clip} scope={scope} sourceRecording={source}
    clips={[{id:clip,title:'skuter1',complete:true,frames:2}]} video={{current:null}} ready binding={{captureEpoch:'1'.repeat(32),width:1920,height:1080}} onReview={jest.fn()}
    vehicleInput={{issue:null,hudProfile:'black_russia_scooter_v1',open:jest.fn()}}/>);
  return {...view,bound,setNavigation:(state:NavigationState)=>{current=state;}};
}

test('a retained verified schema can prepare directly despite a failed old primary, with one source-bound intent',async()=>{
  fixture();
  const button=await screen.findByRole('button',{name:'Подготовить карту из выбранной схемы'});
  expect(button).toBeEnabled();expect(screen.queryByRole('button',{name:'Открыть подготовку записи'})).not.toBeInTheDocument();
  expect(screen.queryByText(/Подготовка выбранной попытки остановлена ресурсной проверкой/)).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  fireEvent.click(button);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[2]?.method==='POST')).toHaveLength(1));
  const [path,,init]=jest.mocked(reconstructionRequest).mock.calls.find(call=>call[2]?.method==='POST')!;
  expect(path).toBe(`/jobs/${job.id}/navigation/prepare`);
  expect(JSON.parse(String(init?.body))).toEqual({id:'f'.repeat(32),alternativeId:'retained-173'});
  await screen.findByRole('button',{name:'Готовим карту из схемы…'});
  expect(screen.getByLabelText('Схема для живой проверки')).toHaveValue('retained-173');
  expect(screen.getByLabelText('Схема для живой проверки')).toBeDisabled();
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
});

test('displaying many points never offers preparation without backend-approved exact source measurements',async()=>{
  fixture({phase:'not_prepared'},false);
  await screen.findByText('actual-selected-geometry');
  await screen.findByRole('button',{name:'Проверить готовность схемы'});
  expect(screen.queryByRole('button',{name:'Подготовить карту из выбранной схемы'})).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});

test('an awaiting qualification result is an idle read-only wait, not another preparation or resource refusal',async()=>{
  fixture({phase:'awaiting_qualification',error:'route_reference_lk_unqualified',source:{alternativeId:'retained-173',geometry_sha256:geometrySha,runtime_family:'reference_lk'}});
  await screen.findByRole('button',{name:'Проверить готовность карты'});
  expect(screen.queryByRole('button',{name:'Подготовить карту из выбранной схемы'})).not.toBeInTheDocument();
  const card=screen.getByLabelText('Подготовка карты выбранной схемы');
  expect(within(card).getByRole('status')).toHaveTextContent('Карта построена');
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Проверить готовность карты'}));
  await act(async()=>{await Promise.resolve();});
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});

test('only the exact selected prepared alternative can unlock a manually confirmed observation',async()=>{
  fixture({phase:'ready',source:{alternativeId:'retained-173',geometry_sha256:geometrySha,runtime_family:'reference_lk'}});
  await screen.findByText('actual-selected-geometry');
  expect(screen.getByLabelText('Схема для живой проверки')).toHaveValue('retained-173');
  await waitFor(()=>expect(within(screen.getByLabelText('Подготовка карты выбранной схемы')).getByRole('status')).toHaveTextContent('готова к проверке'));
  fireEvent.click(screen.getByRole('checkbox',{name:/На экране игровой мир/}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Схема для живой проверки'),{target:{value:'comparison'}});
  await waitFor(()=>expect(screen.getByLabelText('Подготовка карты выбранной схемы')).toHaveTextContent('другой схеме'));
  fireEvent.click(screen.getByRole('checkbox',{name:/На экране игровой мир/}));
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});

test('changing the control panel preserves a manually selected schema and cannot inherit another source readiness',async()=>{
  fixture({phase:'ready',source:{alternativeId:'retained-173',geometry_sha256:geometrySha,runtime_family:'reference_lk'}});
  await waitFor(()=>expect(within(screen.getByLabelText('Подготовка карты выбранной схемы')).getByRole('status')).toHaveTextContent('готова к проверке'));
  fireEvent.change(screen.getByLabelText('Схема для живой проверки'),{target:{value:'comparison'}});
  await waitFor(()=>expect(within(screen.getByLabelText('Подготовка карты выбранной схемы')).getByRole('status')).toHaveTextContent('другой схеме'));
  fireEvent.click(screen.getByRole('button',{name:'Транспорт · газ и руль'}));
  await waitFor(()=>expect(screen.getByLabelText('Схема для живой проверки')).toHaveValue('comparison'));
  await waitFor(()=>expect(within(screen.getByLabelText('Подготовка карты выбранной схемы')).getByRole('status')).toHaveTextContent('другой схеме'));
  expect(screen.getByRole('button',{name:'Запустить транспорт'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});

test.each([403,409] as const)('observer start sends the validated source fence and a %s mismatch never reaches observation',async(status)=>{
  const bound={alternativeId:'retained-173',geometry_sha256:geometrySha,runtime_family:'reference_lk' as const};
  fixture({phase:'ready',source:bound},true,status);
  await waitFor(()=>expect(within(screen.getByLabelText('Подготовка карты выбранной схемы')).getByRole('status')).toHaveTextContent('готова к проверке'));
  fireEvent.click(screen.getByRole('checkbox',{name:/На экране игровой мир/}));
  fireEvent.click(screen.getByRole('button',{name:'Проверить направление · 120 с'}));
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(([path])=>path.endsWith('/navigation/stop'))).toBe(true));
  const posts=jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[2]?.method==='POST');
  expect(posts.map(([path])=>path.split('/').at(-1))).toEqual(['start','stop']);
  expect(JSON.parse(String(posts[0][2]?.body)).expectedSource).toEqual(bound);
});
