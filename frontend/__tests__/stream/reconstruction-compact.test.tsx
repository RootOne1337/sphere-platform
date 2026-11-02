import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {TeachingReconstruction} from '@/src/features/stream/TeachingReconstruction';
import {reconstructionRequest,uploadReconstruction,type ReconstructionState} from '@/src/features/stream/reconstructionClient';
import {ensureAutomaticReconstructionLink,listReconstructionLinks,readReconstructionLink,saveReconstructionLink} from '@/src/features/stream/reconstructionLink';
import ReferenceComparison from '@/src/features/stream/ReferenceComparison';
import type {SceneGeometrySelection} from '@/src/features/stream/sceneGeometrySelection';
const mockScene=jest.fn((props:{selectedGeometry?:SceneGeometrySelection|null})=><div data-testid="compact-scene" data-choice={props.selectedGeometry===null?'none':props.selectedGeometry?.id??'legacy'}/>);
jest.mock('next/dynamic',()=>()=>function MockScene(props:Parameters<typeof mockScene>[0]){return mockScene(props);});
jest.mock('@/src/features/stream/ReferenceComparison',()=>({__esModule:true,default:jest.fn(()=> <p>Сравнение с исходными ракурсами</p>)}));
jest.mock('@/src/features/stream/reconstructionLink',()=>({readReconstructionLink:jest.fn(),listReconstructionLinks:jest.fn(),saveReconstructionLink:jest.fn(async()=>{}),ensureAutomaticReconstructionLink:jest.fn(),automaticReconstructionStopped:jest.fn(async()=>false),stopAutomaticReconstruction:jest.fn(async()=>{}),validReconstructionJob:(value:unknown)=>!!value}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn(),uploadReconstruction:jest.fn(async()=>{})}));
const clip='c'.repeat(32),scope='d'.repeat(32),manifest='f'.repeat(64),saved={id:'a'.repeat(32),key:'b'.repeat(64)};
const folder={} as FileSystemDirectoryHandle;
const props={clip,scope,folder:()=>folder,complete:true,sourceManifestSha:manifest,onBusyChange:jest.fn(),manageAutomaticPreparation:false,presentation:'compact' as const,sceneContainer:null};
let status:ReconstructionState;
beforeEach(()=>{
  sessionStorage.clear();jest.clearAllMocks();mockScene.mockClear();
  status={phase:'complete',source_manifest_sha256:manifest,geometry_available:true,sparse_available:true,dense_available:true,surface_supported:true,navigation:{phase:'ready'},quality:{registered:36,selected:36,coverage:1,points:22000,mean_reprojection_px:.9}};
  jest.mocked(readReconstructionLink).mockResolvedValue(saved);jest.mocked(listReconstructionLinks).mockResolvedValue([saved]);
  jest.mocked(saveReconstructionLink).mockResolvedValue();jest.mocked(ensureAutomaticReconstructionLink).mockImplementation(async(_folder,_clip,_mask,candidate)=>candidate!);
  jest.mocked(reconstructionRequest).mockImplementation(async()=>({json:async()=>status}) as Response);
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'});
});
afterEach(()=>{jest.restoreAllMocks();});
test('compact mode has one workflow card and keeps Gaussian controls collapsed without sending intents',async()=>{
  jest.mocked(readReconstructionLink).mockResolvedValue(null);jest.mocked(listReconstructionLinks).mockResolvedValue([]);
  render(<TeachingReconstruction {...props}/>);
  expect(await screen.findByRole('region',{name:'Подготовка выбранной записи'})).toBeInTheDocument();
  await waitFor(()=>expect(screen.getByRole('button',{name:'Подготовить ориентиры'})).toBeEnabled());
  expect(screen.queryByRole('region',{name:'Построение плотной 3D-сцены'})).not.toBeInTheDocument();
  expect(screen.queryByRole('combobox',{name:'Маска записи'})).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Построить 3D-сцену'})).not.toBeInTheDocument();
  expect(reconstructionRequest).not.toHaveBeenCalled();
  const advanced=screen.getByRole('button',{name:'Дополнительно · Gaussian и настройки'});expect(advanced).toHaveAttribute('aria-expanded','false');
  expect(document.getElementById(advanced.getAttribute('aria-controls')!)).toBeInTheDocument();
  fireEvent.click(advanced);expect(screen.getByRole('combobox',{name:'Качество обработки'})).toHaveValue('30000');
  fireEvent.change(screen.getByRole('combobox',{name:'Маска записи'}),{target:{value:'none'}});
  fireEvent.change(screen.getByRole('combobox',{name:'Качество обработки'}),{target:{value:'5000'}});
  fireEvent.click(screen.getByRole('button',{name:'Подготовить ориентиры'}));
  await waitFor(()=>expect(saveReconstructionLink).toHaveBeenCalled());
  expect(jest.mocked(saveReconstructionLink).mock.calls[0][2].creation).toMatchObject({mask:'none',steps:5000,prepare_route:true,route_only:true});
});
test('a failed job is not automatically retried; the explicit retry remains under saved attempts',async()=>{
  status={phase:'failed',source_manifest_sha256:manifest,error:'resource_guard'};
  render(<TeachingReconstruction {...props}/>);
  await screen.findByText('У этой попытки сохранён прежний ресурсный отказ. Это не замер памяти сейчас. Исходное видео сохранено.');
  expect(screen.queryByRole('button',{name:'Повторить подготовку записи'})).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Попытки и повторная обработка'}));
  fireEvent.click(screen.getByRole('button',{name:'Повторить подготовку записи'}));
  await waitFor(()=>expect(saveReconstructionLink).toHaveBeenCalled());
  expect(jest.mocked(saveReconstructionLink).mock.calls[0][2]).toMatchObject({id:'e'.repeat(32),creation:{prepare_route:true,route_only:true}});
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[0]==='/jobs')).toHaveLength(1);
});
test('camera rejection is visible and cannot be hidden behind advanced controls or a clickable map preparation',async()=>{
  status={...status,navigation:{phase:'not_prepared'},camera_motion:{warning:'unverified',rapid_reversals:4,navigation_qualified:false}};
  render(<TeachingReconstruction {...props}/>);
  await screen.findByText('Траектория камер требует проверки. Движение по этой версии карты выключено.');
  expect(screen.queryByRole('button',{name:'Подготовить карту'})).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
test('compact readiness cannot be green or claim prepared from an unbound ready response',async()=>{
  const changed=jest.fn();status={...status,source_manifest_sha256:null};render(<TeachingReconstruction {...props} onRouteChange={changed}/>);
  await screen.findByText(/Задание относится к другой записи/);
  expect(screen.queryByText(/Основная попытка:/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Карта подготовлена'})).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Проверить состояние'})).toBeEnabled();
  expect(changed.mock.calls.every(([job])=>job===null)).toBe(true);
});

test('a retry of the same capture cannot borrow ready status before its own deferred reply',async()=>{
  const next={id:'1'.repeat(32),key:'2'.repeat(64)},changed=jest.fn();let release:(value:ReconstructionState)=>void=()=>{};
  const pending=new Promise<ReconstructionState>(resolve=>{release=resolve;});
  jest.mocked(reconstructionRequest).mockImplementation(async path=>({json:async()=>path===`/jobs/${next.id}`?pending:status}) as Response);
  const view=render(<TeachingReconstruction {...props} onRouteChange={changed}/>);
  await waitFor(()=>expect(changed).toHaveBeenLastCalledWith(saved));
  jest.mocked(readReconstructionLink).mockResolvedValue(next);jest.mocked(listReconstructionLinks).mockResolvedValue([saved,next]);
  view.rerender(<TeachingReconstruction {...props} processingJobId={next.id} onRouteChange={changed}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(call=>call[0]===`/jobs/${next.id}`)).toBe(true));
  expect(changed).toHaveBeenLastCalledWith(null);expect(changed.mock.calls.some(([job])=>job?.id===next.id)).toBe(false);
  expect(screen.queryByRole('button',{name:'Карта подготовлена'})).not.toBeInTheDocument();
  await act(async()=>{release(status);});
  await waitFor(()=>expect(changed).toHaveBeenLastCalledWith(next));
});

test('a failed new attempt visibly offers the previous source-bound result without changing it automatically',async()=>{
  const previous={id:'6a770406'.padEnd(32,'0'),key:'9'.repeat(64)},changed=jest.fn();
  status={phase:'failed',source_manifest_sha256:manifest,error:"No module named 'av'",geometry_available:false,navigation:{phase:'not_prepared'}};
  jest.mocked(listReconstructionLinks).mockResolvedValue([saved,previous]);
  jest.mocked(reconstructionRequest).mockImplementation(async path=>({json:async()=>path===`/jobs/${previous.id}`?
    {phase:'failed',source_manifest_sha256:manifest,error:'resource_guard',geometry_available:true,quality:{registered:144,selected:173,points:9529,mean_reprojection_px:1.2},navigation:{phase:'not_prepared'}}:
    path===`/jobs/${previous.id}/geometry-alternatives`?{preferredAlternativeId:'saved-173',alternatives:[{id:'saved-173',label:'Полный сохранённый проход',cameras:173,points:20556}]}:
    path.endsWith('/geometry-alternatives')?{alternatives:[]}:status}) as Response);
  const view=render(<TeachingReconstruction {...props} onRouteChange={changed}/>);
  const card=await screen.findByRole('region',{name:'Сохранённые результаты предыдущих попыток'});
  expect(screen.getByRole('alert')).toHaveTextContent('Не запустился декодер видео. Это ошибка обработчика. Исходное видео сохранено.');
  expect(card).toHaveTextContent(/173 камер.*20.*556 точек/);expect(card).toHaveTextContent('Это схема для просмотра. Она не означает, что карта движения подготовлена.');
  expect(saveReconstructionLink).not.toHaveBeenCalled();expect(changed).toHaveBeenLastCalledWith(saved);
  expect(view.container.innerHTML).not.toContain(previous.key);expect(screen.queryByRole('button',{name:'Карта подготовлена'})).not.toBeInTheDocument();
  fireEvent.click(within(card).getByRole('button',{name:'Открыть сохранённый результат · 6a770406'}));
  await waitFor(()=>expect(saveReconstructionLink).toHaveBeenCalledWith(folder,clip,previous));
  await waitFor(()=>expect(changed).toHaveBeenLastCalledWith(previous));
  await screen.findByText('У этой попытки сохранён прежний ресурсный отказ. Это не замер памяти сейчас. Исходное видео сохранено.');
  expect(screen.queryByText(/Недостаточно ресурсов для безопасного продолжения/)).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
test.each(['sparse_complete','complete'])('a newer %s attempt with rejected navigation retains an explicit prior result choice',async phase=>{
  const current={id:'f303'.padEnd(32,'0'),key:'8'.repeat(64)},previous={id:'6a770406'.padEnd(32,'0'),key:'9'.repeat(64)},changed=jest.fn();
  status={phase,source_manifest_sha256:manifest,geometry_available:true,quality:{registered:173,selected:173,coverage:1,points:10630,mean_reprojection_px:1.1},navigation:{phase:'rejected',error:'route_map_has_unobserved_sections'}};
  jest.mocked(readReconstructionLink).mockResolvedValue(current);jest.mocked(listReconstructionLinks).mockResolvedValue([current,previous]);
  jest.mocked(reconstructionRequest).mockImplementation(async path=>({json:async()=>path===`/jobs/${previous.id}`?
    {phase:'failed',source_manifest_sha256:manifest,error:'resource_guard',geometry_available:true,navigation:{phase:'not_prepared'}}:
    path===`/jobs/${previous.id}/geometry-alternatives`?{preferredAlternativeId:'saved-173',alternatives:[{id:'saved-173',label:'Полный сохранённый проход',cameras:173,points:20556}]}:
    path.endsWith('/geometry-alternatives')?{alternatives:[]}:status}) as Response);
  const view=render(<TeachingReconstruction {...props} onRouteChange={changed}/>);
  const card=await screen.findByRole('region',{name:'Сохранённые результаты предыдущих попыток'});
  expect(card).toHaveTextContent(/173 камер.*20.*556 точек/);
  expect(card).toHaveTextContent('Это схема для просмотра. Она не означает, что карта движения подготовлена.');
  expect(screen.getByText(/Основная попытка: 173\/173 камер.*10.*630 точек/)).toBeInTheDocument();
  expect(saveReconstructionLink).not.toHaveBeenCalled();expect(changed).toHaveBeenLastCalledWith(current);
  expect(screen.queryByRole('button',{name:'Карта подготовлена'})).not.toBeInTheDocument();expect(view.container.innerHTML).not.toContain(previous.key);
  fireEvent.click(within(card).getByRole('button',{name:'Открыть сохранённый результат · 6a770406'}));
  await waitFor(()=>expect(saveReconstructionLink).toHaveBeenCalledWith(folder,clip,previous));
  await waitFor(()=>expect(changed).toHaveBeenLastCalledWith(previous));
  expect(screen.queryByRole('button',{name:'Карта подготовлена'})).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});

test('the chosen geometry is portaled into the single viewer even when primary geometry is unavailable',async()=>{
  status={phase:'quality_rejected',source_manifest_sha256:manifest,geometry_available:false};
  const target=document.createElement('div');document.body.appendChild(target);
  const selection:SceneGeometrySelection={sourceKey:`${scope}:${clip}`,jobId:saved.id,sourceManifestSha:manifest,id:'diagnostic-173',label:'Выбранная схема · 173',diagnostic:true,geometry:null};
  const view=render(<TeachingReconstruction {...props} sceneContainer={target} selectedGeometry={selection}/>);
  await within(target).findByTestId('compact-scene');
  expect(mockScene.mock.calls.at(-1)?.[0]).toMatchObject({sourceKey:`${scope}:${clip}`,selectedGeometry:selection});
  expect(within(screen.getByRole('region',{name:'Подготовка выбранной записи'})).queryByTestId('compact-scene')).not.toBeInTheDocument();
  view.rerender(<TeachingReconstruction {...props} sceneContainer={target} selectedGeometry={null}/>);
  expect(within(target).getByTestId('compact-scene')).toHaveAttribute('data-choice','none');
  const stale={...selection,jobId:'9'.repeat(32)};
  view.rerender(<TeachingReconstruction {...props} sceneContainer={target} selectedGeometry={stale}/>);
  expect(mockScene.mock.calls.at(-1)?.[0].selectedGeometry).toBe(stale);
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
  view.unmount();target.remove();
});
test('explicit null scene slot unmounts 3D, and toggling the slot never repeats processing intents or job polling',async()=>{
  const target=document.createElement('div');document.body.appendChild(target);
  const view=render(<TeachingReconstruction {...props} selectedGeometry={null}/>);
  await screen.findByRole('button',{name:'Карта подготовлена'});expect(mockScene).not.toHaveBeenCalled();
  const requests=jest.mocked(reconstructionRequest).mock.calls.length;
  view.rerender(<TeachingReconstruction {...props} sceneContainer={target} selectedGeometry={null}/>);
  expect(within(target).getByTestId('compact-scene')).toBeInTheDocument();
  view.rerender(<TeachingReconstruction {...props} sceneContainer={null} selectedGeometry={null}/>);
  expect(within(target).queryByTestId('compact-scene')).not.toBeInTheDocument();
  view.rerender(<TeachingReconstruction {...props} sceneContainer={target} selectedGeometry={null}/>);
  expect(jest.mocked(reconstructionRequest).mock.calls).toHaveLength(requests);view.unmount();target.remove();
});
test('closed quality evidence does not mount expensive comparison until requested',async()=>{
  render(<TeachingReconstruction {...props}/>);await screen.findByRole('button',{name:'Карта подготовлена'});
  expect(ReferenceComparison).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Метрики, HUD и проверка качества'}));
  expect(ReferenceComparison).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button',{name:'Метрики, HUD и проверка качества'}));
  expect(screen.queryByText('Сравнение с исходными ракурсами')).not.toBeInTheDocument();
});
test('surface fragment controls remain available in their own collapsed group and start only explicitly',async()=>{
  render(<TeachingReconstruction {...props}/>);await screen.findByRole('button',{name:'Карта подготовлена'});
  expect(screen.queryByRole('button',{name:'Построить поверхности'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Дополнительно · поверхности'}));
  fireEvent.change(screen.getByLabelText('Начальный ракурс фрагмента'),{target:{value:'5'}});
  fireEvent.click(screen.getByRole('button',{name:'Построить поверхности'}));
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(call=>call[0].includes('/fragments/'))).toBe(true));
  const call=jest.mocked(reconstructionRequest).mock.calls.find(item=>item[0].includes('/fragments/'))!;
  expect(JSON.parse(String(call[2]?.body))).toEqual({first_view:4,view_count:18});expect(uploadReconstruction).not.toHaveBeenCalled();
});
test('full presentation remains the default legacy layout',async()=>{
  render(<TeachingReconstruction {...props} presentation={undefined} sceneContainer={undefined}/>);
  await screen.findByRole('region',{name:'Построение плотной 3D-сцены'});
  expect(screen.queryByRole('region',{name:'Подготовка выбранной записи'})).not.toBeInTheDocument();
});
function selectedPreview():SceneGeometrySelection{return {sourceKey:`${scope}:${clip}`,jobId:saved.id,sourceManifestSha:manifest,id:'loop-173',label:'Уточнённая геометрия',diagnostic:true,geometry:{source_manifest_sha256:manifest,
  cameras:Array.from({length:173},(_,i)=>({center:[i,0,0],ticks_90k:i*9000})),points:Array.from({length:20556},()=>[1,2,3,200,210,220])}};}
test('primary144 metrics and bound selected173 preview are named separately without admitting the selected preview for navigation',async()=>{
  status={...status,navigation:{phase:'failed',error:'route_map_has_unobserved_sections'},quality:{registered:144,selected:144,coverage:1,points:9529,mean_reprojection_px:.9}};
  render(<TeachingReconstruction {...props} selectedGeometry={selectedPreview()}/>);
  await screen.findByText(/Основная попытка: 144\/144 камер.*9.*529 точек/);
  expect(screen.getByText(/Выбранный просмотр: Уточнённая геометрия.*173 камер.*20.*556 точек/)).toBeInTheDocument();
  expect(screen.getByText('Основная карта для проверки')).toBeInTheDocument();expect(screen.queryByRole('button',{name:'Карта подготовлена'})).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
test.each(['scope','job','manifest','geometry-manifest','loading'])('an unbound or loading %s wrapper cannot publish the selected173 counts or borrow primary admission',async invalid=>{
  const selection=selectedPreview();
  if(invalid==='scope')selection.sourceKey=`${'9'.repeat(32)}:${clip}`;
  if(invalid==='job')selection.jobId='9'.repeat(32);
  if(invalid==='manifest')selection.sourceManifestSha='9'.repeat(64);
  if(invalid==='geometry-manifest')selection.geometry!.source_manifest_sha256='9'.repeat(64);
  if(invalid==='loading')selection.geometry=null;
  render(<TeachingReconstruction {...props} selectedGeometry={selection}/>);
  await screen.findByRole('button',{name:'Карта подготовлена'});
  expect(screen.queryByText(/Выбранный просмотр:/)).not.toBeInTheDocument();
  expect(screen.getByText(/Основная попытка: 36\/36 камер/)).toBeInTheDocument();
});
