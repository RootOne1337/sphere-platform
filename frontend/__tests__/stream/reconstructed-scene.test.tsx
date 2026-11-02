import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import ReconstructedScene from '@/src/features/stream/ReconstructedScene';
import {readImportedRouteGeometry} from '@/src/features/stream/routeMapProjection';
import type {SceneGeometrySelection} from '@/src/features/stream/sceneGeometrySelection';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
import {loadSurface} from '@/src/features/stream/surfaceAsset';

const mockThree={points:[] as number[],disposed:0,contextsReleased:0,spark:0};
jest.mock('@/src/features/stream/reconstructionClient',()=>({reconstructionRequest:jest.fn()}));
jest.mock('@/src/features/stream/surfaceAsset',()=>({loadSurface:jest.fn()}));
jest.mock('@/src/features/stream/RouteGeometryMap',()=>({__esModule:true,default:()=>null}));
jest.mock('@/src/features/stream/RecordedSourceFrame',()=>({__esModule:true,default:()=>null}));
jest.mock('three/addons/controls/OrbitControls.js',()=>({OrbitControls:class{target=new (jest.requireMock('three').Vector3)();update(){}dispose(){}}}));
jest.mock('@sparkjsdev/spark',()=>{mockThree.spark++;return {};});
jest.mock('three',()=>{
  class Vector3{constructor(public x=0,public y=0,public z=0){}set(x:number,y:number,z:number){Object.assign(this,{x,y,z});return this;}copy(v:Vector3){return this.set(v.x,v.y,v.z);}add(v:Vector3){return this.set(this.x+v.x,this.y+v.y,this.z+v.z);}multiplyScalar(s:number){return this.set(this.x*s,this.y*s,this.z*s);}length(){return Math.hypot(this.x,this.y,this.z);}}
  class Box3{points:Vector3[]=[];setFromPoints(p:Vector3[]){this.points=p;return this;}getCenter(out:Vector3){return out.set(0,0,0);}getSize(out:Vector3){return out.set(1,1,1);}}
  class Matrix{makePerspective(){return this;}copy(){return this;}invert(){return this;}}
  class Object3D{visible=true;position=new Vector3();add(){}}
  class BufferGeometry{attributes:Record<string,{array:number[]}>= {};setAttribute(name:string,value:{array:number[]}){this.attributes[name]=value;return this;}setFromPoints(){return this;}dispose(){}}
  class Material{dispose(){}}
  return {Vector3,Box3,Scene:class extends Object3D{},Color:class{},PerspectiveCamera:class{position=new Vector3();up=new Vector3();projectionMatrix=new Matrix();projectionMatrixInverse=new Matrix();updateProjectionMatrix(){}},
    WebGLRenderer:class{domElement=document.createElement('canvas');setPixelRatio(){}setSize(){}setAnimationLoop(){}dispose(){mockThree.disposed++;}forceContextLoss(){mockThree.contextsReleased++;}},BufferGeometry,
    Float32BufferAttribute:class{constructor(public array:number[],public itemSize:number){}},PointsMaterial:Material,LineBasicMaterial:Material,Group:Object3D,
    Points:class extends Object3D{constructor(g:BufferGeometry){super();mockThree.points.push(g.attributes.position.array.length/3);}},LineSegments:Object3D};
});
const request=reconstructionRequest as jest.Mock;
const sha='a'.repeat(64),job={id:'a'.repeat(32),key:'b'.repeat(64)},sourceKey='account:clip';
const ticks=new Set(Array.from({length:173},(_,i)=>i*9000));
function raw(count=173,points=20556){return {schema:'sphere-recovered-scene-v1',source_manifest_sha256:sha,cameras:Array.from(ticks).slice(173-count).map((ticks_90k,i)=>({ticks_90k,center:[i,0,0],image:`${String(i).padStart(8,'0')}.png`,camera_to_world:[[1,0,0,i],[0,1,0,0],[0,0,1,0]],intrinsics:{width:1920,height:1080,fx:604,fy:604,cx:960,cy:540}})),points:Array.from({length:points},(_,i)=>[i,0,1,255,255,255])};}
function selection():SceneGeometrySelection{return {sourceKey,jobId:job.id,sourceManifestSha:sha,id:'selected-173',label:'Выбранная схема173',diagnostic:true,geometry:readImportedRouteGeometry(raw(),sha,ticks),recordingRange:{firstTicks:0,lastTicks:1548000,frames:173}};}
const props={job,status:{phase:'failed',geometry_available:true},sourceManifestSha:sha,sourceKey,validTicks:ticks,showGeometryMap:false};
beforeEach(()=>{jest.clearAllMocks();mockThree.points=[];mockThree.disposed=0;mockThree.contextsReleased=0;mockThree.spark=0;global.ResizeObserver=class{observe(){}disconnect(){}unobserve(){}} as unknown as typeof ResizeObserver;});

test('selected173/20556 is the only3D geometry even when primary dense/surface assets exist',async()=>{
  render(<ReconstructedScene {...props} selectedGeometry={selection()} status={{...props.status,dense_available:true,surface:{available:true,id:'surface'} as never}}/>);
  await screen.findByText(/173 камер · 20\s?556 опорных точек/);
  expect(mockThree.points).toEqual([20556]);expect(request).not.toHaveBeenCalled();expect(loadSurface).not.toHaveBeenCalled();expect(mockThree.spark).toBe(0);
  expect(screen.queryByRole('button',{name:/Скачать GLB/})).not.toBeInTheDocument();
  expect(screen.getByText(/Диагностическая схема/)).toHaveTextContent('selected-173');
});
test('explicit null and loading choice never fall back to primary',async()=>{
  const selected=selection(),view=render(<ReconstructedScene {...props} selectedGeometry={selected}/>);
  await screen.findByText(/173 камер/);
  view.rerender(<ReconstructedScene {...props} selectedGeometry={null}/>);
  expect(screen.getByLabelText('Восстановленная 3D-сцена')).not.toBeVisible();
  await screen.findByText('Выберите сохранённую схему ориентиров.');
  view.rerender(<ReconstructedScene {...props} selectedGeometry={{...selected,geometry:null}}/>);
  await screen.findByText(/Основная геометрия не подставляется/);expect(request).not.toHaveBeenCalled();expect(screen.queryByRole('slider')).not.toBeInTheDocument();
});
test('wrong source/account/job selection refuses before any primary request',async()=>{
  render(<ReconstructedScene {...props} selectedGeometry={{...selection(),sourceKey:'other:clip'}}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('не относится');expect(request).not.toHaveBeenCalled();
});
test('external source ticks control an existing camera and slider seeks only exact source ticks',async()=>{
  const seek=jest.fn(),selected=selection();const view=render(<ReconstructedScene {...props} selectedGeometry={selected} selectedTicks={18000} onSeekCamera={seek}/>);
  await waitFor(()=>expect(screen.getByRole('slider')).toHaveValue('2'));expect(seek).not.toHaveBeenCalled();
  view.rerender(<ReconstructedScene {...props} selectedGeometry={selected} selectedTicks={9000} onSeekCamera={seek}/>);
  await waitFor(()=>expect(screen.getByRole('slider')).toHaveValue('1'));
  fireEvent.change(screen.getByRole('slider'),{target:{value:'3'}});expect(seek).toHaveBeenCalledWith(27000);
});
test('late old primary response is cancelled and cannot replace selected geometry after account/key change',async()=>{
  let resolve!:(v:unknown)=>void;request.mockReturnValue(new Promise(r=>{resolve=r;}));
  const view=render(<ReconstructedScene {...props}/>);await waitFor(()=>expect(request).toHaveBeenCalledTimes(1));
  const signal=request.mock.calls[0][2].signal as AbortSignal,selected=selection();
  view.rerender(<ReconstructedScene {...props} job={{...job,key:'c'.repeat(64)}} sourceKey="other:clip" selectedGeometry={{...selected,sourceKey:'other:clip'}}/>);
  await screen.findByText(/173 камер/);expect(signal.aborted).toBe(true);
  await act(async()=>resolve({json:async()=>raw(144,10)}));
  expect(screen.getByText(/173 камер ·/)).toBeInTheDocument();expect(screen.queryByText(/144 камер/)).not.toBeInTheDocument();expect(mockThree.points).toEqual([20556]);
});
test('primary geometry can load only after explicit historical choice and remains labelled separately',async()=>{
  request.mockResolvedValue({json:async()=>raw(144,10)});
  render(<ReconstructedScene {...props} selectedGeometry={{...selection(),id:'primary'}}/>);await screen.findByText(/173 камер/);
  fireEvent.click(screen.getByText('Другие представления основного расчёта'));
  fireEvent.click(screen.getByRole('button',{name:'Основной расчёт · камеры и точки'}));
  await screen.findByText(/144 камер · 10 опорных точек/);
  expect(request).toHaveBeenCalledTimes(1);expect(screen.getByText(/Исторический результат основного расчёта/)).toBeInTheDocument();
  expect(mockThree.points).toEqual([20556,10]);expect(mockThree.disposed).toBeGreaterThan(0);expect(mockThree.contextsReleased).toBeGreaterThan(0);
});


test('an alternative selection cannot silently open primary geometry under the selected-result header',async()=>{
  render(<ReconstructedScene {...props} selectedGeometry={selection()} status={{...props.status,geometry_available:true}}/>);
  await screen.findByText(/173 камер/);
  expect(screen.queryByRole('button',{name:'Основной расчёт · камеры и точки'})).not.toBeInTheDocument();
  expect(request).not.toHaveBeenCalled();
});
